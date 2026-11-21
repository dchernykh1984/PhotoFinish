package com.dchernykh.photofinish.camera.stream

import com.dchernykh.photofinish.camera.capture.FpsRange
import com.dchernykh.photofinish.camera.capture.Resolution
import com.dchernykh.photofinish.camera.capture.StreamFormat
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption
import java.util.concurrent.atomic.AtomicReference

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
    /** The sound's AudioSpecificConfig, when the stream has sound (specs/013): a header written before never does. */
    val sound: ByteArray? = null,
) {
    /**
     * Written into [folder], over the one there, synced to the storage with its folder before the stream's first
     * run is: a power cut leaves the frames with their header (specs/009, FR-001); false when the storage refuses it.
     */
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
                "record" to hexOf(record),
            ).plus(listOfNotNull(sound?.let { "sound" to hexOf(it) }))
                .joinToString("") { (key, value) -> "$key=$value\n" }
        val temporary = File(folder, "$FILE.new")
        return try {
            FileOutputStream(temporary).use { out ->
                out.write(lines.toByteArray(Charsets.US_ASCII))
                out.fd.sync()
            }
            temporary.renameTo(File(folder, FILE)).also { if (it) syncFolder(folder) }
        } catch (_: IOException) {
            false
        }
    }

    /** The folder's names on the storage, the rename with them; a system that will not is left to its own pace. */
    private fun syncFolder(folder: File) {
        try {
            FileChannel.open(folder.toPath(), StandardOpenOption.READ).use { it.force(true) }
        } catch (_: IOException) {
            // a folder that cannot be opened to sync: the rename is the system's to write
        }
    }

    companion object {
        const val FILE = "stream.txt"
        private const val VERSION = 1
        private const val HEX = 16

        /**
         * A stream's header kept in [folder] as the encoder gives it, written by [later] -- the stores' own thread,
         * never the encoder's, which a slow flash's sync would hold up --: true once a record is known kept, so that
         * one the storage refused, [failed] told, is written again as the encoder gives it again. A folder gone by
         * then -- its store discarded, or sent whole -- has nothing to keep it for.
         */
        fun keeper(
            header: (ByteArray, ByteArray?) -> StreamHeader,
            folder: File,
            later: (Runnable) -> Unit,
            failed: () -> Unit,
        ): (ByteArray, ByteArray?) -> Boolean {
            val kept = AtomicReference<List<ByteArray?>?>()
            return { record, sound ->
                val asked = listOf(record, sound)
                kept.get()?.let { same(it, asked) } == true ||
                    false.also {
                        later(
                            Runnable {
                                when {
                                    !folder.isDirectory -> Unit
                                    header(record, sound).write(folder) -> kept.set(asked)
                                    folder.isDirectory -> failed() // gone as it was written: nothing failed
                                }
                            },
                        )
                    }
            }
        }

        private fun same(
            one: List<ByteArray?>,
            other: List<ByteArray?>,
        ): Boolean = one.zip(other).all { (a, b) -> a.contentEquals(b) }

        private fun hexOf(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }

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
            val sound = values["sound"]?.let { hex(it) }?.takeIf { it.isNotEmpty() } // garbled: sent without
            return StreamHeader(lens, requireNotNull(RtmpAddress.parse(text("address"))), format, record, sound)
        }

        private fun hex(text: String): ByteArray? {
            if (text.length % 2 != 0) return null
            return ByteArray(text.length / 2) { index ->
                text.substring(index * 2, index * 2 + 2).toIntOrNull(HEX)?.toByte() ?: return null
            }
        }
    }
}
