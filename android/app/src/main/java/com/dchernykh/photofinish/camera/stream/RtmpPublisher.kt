package com.dchernykh.photofinish.camera.stream

import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.Closeable
import java.io.FilterOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.ByteBuffer
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

    /** The sound's AudioSpecificConfig, before its first piece (specs/013); nothing from a sink without sound. */
    fun sendSoundHeader(config: ByteArray) = Unit

    /** One piece of AAC sound, at [timestampMs] from the connection's first frame (specs/013). */
    fun sendSound(
        timestampMs: Long,
        piece: ByteArray,
    ) = Unit

    /** The bytes written to the server so far; 0 from a sink that does not count them. */
    val sentBytes: Long get() = 0

    /** The bytes the server says it has read so far, by its acknowledgements: 0 until it says. */
    val acknowledgedBytes: Long get() = 0

    /**
     * Asks the server to say it has read all that was sent: a ping, which it answers once it has read up to it --
     * [acknowledgedBytes] then counts it all, a tail under the acknowledgements' step too. Nothing from a sink that
     * cannot ask.
     */
    fun flush() = Unit
}

/** A connection to the server: its streams, so a test can stand in for a socket. */
interface RtmpConnection : Closeable {
    val input: InputStream
    val output: OutputStream

    /** Reads from now on wait as long as the server is quiet. */
    fun clearReadTimeout() = Unit
}

/**
 * Publishes one H.264 stream to an RTMP server -- FFmpeg's listener in PhotoFinish's
 * recorder -- as OBS and Larix do: the simple handshake, connect, releaseStream,
 * FCPublish, createStream and publish, then onMetaData, the sequence header and the
 * frames. Not thread-safe: one thread publishes; [close] may come from another.
 */
@Suppress("TooManyFunctions") // the protocol's steps, each a few lines
class RtmpPublisher(
    private val address: RtmpAddress,
    /** H.265 goes over Enhanced RTMP's tags (specs/010-hevc). */
    private val codec: Codec = Codec.AVC,
    private val connect: (RtmpAddress) -> RtmpConnection = ::socketConnection,
) : VideoSink {
    @Volatile private var connection: RtmpConnection? = null
    private lateinit var writer: RtmpChunkWriter
    private lateinit var reader: RtmpChunkReader
    private var streamId = 0

    @Volatile private var closed = false

    /** Counted as they reach the socket: the handshake and the commands too, so never fewer than the server's. */
    @Volatile override var sentBytes = 0L
        private set

    @Volatile override var acknowledgedBytes = 0L
        private set

    /** The bytes sent before each ping of ours not answered yet, by its number: its answer says all were read. */
    private val pings = java.util.concurrent.ConcurrentSkipListMap<Int, Long>()
    private var pinged = 0

    override fun flush() {
        val number = ++pinged
        pings[number] = sentBytes
        val ping = byteArrayOf(0, PING_REQUEST.toByte()) + int32(number.toLong())
        send(CONTROL_STREAM, 0, RtmpType.USER_CONTROL, 0, ping)
    }

    override fun publish(metadata: Map<String, Any?>) {
        val opened = connect(address)
        connection = opened
        if (closed) { // closed while it connected: it must not hold the server's one place
            opened.close()
            throw IOException("the stream was closed")
        }
        val counted =
            object : FilterOutputStream(opened.output) {
                override fun write(b: Int) {
                    out.write(b)
                    sentBytes++
                }

                override fun write(
                    b: ByteArray,
                    off: Int,
                    len: Int,
                ) {
                    out.write(b, off, len)
                    sentBytes += len
                }
            }
        val output = BufferedOutputStream(counted, BUFFER_SIZE)
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
        // FFmpeg acknowledges what it reads every half window, a megabyte by default: a slow stream would
        // hear none for long. Asked for one every 64 KiB, it says how far it read every moment (specs/007).
        send(CONTROL_STREAM, 0, RtmpType.WINDOW_ACK_SIZE, 0, int32(ACK_WINDOW.toLong()))
        // Publishing, the server may stay quiet for long: a read timed out then could cut a
        // message in two and leave the reader out of step.
        opened.clearReadTimeout()
        Thread({ drain() }, "rtmp-reader").apply { isDaemon = true }.start()
    }

    override fun sendSequenceHeader(record: ByteArray) {
        val tag = if (codec == Codec.HEVC) Hevc.sequenceHeaderTag(record) else Avc.sequenceHeaderTag(record)
        send(VIDEO_STREAM, 0, RtmpType.VIDEO, streamId, tag)
    }

    override fun sendFrame(
        timestampMs: Long,
        keyframe: Boolean,
        nalUnits: List<ByteArray>,
    ) {
        val tag = if (codec == Codec.HEVC) Hevc.frameTag(keyframe, nalUnits) else Avc.frameTag(keyframe, nalUnits)
        send(VIDEO_STREAM, timestampMs, RtmpType.VIDEO, streamId, tag)
    }

    override fun sendSoundHeader(config: ByteArray) {
        send(AUDIO_STREAM, 0, RtmpType.AUDIO, streamId, Aac.sequenceHeaderTag(config))
    }

    override fun sendSound(
        timestampMs: Long,
        piece: ByteArray,
    ) {
        send(AUDIO_STREAM, timestampMs, RtmpType.AUDIO, streamId, Aac.pieceTag(piece))
    }

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
     * Reads what the server sends while the frames go out, so its acknowledgements never fill the socket over
     * a long race -- each telling how far it has read (specs/007) -- and answers its pings.
     */
    @Suppress("TooGenericExceptionCaught") // an exception left to escape would end the app
    private fun drain() {
        try {
            while (!closed) {
                val message = reader.read()
                if (message.typeId == RtmpType.ACKNOWLEDGEMENT && message.payload.size >= 4) {
                    acknowledgedBytes = unwrapped(ByteBuffer.wrap(message.payload).int.toLong(), sentBytes)
                }
                val pingRequest =
                    message.typeId == RtmpType.USER_CONTROL &&
                        message.payload.size >= 6 &&
                        message.payload[1].toInt() == PING_REQUEST
                if (pingRequest) {
                    val pong = byteArrayOf(0, PING_RESPONSE.toByte()) + message.payload.copyOfRange(2, 6)
                    send(CONTROL_STREAM, 0, RtmpType.USER_CONTROL, 0, pong)
                }
                val pingResponse =
                    message.typeId == RtmpType.USER_CONTROL &&
                        message.payload.size >= 6 &&
                        message.payload[1].toInt() == PING_RESPONSE
                if (pingResponse) answered(ByteBuffer.wrap(message.payload, 2, 4).int)
            }
        } catch (_: IOException) {
            // The connection ended: closed, so that the publishing thread finds out as it next sends, idle too.
            close()
        } catch (_: RuntimeException) {
            // Bytes that are not RTMP: no more pings answered, and the frames go on.
        }
    }

    /** Our ping [number] answered: the server has read all sent before it, and before those of ours before it. */
    private fun answered(number: Int) {
        val read = pings.headMap(number, true)
        read.values.maxOrNull()?.let { bytes -> acknowledgedBytes = maxOf(acknowledgedBytes, bytes) }
        read.clear()
    }

    companion object {
        const val CHUNK_SIZE = 65536
        private const val ACK_WINDOW = 128 * 1024
        private const val BUFFER_SIZE = 1 shl 16
        private const val HANDSHAKE_SIZE = 1536
        private const val RTMP_VERSION = 3
        private const val CONTROL_STREAM = 2
        private const val COMMAND_STREAM = 3
        private const val DATA_STREAM = 4
        private const val AUDIO_STREAM = 5
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

        /**
         * The bytes the server has read, from its acknowledgement's 32 bits, which go round every 4 GiB -- half an
         * hour at 20 Mbit/s: the count at most [sent] whose low 32 bits they are.
         */
        fun unwrapped(
            acknowledged: Long,
            sent: Long,
        ): Long = sent - ((sent - acknowledged) and 0xFFFFFFFFL)

        private fun describe(values: List<Any?>): String =
            (values.getOrNull(3) as? Map<*, *>)?.get("description")?.toString() ?: values.toString()

        fun socketConnection(
            address: RtmpAddress,
            readTimeoutMs: Int = READ_TIMEOUT_MS,
        ): RtmpConnection {
            val socket = Socket()
            socket.connect(InetSocketAddress(address.host, address.port), CONNECT_TIMEOUT_MS)
            socket.tcpNoDelay = true
            socket.soTimeout = readTimeoutMs
            return object : RtmpConnection {
                override val input: InputStream = socket.getInputStream()
                override val output: OutputStream = socket.getOutputStream()

                override fun clearReadTimeout() {
                    socket.soTimeout = 0
                }

                override fun close() = socket.close()
            }
        }
    }
}
