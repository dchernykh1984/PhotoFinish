package com.dchernykh.photofinish.camera.stream

import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.Closeable
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import java.security.SecureRandom

/** Where the frames go: an RTMP server, or a test's stand-in. */
interface VideoSink : Closeable {
    /** Connects and starts publishing; throws IOException when refused. */
    fun publish(metadata: Map<String, Any?>)

    /** The stream's AVC configuration record. */
    fun sendSequenceHeader(record: ByteArray)

    /** One frame's NAL units, at [timestampMs] from the connection's first frame. */
    fun sendFrame(
        timestampMs: Long,
        keyframe: Boolean,
        nalUnits: List<ByteArray>,
    )
}

/** A connection to the server: its streams, so a test can stand in for a socket. */
interface RtmpConnection : Closeable {
    val input: InputStream
    val output: OutputStream
}

/**
 * Publishes one H.264 stream to an RTMP server -- FFmpeg's listener in PhotoFinish's
 * recorder -- as OBS and Larix do: the simple handshake, connect, releaseStream,
 * FCPublish, createStream and publish, then onMetaData, the sequence header and the
 * frames. Not thread-safe: one thread publishes; [close] may come from another.
 */
class RtmpPublisher(
    private val address: RtmpAddress,
    private val connect: (RtmpAddress) -> RtmpConnection = ::socketConnection,
) : VideoSink {
    @Volatile private var connection: RtmpConnection? = null
    private lateinit var writer: RtmpChunkWriter
    private lateinit var reader: RtmpChunkReader
    private var streamId = 0

    @Volatile private var closed = false

    override fun publish(metadata: Map<String, Any?>) {
        val opened = connect(address)
        connection = opened
        if (closed) { // closed while it connected: it must not hold the server's one place
            opened.close()
            throw IOException("the stream was closed")
        }
        val output = BufferedOutputStream(opened.output, BUFFER_SIZE)
        val input = BufferedInputStream(opened.input)
        handshake(input, output)
        writer = RtmpChunkWriter(output)
        reader = RtmpChunkReader(input)
        send(CONTROL_STREAM, 0, RtmpType.SET_CHUNK_SIZE, 0, int32(CHUNK_SIZE.toLong()))
        writer.chunkSize = CHUNK_SIZE
        val app = mapOf("app" to address.app, "type" to "nonprivate", "flashVer" to FLASH_VER, "tcUrl" to address.tcUrl)
        command(0, "connect", 1, app)
        awaitResult(1)
        command(0, "releaseStream", 2, null, address.stream)
        command(0, "FCPublish", 3, null, address.stream)
        command(0, "createStream", 4, null)
        streamId = ((awaitResult(4).getOrNull(3) as? Double) ?: 1.0).toInt()
        command(streamId, "publish", 5, null, address.stream, "live")
        awaitStatus("NetStream.Publish.Start")
        send(
            DATA_STREAM,
            0,
            RtmpType.DATA_AMF0,
            streamId,
            Amf0.encode("@setDataFrame", "onMetaData", Amf0.EcmaArray(metadata)),
        )
        Thread({ drain() }, "rtmp-reader").apply { isDaemon = true }.start()
    }

    override fun sendSequenceHeader(record: ByteArray) =
        send(VIDEO_STREAM, 0, RtmpType.VIDEO, streamId, Avc.sequenceHeaderTag(record))

    override fun sendFrame(
        timestampMs: Long,
        keyframe: Boolean,
        nalUnits: List<ByteArray>,
    ) = send(VIDEO_STREAM, timestampMs, RtmpType.VIDEO, streamId, Avc.frameTag(keyframe, nalUnits))

    override fun close() {
        closed = true
        connection?.close()
    }

    private fun command(
        stream: Int,
        name: String,
        transaction: Int,
        vararg arguments: Any?,
    ) = send(COMMAND_STREAM, 0, RtmpType.COMMAND_AMF0, stream, Amf0.encode(name, transaction, *arguments))

    @Synchronized // the reader thread answers pings while the frames go out
    private fun send(
        chunkStream: Int,
        timestamp: Long,
        type: Int,
        stream: Int,
        payload: ByteArray,
    ) {
        if (closed) throw IOException("the stream was closed")
        writer.write(RtmpMessage(chunkStream, timestamp, type, stream, payload))
    }

    /** The values of the server's `_result` to [transaction]; its `_error` throws. */
    private fun awaitResult(transaction: Int): List<Any?> {
        while (true) {
            val values = nextCommand() ?: continue
            val number = (values.getOrNull(1) as? Double)?.toInt()
            when {
                values[0] == "_result" && number == transaction -> return values
                values[0] == "_error" && number == transaction -> throw IOException(
                    "the server refused: ${describe(values)}",
                )
            }
        }
    }

    private fun awaitStatus(code: String) {
        while (true) {
            val info = nextCommand()?.takeIf { it[0] == "onStatus" }?.getOrNull(3) as? Map<*, *> ?: continue
            if (info["code"] == code) return
            if (info["level"] == "error") throw IOException("the server refused: ${info["code"]}")
        }
    }

    private fun nextCommand(): List<Any?>? {
        val message = reader.read()
        if (message.typeId != RtmpType.COMMAND_AMF0) return null
        return Amf0.decode(message.payload).takeIf { it.isNotEmpty() }
    }

    /**
     * Reads what the server sends while the frames go out, so its acknowledgements
     * never fill the socket over a long race, and answers its pings.
     */
    private fun drain() {
        try {
            while (!closed) {
                val message =
                    try {
                        reader.read()
                    } catch (_: SocketTimeoutException) {
                        continue // a quiet server: nothing to drain
                    }
                val pingRequest =
                    message.typeId == RtmpType.USER_CONTROL &&
                        message.payload.size >= 6 &&
                        message.payload[1].toInt() == PING_REQUEST
                if (pingRequest) {
                    val pong = byteArrayOf(0, PING_RESPONSE.toByte()) + message.payload.copyOfRange(2, 6)
                    send(CONTROL_STREAM, 0, RtmpType.USER_CONTROL, 0, pong)
                }
            }
        } catch (_: IOException) {
            // The connection ended: the publishing thread finds out on its next frame.
        }
    }

    companion object {
        const val CHUNK_SIZE = 65536
        private const val BUFFER_SIZE = 1 shl 16
        private const val HANDSHAKE_SIZE = 1536
        private const val RTMP_VERSION = 3
        private const val CONTROL_STREAM = 2
        private const val COMMAND_STREAM = 3
        private const val DATA_STREAM = 4
        private const val VIDEO_STREAM = 6
        private const val PING_REQUEST = 6
        private const val PING_RESPONSE = 7
        private const val FLASH_VER = "FMLE/3.0 (compatible; PhotoFinish Camera)"
        const val CONNECT_TIMEOUT_MS = 5_000
        const val READ_TIMEOUT_MS = 10_000

        private fun handshake(
            input: InputStream,
            output: OutputStream,
        ) {
            val c1 = ByteArray(HANDSHAKE_SIZE)
            SecureRandom().nextBytes(c1)
            c1.fill(0, 0, 8) // time and zeros: the simple handshake
            output.write(RTMP_VERSION)
            output.write(c1)
            output.flush()
            if (input.read() != RTMP_VERSION) throw IOException("the server does not speak RTMP 3")
            val s1 = readFully(input, HANDSHAKE_SIZE)
            readFully(input, HANDSHAKE_SIZE) // S2, the echo of C1
            output.write(s1) // C2: the echo of S1
            output.flush()
        }

        private fun describe(values: List<Any?>): String =
            (values.getOrNull(3) as? Map<*, *>)?.get("description")?.toString() ?: values.toString()

        private fun int32(value: Long): ByteArray =
            byteArrayOf((value shr 24).toByte(), (value shr 16).toByte(), (value shr 8).toByte(), value.toByte())

        private fun readFully(
            input: InputStream,
            length: Int,
        ): ByteArray {
            val bytes = ByteArray(length)
            var offset = 0
            while (offset < length) {
                val read = input.read(bytes, offset, length - offset)
                if (read < 0) throw IOException("the server closed the connection during the handshake")
                offset += read
            }
            return bytes
        }

        fun socketConnection(address: RtmpAddress): RtmpConnection {
            val socket = Socket()
            socket.connect(InetSocketAddress(address.host, address.port), CONNECT_TIMEOUT_MS)
            socket.tcpNoDelay = true
            socket.soTimeout = READ_TIMEOUT_MS
            return object : RtmpConnection {
                override val input: InputStream = socket.getInputStream()
                override val output: OutputStream = socket.getOutputStream()

                override fun close() = socket.close()
            }
        }
    }
}
