package com.dchernykh.photofinish.camera.diagnostics

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.SocketTimeoutException

/** A recorder's end of the log: what it was sent, and its answers. */
private class FakeRecorder {
    val socket = DatagramSocket(0, InetAddress.getLoopbackAddress()).apply { soTimeout = 200 }
    val port: Int get() = socket.localPort

    /** The line the last round began with, as its messages said, and each message's line before its first. */
    var from = 0L
    val prevs = mutableListOf<Long>()

    /** The lines of the messages received now, by their numbers. */
    fun received(): List<Long> {
        val seqs = mutableListOf<Long>()
        val buffer = ByteArray(2_048)
        while (true) {
            val packet = DatagramPacket(buffer, buffer.size)
            try {
                socket.receive(packet)
            } catch (_: SocketTimeoutException) {
                return seqs
            }
            val lines = String(buffer, 0, packet.length, Charsets.UTF_8).trim().lines()
            val head = lines.first().split(' ')
            from = head[3].toLong()
            prevs += head[4].toLong()
            seqs += lines.drop(1).map { it.substringBefore(' ').toLong() }
            last = packet
        }
    }

    private var last: DatagramPacket? = null

    fun answer(
        run: String,
        seq: Long,
    ) {
        val bytes = "PFLG 1 $run $seq\n".toByteArray()
        socket.send(DatagramPacket(bytes, bytes.size, last!!.socketAddress))
    }
}

class LogSenderTest {
    private var now = 0L
    private val log = PhoneLog(clockMs = { 1_000_000L + now })
    private val recorder = FakeRecorder()
    private val opened = mutableListOf<LogSender>()

    private fun sender(to: () -> List<Pair<String, Int>> = { listOf("127.0.0.1" to recorder.port) }) =
        LogSender(log, to, nowMs = { now }).also { opened += it }

    @After
    fun close() {
        opened.forEach { it.close() }
        recorder.socket.close()
    }

    @Test
    fun `lines go from the one after the newest answered, again until answered`() {
        val sender = sender()
        repeat(3) { log.info(null, "line $it") }
        sender.round()
        assertEquals(listOf(1L, 2L, 3L), recorder.received())
        recorder.answer(log.run, 2) // the message with line 3 is lost on the way
        sender.hear()
        assertEquals(2L, sender.answered("127.0.0.1", recorder.port))
        now += 500
        sender.round()
        assertEquals(listOf(3L), recorder.received())
        assertEquals(3L, recorder.from) // the round begins after the newest answered
        recorder.answer(log.run, 3)
        sender.hear()
        now += 500
        sender.round()
        assertEquals(emptyList<Long>(), recorder.received()) // nothing new: nothing sent
    }

    @Test
    fun `no answer in time is no answer, and nothing more`() {
        val sender = sender()
        sender.hear() // the emulator's crash: a packet that never came asked who sent it
        assertNull(sender.answered("127.0.0.1", recorder.port))
    }

    @Test
    fun `a round that throws costs that round alone, the sender going on`() {
        var calls = 0
        val sender =
            sender {
                if (calls++ == 0) error("a code that cannot be read now")
                listOf("127.0.0.1" to recorder.port)
            }
        log.info(null, "line")
        sender.start()
        val deadline = System.currentTimeMillis() + 5_000
        var seen = emptyList<Long>()
        while (seen.isEmpty() && System.currentTimeMillis() < deadline) seen = recorder.received()
        assertTrue(seen.isNotEmpty())
        assertTrue(log.after(0).any { it.text.startsWith("the log could not be sent: IllegalStateException") })
    }

    @Test
    fun `a backlog goes in several messages a round once the recorder answers, each saying where the round began`() {
        val sender = sender()
        repeat(20) { log.info(null, "x".repeat(300) + it) } // three to a message
        sender.round()
        assertEquals(listOf(1L, 2L, 3L), recorder.received()) // one, till it is known to answer
        recorder.answer(log.run, 3)
        sender.hear()
        now += 500
        recorder.prevs.clear()
        sender.round()
        assertEquals((4L..20L).toList(), recorder.received())
        assertEquals(4L, recorder.from)
        assertEquals(listOf(3L, 6L, 9L, 12L, 15L, 18L), recorder.prevs) // each after the one before
    }

    @Test
    fun `lines the phone let go of between kept ones leave gaps the messages carry`() {
        val small = PhoneLog(capacity = 4, clockMs = { 1_000_000L + now })
        val sender = LogSender(small, { listOf("127.0.0.1" to recorder.port) }, nowMs = { now }).also { opened += it }
        small.info(null, "start")
        small.system('e', "driver: one")
        small.error(null, "camera error 4")
        small.system('e', "driver: two")
        small.info(null, "connecting") // full: the system log's oldest goes, from between
        sender.round()
        assertEquals(listOf(1L, 3L, 4L, 5L), recorder.received())
        assertEquals(listOf(0L), recorder.prevs)
    }

    @Test
    fun `lines the phone no longer keeps are passed over, the round beginning at the oldest kept`() {
        val small = PhoneLog(capacity = 2, clockMs = { 1_000_000L + now })
        val sender = LogSender(small, { listOf("127.0.0.1" to recorder.port) }, nowMs = { now }).also { opened += it }
        repeat(5) { small.info(null, "line $it") }
        sender.round()
        assertEquals(listOf(4L, 5L), recorder.received())
        assertEquals(4L, recorder.from) // the recorder says lines 1 to 3 were lost on the phone
    }

    @Test
    fun `an answer of another run, or from no recorder sent to, is passed over`() {
        val sender = sender()
        log.info(null, "line")
        sender.round()
        recorder.received()
        recorder.answer("fedcba9876543210", 1)
        sender.hear()
        assertEquals(0L, sender.answered("127.0.0.1", recorder.port))
        val stranger = DatagramSocket(0, InetAddress.getLoopbackAddress())
        val bytes = "PFLG 1 ${log.run} 1\n".toByteArray()
        stranger.send(DatagramPacket(bytes, bytes.size, InetAddress.getLoopbackAddress(), 1))
        stranger.close()
        sender.hear()
        assertEquals(0L, sender.answered("127.0.0.1", recorder.port))
    }

    @Test
    fun `a recorder that answers nothing is sent to every five seconds, after ten`() {
        val sender = sender()
        log.info(null, "line")
        var sent = 0
        repeat(60) {
            // thirty seconds, two rounds a second
            sender.round()
            sent += recorder.received().size.coerceAtMost(1)
            now += 500
        }
        assertEquals(21 + 3, sent) // every round for ten seconds, then at 15, 20 and 25 s
    }

    @Test
    fun `a recorder no longer in the code is forgotten`() {
        var to = listOf("127.0.0.1" to recorder.port)
        val sender = sender { to }
        log.info(null, "line")
        sender.round()
        to = emptyList()
        sender.round()
        assertNull(sender.answered("127.0.0.1", recorder.port))
        to = listOf("no-such-host.invalid" to 1)
        sender.round() // a name that does not resolve is left for a later round
        assertTrue(recorder.received().size == 1)
    }

    @Test
    fun `the log goes to each recorder the kept pairing code names, once`() {
        val code = "main rtmp://10.89.30.50:1935/live/cam7\ntelephoto rtmp://10.89.30.50:1937/live/cam9"
        assertEquals(listOf("10.89.30.50" to 1935, "10.89.30.50" to 1937), LogSender.recordersOf(code))
        assertEquals(listOf("10.0.0.5" to 1935), LogSender.recordersOf("rtmp://10.0.0.5/live/phone"))
        assertEquals(emptyList<Pair<String, Int>>(), LogSender.recordersOf(""))
    }

    @Test
    fun `a recorder whose name does not resolve now is kept, with what it answered`() {
        val sender = sender { listOf("no-such-host.invalid" to 1) }
        log.info(null, "line")
        sender.round() // not found: nothing sent, the recorder not forgotten
        assertEquals(0L, sender.answered("no-such-host.invalid", 1))
    }
}
