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
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
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
    private val acknowledgeTo: Int = 0,
) : VideoSink {
    @Volatile override var sentBytes = 0L

    /** Acknowledged up to the frame [acknowledgeTo], once it is sent: the server read no further. */
    @Volatile override var acknowledgedBytes = 0L

    val metadata = CopyOnWriteArrayList<Map<String, Any?>>()
    val headers = CopyOnWriteArrayList<ByteArray>()
    val frames = LinkedBlockingQueue<Sent>()
    val closed = CountDownLatch(1)

    /** A send that waits until [gate] opens, as on a slow network; [atGate] says it is there. */
    val gate = CountDownLatch(1)
    val atGate = CountDownLatch(1)
    private var count = 0

    override fun publish(metadata: Map<String, Any?>) {
        publishFailure?.let { throw it }
        this.metadata += metadata
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
        sentBytes += nalUnits.sumOf { it.size }
        if (count == acknowledgeTo) acknowledgedBytes = sentBytes
        frames.put(Sent(timestampMs, keyframe, nalUnits))
    }

    override fun close() = closed.countDown()

    fun next(): Sent = frames.poll(5, TimeUnit.SECONDS) ?: error("no frame sent")
}

class UplinkTest {
    @get:Rule
    val temporary = TemporaryFolder()

    private val address = RtmpAddress("127.0.0.1", 1935, "live", "cam1")
    private val format = StreamFormat(Resolution(1920, 1080), 30, FpsRange(30, 30), 5_000_000)
    private val sps = byteArrayOf(0x67, 0x64, 0, 0x28)
    private val pps = byteArrayOf(0x68, 1)
    private val statuses = CopyOnWriteArrayList<UplinkStatus>()
    private val keyframesAsked = Semaphore(0)
    private val running = mutableListOf<Uplink>()
    private val kept: File get() = File(temporary.root, "kept")

    private fun uplink(
        sinks: List<VideoSink>,
        offset: Long? = 1_000_000,
        waitForClockMs: Long = 2_000,
        stallMs: Long = 5_000,
        clock: AtomicReference<Sample?> = AtomicReference(offset?.let { exchange(it) }),
        capBytes: Long = Long.MAX_VALUE,
    ): Uplink {
        val queue = ArrayDeque(sinks)
        val link =
            Uplink(
                address = address,
                format = format,
                clock = { clock.get() },
                requestKeyframe = { keyframesAsked.release() },
                report = { statuses += it },
                store = FrameStore(kept, capBytes, reserveBytes = 0, freeBytes = { Long.MAX_VALUE }),
            )
        link.connect = { synchronized(queue) { queue.removeFirst() } }
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

    /** [seconds] of frames at 10 fps, a keyframe each second. */
    private fun offerSeconds(
        link: Uplink,
        seconds: Int,
    ) = repeat(seconds * 10) { link.offer(frame(it * 100_000L, keyframe = it % 10 == 0)) }

    @After
    fun stop() = running.forEach { it.stop() }

    @Test
    fun `frames go from a keyframe on, each with its moment on the recorder's clock`() {
        val sink = FakeSink()
        val link = uplink(listOf(sink))
        start(link)
        awaitConnected()
        link.offer(frame(100_000, keyframe = false)) // before any keyframe: nothing to start from
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
        assertEquals(1L, link.dropped)
    }

    @Test
    fun `keyframes carry the phone's status after their moment, with the frames dropped so far`() {
        val sink = FakeSink()
        val link = uplink(listOf(sink))
        val asked = CopyOnWriteArrayList<Long>()
        link.status = { dropped -> "battery=57;dropped=$dropped".also { asked += dropped } }
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        link.offer(frame(33_333, keyframe = false))
        val key = sink.next()
        assertEquals(listOf(Avc.NAL_SEI, Avc.NAL_SEI, Avc.NAL_IDR), key.units.map { Avc.type(it) })
        assertEquals(1_000_000L, momentOf(key.units[0])) // the moment first, for its reader
        val status = unescape(key.units[1].copyOfRange(1, key.units[1].size))
        assertEquals("PFS1battery=57;dropped=0", String(status.copyOfRange(18, 18 + 24)))
        assertEquals(listOf(Avc.NAL_SEI, 1), sink.next().units.map { Avc.type(it) }) // a slice: no status
        assertEquals(listOf(0L), asked)
    }

    @Test
    fun `a status the phone fails to read costs the keyframe its status, not the connection`() {
        val sink = FakeSink()
        val link = uplink(listOf(sink), offset = null, waitForClockMs = 50)
        link.status = { error("no battery") }
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        assertEquals(listOf(Avc.NAL_IDR), sink.next().units.map { Avc.type(it) })
        assertFalse(statuses.any { it is UplinkStatus.Reconnecting })
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
    fun `a connection without moments sends nothing kept, after a loss either, but the next keyframe on`() {
        val first = FakeSink(failOn = 3)
        val second = FakeSink()
        val link = uplink(listOf(first, second), offset = null, waitForClockMs = 50)
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        link.offer(frame(33_333, keyframe = false))
        repeat(2) { first.next() }
        link.offer(frame(66_666, keyframe = false)) // fails: the connection is lost
        link.offer(frame(100_000, keyframe = true)) // kept meanwhile: placed by its arrival, it would be late
        link.offer(frame(133_333, keyframe = false))
        awaitConnected()
        link.offer(frame(1_000_000, keyframe = true))
        link.offer(frame(1_050_000, keyframe = false))
        assertEquals(listOf(0L, 50L), List(2) { second.next().timestampMs }) // not 0 s, 33 ms, ... again
    }

    @Test
    fun `a connection with moments after one without sends none of that one's frames again`() {
        val first = FakeSink(failOn = 4)
        val second = FakeSink()
        val clock = AtomicReference<Sample?>(null)
        val link = uplink(listOf(first, second), waitForClockMs = 50, clock = clock)
        link.stampWindowMs = 0 // the clock comes once the race is under way: left for the next connection
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        first.next()
        clock.set(exchange(2_000_000))
        link.offer(frame(33_333, keyframe = false))
        link.offer(frame(100_000, keyframe = true)) // kept with its moment, sent without: the recorder has it
        repeat(2) { first.next() }
        link.offer(frame(133_333, keyframe = false)) // fails: the connection is lost
        awaitConnected()
        link.offer(frame(1_000_000, keyframe = true))
        assertEquals(1_000_000L + 2_000_000, momentOf(second.next().units[0])) // not 100 ms, listed twice
    }

    @Test
    fun `a clock that comes early makes a new connection from the keyframe it came with`() {
        val unstamped = FakeSink()
        val stamped = FakeSink()
        val clock = AtomicReference<Sample?>(null)
        val link = uplink(listOf(unstamped, stamped), waitForClockMs = 50, clock = clock)
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        unstamped.next()
        clock.set(exchange(2_000_000))
        link.offer(frame(33_333, keyframe = true)) // read, and not sent on a connection without moments
        awaitConnected()
        assertEquals(33_333L + 2_000_000, momentOf(stamped.next().units[0]))
    }

    @Test
    fun `a better exchange moves the frames' moments two milliseconds a second, not at once`() {
        val sink = FakeSink()
        val clock = AtomicReference<Sample?>(exchange(1_000_000))
        val link = uplink(listOf(sink), clock = clock)
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        assertEquals(1_000_000L, momentOf(sink.next().units[0]))
        link.offer(frame(3_000_000, keyframe = false)) // past the first exchanges' settling
        sink.next()
        clock.set(exchange(1_005_000)) // 5 ms on, as a shorter round trip may say
        link.offer(frame(4_000_000, keyframe = false)) // a second of frames later
        assertEquals(4_000_000L + 1_002_000, momentOf(sink.next().units[0]))
    }

    @Test
    fun `a better exchange takes no frame's moment back past the one before, so one sent again carries the same`() {
        val sink = FakeSink()
        val clock = AtomicReference<Sample?>(exchange(1_000_000))
        val link = uplink(listOf(sink), clock = clock)
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        link.offer(frame(33_333, keyframe = false))
        clock.set(exchange(960_000)) // a shorter round trip at the start: 40 ms back, taken at once
        link.offer(frame(66_666, keyframe = false))
        link.offer(frame(200_000, keyframe = false))
        val moments = List(4) { momentOf(sink.next().units[0]) }
        assertEquals(listOf(1_000_000L, 1_033_333L, 1_034_333L, 1_160_000L), moments)
    }

    @Test
    fun `the recorder's clock set back takes the frames' moments back with it, at once`() {
        val sink = FakeSink()
        val clock = AtomicReference<Sample?>(exchange(60_000_000))
        val link = uplink(listOf(sink), clock = clock)
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        clock.set(exchange(1_000_000)) // a recorder started again on a clock a minute back
        link.offer(frame(33_333, keyframe = false))
        val moments = List(2) { momentOf(sink.next().units[0]) }
        assertEquals(listOf(60_000_000L, 1_033_333L), moments) // not a millisecond a frame for a minute
    }

    @Test
    fun `a clock that comes once a connection has run is left for the next, with no gap now`() {
        val sink = FakeSink()
        val clock = AtomicReference<Sample?>(null)
        val link = uplink(listOf(sink, FakeSink()), waitForClockMs = 50, clock = clock)
        link.stampWindowMs = 0 // the race under way
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        sink.next()
        clock.set(exchange(2_000_000))
        link.offer(frame(33_333, keyframe = false))
        assertEquals(listOf(Avc.type(byteArrayOf(0x41))), sink.next().units.map { Avc.type(it) })
    }

    @Test
    fun `a lost connection is made again, its header resent, from the keyframe before what it swallowed`() {
        val first = FakeSink(failOn = 3)
        val second = FakeSink()
        val link = uplink(listOf(first, second))
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        link.offer(frame(33_333, keyframe = false))
        repeat(2) { first.next() }
        link.offer(frame(66_666, keyframe = false)) // fails: the connection is lost
        awaitConnected()
        assertTrue(statuses.any { it is UplinkStatus.Reconnecting && it.reason == "lost" })
        val resumed = second.next()
        assertTrue(resumed.keyframe)
        assertEquals(0L, resumed.timestampMs) // timestamps start again with the connection
        assertEquals(1_000_000L, momentOf(resumed.units[0])) // the frame sent before, as it was
        assertEquals(listOf(33L, 66L), List(2) { second.next().timestampMs })
        assertEquals(1, second.headers.size)
    }

    @Test
    fun `after a loss the last six seconds go again, with the moments they were kept with`() {
        val first = FakeSink(failOn = 101) // 10 s of frames arrive; the eleventh second's is lost
        val second = FakeSink()
        val clock = AtomicReference<Sample?>(exchange(1_000_000))
        val link = uplink(listOf(first, second), clock = clock)
        offerSeconds(link, 11) // kept through a break, before the uplink connects
        clock.set(exchange(1_300_000)) // the clock moved meanwhile: what was kept keeps its moments
        start(link)
        repeat(100) { first.next() }
        val resumed = second.next()
        assertTrue(resumed.keyframe)
        assertEquals(4_000_000L + 1_000_000, momentOf(resumed.units[0])) // 6 s before 10 s, its keyframe
        assertEquals(100L, second.next().timestampMs)
    }

    @Test
    fun `after a loss frames go again from two seconds before the newest the server read`() {
        val first = FakeSink(failOn = 101, acknowledgeTo = 31) // read to 3.0 s; the rest lost on the way
        val second = FakeSink()
        val link = uplink(listOf(first, second))
        offerSeconds(link, 11)
        start(link)
        repeat(100) { first.next() }
        val resumed = second.next()
        assertTrue(resumed.keyframe)
        assertEquals(1_000_000L + 1_000_000, momentOf(resumed.units[0])) // 1.0 s, not 4.0 s
    }

    @Test
    fun `a connection says how long its first frame was kept`() {
        val refused = FakeSink(publishFailure = IllegalStateException("refused"))
        val second = FakeSink()
        val link = uplink(listOf(refused, second))
        link.captureClock = { 9_000_000 }
        link.offer(frame(0, keyframe = true))
        start(link)
        awaitConnected()
        val said = second.metadata.single()
        assertEquals(9_000L, said["held_ms"])
        assertEquals("PhotoFinish Camera", said["encoder"])
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
    fun `a connection that streamed is made again at once after each loss, all day`() {
        val sinks = List(5) { FakeSink(failOn = 2) } // each sends the keyframe again, then loses the next
        val link = uplink(sinks)
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        link.offer(frame(33_333, keyframe = false))
        for (sink in sinks.dropLast(1)) {
            sink.next()
            val since = System.nanoTime()
            awaitConnected() // the next, soon
            assertTrue((System.nanoTime() - since) / 1_000_000 < 900)
        }
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
    fun `frames the store has no room for are counted, with no keyframe asked for, as the next run has its own`() {
        val link = uplink(emptyList(), capBytes = 10) // room for one frame of 6 bytes, and a run more
        link.offer(frame(0, keyframe = true))
        link.offer(frame(1_000_000, keyframe = false))
        repeat(3) { link.offer(frame((it + 2) * 1_000_000L, keyframe = true)) } // two make room
        assertEquals(3L, link.dropped)
        assertFalse(keyframesAsked.tryAcquire()) // a keyframe asked for each would make more to keep
    }

    @Test
    fun `a frame the store cannot keep has a keyframe asked for, once until one comes`() {
        val link = uplink(emptyList())
        link.offer(frame(0, keyframe = true))
        kept.deleteRecursively()
        kept.writeBytes(ByteArray(0)) // a file where the folder was: nothing more can be written
        link.offer(frame(100_000, keyframe = true))
        assertFalse(keyframesAsked.tryAcquire()) // a keyframe lost: the frames after it ask
        repeat(2) { link.offer(frame((it + 2) * 100_000L, keyframe = false)) }
        assertTrue(keyframesAsked.tryAcquire())
        assertFalse(keyframesAsked.tryAcquire())
        assertEquals(3L, link.dropped)
    }

    @Test
    fun `a keyframe tells the frames dropped in the last minute, not since the start`() {
        val sink = FakeSink(gateOn = 2)
        val link = uplink(listOf(sink), capBytes = 10)
        var now = 0L
        link.nanos = { now }
        val told = CopyOnWriteArrayList<Long>()
        link.status = { dropped -> null.also { told += dropped } }
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        link.offer(frame(1_000_000, keyframe = false))
        assertTrue(sink.atGate.await(5, TimeUnit.SECONDS)) // its send is under way
        link.offer(frame(2_000_000, keyframe = true))
        link.offer(frame(3_000_000, keyframe = false))
        link.offer(frame(4_000_000, keyframe = true)) // no room: the 2 s and 3 s frames go unsent
        sink.gate.countDown()
        repeat(3) { sink.next() }
        now = 61_000_000_000L // a minute on
        link.offer(frame(5_000_000, keyframe = true))
        sink.next()
        assertEquals(listOf(0L, 2L, 0L), told.toList())
    }

    @Test
    fun `frames kept while a send waits all go after it, in order`() {
        val sink = FakeSink(gateOn = 2)
        val link = uplink(listOf(sink))
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        link.offer(frame(1_000_000, keyframe = false))
        assertTrue(sink.atGate.await(5, TimeUnit.SECONDS)) // its send is under way: a slow network
        repeat(4) { link.offer(frame((it + 2) * 1_000_000L, keyframe = it == 3)) }
        sink.gate.countDown()
        assertEquals(listOf(0L, 1_000L, 2_000L, 3_000L, 4_000L, 5_000L), List(6) { sink.next().timestampMs })
        assertEquals(0L, link.dropped)
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
        assertTrue(second.next().keyframe) // the frame the hung send never delivered
    }

    @Test
    fun `stop ends the loop and drops what is kept`() {
        val sink = FakeSink()
        val link = uplink(listOf(sink))
        val thread = start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        sink.next() // sent, and kept to be sent again after a loss
        link.stop()
        thread.join(5_000)
        assertFalse(thread.isAlive)
        assertTrue(kept.listFiles()!!.isEmpty())
    }
}
