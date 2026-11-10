package com.dchernykh.photofinish.camera.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.nio.ByteBuffer

class ClockSyncTest {
    @Test
    fun `an exchange gives the offset and the delay`() {
        // The recorder is 1000 us ahead; 10 us each way; 2 us spent answering.
        val sample = Sample(t1 = 100, t2 = 1110, t3 = 1112, t4 = 122)
        assertEquals(1000L, sample.offset)
        assertEquals(20L, sample.delay)
    }

    @Test
    fun `the offset kept is the one of the shortest delay among the recent`() {
        val offsets = ClockOffset(capacity = 3)
        assertNull(offsets.best())
        offsets.add(Sample(0, 1010, 1010, 40)) // delay 40
        offsets.add(Sample(0, 1002, 1002, 4)) // delay 4: the best
        offsets.add(Sample(0, 1020, 1020, 60))
        assertEquals(4L, offsets.best()!!.delay)
        offsets.add(Sample(0, 1020, 1020, 50))
        offsets.add(Sample(0, 1020, 1020, 50)) // the best is now older than the last three
        assertEquals(50L, offsets.best()!!.delay)
        offsets.add(Sample(10, 0, 0, 5)) // a clock gone back: a negative delay
        assertEquals(50L, offsets.best()!!.delay)
    }

    @Test
    fun `an offset no delay explains is a recorder clock that changed, and the older ones go`() {
        val offsets = ClockOffset()
        offsets.add(Sample(0, 1002, 1002, 4)) // offset 1000, delay 4: the best
        offsets.add(Sample(0, 1012, 1012, 30)) // offset 997: within what 30 us explain
        assertEquals(4L, offsets.best()!!.delay)
        offsets.add(Sample(0, 2_001_010, 2_001_010, 20)) // 2 s on: the recorder started again
        assertEquals(2_001_000L, offsets.best()!!.offset)
    }

    @Test
    fun `an old exchange gives way to a fresher one only a little worse`() {
        // The recorder's clock may move 1 ms a second towards its computer's: age counts.
        val offsets = ClockOffset()
        offsets.add(Sample(0, 1_001, 1_001, 2)) // a 2 us round trip
        offsets.add(Sample(14_000_000, 14_001_004, 14_001_004, 14_000_008)) // 8 us, 14 s on
        assertEquals(8L, offsets.best()!!.delay)
        val fresh = ClockOffset()
        fresh.add(Sample(0, 3_000, 3_000, 2_000)) // 2 ms
        fresh.add(Sample(5_000_000, 5_026_000, 5_026_000, 5_050_000)) // 50 ms, 5 s on
        assertEquals(2_000L, fresh.best()!!.delay) // much better still, though older
    }

    @Test
    fun `the messages are tagged and sized`() {
        val request = ClockExchange.request(42)
        assertEquals(ClockExchange.REQUEST_SIZE, request.size)
        assertEquals("PFTS", String(request, 0, 4))
        val answer =
            ByteBuffer
                .allocate(ClockExchange.ANSWER_SIZE)
                .put("PFTS".toByteArray())
                .put(1)
                .putLong(42)
                .putLong(7)
                .putLong(8)
                .array()
        val read = ClockExchange.answer(answer, answer.size)!!
        assertEquals(listOf(42L, 7L, 8L), listOf(read.t1, read.t2, read.t3))
        assertNull(ClockExchange.answer(answer, answer.size - 1))
        assertNull(ClockExchange.answer(answer.copyOf().also { it[0] = 'X'.code.toByte() }, answer.size))
        assertNull(ClockExchange.answer(answer.copyOf().also { it[4] = 2 }, answer.size))
    }

    @Test
    fun `an exchange with a recorder sets the offset, and silence leaves it unset`() {
        val recorder = DatagramSocket(0, InetAddress.getLoopbackAddress())
        val answering =
            Thread {
                val buffer = ByteArray(64)
                val packet = DatagramPacket(buffer, buffer.size)
                recorder.receive(packet)
                val t1 = ByteBuffer.wrap(buffer, 5, 8).getLong()
                // A stray answer first: not to this request, so not taken.
                val stray =
                    ByteBuffer
                        .allocate(29)
                        .put("PFTS".toByteArray())
                        .put(1)
                        .putLong(t1 + 1)
                        .putLong(0)
                        .putLong(0)
                        .array()
                recorder.send(DatagramPacket(stray, stray.size, packet.socketAddress))
                val answer =
                    ByteBuffer
                        .allocate(29)
                        .put("PFTS".toByteArray())
                        .put(1)
                        .putLong(t1)
                        .putLong(5_000)
                        .putLong(5_000)
                        .array()
                recorder.send(DatagramPacket(answer, answer.size, packet.socketAddress))
            }
        answering.start()
        var now = 1_000L
        val sync = ClockSync("127.0.0.1", recorder.localPort, { now++ })
        sync.start()
        val deadline = System.currentTimeMillis() + 5_000
        while (sync.offset.best() == null && System.currentTimeMillis() < deadline) Thread.sleep(10)
        sync.close()
        recorder.close()
        val best = sync.offset.best()
        assertNotNull(best)
        assertEquals(1_000L, best!!.t1)
        assertTrue(best.offset > 3_000)
    }

    @Test
    fun `an exchange nobody answers says so`() {
        val silent = DatagramSocket(0, InetAddress.getLoopbackAddress())
        val sync = ClockSync("127.0.0.1", silent.localPort, { 0 })
        sync.start()
        sync.close()
        assertFalse(sync.exchange())
        silent.close()
    }

    @Test
    fun `a host that does not resolve is an exchange unanswered`() {
        val sync = ClockSync("photofinish.invalid", 1935, { 0 })
        assertFalse(sync.exchange()) // not an exception, which would end the app
        sync.close()
    }
}
