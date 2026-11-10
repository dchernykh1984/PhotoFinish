package com.dchernykh.photofinish.camera.stream

import com.dchernykh.photofinish.camera.capture.FpsRange
import com.dchernykh.photofinish.camera.capture.Resolution
import com.dchernykh.photofinish.camera.capture.StreamFormat
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import com.dchernykh.photofinish.camera.sync.Sample
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** A frame as a sink received it. */
private class Sent(
    val timestampMs: Long,
    val keyframe: Boolean,
    val units: List<ByteArray>,
)

/** A stand-in for the server: records what it is sent; may fail or hang on a frame. */
private class FakeSink(
    private val failOn: Int = 0,
    private val hangOn: Int = 0,
    private val publishFailure: RuntimeException? = null,
    private val gateOn: Int = 0,
) : VideoSink {
    val headers = CopyOnWriteArrayList<ByteArray>()
    val frames = LinkedBlockingQueue<Sent>()
    val closed = CountDownLatch(1)

    /** A send that waits until [gate] opens, as on a slow network; [atGate] says it is there. */
    val gate = CountDownLatch(1)
    val atGate = CountDownLatch(1)
    private var count = 0

    override fun publish(metadata: Map<String, Any?>) {
        publishFailure?.let { throw it }
    }

    override fun sendSequenceHeader(record: ByteArray) {
        headers += record
    }

    override fun sendFrame(
        timestampMs: Long,
        keyframe: Boolean,
        nalUnits: List<ByteArray>,
    ) {
        count++
        if (count == gateOn) {
            atGate.countDown()
            gate.await(5, TimeUnit.SECONDS)
        }
        if (count == failOn) throw IOException("lost")
        if (count == hangOn) {
            closed.await(5, TimeUnit.SECONDS) // a dead Wi-Fi: the send hangs until closed
            throw IOException("closed")
        }
        frames.put(Sent(timestampMs, keyframe, nalUnits))
    }

    override fun close() = closed.countDown()

    fun next(): Sent = frames.poll(5, TimeUnit.SECONDS) ?: error("no frame sent")
}

class UplinkTest {
    private val address = RtmpAddress("127.0.0.1", 1935, "live", "cam1")
    private val format = StreamFormat(Resolution(1920, 1080), 30, FpsRange(30, 30), 5_000_000)
    private val sps = byteArrayOf(0x67, 0x64, 0, 0x28)
    private val pps = byteArrayOf(0x68, 1)
    private val statuses = CopyOnWriteArrayList<UplinkStatus>()
    private val keyframesAsked = Semaphore(0)
    private val running = mutableListOf<Uplink>()

    private fun uplink(
        sinks: List<VideoSink>,
        offset: Long? = 1_000_000,
        waitForClockMs: Long = 2_000,
        stallMs: Long = 5_000,
        fps: Int = 30,
        clock: AtomicReference<Sample?> = AtomicReference(offset?.let { exchange(it) }),
    ): Uplink {
        val queue = ArrayDeque(sinks)
        val link =
            Uplink(
                address = address,
                format = format.copy(fps = fps),
                clock = { clock.get() },
                requestKeyframe = { keyframesAsked.release() },
                report = { statuses += it },
                connect = { synchronized(queue) { queue.removeFirst() } },
            )
        link.waitForClockMs = waitForClockMs
        link.stallMs = stallMs
        link.configure(sps, pps)
        running += link
        return link
    }

    private fun start(link: Uplink) = Thread { link.run() }.apply { start() }

    /** An exchange 1.5 ms long that puts the recorder [offset] us ahead. */
    private fun exchange(offset: Long) = Sample(t1 = 0, t2 = offset + 750, t3 = offset + 750, t4 = 1_500)

    /** Waits for the uplink to be ready for frames: it asks for a keyframe once connected. */
    private fun awaitConnected() = assertTrue(keyframesAsked.tryAcquire(5, TimeUnit.SECONDS))

    private fun frame(
        ptsUs: Long,
        keyframe: Boolean,
    ) = EncodedFrame(byteArrayOf(0, 0, 0, 1, if (keyframe) 0x65 else 0x41, 7), ptsUs, keyframe)

    @After
    fun stop() = running.forEach { it.stop() }

    @Test
    fun `frames go from a keyframe on, each with its moment on the recorder's clock`() {
        val sink = FakeSink()
        val link = uplink(listOf(sink))
        start(link)
        awaitConnected()
        link.offer(frame(100_000, keyframe = false)) // before any keyframe: not sent
        link.offer(frame(133_333, keyframe = true))
        link.offer(frame(166_666, keyframe = false))
        val key = sink.next()
        assertEquals(0L, key.timestampMs)
        assertTrue(key.keyframe)
        assertEquals(listOf(Avc.NAL_SEI, Avc.NAL_IDR), key.units.map { Avc.type(it) })
        assertEquals(133_333L + 1_000_000, momentOf(key.units[0]))
        assertEquals(33L, sink.next().timestampMs)
        assertArrayEquals(Avc.configurationRecord(sps, pps), sink.headers.single())
        assertTrue(statuses.first() is UplinkStatus.Connecting)
    }

    @Test
    fun `without the clock frames go without moments, and it is said`() {
        val sink = FakeSink()
        val link = uplink(listOf(sink), offset = null, waitForClockMs = 50)
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        assertEquals(listOf(Avc.NAL_IDR), sink.next().units.map { Avc.type(it) })
        repeat(40) { link.offer(frame((it + 1) * 33_333L, keyframe = false)) }
        val deadline = System.currentTimeMillis() + 5_000
        while (statuses.none { it is UplinkStatus.Streaming } && System.currentTimeMillis() < deadline) {
            link.offer(frame(System.nanoTime() / 1000, keyframe = false))
            Thread.sleep(50)
        }
        val streaming = statuses.filterIsInstance<UplinkStatus.Streaming>().first()
        assertEquals(null, streaming.clockMs)
    }

    @Test
    fun `a clock that comes late makes a new connection, whose frames all carry their moments`() {
        val unstamped = FakeSink()
        val stamped = FakeSink()
        val clock = AtomicReference<Sample?>(null)
        val link = uplink(listOf(unstamped, stamped), waitForClockMs = 50, clock = clock)
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        assertEquals(listOf(Avc.NAL_IDR), unstamped.next().units.map { Avc.type(it) })
        clock.set(exchange(2_000_000)) // the exchange gets through at last
        link.offer(frame(33_333, keyframe = false)) // not on a connection whose frames had none
        awaitConnected()
        link.offer(frame(66_666, keyframe = true))
        val first = stamped.next()
        assertEquals(Avc.NAL_SEI, Avc.type(first.units[0]))
        assertEquals(66_666L + 2_000_000, momentOf(first.units[0]))
        assertTrue(unstamped.frames.isEmpty())
    }

    @Test
    fun `a better exchange moves the frames' moments a millisecond a second, not at once`() {
        val sink = FakeSink()
        val clock = AtomicReference<Sample?>(exchange(1_000_000))
        val link = uplink(listOf(sink), clock = clock)
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        assertEquals(1_000_000L, momentOf(sink.next().units[0]))
        clock.set(exchange(1_005_000)) // 5 ms on, as a shorter round trip may say
        link.offer(frame(1_000_000, keyframe = false)) // a second of frames later
        assertEquals(1_000_000L + 1_001_000, momentOf(sink.next().units[0]))
    }

    @Test
    fun `a lost connection is made again, its header resent, from a keyframe`() {
        val first = FakeSink(failOn = 2)
        val second = FakeSink()
        val link = uplink(listOf(first, second))
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        first.next()
        link.offer(frame(33_333, keyframe = false)) // fails: the connection is lost
        awaitConnected()
        assertTrue(statuses.any { it is UplinkStatus.Reconnecting && it.reason == "lost" })
        link.offer(frame(66_666, keyframe = false))
        link.offer(frame(100_000, keyframe = true))
        val resumed = second.next()
        assertTrue(resumed.keyframe)
        assertEquals(0L, resumed.timestampMs) // timestamps start again with the connection
        assertEquals(1, second.headers.size)
    }

    @Test
    fun `a send that failed leaves the next connection to run`() {
        val first = FakeSink(failOn = 2)
        val second = FakeSink()
        val link = uplink(listOf(first, second), stallMs = 200)
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        first.next()
        link.offer(frame(33_333, keyframe = false)) // fails: the connection is lost
        awaitConnected() // after the pause, longer than a stall
        assertFalse(second.closed.await(600, TimeUnit.MILLISECONDS))
    }

    @Test
    fun `an answer the publisher cannot read is a lost connection too`() {
        val garbled = FakeSink(publishFailure = IllegalArgumentException("AMF0 type 12"))
        val link = uplink(listOf(garbled, FakeSink()))
        start(link)
        awaitConnected() // the second connection: the first one's failure did not end the uplink
        assertTrue(statuses.any { it is UplinkStatus.Reconnecting && it.reason == "AMF0 type 12" })
    }

    @Test
    fun `a full queue is emptied, counted and a keyframe asked for`() {
        val link = uplink(emptyList(), fps = 1) // two seconds at 1 fps: room for 2
        repeat(3) { link.offer(frame(it * 1_000_000L, keyframe = it == 0)) }
        assertEquals(3L, link.dropped)
        assertTrue(keyframesAsked.tryAcquire())
    }

    @Test
    fun `frames dropped while a send waits are followed by a keyframe, not by what came after`() {
        val sink = FakeSink(gateOn = 2)
        val link = uplink(listOf(sink), fps = 1) // room for two frames
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        link.offer(frame(1_000_000, keyframe = false))
        assertTrue(sink.atGate.await(5, TimeUnit.SECONDS)) // its send is under way
        repeat(3) { link.offer(frame((it + 2) * 1_000_000L, keyframe = false)) } // dropped
        link.offer(frame(5_000_000, keyframe = false)) // after a gap: no picture without its keyframe
        link.offer(frame(6_000_000, keyframe = true))
        sink.gate.countDown()
        assertEquals(listOf(0L, 1_000L, 6_000L), List(3) { sink.next().timestampMs })
    }

    @Test
    fun `a send that hangs is cut, and the uplink connects again`() {
        val hanging = FakeSink(hangOn = 1)
        val second = FakeSink()
        val link = uplink(listOf(hanging, second), stallMs = 200)
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        assertTrue(hanging.closed.await(5, TimeUnit.SECONDS))
        awaitConnected()
        link.offer(frame(33_333, keyframe = true))
        assertTrue(second.next().keyframe)
    }

    @Test
    fun `stop ends the loop`() {
        val link = uplink(listOf(FakeSink()))
        val thread = start(link)
        awaitConnected()
        link.stop()
        thread.join(5_000)
        assertFalse(thread.isAlive)
    }
}
