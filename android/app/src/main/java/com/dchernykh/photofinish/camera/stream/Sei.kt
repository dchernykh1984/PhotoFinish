package com.dchernykh.photofinish.camera.stream

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.util.UUID

/**
 * The frame's moment, in an SEI NAL unit the recorder reads (specs/003,
 * contracts/phone-stream.md): user_data_unregistered under PhotoFinish's UUID,
 * then `PFT1` and the capture moment in Unix microseconds on the recorder's clock.
 */
object Sei {
    val uuid: UUID = UUID.fromString("e1a46cea-b5ff-4c7d-b445-4c7dbd7ea281")
    private val tag = "PFT1".toByteArray(Charsets.US_ASCII)
    private const val USER_DATA_UNREGISTERED = 5

    fun frameMoment(momentUs: Long): ByteArray {
        val payload =
            ByteBuffer
                .allocate(16 + tag.size + 8)
                .putLong(uuid.mostSignificantBits)
                .putLong(uuid.leastSignificantBits)
                .put(tag)
                .putLong(momentUs)
                .array()
        val rbsp = ByteArrayOutputStream()
        rbsp.write(USER_DATA_UNREGISTERED)
        rbsp.write(payload.size)
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
