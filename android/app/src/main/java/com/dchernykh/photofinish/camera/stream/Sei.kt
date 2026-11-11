package com.dchernykh.photofinish.camera.stream

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.util.UUID

/**
 * What the frames carry for the recorder, in SEI NAL units (specs/003, contracts/phone-stream.md):
 * user_data_unregistered under PhotoFinish's UUID, then `PFT1` and the capture moment in Unix
 * microseconds on the recorder's clock; or `PFS1` and the phone's status line (specs/005).
 */
object Sei {
    val uuid: UUID = UUID.fromString("e1a46cea-b5ff-4c7d-b445-4c7dbd7ea281")
    private val momentTag = "PFT1".toByteArray(Charsets.US_ASCII)
    private val statusTag = "PFS1".toByteArray(Charsets.US_ASCII)
    private const val USER_DATA_UNREGISTERED = 5
    private const val UUID_BYTES = 16
    private const val FULL_SIZE = 255

    fun frameMoment(momentUs: Long): ByteArray =
        unit(ByteBuffer.allocate(Long.SIZE_BYTES).putLong(momentUs).array(), momentTag)

    /** The phone's status, `key=value;...` in ASCII (specs/005-phone-status). */
    fun phoneStatus(line: String): ByteArray = unit(line.toByteArray(Charsets.US_ASCII), statusTag)

    private fun unit(
        data: ByteArray,
        tag: ByteArray,
    ): ByteArray {
        val payload =
            ByteBuffer
                .allocate(UUID_BYTES + tag.size + data.size)
                .putLong(uuid.mostSignificantBits)
                .putLong(uuid.leastSignificantBits)
                .put(tag)
                .put(data)
                .array()
        val rbsp = ByteArrayOutputStream()
        rbsp.write(USER_DATA_UNREGISTERED)
        var size = payload.size
        while (size >= FULL_SIZE) { // a size past 254 as SEI writes it: 255 for each full 255
            rbsp.write(FULL_SIZE)
            size -= FULL_SIZE
        }
        rbsp.write(size)
        rbsp.write(payload)
        rbsp.write(0x80) // rbsp trailing bits
        return byteArrayOf(Avc.NAL_SEI.toByte()) + escape(rbsp.toByteArray())
    }

    /** The payload with an emulation-prevention byte wherever two zeros meet 0-3. */
    fun escape(rbsp: ByteArray): ByteArray {
        val out = ByteArrayOutputStream(rbsp.size + rbsp.size / 64 + 1)
        var zeros = 0
        for (byte in rbsp) {
            val value = byte.toInt() and 0xFF
            if (zeros >= 2 && value <= 3) {
                out.write(3)
                zeros = 0
            }
            out.write(value)
            zeros = if (value == 0) zeros + 1 else 0
        }
        return out.toByteArray()
    }
}
