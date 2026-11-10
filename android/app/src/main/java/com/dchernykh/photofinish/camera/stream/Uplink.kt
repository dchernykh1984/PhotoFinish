package com.dchernykh.photofinish.camera.stream

import com.dchernykh.photofinish.camera.capture.StreamFormat
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import com.dchernykh.photofinish.camera.sync.OffsetSlew
import com.dchernykh.photofinish.camera.sync.Sample
import java.io.IOException
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** One encoded frame: Annex B units, its presentation time on the camera's clock, us. */
class EncodedFrame(
    val data: ByteArray,
    val ptsUs: Long,
    val keyframe: Boolean,
) {
    /** The run of frames it belongs to: a run ends where frames were dropped. */
    internal var run = 0
}

/** What the uplink says to the screen. */
sealed interface UplinkStatus {
    data class Connecting(
        val address: String,
    ) : UplinkStatus

    data class Streaming(
        val fps: Double,
        val mbps: Double,
        val clockMs: Double?,
    ) : UplinkStatus

    data class Reconnecting(
        val reason: String,
    ) : UplinkStatus
}

/**
 * Takes the encoder's frames to PhotoFinish: connects, sends the stream's header
 * and the frames, each with its moment on the recorder's clock once the clock is
 * in step, and connects again after a loss. Frames the network cannot take are
 * dropped up to the next keyframe, never sent late in a pile.
 *
 * [clock] gives the best clock exchange so far, null while there is none: its
 * offset is the recorder's clock minus the camera's. [requestKeyframe] asks the
 * encoder for one, as every connection must start with it.
 */
class Uplink(
    private val address: RtmpAddress,
    private val format: StreamFormat,
    private val clock: () -> Sample?,
    private val requestKeyframe: () -> Unit,
    private val report: (UplinkStatus) -> Unit,
    private val connect: (RtmpAddress) -> VideoSink = { RtmpPublisher(it) },
) {
    /** How long a connection waits for the clock before frames go without moments. */
    internal var waitForClockMs = WAIT_FOR_CLOCK_MS

    /** How long a send may hang before the connection is given up. */
    internal var stallMs = STALL_MS

    private val queue = LinkedBlockingQueue<EncodedFrame>(maxOf(format.fps * QUEUE_SECONDS, 1))
    private val slew = OffsetSlew()

    @Volatile private var record: ByteArray? = null

    @Volatile private var running = true

    @Volatile private var publisher: VideoSink? = null

    @Volatile private var sendingSince = 0L

    /** The connection under way has sent a frame; the uplink's thread alone keeps it. */
    private var streamed = false

    /** The run of frames being offered; the encoder's thread alone counts it. */
    private var run = 0

    /** Frames dropped because the network fell behind. */
    @Volatile var dropped = 0L
        private set

    /** The encoder's SPS and PPS: the stream's header. */
    fun configure(
        sps: ByteArray,
        pps: ByteArray,
    ) {
        record = Avc.configurationRecord(sps, pps)
    }

    /**
     * A frame from the encoder; when the queue is full it is emptied and a keyframe asked for,
     * and the frames that follow make a new run: none of them is sent before its keyframe.
     */
    fun offer(frame: EncodedFrame) {
        frame.run = run
        if (!queue.offer(frame)) {
            dropped += queue.size + 1L
            run++
            queue.clear()
            requestKeyframe()
        }
    }

    fun stop() {
        running = false
        publisher?.close()
    }

    /**
     * The uplink's loop, on a thread of its own, until [stop]. Whatever a connection throws -- a
     * lost socket, an answer the publisher cannot read -- it connects again: an exception left to
     * escape would end the app mid-race.
     */
    @Suppress("TooGenericExceptionCaught")
    fun run() {
        val watchdog = Thread({ watch() }, "uplink-watchdog").apply { isDaemon = true }
        watchdog.start()
        var pause = FIRST_PAUSE_MS
        while (running) {
            report(UplinkStatus.Connecting(address.toString()))
            try {
                stream() // returns once stopped; a lost connection throws
            } catch (error: Exception) {
                publisher?.close()
                if (!running) break
                if (streamed) pause = FIRST_PAUSE_MS // a connection that streamed: the pauses start over
                report(UplinkStatus.Reconnecting(error.message ?: error.javaClass.simpleName))
                sleep(pause)
                pause = minOf(pause * 2, MAX_PAUSE_MS)
            }
        }
        publisher?.close()
    }

    private fun stream() {
        streamed = false
        val connected = connect(address)
        publisher = connected
        connected.publish(metadata(format))
        awaitClock()
        // A connection's frames all carry their moments, or none do: the recorder places frames
        // without one by their arrival, seconds late at a connection's start, and a mix of the two
        // would not keep its order. A clock that comes later makes a new connection.
        val stamped = clock() != null
        connected.sendSequenceHeader(awaitRecord())
        queue.clear()
        requestKeyframe()
        var first: Long? = null
        var sentRun: Int? = null
        val throughput = Throughput()
        while (running) {
            // A connection starts on a keyframe, and so does a run after frames were dropped.
            val frame =
                queue.poll(POLL_MS, TimeUnit.MILLISECONDS)?.takeIf { it.keyframe || it.run == sentRun } ?: continue
            val sample = clock()
            if (!stamped && sample != null) throw IOException("the clock is in step now")
            sentRun = frame.run
            val start = first ?: frame.ptsUs
            first = start
            send(connected, frame, frame.ptsUs - start, sample)
            streamed = true
            val rates = throughput.count(frame.data.size)
            if (rates != null) report(UplinkStatus.Streaming(rates.first, rates.second, sample?.delay?.div(1000.0)))
        }
    }

    /** One frame, [sinceStartUs] into the connection, with its moment when the clock is known. */
    private fun send(
        connected: VideoSink,
        frame: EncodedFrame,
        sinceStartUs: Long,
        sample: Sample?,
    ) {
        val units = Avc.splitAnnexB(frame.data).toMutableList()
        if (sample != null) units.add(0, Sei.frameMoment(frame.ptsUs + slew.at(frame.ptsUs, sample.offset)))
        sendingSince = System.nanoTime()
        try {
            connected.sendFrame(sinceStartUs / 1000, frame.keyframe, units)
        } finally {
            sendingSince = 0 // a send that failed is no send hanging: the next connection is not cut
        }
    }

    /** Waits a little for the clock, so that the connection's frames carry their moments. */
    private fun awaitClock() {
        val until = System.nanoTime() + waitForClockMs * 1_000_000
        while (clock() == null && System.nanoTime() < until && running) sleep(POLL_MS)
    }

    private fun awaitRecord(): ByteArray {
        while (running) {
            record?.let { return it }
            sleep(POLL_MS)
        }
        throw IOException("stopped")
    }

    /** Closes a connection whose send has hung -- a Wi-Fi gone -- so the loop connects again. */
    private fun watch() {
        while (running) {
            sleep(POLL_MS)
            val since = sendingSince
            if (since != 0L && System.nanoTime() - since > stallMs * 1_000_000) publisher?.close()
        }
    }

    private fun sleep(ms: Long) {
        try {
            Thread.sleep(ms)
        } catch (_: InterruptedException) {
            running = false
        }
    }

    /** Frames and megabits per second, once a second. */
    private class Throughput {
        private var frames = 0
        private var bytes = 0L
        private var since = System.nanoTime()

        /** Counts a frame of [size] bytes; once a second, the rates since the last time. */
        fun count(size: Int): Pair<Double, Double>? {
            frames++
            bytes += size
            val elapsed = System.nanoTime() - since
            if (elapsed < REPORT_NS) return null
            val seconds = elapsed / 1e9
            val rates = frames / seconds to bytes * 8 / seconds / 1e6
            frames = 0
            bytes = 0
            since = System.nanoTime()
            return rates
        }
    }

    companion object {
        private const val QUEUE_SECONDS = 2
        private const val POLL_MS = 100L
        private const val REPORT_NS = 1_000_000_000L
        private const val FIRST_PAUSE_MS = 500L
        private const val MAX_PAUSE_MS = 8_000L
        private const val WAIT_FOR_CLOCK_MS = 3_000L
        private const val STALL_MS = 5_000L
        private const val VIDEO_CODEC_AVC = 7

        private fun metadata(format: StreamFormat): Map<String, Any?> =
            mapOf(
                "width" to format.resolution.width,
                "height" to format.resolution.height,
                "framerate" to format.fps,
                "videocodecid" to VIDEO_CODEC_AVC,
                "videodatarate" to format.bitrate / 1000,
                "encoder" to "PhotoFinish Camera",
            )
    }
}
