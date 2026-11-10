package com.dchernykh.photofinish.camera.stream

import java.io.ByteArrayOutputStream
import java.io.EOFException
import java.io.InputStream
import java.io.OutputStream

/** An RTMP message: its chunk stream, timestamp (ms), type and message stream. */
class RtmpMessage(
    val chunkStreamId: Int,
    val timestamp: Long,
    val typeId: Int,
    val streamId: Int,
    val payload: ByteArray,
)

/** RTMP's message types the app sends or reads. */
object RtmpType {
    const val SET_CHUNK_SIZE = 1
    const val ACKNOWLEDGEMENT = 3
    const val USER_CONTROL = 4
    const val WINDOW_ACK_SIZE = 5
    const val SET_PEER_BANDWIDTH = 6
    const val VIDEO = 9
    const val DATA_AMF0 = 18
    const val COMMAND_AMF0 = 20
}

private const val MAX_PLAIN_TIMESTAMP = 0xFFFFFFL
private const val TIMESTAMP_MASK = 0xFFFFFFFFL

/**
 * Writes messages as chunks: a full header on the first chunk, a one-byte header on
 * the rest. A timestamp of 0xFFFFFF ms (4.6 hours) or more goes as an extended
 * timestamp, repeated on every chunk of the message, as FFmpeg reads it.
 */
class RtmpChunkWriter(
    private val out: OutputStream,
) {
    var chunkSize = 128

    fun write(message: RtmpMessage) {
        val timestamp = message.timestamp and TIMESTAMP_MASK
        val extended = timestamp >= MAX_PLAIN_TIMESTAMP
        val header = ByteArrayOutputStream()
        header.write(basicHeader(0, message.chunkStreamId))
        writeInt24(header, if (extended) MAX_PLAIN_TIMESTAMP.toInt() else timestamp.toInt())
        writeInt24(header, message.payload.size)
        header.write(message.typeId)
        // The message stream id is the one little-endian field of the header.
        for (shift in 0..24 step 8) header.write((message.streamId shr shift) and 0xFF)
        if (extended) writeInt32(header, timestamp)
        out.write(header.toByteArray())
        var offset = 0
        do {
            if (offset > 0) {
                out.write(basicHeader(3, message.chunkStreamId))
                if (extended) out.write(int32(timestamp))
            }
            val length = minOf(chunkSize, message.payload.size - offset)
            out.write(message.payload, offset, length)
            offset += length
        } while (offset < message.payload.size)
        out.flush()
    }

    private fun basicHeader(
        format: Int,
        chunkStreamId: Int,
    ): ByteArray {
        require(chunkStreamId in 2..63) { "chunk stream $chunkStreamId is not written" }
        return byteArrayOf(((format shl 6) or chunkStreamId).toByte())
    }

    private fun writeInt24(
        out: ByteArrayOutputStream,
        value: Int,
    ) {
        out.write((value shr 16) and 0xFF)
        out.write((value shr 8) and 0xFF)
        out.write(value and 0xFF)
    }

    private fun writeInt32(
        out: ByteArrayOutputStream,
        value: Long,
    ) = out.write(int32(value))
}

/** [value]'s low four bytes, big-endian, as RTMP writes its numbers. */
internal fun int32(value: Long): ByteArray =
    byteArrayOf(
        (value shr 24).toByte(),
        (value shr 16).toByte(),
        (value shr 8).toByte(),
        value.toByte(),
    )

/** [length] bytes from [input]; the stream ending before them throws EOFException. */
internal fun readFully(
    input: InputStream,
    length: Int,
): ByteArray {
    val bytes = ByteArray(length)
    var offset = 0
    while (offset < length) {
        val read = input.read(bytes, offset, length - offset)
        if (read < 0) throw EOFException("the server closed the connection")
        offset += read
    }
    return bytes
}

/**
 * Reads chunks back into messages, keeping each chunk stream's last header as RTMP
 * compresses them; a Set Chunk Size message changes the size read from then on.
 */
class RtmpChunkReader(
    private val input: InputStream,
) {
    var chunkSize = 128

    private class ChunkStream {
        var timestamp = 0L
        var delta = 0L
        var length = 0
        var typeId = 0
        var streamId = 0
        var extended = false
        var partial: ByteArrayOutputStream? = null
    }

    private val streams = HashMap<Int, ChunkStream>()

    fun read(): RtmpMessage {
        while (true) {
            val message = readChunk()
            if (message != null) {
                if (message.typeId == RtmpType.SET_CHUNK_SIZE && message.payload.size >= 4) {
                    chunkSize = (readInt32(message.payload) and 0x7FFFFFFF).toInt()
                }
                return message
            }
        }
    }

    private fun readChunk(): RtmpMessage? {
        val first = readByte()
        val format = first shr 6
        val chunkStreamId =
            when (val low = first and 0x3F) {
                0 -> 64 + readByte()
                1 -> 64 + readByte() + readByte() * 256
                else -> low
            }
        val stream = streams.getOrPut(chunkStreamId) { ChunkStream() }
        readHeader(format, stream)
        val partial = stream.partial ?: ByteArrayOutputStream(stream.length).also { stream.partial = it }
        val length = minOf(chunkSize, stream.length - partial.size())
        partial.write(readFully(input, length))
        if (partial.size() < stream.length) return null
        stream.partial = null
        return RtmpMessage(
            chunkStreamId,
            stream.timestamp and TIMESTAMP_MASK,
            stream.typeId,
            stream.streamId,
            partial.toByteArray(),
        )
    }

    /** The message header of a chunk of [format] 0 to 3, into its chunk stream's state. */
    private fun readHeader(
        format: Int,
        stream: ChunkStream,
    ) {
        when (format) {
            0 -> {
                val timestamp = readInt24().toLong()
                stream.length = readInt24()
                stream.typeId = readByte()
                stream.streamId = readByte() or (readByte() shl 8) or (readByte() shl 16) or (readByte() shl 24)
                stream.extended = timestamp == MAX_PLAIN_TIMESTAMP
                stream.timestamp = if (stream.extended) readInt32Value() else timestamp
                stream.delta = 0
            }
            1, 2 -> {
                val delta = readInt24().toLong()
                if (format == 1) {
                    stream.length = readInt24()
                    stream.typeId = readByte()
                }
                stream.extended = delta == MAX_PLAIN_TIMESTAMP
                stream.delta = if (stream.extended) readInt32Value() else delta
                stream.timestamp += stream.delta
            }
            else -> {
                if (stream.extended) readInt32Value()
                // A type 3 chunk that starts a message repeats the last delta; one that continues it, nothing.
                if (stream.partial == null) stream.timestamp += stream.delta
            }
        }
    }

    private fun readByte(): Int {
        val value = input.read()
        if (value < 0) throw EOFException("the server closed the connection")
        return value
    }

    private fun readInt24(): Int = (readByte() shl 16) or (readByte() shl 8) or readByte()

    private fun readInt32Value(): Long = readInt32(readFully(input, 4))

    companion object {
        fun readInt32(bytes: ByteArray): Long =
            ((bytes[0].toLong() and 0xFF) shl 24) or
                ((bytes[1].toLong() and 0xFF) shl 16) or
                ((bytes[2].toLong() and 0xFF) shl 8) or
                (bytes[3].toLong() and 0xFF)
    }
}
