package com.dchernykh.photofinish.camera.stream

import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** A server that speaks just enough RTMP, as FFmpeg's listener does, to be published to. */
private class FakeServer(
    private val refuse: String? = null,
) : AutoCloseable {
    val socket = ServerSocket(0, 1, InetAddress.getLoopbackAddress())
    val received = LinkedBlockingQueue<RtmpMessage>()
    private lateinit var client: Socket
    private lateinit var writer: RtmpChunkWriter

    val address get() = RtmpAddress("127.0.0.1", socket.localPort, "live", "cam1")

    fun serve() =
        Thread {
            client = socket.accept()
            val input = client.getInputStream()
            val output = client.getOutputStream()
            check(input.read() == 3)
            val c1 = input.readNBytes(1536)
            val s1 = ByteArray(1536) { (it * 7).toByte() }
            output.write(byteArrayOf(3) + s1 + c1)
            output.flush()
            check(input.readNBytes(1536).contentEquals(s1)) { "C2 must echo S1" }
            val reader = RtmpChunkReader(input)
            writer = RtmpChunkWriter(output)
            try {
                while (true) {
                    val message = reader.read()
                    received.put(message)
                    if (message.typeId == RtmpType.COMMAND_AMF0) answer(Amf0.decode(message.payload))
                }
            } catch (_: IOException) {
                // the client went
            }
        }.apply { start() }

    private fun answer(command: List<Any?>) {
        val transaction = command[1]
        when (command[0]) {
            "connect" ->
                reply(
                    if (refuse == "connect") "_error" else "_result",
                    transaction,
                    null,
                    mapOf("code" to "NetConnection.Connect.Success", "description" to "no"),
                )
            "createStream" -> reply("_result", transaction, null, 1.0)
            "publish" ->
                reply(
                    "onStatus",
                    0,
                    null,
                    if (refuse == "publish") {
                        mapOf("level" to "error", "code" to "NetStream.Publish.BadName")
                    } else {
                        mapOf("level" to "status", "code" to "NetStream.Publish.Start")
                    },
                )
        }
    }

    private fun reply(vararg values: Any?) {
        // A window size first, as FFmpeg sends, which the client reads past.
        writer.write(RtmpMessage(2, 0, RtmpType.WINDOW_ACK_SIZE, 0, byteArrayOf(0, 0x26, 0x25, 0xA0.toByte())))
        writer.write(RtmpMessage(3, 0, RtmpType.COMMAND_AMF0, 0, Amf0.encode(*values)))
    }

    fun ping() = writer.write(RtmpMessage(2, 0, RtmpType.USER_CONTROL, 0, byteArrayOf(0, 6, 0, 0, 1, 2)))

    fun next(): RtmpMessage = received.poll(5, TimeUnit.SECONDS) ?: error("nothing received")

    fun nextOfType(type: Int): RtmpMessage {
        while (true) {
            val message = next()
            if (message.typeId == type) return message
        }
    }

    override fun close() = socket.close()
}

class RtmpPublisherTest {
    private val servers = mutableListOf<FakeServer>()

    private fun server(refuse: String? = null) = FakeServer(refuse).also { servers += it }

    @After
    fun closeServers() = servers.forEach { it.close() }

    @Test
    fun `it publishes as FFmpeg's listener expects, then the frames`() {
        val server = server()
        server.serve()
        val publisher = RtmpPublisher(server.address)
        publisher.publish(mapOf("width" to 1920, "height" to 1080, "framerate" to 60, "videocodecid" to 7))

        assertEquals(RtmpType.SET_CHUNK_SIZE, server.next().typeId)
        val connect = Amf0.decode(server.nextOfType(RtmpType.COMMAND_AMF0).payload)
        assertEquals("connect", connect[0])
        val app = connect[2] as Map<*, *>
        assertEquals("live", app["app"])
        assertEquals("rtmp://127.0.0.1:${server.socket.localPort}/live", app["tcUrl"])
        val names = List(4) { Amf0.decode(server.nextOfType(RtmpType.COMMAND_AMF0).payload)[0] }
        assertEquals(listOf("releaseStream", "FCPublish", "createStream", "publish"), names)

        val metadata = server.nextOfType(RtmpType.DATA_AMF0)
        assertEquals(1, metadata.streamId)
        val values = Amf0.decode(metadata.payload)
        assertEquals(listOf("@setDataFrame", "onMetaData"), values.take(2))
        assertEquals(1920.0, (values[2] as Map<*, *>)["width"])

        publisher.sendSequenceHeader(byteArrayOf(1, 0x64, 0, 0x28))
        val header = server.nextOfType(RtmpType.VIDEO)
        assertArrayEquals(byteArrayOf(0x17, 0, 0, 0, 0, 1, 0x64, 0, 0x28), header.payload)

        val sixHours = 6L * 3600 * 1000
        val frame = ByteArray(100_000) { 1 } // more than one chunk
        publisher.sendFrame(sixHours, keyframe = true, nalUnits = listOf(Sei.frameMoment(42), frame))
        val sent = server.nextOfType(RtmpType.VIDEO)
        assertEquals(sixHours, sent.timestamp)
        assertEquals(5 + 4 + Sei.frameMoment(42).size + 4 + frame.size, sent.payload.size)

        server.ping()
        val pong = server.nextOfType(RtmpType.USER_CONTROL)
        assertArrayEquals(byteArrayOf(0, 7, 0, 0, 1, 2), pong.payload)

        publisher.close()
        assertThrows(IOException::class.java) { publisher.sendFrame(0, false, listOf(byteArrayOf(1))) }
    }

    @Test
    fun `a refused connection or publish throws`() {
        for (refuse in listOf("connect", "publish")) {
            val server = server(refuse)
            server.serve()
            val error = assertThrows(IOException::class.java) { RtmpPublisher(server.address).publish(emptyMap()) }
            assertTrue(error.message!!, error.message!!.startsWith("the server refused"))
        }
    }

    @Test
    fun `a server that is not RTMP fails the handshake`() {
        val server = ServerSocket(0, 1, InetAddress.getLoopbackAddress())
        Thread {
            server.accept().use {
                it.getInputStream().readNBytes(1537)
                it.getOutputStream().write(byteArrayOf(9))
            }
        }.start()
        val address = RtmpAddress("127.0.0.1", server.localPort, "live", "x")
        assertThrows(IOException::class.java) { RtmpPublisher(address).publish(emptyMap()) }
        server.close()
    }
}
