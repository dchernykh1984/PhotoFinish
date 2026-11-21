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
import org.junit.Assert.assertNull
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
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
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
    /** Answers a ping as FFmpeg does: all sent before it read. */
    private val answersPings: Boolean = false,
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

    val soundHeaders = CopyOnWriteArrayList<ByteArray>()
    val sounds = LinkedBlockingQueue<Pair<Long, ByteArray>>()

    override fun sendSoundHeader(config: ByteArray) {
        soundHeaders += config
    }

    override fun sendSound(
        timestampMs: Long,
        piece: ByteArray,
    ) {
        sentBytes += piece.size
        sounds.put(timestampMs to piece)
    }

    val pinged = AtomicInteger()

    override fun flush() {
        if (closed.count == 0L) throw IOException("closed")
        pinged.incrementAndGet()
        if (answersPings) acknowledgedBytes = sentBytes
    }

    fun next(): Sent = frames.poll(5, TimeUnit.SECONDS) ?: error("no frame sent")
}

@Suppress("LargeClass") // the uplink's ways, a test each, on its helpers
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
        floorBytes: Long = Long.MAX_VALUE,
    ): Uplink {
        val queue = ArrayDeque(sinks)
        val link =
            Uplink(
                address = address,
                format = format,
                clock = { clock.get() },
                requestKeyframe = { keyframesAsked.release() },
                report = { statuses += it },
                // [floorBytes] all it holds: the phone short of its reserve, frames past the last 2 s give way
                store = FrameStore(kept, floorBytes, Long.MAX_VALUE, minFreeBytes = 0, freeBytes = { 0 }),
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
    fun `a clock in step since a connection began makes a new one when a camera feeds the lens again`() {
        val unstamped = FakeSink()
        val stamped = FakeSink()
        val clock = AtomicReference<Sample?>(null)
        val link = uplink(listOf(unstamped, stamped), waitForClockMs = 50, clock = clock)
        link.stampWindowMs = 0 // the clock comes once the race is under way: left for the next connection
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        unstamped.next()
        clock.set(exchange(2_000_000))
        link.offer(frame(100_000, keyframe = true)) // kept with its moment, sent without
        unstamped.next()
        link.stampWindowMs = 10_000
        link.stampAgain() // its camera lost and opened again: the lens's frames start anew
        link.offer(frame(3_000_000, keyframe = true))
        awaitConnected()
        assertEquals(3_000_000L + 2_000_000, momentOf(stamped.next().units[0])) // with its moment, as at a start
    }

    @Test
    fun `a feed's new connection waits for a keyframe, a run under way sent whole on the one going`() {
        val unstamped = FakeSink(gateOn = 2)
        val stamped = FakeSink()
        val clock = AtomicReference<Sample?>(null)
        val link = uplink(listOf(unstamped, stamped), waitForClockMs = 50, clock = clock)
        link.stampWindowMs = 0 // the clock comes once the race is under way: left for the next connection
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        unstamped.next()
        clock.set(exchange(2_000_000))
        link.offer(frame(100_000, keyframe = true))
        assertTrue(unstamped.atGate.await(5, TimeUnit.SECONDS)) // its send held, as on a slow network
        link.offer(frame(133_333, keyframe = false)) // its run kept, with moments, unsent
        link.offer(frame(166_666, keyframe = false))
        link.stampWindowMs = 10_000
        link.stampAgain() // its camera opened again meanwhile
        unstamped.gate.countDown()
        repeat(3) { unstamped.next() } // the run under way all sent, none skipped for the new connection
        link.offer(frame(200_000, keyframe = true))
        awaitConnected()
        assertEquals(200_000L + 2_000_000, momentOf(stamped.next().units[0])) // the new one from the keyframe
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
    fun `a lens waiting for its clock is not connected yet, holding no other lens back`() {
        val sink = FakeSink()
        val link = uplink(listOf(sink), offset = null) // no clock: it waits for one, then goes without
        start(link)
        Thread.sleep(300)
        assertFalse(link.connected)
        awaitConnected()
        assertTrue(link.connected)
    }

    @Test
    fun `a tail under the acknowledgements' step is asked for once idle, the frames then sent`() {
        val sink = FakeSink(answersPings = true) // acknowledges no window: a stream of a few small frames
        val link = uplink(listOf(sink))
        start(link)
        awaitConnected()
        repeat(5) { link.offer(frame(it * 100_000L, keyframe = it == 0)) }
        repeat(5) { sink.next() }
        val deadline = System.currentTimeMillis() + 5_000
        while (link.unsent && System.currentTimeMillis() < deadline) Thread.sleep(20)
        assertFalse(link.unsent) // a kept stream ends, never holding its camera for good
        assertTrue(sink.pinged.get() >= 1)
    }

    @Test
    fun `an idle connection that says nothing of what it was sent is let go, the frames sent again`() {
        val silent = FakeSink() // neither acknowledges nor answers: a connection gone
        val again = FakeSink(answersPings = true)
        val link = uplink(listOf(silent, again))
        link.answerWaitMs = 300
        start(link)
        awaitConnected()
        repeat(5) { link.offer(frame(it * 100_000L, keyframe = it == 0)) }
        repeat(5) { silent.next() }
        assertEquals(0L, again.next().timestampMs) // sent again from its keyframe on the next connection
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
    fun `how long a connection's first frame was kept is told of the frame it starts at`() {
        val sink = FakeSink()
        val clock = AtomicReference<Sample?>(null)
        val link = uplink(listOf(sink), clock = clock)
        link.captureClock = { 9_000_000 }
        link.offer(frame(0, keyframe = true)) // kept before the clock came: not sent
        clock.set(exchange(1_000_000))
        link.offer(frame(5_000_000, keyframe = true))
        start(link)
        awaitConnected()
        assertEquals(4_000L, sink.metadata.single()["held_ms"]) // the keyframe of 5 s, not that of 0 s
        assertEquals(5_000_000L + 1_000_000, momentOf(sink.next().units[0]))
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
        val link = uplink(emptyList(), floorBytes = 10) // room for one frame of 6 bytes, and a run more
        link.offer(frame(0, keyframe = true))
        link.offer(frame(1_000_000, keyframe = false))
        repeat(3) { link.offer(frame((it + 2) * 1_000_000L, keyframe = true)) } // the run of 0 s goes at 4 s
        assertEquals(2L, link.dropped)
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
        val link = uplink(listOf(sink), floorBytes = 10)
        var now = 0L
        link.nanos = { now }
        val told = CopyOnWriteArrayList<Long>()
        link.status = { dropped -> null.also { told += dropped } }
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        link.offer(frame(1_000_000, keyframe = false))
        assertTrue(sink.atGate.await(5, TimeUnit.SECONDS)) // its send is under way
        link.offer(frame(3_000_000, keyframe = true))
        link.offer(frame(4_000_000, keyframe = false))
        link.offer(frame(7_000_000, keyframe = true)) // no room: the 3 s and 4 s frames go unsent
        sink.gate.countDown()
        repeat(3) { sink.next() }
        now = 61_000_000_000L // a minute on
        link.offer(frame(8_000_000, keyframe = true))
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
    fun `frames a server never acknowledges are not kept waiting all day`() {
        val sink = FakeSink() // acknowledges nothing
        val link = uplink(listOf(sink))
        val thread = start(link)
        awaitConnected()
        offerSeconds(link, 110) // 1,100 frames
        repeat(1_100) { sink.next() }
        link.stop()
        thread.join(5_000)
        assertEquals(1_024, link.waitingForAcknowledgement)
    }

    @Test
    fun `stop ends the loop and leaves what is kept to the store's owner, to hand over or drop`() {
        val sink = FakeSink()
        val link = uplink(listOf(sink))
        val thread = start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        sink.next() // sent, and kept to be sent again after a loss
        link.stop()
        thread.join(5_000)
        assertFalse(thread.isAlive)
        assertFalse(link.connected)
        assertEquals(2, kept.listFiles()!!.size) // the run's frames and their index
    }

    @Test
    fun `an acknowledgement coming after the last frame sent is taken while idle, the frames then sent`() {
        val sink = FakeSink()
        val link = uplink(listOf(sink))
        start(link)
        awaitConnected()
        link.offer(frame(1_000_000, keyframe = true))
        link.offer(frame(3_000_000, keyframe = false)) // 2 s of frames
        sink.next()
        sink.next()
        assertTrue(link.unsent) // nothing confirmed: perhaps swallowed
        sink.acknowledgedBytes = sink.sentBytes // the server's word, late, no frame after it
        val until = System.nanoTime() + 2_000_000_000L
        while (link.unsent && System.nanoTime() < until) Thread.sleep(20)
        assertFalse(link.unsent)
    }

    private fun sound(
        ptsUs: Long,
        mark: Byte,
    ) = EncodedFrame(byteArrayOf(mark), ptsUs, keyframe = false, sound = true)

    @Test
    fun `a piece of sound read before a frame taken earlier confirms nothing past that frame`() {
        // Kept as they come: a piece encoded sooner than a frame taken before it goes first. The server's word on the
        // piece alone leaves the frame unconfirmed -- a stream is done, and let go, only once its recorder has it.
        val sink = FakeSink()
        val link = uplink(listOf(sink))
        link.configureSound(byteArrayOf(0x11, 0x88.toByte()))
        start(link)
        awaitConnected()
        link.offer(frame(100_000, keyframe = true))
        link.offerSound(sound(150_000, 1))
        link.offer(frame(133_333, keyframe = false)) // taken before the piece, encoded after it
        sink.next()
        sink.sounds.poll(5, TimeUnit.SECONDS) ?: error("no sound sent")
        val last = sink.next()
        sink.acknowledgedBytes = sink.sentBytes - last.units.sumOf { it.size } // read up to the piece alone
        Thread.sleep(1_500) // asked, and its word taken, while idle
        assertTrue(link.unsent)
        sink.acknowledgedBytes = sink.sentBytes
        val until = System.nanoTime() + 3_000_000_000L
        while (link.unsent && System.nanoTime() < until) Thread.sleep(20)
        assertFalse(link.unsent)
    }

    @Test
    fun `sound goes after its config, timed from the connection's first frame, none heard before it`() {
        val sink = FakeSink()
        val link = uplink(listOf(sink))
        link.configureSound(byteArrayOf(0x11, 0x88.toByte()))
        start(link)
        awaitConnected()
        link.offerSound(sound(50_000, 0)) // before any run: kept nowhere, no frame dropped
        link.offer(frame(100_000, keyframe = true))
        link.offerSound(sound(90_000, 1)) // heard before the connection's first frame: not sent on it
        link.offerSound(sound(121_000, 2))
        link.offer(frame(133_333, keyframe = false))
        assertEquals(0L, sink.next().timestampMs)
        assertEquals(33L, sink.next().timestampMs)
        val (at, piece) = sink.sounds.poll(5, TimeUnit.SECONDS) ?: error("no sound sent")
        assertEquals(21L, at)
        assertArrayEquals(byteArrayOf(2), piece)
        assertTrue(sink.sounds.isEmpty())
        assertArrayEquals(byteArrayOf(0x11, 0x88.toByte()), sink.soundHeaders.single())
        assertEquals(10, sink.metadata.single()["audiocodecid"])
        assertEquals(0L, link.dropped)
    }

    @Test
    fun `a stream with sound waits a moment for its config before it publishes, so the recorder hears of it`() {
        // FFmpeg takes a stream's sound only when its first piece comes as it looks the stream over (specs/013).
        val sink = FakeSink()
        val link = uplink(listOf(sink))
        link.sounded = true
        start(link)
        Thread.sleep(300)
        assertTrue(sink.metadata.isEmpty()) // waiting for the sound's config
        link.configureSound(byteArrayOf(0x11, 0x88.toByte()))
        awaitConnected()
        assertEquals(10, sink.metadata.single()["audiocodecid"])
    }

    @Test
    fun `sound that begins on a connection published without it makes a new one that tells of it`() {
        // The microphone allowed mid-stream: FFmpeg takes a stream's sound only from its start (specs/013).
        val first = FakeSink()
        val second = FakeSink()
        val link = uplink(listOf(first, second))
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        first.next()
        assertNull(first.metadata.single()["audiocodecid"])
        link.configureSound(byteArrayOf(0x11, 0x88.toByte()))
        assertTrue(first.closed.await(5, TimeUnit.SECONDS))
        awaitConnected()
        assertEquals(10, second.metadata.single()["audiocodecid"])
    }

    @Test
    fun `sound a stream has no config for is passed over, never held unsent for good`() {
        // A kept stream whose header was written before its sound's config: its pieces cannot go, and are not
        // read -- read, they would never be confirmed, the stream never done and its lens's live one never sent.
        val sink = FakeSink(answersPings = true)
        val link = uplink(listOf(sink))
        start(link)
        awaitConnected()
        link.offer(frame(100_000, keyframe = true))
        link.offerSound(sound(121_000, 2))
        link.offerSound(sound(142_000, 3)) // the last kept: after every frame
        sink.next()
        val done = System.nanoTime() + 5_000_000_000L
        while (link.unsent && System.nanoTime() < done) Thread.sleep(50)
        assertFalse(link.unsent)
    }

    @Test
    fun `sound with no config to decode it by is not sent`() {
        val sink = FakeSink()
        val link = uplink(listOf(sink))
        start(link)
        awaitConnected()
        link.offer(frame(100_000, keyframe = true))
        link.offerSound(sound(121_000, 2))
        link.offer(frame(133_333, keyframe = false))
        sink.next()
        sink.next()
        assertTrue(sink.sounds.isEmpty())
        assertTrue(sink.soundHeaders.isEmpty())
        assertNull(sink.metadata.single()["audiocodecid"])
    }

    @Test
    fun `the sound's config is kept with the stream's header`() {
        val told = mutableListOf<ByteArray?>()
        val link = Uplink(address, format, { null }, {}, {}, FrameStore(kept, freeBytes = { Long.MAX_VALUE }))
        link.onConfigured = { _, config -> true.also { told += config } }
        link.configureSound(byteArrayOf(1)) // no header yet: kept with it when it comes
        assertTrue(told.isEmpty())
        link.configure(sps, pps)
        link.configureSound(byteArrayOf(2)) // another: the header kept again with it
        assertEquals(listOf(1.toByte(), 2.toByte()), told.map { it!!.single() })
    }
}

/** [Uplink.Throughput]: a lens's rates, once a second. */
class ThroughputTest {
    @Test
    fun `the first rate after a pause, the camera closed a while, counts the frames after it alone`() {
        var now = 0L
        val throughput = Uplink.Throughput { now }
        val rates = mutableListOf<Double>()
        val count = { atNs: Long ->
            now = atNs
            throughput.count(1_000)?.let { rates += it.first }
        }
        repeat(32) { count(it * 33_333_333L) } // a second at 30 fps: told
        for (idleNs in 1_100_000_000L..5_900_000_000L step 100_000_000L) { // nothing to send, as the uplink polls
            now = idleNs
            throughput.idle()
        }
        repeat(32) { count(6_000_000_000L + it * 33_333_333L) } // 5 s without a frame, then a second more
        assertEquals(2, rates.size)
        assertTrue(rates.toString(), rates.all { it > 25 }) // not one frame over the 5 s pause
    }

    @Test
    fun `a send that hangs a while, its frames waiting, is told in the rate after it`() {
        var now = 0L
        val throughput = Uplink.Throughput { now }
        val rates = mutableListOf<Double>()
        val count = { atNs: Long ->
            now = atNs
            throughput.count(1_000)?.let { rates += it.first }
        }
        repeat(32) { count(it * 33_333_333L) } // a second at 30 fps
        count(2_500_000_000L) // a send hung 1.5 s, the network stalled: never idle meanwhile
        assertEquals(2, rates.size)
        assertTrue(rates.toString(), rates[1] < 25) // the stall told, not hidden
    }
}

/** The uplink's waits (specs/009): kept frames sent alone, its turn at an address, the first lens first. */
class UplinkWaitsTest {
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

    private fun start(link: Uplink) = Thread { link.run() }.apply { start() }

    private fun exchange(offset: Long) = Sample(t1 = 0, t2 = offset + 750, t3 = offset + 750, t4 = 1_500)

    private fun awaitConnected() = assertTrue(keyframesAsked.tryAcquire(5, TimeUnit.SECONDS))

    private fun frame(
        ptsUs: Long,
        keyframe: Boolean,
    ) = EncodedFrame(byteArrayOf(0, 0, 0, 1, if (keyframe) 0x65 else 0x41, 7), ptsUs, keyframe)

    @After
    fun stop() = running.forEach { it.stop() }

    /** A store read back from one that kept a second of frames without moments, then [seconds] with. */
    private fun keptBefore(seconds: Int): FrameStore {
        val before = FrameStore(kept, freeBytes = { Long.MAX_VALUE })
        repeat(10 + seconds * 10) {
            val pts = it * 100_000L
            before.keep(frame(pts, keyframe = it % 10 == 0), if (it < 10) null else pts + 7_000_000)
        }
        before.close()
        return FrameStore(kept, freeBytes = { Long.MAX_VALUE })
    }

    @Test
    fun `kept frames sent alone go from the first keyframe with a moment, with theirs, waiting for no clock`() {
        val sink = FakeSink()
        val record = byteArrayOf(1, 0x64, 0, 0x28)
        val link =
            Uplink(address, format, clock = {
                null
            }, requestKeyframe = {}, report = { statuses += it }, keptBefore(2), alone = true)
        link.connect = { sink }
        link.waitForClockMs = 60_000 // waited for, it would hold the frames a minute
        link.configure(record)
        running += link
        start(link)
        val key = sink.next()
        assertTrue(key.keyframe)
        assertEquals(1_000_000L + 7_000_000, momentOf(key.units[0]))
        assertEquals(1_100_000L + 7_000_000, momentOf(sink.next().units[0]))
        assertArrayEquals(record, sink.headers.single())
        assertTrue((sink.metadata.single()["held_ms"] as Long) >= 0)
    }

    @Test
    fun `a stream connects only once its address is free of the streams kept before it`() {
        val sink = FakeSink()
        val free =
            java.util.concurrent.atomic
                .AtomicBoolean(false)
        val link =
            Uplink(
                address,
                format,
                clock = { exchange(1_000_000) },
                requestKeyframe = { keyframesAsked.release() },
                report = { statuses += it },
                FrameStore(kept, freeBytes = { Long.MAX_VALUE }),
                turn = { free.get() },
            )
        link.connect = { sink }
        link.configure(sps, pps)
        running += link
        start(link)
        link.offer(frame(0, keyframe = true))
        Thread.sleep(300)
        assertTrue(sink.metadata.isEmpty())
        assertEquals(listOf(UplinkStatus.Waiting(first = false)), statuses.toList())
        free.set(true)
        awaitConnected()
        assertEquals(1_000_000L, momentOf(sink.next().units[0]))
    }

    @Test
    fun `a lens not first sends nothing while the first is behind, and lets its connection go meanwhile`() {
        val held = FakeSink()
        val again = FakeSink()
        val allowed =
            java.util.concurrent.atomic
                .AtomicBoolean(true)
        val queue = ArrayDeque(listOf(held, again))
        val link =
            Uplink(
                address,
                format,
                clock = { exchange(1_000_000) },
                requestKeyframe = { keyframesAsked.release() },
                report = { statuses += it },
                FrameStore(kept, freeBytes = { Long.MAX_VALUE }),
                firstLens = { allowed.get() },
            )
        link.connect = { queue.removeFirst() }
        link.configure(sps, pps)
        running += link
        start(link)
        awaitConnected()
        link.offer(frame(0, keyframe = true))
        held.next()
        allowed.set(false)
        link.offer(frame(100_000, keyframe = false))
        assertTrue(held.closed.await(Uplink.HOLD_MS + 2_000, TimeUnit.MILLISECONDS))
        assertTrue(held.frames.isEmpty())
        assertFalse(link.connected)
        // Said before it is let on: on a busy machine the test would otherwise let it on before it waits.
        val deadline = System.nanoTime() + 5_000_000_000L
        while (UplinkStatus.Waiting(first = true) !in statuses && System.nanoTime() < deadline) Thread.sleep(10)
        assertTrue(UplinkStatus.Waiting(first = true) in statuses)
        allowed.set(true)
        awaitConnected()
        assertEquals(0L, again.next().timestampMs) // sent again from its keyframe: nothing lost
        assertEquals(100L, again.next().timestampMs)
        assertTrue(statuses.none { it is UplinkStatus.Reconnecting })
    }

    @Test
    fun `a lens held for the first sends again only what its recorder did not confirm`() {
        val held = FakeSink(acknowledgeTo = 31) // read to 3.0 s
        val again = FakeSink()
        val allowed =
            java.util.concurrent.atomic
                .AtomicBoolean(true)
        val queue = ArrayDeque(listOf(held, again))
        val link =
            Uplink(
                address,
                format,
                clock = { exchange(1_000_000) },
                requestKeyframe = { keyframesAsked.release() },
                report = { statuses += it },
                FrameStore(kept, freeBytes = { Long.MAX_VALUE }),
                firstLens = { allowed.get() },
            )
        link.connect = { queue.removeFirst() }
        link.configure(sps, pps)
        running += link
        start(link)
        awaitConnected()
        repeat(40) { link.offer(frame(it * 100_000L, keyframe = it % 10 == 0)) }
        repeat(40) { held.next() }
        allowed.set(false)
        assertTrue(held.closed.await(Uplink.HOLD_MS + 2_000, TimeUnit.MILLISECONDS))
        allowed.set(true)
        awaitConnected()
        // Its keyframe at 3.0 s, not 2 s before it again: the moment is the frame's capture, the recorder 1 s ahead.
        assertEquals(3_000_000L + 1_000_000, momentOf(again.next().units[0]))
    }

    @Test
    fun `an h265 stream's frames carry its sei units, and its metadata names hvc1`() {
        val sink = FakeSink()
        val hevc = StreamFormat(Resolution(1920, 1080), 30, FpsRange(30, 30), 3_500_000, Codec.HEVC)
        val link =
            Uplink(address, hevc, {
                exchange(1_000_000)
            }, { keyframesAsked.release() }, { statuses += it }, FrameStore(kept, freeBytes = { Long.MAX_VALUE }))
        link.connect = { sink }
        link.configure(byteArrayOf(1, 2, 3))
        link.status = { "battery=9" }
        running += link
        start(link)
        awaitConnected()
        link.offer(EncodedFrame(byteArrayOf(0, 0, 0, 1, 0x26, 0x01, 7), 0, keyframe = true))
        val sent = sink.next()
        assertEquals(listOf(Hevc.NAL_PREFIX_SEI, Hevc.NAL_PREFIX_SEI, 19), sent.units.map { Hevc.type(it) })
        assertEquals(0x68766331, sink.metadata.single()["videocodecid"])
    }

    @Test
    fun `a header the storage refused is tried again at each keyframe until it is kept`() {
        var told = 0
        val link = Uplink(address, format, { null }, {}, {}, FrameStore(kept, freeBytes = { Long.MAX_VALUE }))
        link.onConfigured = { _, _ -> ++told > 1 } // the first write refused
        link.configure(sps, pps)
        link.offer(frame(0, keyframe = true)) // tried again: kept
        link.offer(frame(100_000, keyframe = false))
        link.offer(frame(1_000_000, keyframe = true)) // kept already: not told again
        assertEquals(2, told)
    }

    @Test
    fun `the stream's header is told once a new one comes, to be kept with the frames`() {
        val told = mutableListOf<ByteArray>()
        val link = Uplink(address, format, { null }, {}, {}, FrameStore(kept, freeBytes = { Long.MAX_VALUE }))
        link.onConfigured = { record, _ ->
            told += record
            told.size != 2 // the second write refused, as a full storage would
        }
        link.configure(sps, pps)
        link.configure(sps, pps) // kept: not told again
        link.configure(byteArrayOf(9, 9)) // refused
        link.configure(byteArrayOf(9, 9)) // the same again: tried again
        assertEquals(3, told.size)
        assertArrayEquals(Avc.configurationRecord(sps, pps), told[0])
        assertArrayEquals(byteArrayOf(9, 9), told[1])
    }
}
