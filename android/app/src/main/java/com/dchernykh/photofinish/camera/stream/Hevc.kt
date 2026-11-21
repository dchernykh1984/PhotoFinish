package com.dchernykh.photofinish.camera.stream

import java.io.ByteArrayOutputStream

/**
 * H.265 as Enhanced RTMP carries it (specs/010-hevc): the HEVCDecoderConfigurationRecord from the encoder's VPS,
 * SPS and PPS, and the video tags -- a first byte of 0x80, the frame type and the packet type, then `hvc1`.
 */
object Hevc {
    const val NAL_VPS = 32
    const val NAL_SPS = 33
    const val NAL_PPS = 34
    const val NAL_PREFIX_SEI = 39

    private val FOURCC = "hvc1".toByteArray(Charsets.US_ASCII)
    private const val EX_HEADER = 0x80
    private const val KEY_FRAME = 1
    private const val INTER_FRAME = 2
    private const val SEQUENCE_START = 0
    private const val CODED_FRAMES_X = 3 // frames with no composition time: no B-frames
    private const val HEADER_BYTES = 2
    private const val PROFILE_BYTES = 12 // profile space .. level, after the SPS's first byte
    private const val LENGTH_SIZE_MINUS_ONE = 3
    private const val MAIN_CHROMA = 0xFD // reserved bits, chroma 4:2:0
    private const val EIGHT_BITS = 0xF8 // reserved bits, bit depth 8
    private const val ARRAY_COMPLETE = 0x80
    private const val BYTE = 0xFF

    fun type(nal: ByteArray): Int = (nal[0].toInt() shr 1) and 0x3F

    /**
     * The decoder configuration record (ISO/IEC 14496-15, 8.3.3): profile, tier, level and flags read from the
     * SPS's profile_tier_level, the sub-layers and their nesting from its first byte; 4:2:0 and 8 bits, as phone
     * encoders give; then the three units, an array each.
     */
    fun configurationRecord(
        vps: ByteArray,
        sps: ByteArray,
        pps: ByteArray,
    ): ByteArray {
        val rbsp = unescape(sps.copyOfRange(HEADER_BYTES, sps.size))
        require(rbsp.size > PROFILE_BYTES) { "an SPS too short to read its profile" }
        val first = rbsp[0].toInt()
        val layers = ((first shr 1) and 0x07) + 1
        val nested = first and 0x01
        val out = ByteArrayOutputStream()
        out.write(1) // configurationVersion
        out.write(rbsp, 1, PROFILE_BYTES) // profile space, tier, profile; compatibility; constraints; level
        out.write(0xF0) // min_spatial_segmentation_idc: none
        out.write(0x00)
        out.write(0xFC) // parallelismType: unknown
        out.write(MAIN_CHROMA)
        out.write(EIGHT_BITS)
        out.write(EIGHT_BITS)
        out.write(0x00) // avgFrameRate: unknown
        out.write(0x00)
        out.write((layers shl 3) or (nested shl 2) or LENGTH_SIZE_MINUS_ONE)
        out.write(3) // numOfArrays
        for ((kind, unit) in listOf(NAL_VPS to vps, NAL_SPS to sps, NAL_PPS to pps)) {
            out.write(ARRAY_COMPLETE or kind)
            out.write(0)
            out.write(1) // numNalus
            out.write((unit.size shr 8) and BYTE)
            out.write(unit.size and BYTE)
            out.write(unit)
        }
        return out.toByteArray()
    }

    /** The video tag carrying the configuration record: Enhanced RTMP's SequenceStart. */
    fun sequenceHeaderTag(record: ByteArray): ByteArray = header(KEY_FRAME, SEQUENCE_START) + record

    /** The video tag carrying one frame's units, each after its 4-byte length: CodedFramesX. */
    fun frameTag(
        keyframe: Boolean,
        nalUnits: List<ByteArray>,
    ): ByteArray {
        val out = ByteArrayOutputStream()
        out.write(header(if (keyframe) KEY_FRAME else INTER_FRAME, CODED_FRAMES_X))
        for (nal in nalUnits) {
            out.write(nal.size ushr 24)
            out.write((nal.size shr 16) and BYTE)
            out.write((nal.size shr 8) and BYTE)
            out.write(nal.size and BYTE)
            out.write(nal)
        }
        return out.toByteArray()
    }

    private fun header(
        frameType: Int,
        packetType: Int,
    ): ByteArray = byteArrayOf((EX_HEADER or (frameType shl 4) or packetType).toByte()) + FOURCC

    /** The bytes without emulation prevention: 00 00 03 is 00 00. */
    private fun unescape(data: ByteArray): ByteArray {
        val out = ByteArrayOutputStream(data.size)
        var zeros = 0
        for (byte in data) {
            val value = byte.toInt() and BYTE
            if (zeros >= 2 && value == 3) {
                zeros = 0
                continue
            }
            out.write(value)
            zeros = if (value == 0) zeros + 1 else 0
        }
        return out.toByteArray()
    }
}
