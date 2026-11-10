package com.dchernykh.photofinish.camera.stream

import java.io.ByteArrayOutputStream

/**
 * H.264 as the encoder gives it (Annex B: NAL units after start codes) and as RTMP
 * carries it (FLV video tags: a configuration record, then NAL units each after
 * its length).
 */
object Avc {
    const val NAL_IDR = 5
    const val NAL_SEI = 6
    const val NAL_SPS = 7
    const val NAL_PPS = 8

    private const val CODEC_AVC = 7
    private const val KEY_FRAME = 1
    private const val INTER_FRAME = 2

    fun type(nal: ByteArray): Int = nal[0].toInt() and 0x1F

    /** The NAL units of an Annex B buffer, without their start codes. */
    fun splitAnnexB(data: ByteArray): List<ByteArray> {
        val starts = mutableListOf<Int>() // where each start code begins
        val bodies = mutableListOf<Int>() // where each unit after it begins
        var i = 0
        while (i + 2 < data.size) {
            if (data[i].toInt() == 0 && data[i + 1].toInt() == 0 && data[i + 2].toInt() == 1) {
                starts += if (i > 0 && data[i - 1].toInt() == 0) i - 1 else i
                bodies += i + 3
                i += 3
            } else {
                i++
            }
        }
        if (bodies.isEmpty()) return if (data.isEmpty()) emptyList() else listOf(data)
        return bodies
            .mapIndexed { n, body ->
                val end = if (n + 1 < starts.size) starts[n + 1] else data.size
                data.copyOfRange(body, end)
            }.filter { it.isNotEmpty() }
    }

    /** The AVCDecoderConfigurationRecord of a stream: lengths of 4 bytes, one SPS, one PPS. */
    fun configurationRecord(
        sps: ByteArray,
        pps: ByteArray,
    ): ByteArray {
        val out = ByteArrayOutputStream()
        out.write(1) // version
        out.write(sps[1].toInt()) // profile
        out.write(sps[2].toInt()) // compatibility
        out.write(sps[3].toInt()) // level
        out.write(0xFF) // 6 bits reserved, lengthSizeMinusOne = 3
        out.write(0xE1) // 3 bits reserved, one SPS
        out.write(sps.size shr 8)
        out.write(sps.size and 0xFF)
        out.write(sps)
        out.write(1) // one PPS
        out.write(pps.size shr 8)
        out.write(pps.size and 0xFF)
        out.write(pps)
        return out.toByteArray()
    }

    /** The FLV video tag carrying the configuration record. */
    fun sequenceHeaderTag(record: ByteArray): ByteArray = tagHeader(keyframe = true, packetType = 0) + record

    /** The FLV video tag carrying one frame's NAL units, each after its 4-byte length. */
    fun frameTag(
        keyframe: Boolean,
        nalUnits: List<ByteArray>,
    ): ByteArray {
        val out = ByteArrayOutputStream()
        out.write(tagHeader(keyframe, packetType = 1))
        for (nal in nalUnits) {
            out.write(nal.size ushr 24)
            out.write((nal.size shr 16) and 0xFF)
            out.write((nal.size shr 8) and 0xFF)
            out.write(nal.size and 0xFF)
            out.write(nal)
        }
        return out.toByteArray()
    }

    private fun tagHeader(
        keyframe: Boolean,
        packetType: Int,
    ): ByteArray =
        byteArrayOf(
            (((if (keyframe) KEY_FRAME else INTER_FRAME) shl 4) or CODEC_AVC).toByte(),
            packetType.toByte(),
            0,
            0,
            0, // composition time: no B-frames
        )
}
