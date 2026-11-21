package com.dchernykh.photofinish.camera.stream

import com.dchernykh.photofinish.camera.capture.FpsRange
import com.dchernykh.photofinish.camera.capture.Resolution
import com.dchernykh.photofinish.camera.capture.StreamFormat
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import java.io.File
import java.io.IOException

/**
 * What a kept stream needs to be sent by itself, the app started again since (specs/009, FR-001): its lens,
 * where it goes, its format -- its codec with it (specs/010) -- and the header the recorder decodes it from. Kept
 * in its folder as `stream.txt`, `key=value` lines, written whole or not at all.
 */
class StreamHeader(
    val lens: Lens,
    val address: RtmpAddress,
    val format: StreamFormat,
    val record: ByteArray,
) {
    /** Written into [folder], over the one there; false when the storage refuses it. */
    fun write(folder: File): Boolean {
        val lines =
            listOf(
                "version" to VERSION,
                "lens" to lens.code,
                "address" to address.toString(),
                "width" to format.resolution.width,
                "height" to format.resolution.height,
                "fps" to format.fps,
                "bitrate" to format.bitrate,
                "codec" to format.codec.code,
                "record" to record.joinToString("") { "%02x".format(it) },
            ).joinToString("") { (key, value) -> "$key=$value\n" }
        val temporary = File(folder, "$FILE.new")
        return try {
            temporary.writeText(lines, Charsets.US_ASCII)
            temporary.renameTo(File(folder, FILE))
        } catch (_: IOException) {
            false
        }
    }

    companion object {
        const val FILE = "stream.txt"
        private const val VERSION = 1
        private const val HEX = 16

        /** The header kept in [folder]; null when there is none, or it cannot be read whole. */
        fun read(folder: File): StreamHeader? {
            val text =
                try {
                    File(folder, FILE).takeIf { it.isFile }?.readText(Charsets.US_ASCII)
                } catch (_: IOException) {
                    null
                } ?: return null
            val values =
                text.lines().filter { '=' in it }.associate {
                    it.substringBefore(
                        '=',
                    ) to it.substringAfter('=')
                }
            return try {
                header(values)
            } catch (_: IllegalArgumentException) {
                null // a value missing or unreadable: no header to send the frames with
            }
        }

        private fun header(values: Map<String, String>): StreamHeader {
            require(values["version"]?.toIntOrNull() == VERSION)
            val text = { key: String -> requireNotNull(values[key]) }
            val number = { key: String -> requireNotNull(text(key).toIntOrNull()) }
            val record = requireNotNull(hex(text("record")))
            require(record.isNotEmpty())
            val fps = number("fps")
            val codec = requireNotNull(Codec.named(text("codec")))
            val size = Resolution(number("width"), number("height"))
            val format = StreamFormat(size, fps, FpsRange(fps, fps), number("bitrate"), codec)
            val lens = requireNotNull(Lens.named(text("lens")))
            return StreamHeader(lens, requireNotNull(RtmpAddress.parse(text("address"))), format, record)
        }

        private fun hex(text: String): ByteArray? {
            if (text.length % 2 != 0) return null
            return ByteArray(text.length / 2) { index ->
                text.substring(index * 2, index * 2 + 2).toIntOrNull(HEX)?.toByte() ?: return null
            }
        }
    }
}
