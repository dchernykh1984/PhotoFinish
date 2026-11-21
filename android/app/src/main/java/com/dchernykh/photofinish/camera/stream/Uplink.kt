package com.dchernykh.photofinish.camera.stream

import com.dchernykh.photofinish.camera.capture.StreamFormat
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import com.dchernykh.photofinish.camera.sync.OffsetSlew
import com.dchernykh.photofinish.camera.sync.Sample
import java.io.IOException

/**
 * One encoded frame: Annex B units, its presentation time on the camera's clock, us -- or, [sound], a piece of the
 * phone's sound in AAC, its capture time on the same clock (specs/013).
 */
class EncodedFrame(
    val data: ByteArray,
    val ptsUs: Long,
    val keyframe: Boolean,
    val sound: Boolean = false,
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

    /** Not sending for now, frames kept meanwhile (specs/009): [first] waits for the first lens, else for its turn. */
    data class Waiting(
        val first: Boolean,
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
 * starts from it, and so do the frames after one the store could not keep. [alone]: the frames a stream kept,
 * sent with no camera and no clock (specs/009) -- from the first keyframe with its moment; one without it after
 * that goes without, the recorder placing it by its capture time after the frame before.
 * It connects once [turn] says the address is free of the streams kept before it, and sends while [firstLens]
 * says the first lens lets it; waiting on [firstLens] longer than [HOLD_MS], it lets its connection go.
 */
@Suppress("TooManyFunctions", "LongParameterList") // the uplink's loop and steps; a stream's parts and waits
class Uplink(
    private val address: RtmpAddress,
    private val format: StreamFormat,
    private val clock: () -> Sample?,
    private val requestKeyframe: () -> Unit,
    private val report: (UplinkStatus) -> Unit,
    private val store: FrameStore,
    private val alone: Boolean = false,
    private val turn: () -> Boolean = { true },
    private val firstLens: () -> Boolean = { true },
) {
    /** How a connection is made; a test's stands in for the server. */
    internal var connect: (RtmpAddress) -> VideoSink = { RtmpPublisher(it, format.codec) }

    /** How long a connection waits for the clock before frames go without moments. */
    internal var waitForClockMs = WAIT_FOR_CLOCK_MS

    /** How long a send may hang before the connection is given up. */
    internal var stallMs = STALL_MS

    /** How long an idle connection may say nothing of frames it has not confirmed ([askRead]); a test's is short. */
    internal var answerWaitMs = ANSWER_WAIT_MS

    /** When the server was last asked to say what it read, what it had said then, and since when it says nothing. */
    private var askedNs = 0L
    private var heardBytes = 0L
    private var quietSinceNs = 0L

    /** How long into a connection a clock that comes makes a new one: its start, not the race. */
    internal var stampWindowMs = STAMP_WINDOW_MS

    /** Until when, on the nanosecond clock, a clock come in step makes a new connection: [stampWindowMs] on. */
    @Volatile private var stampUntilNs = Long.MIN_VALUE

    /** The window a feed opened ([stampAgain]): its new connection made at a keyframe alone. */
    @Volatile private var stampAtKeyframe = false

    /**
     * Its camera feeds it anew after a gap -- lost and opened again, the screen back --: a start for its frames, a
     * clock in step since its connection began, left for the next then, making a new one now, with their moments --
     * at a keyframe: a run kept before it, under way, is sent whole on the one going, none of it skipped.
     */
    fun stampAgain() = openStampWindow(atKeyframe = true)

    private fun openStampWindow(atKeyframe: Boolean) {
        stampAtKeyframe = atKeyframe
        stampUntilNs = System.nanoTime() + stampWindowMs * 1_000_000
    }

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

    /** A connection is made and not lost: the first lens's says whether the others wait for it (specs/009). */
    @Volatile var connected = false
        private set

    /**
     * The stream's header -- and its sound's config, if any -- once the encoders gave them: kept with the frames, to be
     * sent after a restart; true once known kept, else told again as the encoder gives it again.
     */
    var onConfigured: (ByteArray, ByteArray?) -> Boolean = { _, _ -> true }

    /** The sound's AudioSpecificConfig, once its encoder gave it (specs/013): its pieces are not sent without. */
    @Volatile private var soundConfig: ByteArray? = null

    /** The connection under way has sent the sound's config; the uplink's thread alone keeps it. */
    private var soundHeaderSent = false

    /** The connection under way was published telling of its sound; the uplink's thread alone keeps it. */
    private var publishedSound = false

    /**
     * The stream takes the phone's sound (specs/013): a connection waits a moment for the sound's config before it
     * publishes, as FFmpeg takes a stream's sound only when its first piece comes while it looks the stream over.
     */
    @Volatile var sounded = false

    /** The header kept with the frames ([onConfigured]). */
    @Volatile private var headerKept = false

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
    ) = configure(Avc.configurationRecord(sps, pps))

    /** The stream's header as the recorder takes it: the encoder's, or one kept with the frames ([alone]). */
    fun configure(record: ByteArray) {
        if (this.record?.contentEquals(record) == true && headerKept) return
        this.record = record
        headerKept = onConfigured(record, soundConfig)
    }

    /** The sound's AudioSpecificConfig, as its encoder gives it, or one kept with the frames ([alone]) (specs/013). */
    fun configureSound(config: ByteArray) {
        if (soundConfig?.contentEquals(config) == true && headerKept) return
        soundConfig = config
        record?.let { headerKept = onConfigured(it, config) }
    }

    /**
     * A piece of the phone's sound, kept with the frames in the order captured, sent with them (specs/013): one with no
     * run of frames to go in yet -- before the stream's first keyframe -- is not, and counts as no frame dropped.
     */
    fun offerSound(piece: EncodedFrame) {
        store.keep(piece, null)
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
        if (frame.keyframe) {
            askedKeyframe = false
            // A header the storage refused, or not known kept yet, tried again at each keyframe: frames kept with no
            // header are never sent after a Stop or a crash, and the encoder gives its header once.
            if (!headerKept) record?.let { headerKept = onConfigured(it, soundConfig) }
        }
        if (lost > 0) {
            dropped += lost
            drops.add(lost.toLong())
            if (!frame.keyframe && !askedKeyframe) {
                askedKeyframe = true
                requestKeyframe()
            }
        }
    }

    /** A frame kept and not sent yet ([FrameStore.unsent]). */
    val unsent: Boolean get() = store.unsent

    /** Streaming over: the loop ends; what the store keeps is its owner's to hand over or drop (specs/009). */
    fun stop() {
        running = false
        publisher?.close()
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
        while (running && awaitTurn()) {
            report(UplinkStatus.Connecting(address.toString()))
            try {
                stream() // returns once stopped; a lost connection throws
            } catch (_: Holding) {
                lost(held = true) // let go to wait for the first lens: no pause, nothing lost
            } catch (_: SoundBegan) {
                lost() // a new connection that tells of its sound: no pause
            } catch (error: Exception) {
                lost()
                if (running) pause = reconnectAfter(error, pause)
            }
        }
        connected = false
        publisher?.close()
    }

    /** A connection lost to [error], said; the pause before the next, [pause] so far: the next one's returned. */
    private fun reconnectAfter(
        error: Exception,
        pause: Long,
    ): Long {
        val waited = if (streamed) FIRST_PAUSE_MS else pause // a connection that streamed: the pauses start over
        report(UplinkStatus.Reconnecting(error.message ?: error.javaClass.simpleName))
        sleep(waited)
        return minOf(waited * 2, MAX_PAUSE_MS)
    }

    /**
     * A connection gone: what it acknowledged before it died taken, and the next begins before what it swallowed --
     * from the newest frame confirmed when it was [held] for the first lens: let go by the phone, to a recorder that
     * wrote what it confirmed, nothing it has is sent again each time the first lens holds it back.
     */
    private fun lost(held: Boolean = false) {
        connected = false
        publisher?.close()
        if (!running) return
        publisher?.let { confirm(it) }
        if (stamped) store.rewind(if (held) 0L else FrameStore.CONFIRMED_MARGIN_US)
    }

    /** Waits, said once, until the address is the stream's turn and the first lens lets it send; false once stopped. */
    private fun awaitTurn(): Boolean {
        var said: UplinkStatus? = null
        while (running) {
            val waiting =
                when {
                    !turn() -> UplinkStatus.Waiting(first = false)
                    !firstLens() -> UplinkStatus.Waiting(first = true)
                    else -> return true
                }
            if (waiting != said) report(waiting)
            said = waiting
            sleep(POLL_MS)
        }
        return false
    }

    /** A connection made, its metadata and header sent: the stream's frames go on it from here. */
    private fun open(): VideoSink {
        streamed = false
        stamped = false
        soundHeaderSent = false
        publishedSound = false
        unacknowledged.clear()
        askedNs = 0L
        heardBytes = 0L
        quietSinceNs = System.nanoTime()
        val connected = connect(address)
        publisher = connected
        // Waits a little for the clock, so that the connection's frames carry their moments, and for the sound's
        // config, so that its pieces come as the recorder looks the stream over.
        if (!alone) await(System.nanoTime() + waitForClockMs * 1_000_000) { clock() != null }
        if (sounded) await(System.nanoTime() + SOUND_WAIT_MS * 1_000_000) { soundConfig != null }
        // A connection's frames all carry their moments, or none do: the recorder places frames without one by
        // their arrival, later than they were taken, and a mix of the two would not keep its order. Once the
        // clock is in step, a connection starts at a keyframe kept with a moment; before, at the next keyframe,
        // as what was kept would be placed late by all the time it was kept. Kept frames sent alone carry theirs.
        if (alone || clock() != null) store.skipToStamped() else store.skipKept()
        // Then how long the frame it starts at was kept is known, the wait for the clock in it too (contract).
        publishedSound = soundConfig != null
        connected.publish(metadata(format, store.heldMs(captureClock?.invoke()), publishedSound))
        // Connected once the recorder took it: a lens waiting for its clock, or connecting in vain, holds no other
        // lens back (PriorityBoard) and keeps no phone awake for a laptop that is not there.
        this.connected = true
        openStampWindow(atKeyframe = false) // the connection's start
        await(Long.MAX_VALUE) { record != null }
        connected.sendSequenceHeader(record ?: throw IOException("stopped"))
        requestKeyframe()
        return connected
    }

    /**
     * The next frame to send, a connection's first a keyframe -- [first] its capture time once one went --, while the
     * first lens lets this one send: null when none came, or it does not, a frame read then put back.
     */
    private fun nextAllowed(first: Long?): KeptFrame? {
        if (!firstLens()) {
            sleep(POLL_MS)
            return null
        }
        val kept = store.next(POLL_MS, fromKeyframe = first == null)
        if (kept != null && !firstLens()) {
            store.back() // the first lens fell behind while this one waited for a frame: it waits too
            return null
        }
        return kept
    }

    /**
     * Since when the first lens has held this connection back, on the nanosecond clock -- 0 while it does not --,
     * [since] the wait so far; past [HOLD_MS] the connection is let go ([Holding]).
     */
    private fun held(since: Long): Long {
        if (firstLens()) return 0L
        val now = System.nanoTime()
        val start = if (since == 0L) now else since
        if (now - start > HOLD_MS * 1_000_000) throw Holding()
        return start
    }

    private fun stream() {
        val connected = open()
        var first: Long? = null
        val throughput = Throughput(nanos)
        var waitingSince = 0L
        while (running) {
            // Sound begun on a connection that did not tell of it -- the microphone allowed mid-stream --: FFmpeg
            // takes a stream's sound only from its start, so a new connection, from what this one may have swallowed.
            if (soundConfig != null && !publishedSound) throw SoundBegan()
            // A connection starts on a keyframe. Idle, the server's late acknowledgements are taken all the same:
            // no frame after them, they say what it read of the last sent (FrameStore.unsent).
            val kept = nextAllowed(first)
            if (kept == null) {
                askRead(connected)
                confirm(connected)
                throughput.idle()
                waitingSince = held(waitingSince)
                continue
            }
            waitingSince = 0L
            // A connection starts at a keyframe: a piece of sound comes after its first frame, never before.
            if (kept.sound) {
                first?.let { sendSound(connected, kept, it) }
            } else {
                first =
                    sendFrame(connected, kept, first, throughput)
            }
        }
    }

    /**
     * One frame [kept] on the connection, its first at [first] if one went; returns the capture time of the
     * connection's first frame.
     */
    private fun sendFrame(
        connected: VideoSink,
        kept: KeptFrame,
        first: Long?,
        throughput: Throughput,
    ): Long {
        if (first == null) stamped = kept.momentUs != null
        if (restamps(kept)) {
            store.back()
            throw IOException("the clock is in step now")
        }
        val start = first ?: kept.ptsUs
        send(connected, kept, kept.ptsUs - start, kept.momentUs?.takeIf { stamped })
        unacknowledged.addLast(connected.sentBytes to kept.ptsUs)
        // A server that acknowledges nothing leaves the store its 6 s after the newest sent (FrameStore).
        if (unacknowledged.size > UNACKNOWLEDGED_KEPT) unacknowledged.removeFirst()
        confirm(connected)
        streamed = true
        val rates = throughput.count(kept.data.size)
        val delay = clock()?.takeIf { stamped }?.delay?.div(1000.0)
        if (rates != null) report(UplinkStatus.Streaming(rates.first, rates.second, delay))
        return start
    }

    /**
     * Whether [kept], with its moment on a connection whose frames go without, makes a new one from it: a clock that
     * comes at the start does -- or as a camera feeds the lens again, at a keyframe --; one that comes once the race
     * may be under way is left for the next, as a new one is a moment of frames sent again.
     */
    private fun restamps(kept: KeptFrame): Boolean {
        val inWindow = System.nanoTime() < stampUntilNs && (kept.keyframe || !stampAtKeyframe)
        return !stamped && kept.momentUs != null && inWindow
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
        if (momentUs != null) units.add(head++, Sei.frameMoment(momentUs, format.codec))
        // The status after the moment: a reader looking for the moment finds it first. A status
        // the phone fails to read costs this keyframe its status, never the connection.
        if (kept.keyframe) {
            runCatching {
                status(
                    drops.lately(),
                )
            }.getOrNull()?.let { units.add(head, Sei.phoneStatus(it, format.codec)) }
        }
        sendingSince = System.nanoTime()
        try {
            connected.sendFrame(sinceStartUs / 1000, kept.keyframe, units)
        } finally {
            sendingSince = 0 // a send that failed is no send hanging: the next connection is not cut
        }
    }

    /**
     * A piece of sound, [kept] [start] us after the connection's first frame on the frames' clock, after the sound's
     * config the first time: one captured before that frame, or with no config to decode it by, is not sent.
     */
    private fun sendSound(
        connected: VideoSink,
        kept: KeptFrame,
        start: Long,
    ) {
        val config = soundConfig ?: return
        val since = kept.ptsUs - start
        if (since < 0) return
        if (!soundHeaderSent) {
            connected.sendSoundHeader(config)
            soundHeaderSent = true
        }
        sendingSince = System.nanoTime()
        try {
            connected.sendSound(since / 1000, kept.data)
        } finally {
            sendingSince = 0
        }
        unacknowledged.addLast(connected.sentBytes to kept.ptsUs)
        if (unacknowledged.size > UNACKNOWLEDGED_KEPT) unacknowledged.removeFirst()
        confirm(connected)
    }

    /**
     * Idle with frames sent and not confirmed -- a tail under the acknowledgements' step, which no frame after it
     * brings --: the server asked, once a second, to say it read it all, so a kept stream ends ([FrameStore.unsent]).
     * A server that says nothing new for [answerWaitMs] is a connection gone: let go, to send again what it swallowed.
     */
    private fun askRead(connected: VideoSink) {
        val now = System.nanoTime()
        val heard = connected.acknowledgedBytes
        if (unacknowledged.isEmpty() || heard != heardBytes) {
            heardBytes = heard
            quietSinceNs = now
        }
        if (unacknowledged.isEmpty()) return
        if (now - quietSinceNs > answerWaitMs * 1_000_000) throw IOException("the server says nothing of what it read")
        if (now - askedNs < ASK_EVERY_MS * 1_000_000) return
        askedNs = now
        connected.flush()
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

    /** The connection let go while the first lens catches up: connected again once it lets this one send. */
    private class Holding : IOException("waiting for the first lens")

    /** The connection let go as its sound began: the next tells of it (specs/013). */
    private class SoundBegan : IOException("the sound began")

    /** Frames and megabits per second, once a second, on the clock of [nanos]. */
    internal class Throughput(
        private val nanos: () -> Long,
    ) {
        private var frames = 0
        private var bytes = 0L
        private var since = nanos()
        private var last = since

        /** Nothing to send a second or more -- its camera closed --: counted anew from the next frame. */
        private var anew = false

        /**
         * Nothing to send now: a second or more since the last frame, the rate is counted anew from the next -- the
         * frames after a pause at their own rate. A send that hangs is no pause: its frames wait, the rate tells it.
         */
        fun idle() {
            if (nanos() - last >= REPORT_NS) anew = true
        }

        /** Counts a frame of [size] bytes; once a second, the rates since the last time. */
        fun count(size: Int): Pair<Double, Double>? {
            val now = nanos()
            if (anew) {
                frames = 0
                bytes = 0
                since = now
                anew = false
            }
            last = now
            frames++
            bytes += size
            val elapsed = now - since
            if (elapsed < REPORT_NS) return null
            val seconds = elapsed / 1e9
            val rates = frames / seconds to bytes * 8 / seconds / 1e6
            frames = 0
            bytes = 0
            since = now
            return rates
        }
    }

    companion object {
        private const val POLL_MS = 100L

        /** How often an idle connection asks the server to say it read what it was sent. */
        private const val ASK_EVERY_MS = 1_000L

        /** An idle connection saying nothing this long of frames it was sent is gone: acknowledgements come oftener. */
        const val ANSWER_WAIT_MS = 30_000L
        private const val REPORT_NS = 1_000_000_000L
        private const val FIRST_PAUSE_MS = 500L
        private const val MAX_PAUSE_MS = 8_000L
        private const val WAIT_FOR_CLOCK_MS = 3_000L

        /** How long a connection waits for the sound's config: the microphone's encoder gives it in a moment. */
        private const val SOUND_WAIT_MS = 1_000L
        private const val STALL_MS = 5_000L
        private const val STAMP_WINDOW_MS = 10_000L

        /** How long a connection waits for the first lens before it lets itself go (specs/009, FR-007). */
        const val HOLD_MS = 2_000L
        private const val VIDEO_CODEC_AVC = 7

        /** Enhanced RTMP's `videocodecid` for H.265: its FourCC, `hvc1`, as a number (specs/010-hevc). */
        private const val VIDEO_CODEC_HEVC = 0x68766331

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

        /** FLV's `audiocodecid` for AAC (specs/013). */
        private const val AUDIO_CODEC_AAC = 10

        /** The stream's metadata; [heldMs]: how long its first frame was kept (specs/007, contract); its [sound]. */
        private fun metadata(
            format: StreamFormat,
            heldMs: Long,
            sound: Boolean,
        ): Map<String, Any?> =
            mapOf(
                "width" to format.resolution.width,
                "height" to format.resolution.height,
                "framerate" to format.fps,
                "videocodecid" to if (format.codec == Codec.HEVC) VIDEO_CODEC_HEVC else VIDEO_CODEC_AVC,
                "videodatarate" to format.bitrate / 1000,
                "encoder" to "PhotoFinish Camera",
                "held_ms" to heldMs,
            ) + if (sound) mapOf("audiocodecid" to AUDIO_CODEC_AAC) else emptyMap()
    }
}
