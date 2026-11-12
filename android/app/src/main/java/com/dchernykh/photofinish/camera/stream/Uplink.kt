package com.dchernykh.photofinish.camera.stream

import com.dchernykh.photofinish.camera.capture.StreamFormat
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import com.dchernykh.photofinish.camera.sync.OffsetSlew
import com.dchernykh.photofinish.camera.sync.Sample
import java.io.IOException

/** One encoded frame: Annex B units, its presentation time on the camera's clock, us. */
class EncodedFrame(
    val data: ByteArray,
    val ptsUs: Long,
    val keyframe: Boolean,
)

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
 * Takes the encoder's frames to PhotoFinish through a [store] on the phone (specs/007): connects, sends the
 * stream's header and the frames kept, each with its moment on the recorder's clock once the clock is in step,
 * and connects again after a loss, from a little before the newest frame the server acknowledged reading, as a
 * dead connection, and the buffers on its way, may have swallowed whatever came after it. Nothing is dropped
 * while the store has room: a break or a network slower than the stream makes the laptop fall behind and catch
 * up, at the network's pace.
 *
 * [clock] gives the best clock exchange so far, null while there is none: its offset is the recorder's clock
 * minus the camera's. [requestKeyframe] asks the encoder for one: a connection waiting for its first frame
 * starts from it, and so do the frames after one the store could not keep.
 */
class Uplink(
    private val address: RtmpAddress,
    private val format: StreamFormat,
    private val clock: () -> Sample?,
    private val requestKeyframe: () -> Unit,
    private val report: (UplinkStatus) -> Unit,
    private val store: FrameStore,
) {
    /** How a connection is made; a test's stands in for the server. */
    internal var connect: (RtmpAddress) -> VideoSink = { RtmpPublisher(it) }

    /** How long a connection waits for the clock before frames go without moments. */
    internal var waitForClockMs = WAIT_FOR_CLOCK_MS

    /** How long a send may hang before the connection is given up. */
    internal var stallMs = STALL_MS

    /** How long into a connection a clock that comes makes a new one: its start, not the race. */
    internal var stampWindowMs = STAMP_WINDOW_MS

    /**
     * The phone's status line a keyframe carries, given the frames dropped so far; null for none
     * (specs/005-phone-status). Set before [run].
     */
    var status: (Long) -> String? = { null }

    /** The frames' own clock now, us, once the first frame told it: how long a connection's first was kept. */
    @Volatile var captureClock: (() -> Long)? = null

    /** The clock drops are timed on, for the last minute's count. */
    internal var nanos: () -> Long = System::nanoTime

    private val drops = RecentDrops { nanos() }
    private val slew = OffsetSlew()

    @Volatile private var record: ByteArray? = null

    @Volatile private var running = true

    @Volatile private var publisher: VideoSink? = null

    @Volatile private var sendingSince = 0L

    /** The connection under way has sent a frame; the uplink's thread alone keeps it. */
    private var streamed = false

    /**
     * The connection under way sends its frames with their moments: the recorder knows a frame sent again by
     * its moment, so only such a connection's loss sends frames again. The uplink's thread alone keeps it.
     */
    private var stamped = false

    /** A keyframe asked for since a frame was lost; the encoder's thread alone keeps it. */
    private var askedKeyframe = false

    /** The moment the last frame was kept with; the encoder's thread alone keeps it. */
    private var lastMomentUs: Long? = null

    /** The connection's frames sent and not yet acknowledged: the bytes sent once each was, and its capture time. */
    private val unacknowledged = ArrayDeque<Pair<Long, Long>>()

    /** How many frames wait for an acknowledgement, for a test once the uplink's thread has ended. */
    internal val waitingForAcknowledgement: Int get() = unacknowledged.size

    /** Frames dropped because the store had no room for them, or could not keep them. */
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
     * A frame from the encoder, kept with its moment on the recorder's clock once the clock is in step: a frame
     * sent again after a loss carries the moment it was first sent with. Frames the store drops are counted; a
     * frame it could not keep has a keyframe asked for, as the frames after it wait for one -- not the oldest
     * runs it drops for a keyframe's room, the next run starting with its own.
     */
    fun offer(frame: EncodedFrame) {
        val moment = clock()?.let { inOrder(frame.ptsUs + slew.at(frame.ptsUs, it.offset), lastMomentUs) }
        moment?.let { lastMomentUs = it }
        val lost = store.keep(frame, moment)
        if (frame.keyframe) askedKeyframe = false
        if (lost > 0) {
            dropped += lost
            drops.add(lost.toLong())
            if (!frame.keyframe && !askedKeyframe) {
                askedKeyframe = true
                requestKeyframe()
            }
        }
    }

    /** Streaming over: the loop ends, and what the store keeps is dropped (FR-004). */
    fun stop() {
        running = false
        publisher?.close()
        store.clear()
    }

    /**
     * The uplink's loop, on a thread of its own, until [stop]. Whatever a connection throws -- a lost socket, an
     * answer the publisher cannot read -- it connects again, from what the dead one may have swallowed: an
     * exception left to escape would end the app mid-race.
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
                publisher?.let { confirm(it) } // what it acknowledged before it died
                if (stamped) store.rewind()
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
        stamped = false
        unacknowledged.clear()
        val connected = connect(address)
        publisher = connected
        // Waits a little for the clock, so that the connection's frames carry their moments.
        await(System.nanoTime() + waitForClockMs * 1_000_000) { clock() != null }
        // A connection's frames all carry their moments, or none do: the recorder places frames without one by
        // their arrival, later than they were taken, and a mix of the two would not keep its order. Once the
        // clock is in step, a connection starts at a keyframe kept with a moment; before, at the next keyframe,
        // as what was kept would be placed late by all the time it was kept.
        if (clock() != null) store.skipToStamped() else store.skipKept()
        // Then how long the frame it starts at was kept is known, the wait for the clock in it too (contract).
        connected.publish(metadata(format, store.heldMs(captureClock?.invoke())))
        val until = System.nanoTime() + stampWindowMs * 1_000_000
        await(Long.MAX_VALUE) { record != null }
        connected.sendSequenceHeader(record ?: throw IOException("stopped"))
        requestKeyframe()
        var first: Long? = null
        val throughput = Throughput()
        while (running) {
            // A connection starts on a keyframe.
            val kept = store.next(POLL_MS)?.takeIf { first != null || it.keyframe } ?: continue
            if (first == null) stamped = kept.momentUs != null
            // A clock that comes at the start makes a new connection, from this frame; one that comes once the
            // race may be under way is left for the next, as a new one is a moment of frames sent again.
            val early = System.nanoTime() < until
            if (!stamped && kept.momentUs != null && early) {
                store.back()
                throw IOException("the clock is in step now")
            }
            val start = first ?: kept.ptsUs
            first = start
            send(connected, kept, kept.ptsUs - start, kept.momentUs?.takeIf { stamped })
            unacknowledged.addLast(connected.sentBytes to kept.ptsUs)
            // A server that acknowledges nothing leaves the store its 6 s after the newest sent (FrameStore).
            if (unacknowledged.size > UNACKNOWLEDGED_KEPT) unacknowledged.removeFirst()
            confirm(connected)
            streamed = true
            val rates = throughput.count(kept.data.size)
            val delay = clock()?.takeIf { stamped }?.delay?.div(1000.0)
            if (rates != null) report(UplinkStatus.Streaming(rates.first, rates.second, delay))
        }
    }

    /** One frame, [sinceStartUs] into the connection, with its [momentUs] when it goes with one. */
    private fun send(
        connected: VideoSink,
        kept: KeptFrame,
        sinceStartUs: Long,
        momentUs: Long?,
    ) {
        val units = Avc.splitAnnexB(kept.data).toMutableList()
        var head = 0
        if (momentUs != null) units.add(head++, Sei.frameMoment(momentUs))
        // The status after the moment: a reader looking for the moment finds it first. A status
        // the phone fails to read costs this keyframe its status, never the connection.
        if (kept.keyframe) {
            runCatching {
                status(
                    drops.lately(),
                )
            }.getOrNull()?.let { units.add(head, Sei.phoneStatus(it)) }
        }
        sendingSince = System.nanoTime()
        try {
            connected.sendFrame(sinceStartUs / 1000, kept.keyframe, units)
        } finally {
            sendingSince = 0 // a send that failed is no send hanging: the next connection is not cut
        }
    }

    /** The frames the server has read, by its acknowledgements, told to the store: a loss sends from them. */
    private fun confirm(connected: VideoSink) {
        val read = connected.acknowledgedBytes
        var newest: Long? = null
        while (unacknowledged.isNotEmpty() && unacknowledged.first().first <= read) {
            newest = unacknowledged.removeFirst().second
        }
        newest?.let { store.confirm(it) }
    }

    /** Waits until [ready], the stop or [untilNs] on the nanosecond clock. */
    private fun await(
        untilNs: Long,
        ready: () -> Boolean,
    ) {
        while (!ready() && System.nanoTime() < untilNs && running) sleep(POLL_MS)
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
        private const val POLL_MS = 100L
        private const val REPORT_NS = 1_000_000_000L
        private const val FIRST_PAUSE_MS = 500L
        private const val MAX_PAUSE_MS = 8_000L
        private const val WAIT_FOR_CLOCK_MS = 3_000L
        private const val STALL_MS = 5_000L
        private const val STAMP_WINDOW_MS = 10_000L
        private const val VIDEO_CODEC_AVC = 7

        /**
         * Frames sent kept waiting for an acknowledgement: FFmpeg's come every 64 KiB, or every half megabyte
         * when it keeps its own window, seconds of frames; more is a server that acknowledges nothing.
         */
        private const val UNACKNOWLEDGED_KEPT = 1024

        /** A frame's moment after the one before, at least: a millisecond, the recorder's step. */
        private const val STEP_US = 1_000L

        /** An offset set back further than a better exchange sets it: the recorder's clock changed (OffsetSlew). */
        private const val CLOCK_SET_US = 50_000L

        /**
         * [momentUs] a millisecond after [lastUs], the moment before, when a better exchange set the offset back --
         * at the start, a few milliseconds: the recorder would put the frame after the one before by where its
         * connection began, and a frame sent again from elsewhere would carry another moment than it was listed
         * with. A step further back is the recorder's clock started again or set: taken, as the frames after it
         * are on that clock.
         */
        private fun inOrder(
            momentUs: Long,
            lastUs: Long?,
        ): Long {
            val next = lastUs?.plus(STEP_US)
            return if (next != null && next - momentUs in 1..CLOCK_SET_US) next else momentUs
        }

        /** The stream's metadata; [heldMs]: how long its first frame was kept (specs/007, contract). */
        private fun metadata(
            format: StreamFormat,
            heldMs: Long,
        ): Map<String, Any?> =
            mapOf(
                "width" to format.resolution.width,
                "height" to format.resolution.height,
                "framerate" to format.fps,
                "videocodecid" to VIDEO_CODEC_AVC,
                "videodatarate" to format.bitrate / 1000,
                "encoder" to "PhotoFinish Camera",
                "held_ms" to heldMs,
            )
    }
}
