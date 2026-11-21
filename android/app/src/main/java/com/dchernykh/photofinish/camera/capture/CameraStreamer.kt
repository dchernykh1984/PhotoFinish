package com.dchernykh.photofinish.camera.capture

import android.annotation.SuppressLint
import android.content.Context
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.params.SessionConfiguration
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Range
import android.view.Surface
import com.dchernykh.photofinish.camera.diagnostics.Crashes
import com.dchernykh.photofinish.camera.diagnostics.PhoneLog
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.LensTarget
import com.dchernykh.photofinish.camera.status.PhoneStatusReader
import com.dchernykh.photofinish.camera.stream.Codec
import com.dchernykh.photofinish.camera.stream.FrameStore
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit

/** What the camera side says to the screen: of the cameras as a whole, or of one lens. */
sealed interface StreamerStatus {
    /** The camera gives frames, to the preview and to any lens streamed. */
    data object Previewing : StreamerStatus

    data class Failed(
        val reason: String,
    ) : StreamerStatus

    data class Link(
        val status: UplinkStatus,
    ) : StreamerStatus

    data object NoClock : StreamerStatus

    /** A lens asked for and not streamed (specs/004-phone-lenses, FR-005). */
    data class Left(
        val why: LeftOut,
    ) : StreamerStatus
}

/**
 * The phone's cameras into the preview and, while streaming, each lens asked for straight into its
 * own H.264 encoder's input surface (specs/004-phone-lenses): an encoder's presentation times are
 * then the camera's sensor timestamps, which the lens's clock exchange maps onto its recorder's
 * clock. The lenses of one camera share its capture session; a second camera -- the front with the
 * back -- is opened beside the first where the phone runs both. Every call is posted to the
 * cameras' own thread.
 */
@Suppress("TooManyFunctions") // the screen's calls and the cameras' steps on their thread, each a step of its own
class CameraStreamer(
    private val context: Context,
    private val lenses: PhoneLenses,
    private val phone: PhoneStatusReader,
    /** Where what is opened, and what fails and why, is told whole (specs/008-phone-log). */
    private val log: PhoneLog,
    /** What a lens's link says while no camera feeds it: into the phone's log, not over its camera's word on screen. */
    private val logged: (Lens?, StreamerStatus) -> Unit,
    private val onStatus: (Lens?, StreamerStatus) -> Unit,
) {
    private val manager = context.getSystemService(CameraManager::class.java)
    private val thread = HandlerThread("camera").apply { start() }
    private val handler = Handler(thread.looper)
    private val executor = Executor { handler.post(it) }
    private val opened = mutableListOf<OpenCamera>()

    /** The lenses the cameras failed with since the referee's start, left out of each open: the cameras' thread's. */
    private val fallback = LensFallback()

    /** The open whose settling is set going: once an open. */
    private var settling: Int? = null

    /** The lenses asked for, in the code's order: the order lenses are left out by. */
    private var order: List<Lens> = emptyList()

    /** The lenses asked for and not streamed, as the status tells the laptop; read from the uplinks' threads. */
    @Volatile private var leftOut: List<String> = emptyList()

    /** Counts the opens: a callback of an earlier one says nothing. Read from the uplinks' threads too. */
    @Volatile private var generation = 0

    /** Where the lenses keep their frames until sent (specs/007), the phone's free space less 10 GB (specs/009). */
    private val kept = File(context.filesDir, Senders.FOLDER)

    /** The lenses' streams, kept across the cameras' opens while the referee's choice lasts: the cameras' thread's. */
    private val keptStreams = KeptStreams<LensStream>()

    /** The other camera's next try alone, put off up to half an hour: dropped as the cameras close. */
    private var aloneTry: Runnable? = null

    init {
        handler.post { sweep() } // what a killed app kept is the backlog's to send (specs/009, FR-002)
    }

    /**
     * The cameras into [preview]; with [targets], each lens into its encoder and up to PhotoFinish too -- after a
     * [stop] for the same, which kept the streams for it or dropped them.
     */
    fun start(
        preview: Surface,
        format: StreamFormat,
        targets: List<LensTarget>,
        asked: Codec = format.codec,
    ) {
        handler.post {
            if (targets.isNotEmpty() && asked != format.codec) {
                log.warning(
                    null,
                    "${asked.paired} asked for, not taken at ${format.resolution}, ${format.fps} fps: h264",
                )
            }
            fallback.start(format, targets) // a choice of the referee's tries every lens again
            open(preview, format, targets)
        }
    }

    /**
     * The cameras closed, for [targets] at [format] to come: the lenses' streams kept when those are what they were
     * made for -- the screen back, its surface made again --, the next start feeding them again; else stopped too,
     * what they kept dropped -- the referee's stop, another choice (FR-004) --, whatever the preview does meanwhile.
     */
    fun stop(
        format: StreamFormat?,
        targets: List<LensTarget>,
    ) {
        handler.post {
            closeCameras()
            // After the cameras: none left writing to the encoders' surfaces as they go.
            if (!fallback.asks(format, targets)) keptStreams.stopAll()
        }
    }

    /**
     * The screen leaving, its preview's surface about to go: the cameras closed at once, before they fail with it
     * -- what they say after is no news --; the lenses' streams send what they kept, and stop once all is sent
     * ([sweep]) unless the screen is back meanwhile, its start feeding them again. The surface is not to be used
     * once the screen's callback returns: the close is waited for, a busy thread [AWAY_WAIT_MS] at most.
     */
    fun away() {
        val closed = CountDownLatch(1)
        val posted =
            handler.post {
                if (opened.isNotEmpty()) log.info(null, "the screen left: the cameras closed until it is back")
                closeCameras() // an open put off for 2 s too (openAgain): none opens on the surface gone
                closed.countDown()
            }
        if (posted) closed.await(AWAY_WAIT_MS, TimeUnit.MILLISECONDS)
    }

    fun release() {
        handler.post {
            closeCameras()
            keptStreams.stopAll() // what they kept handed to the backlog, which outlives the screen (specs/009)
            thread.quitSafely()
        }
    }

    /** What the lenses kept and the backlog holds, dropped: the referee's Discard, confirmed (specs/009, FR-004). */
    fun discard() {
        handler.post {
            keptStreams.discardAll()
            Senders.backlog.discard()
        }
    }

    /**
     * Each second: the lenses' streams no camera has fed for a while -- the screen away, a lens left out -- stopped
     * once they keep nothing unsent ([KeptStreams]): encoders, uplinks, clock exchanges not held for nothing.
     */
    private fun sweep() {
        keptStreams.sweep(SystemClock.elapsedRealtime()).forEach {
            log.info(it.code, "no camera feeds it, all it kept sent: stopped")
        }
        handler.postDelayed({ sweep() }, WATCH_MS)
    }

    // Whatever opening throws -- a camera gone or refused, an encoder that will not take the
    // format -- is said on the screen: an exception left to escape would end the app.
    @Suppress("TooGenericExceptionCaught")
    private fun open(
        preview: Surface,
        format: StreamFormat,
        targets: List<LensTarget>,
    ) {
        closeCameras()
        val mine = ++generation
        order = targets.map { it.lens }
        Senders.board.order = order // the code's first lens sends first (specs/009, FR-007)
        val failedWith = fallback.leftOut
        val plan =
            plan(lenses, targets.filter { it.lens !in failedWith })
                ?: return onStatus(null, StreamerStatus.Failed("no back camera"))
        failedWith.forEach { onStatus(it, StreamerStatus.Left(LeftOut.FAILED_WITH_THE_OTHERS)) }
        plan.left.forEach { (lens, why) -> onStatus(lens, StreamerStatus.Left(why)) }
        leftOut = (failedWith + plan.left.keys).map { it.code }
        // A failure of the lenses' own -- early, by its kind -- leaves one out of the next open (LensFallback).
        val again = { reason: String, failure: CameraFailure?, own: List<Lens> ->
            failedEarly(mine, reason, failure, own)
            fallback.madeAgain(mine, failure).also { if (it) openAgain(preview, format, targets, reason) }
        }
        try {
            val streaming =
                startInTurn(plan.cameras) { camera, withPreview ->
                    val open = OpenCamera(if (withPreview) preview else null, mine, again, camera, format)
                    open.start().also { started -> if (!started) leaveOut(camera.lenses.map { it.target.lens }) }
                }
            if (!streaming) { // no camera streams: the first opened for its preview alone, to aim by
                val first = PlannedCamera(plan.cameras.first().cameraId, emptyList())
                OpenCamera(preview, mine, again, first, format).start()
            }
        } catch (error: Exception) {
            // A camera the phone's camera service lost a moment ago is unknown to it until it is back: tried
            // again, as one lost while streaming is (specs/007, FR-010).
            log.error(null, "opening the cameras: ${Crashes.describe(error)}")
            again(error.message ?: error.javaClass.simpleName, null, emptyList())
        }
    }

    /**
     * The camera of [own] lenses failed, of open [open], for [reason]: the lens the open leaves out from now on,
     * if any, said -- the lenses streaming taken in the code's order, before they are closed.
     */
    private fun failedEarly(
        open: Int,
        reason: String,
        failure: CameraFailure?,
        own: List<Lens>,
    ) {
        val left = fallback.failed(open, streamed, own, failure) ?: return
        log.warning(left.code, "left out from now on: the cameras failed with it ($reason)")
    }

    /** The lenses the open cameras stream, in the code's order. */
    private val streamed: List<Lens>
        get() = opened.flatMap { it.ownLenses }.toSet().let { streaming -> order.filter { it in streaming } }

    /**
     * Whether open [open]'s lenses now run together -- every lens of every camera still open has given a frame, or
     * is waited for, checked at each first frame, when a lens is waited for and when a camera closes alone --:
     * settled [LensFallback.EARLY_MS] on, if the open lasts, whatever fails after it. A lens slow to its first
     * frame, or a second camera started after the first, counted from its own; the settling set going once an open.
     */
    private fun checkSettled(open: Int) {
        val framed = opened.isNotEmpty() && opened.all { it.allFramed } // between two opens, none to settle
        if (open != generation || settling == open || !framed) return
        settling = open
        val settle = { if (open == generation) fallback.settle(SystemClock.elapsedRealtime()) }
        handler.postDelayed(settle, LensFallback.EARLY_MS)
    }

    /**
     * A camera lost mid-stream -- another app took it, its service started again: all closed,
     * said on the screen, and opened again in a moment, as long as nothing else was asked for.
     */
    private fun openAgain(
        preview: Surface,
        format: StreamFormat,
        targets: List<LensTarget>,
        reason: String,
    ) {
        closeCameras() // the lenses' streams kept: the open 2 s on feeds them again, what they kept still sent
        val mine = generation
        onStatus(null, StreamerStatus.Failed("$reason; trying again"))
        handler.postDelayed({ if (mine == generation) open(preview, format, targets) }, OPEN_AGAIN_MS)
    }

    /**
     * The clock the frames are stamped on, read from the first one the encoder gives: Android
     * moves an encoder's frames from boot time to monotonic time, whatever the camera says of
     * its own clock. Neither clock: the lens's frames go without their moments, and the screen says so.
     */
    private fun clockOfFrames(
        stream: LensStream,
        ptsUs: Long,
    ) {
        val clock: (() -> Long)? =
            when (TimestampBase.detect(ptsUs * 1000, SystemClock.elapsedRealtimeNanos(), System.nanoTime())) {
                TimestampBase.REALTIME -> ({ SystemClock.elapsedRealtimeNanos() / 1000 })
                TimestampBase.MONOTONIC -> ({ System.nanoTime() / 1000 })
                null -> null
            }
        handler.post {
            // A stream stopped meanwhile starts none (LensStream.startClock); one idle, its camera closed meanwhile,
            // does: what it kept goes with its moments. "No clock" is a fed stream's word: an idle one's lens keeps
            // its camera's -- left out, failed.
            when {
                clock != null -> stream.startClock(clock)
                !stream.stopped && stream.fed -> onStatus(stream.lens, StreamerStatus.NoClock)
            }
        }
    }

    /**
     * [planned]'s stream at [format], its callbacks the streamer's: it outlives the camera that first fed it
     * ([KeptStreams]), and holds none of it.
     */
    private fun startStream(
        planned: PlannedLens,
        format: StreamFormat,
    ): LensStream {
        val lens = planned.target.lens
        return LensStream.start(
            planned,
            format,
            report = { status -> onStatus(lens, StreamerStatus.Link(status)) },
            logged = { status -> logged(lens, StreamerStatus.Link(status)) },
            onFirstFrame = { stream, ptsUs ->
                handler.post {
                    // It streams: the laptop counts it again, whatever it was told -- unless its camera was lost
                    // since, the frame told after the loss.
                    if (stream.fed) leftOut = leftOut - lens.code
                    checkSettled(generation) // its frame heard, lastFrameMs set: of the open feeding it
                }
                // Fed again, its frames still on the clock told: a first frame drained late is not "no clock".
                if (!stream.clocked) clockOfFrames(stream, ptsUs)
            },
            status = { dropped ->
                val held = Senders.backlog.pendingFor(planned.target.address)
                phone
                    .read()
                    .copy(dropped = dropped, left = leftOut)
                    .holding(held.ms, held.bytes)
                    .line()
            },
            // A folder a stream: one kept from before and the new one of its lens never share files (specs/009).
            store = FrameStore(File(kept, "${lens.code}-${System.currentTimeMillis()}")),
            log = log,
        )
    }

    /** Lenses that do not stream after all, told to the laptop with the next status. */
    private fun leaveOut(lenses: List<Lens>) {
        leftOut = (leftOut + lenses.map { it.code }).distinct()
    }

    /** The cameras closed, their lenses' streams kept ([KeptStreams]): an open for the same feeds them again. */
    private fun closeCameras() {
        aloneTry?.let { handler.removeCallbacks(it) } // of an open over: nothing of it kept waiting
        aloneTry = null
        generation++
        opened.forEach { it.close() }
        opened.clear()
    }

    /**
     * One camera device opened: the lenses it streams at one format, in one capture session, and
     * the [preview] it shows -- the first camera's that streams. [again] opens everything again after a loss;
     * [plan] and [chosen], what it is opened for, open it again alone ([openAlone]).
     */
    @Suppress("TooManyFunctions") // Camera2's callbacks and the watches of the frames, each a step of its own
    private inner class OpenCamera(
        private val preview: Surface?,
        private val mine: Int,
        /**
         * Opens everything again after a loss, told the failure -- the lenses' own, perhaps -- and its lenses: false
         * when it does not, the same made again to fail the same way.
         */
        private val again: (String, CameraFailure?, List<Lens>) -> Boolean,
        private val plan: PlannedCamera,
        private val chosen: StreamFormat,
    ) : CameraDevice.StateCallback() {
        private val streams = mutableListOf<LensStream>()
        private var format: StreamFormat? = null

        /** When the lenses started, on the clock of [SystemClock.elapsedRealtime]: null before. */
        private var startedMs: Long? = null

        /** The request the session was made with (Android 15): its frames asked by it, not by one built anew. */
        private var asked: CaptureRequest.Builder? = null

        /** How long ago the lenses started; null before. */
        private val sinceStart: Long? get() = startedMs?.let { SystemClock.elapsedRealtime() - it }

        /** The lenses it streams: its own, not the phone's. */
        val ownLenses: List<Lens> get() = streams.map { it.lens }

        /** Each of its lenses has given a frame, or is waited for (LensFallback.waitsFor): none of a camera closed. */
        val allFramed: Boolean get() = streams.all { it.lastFrameMs != 0L || fallback.waitsFor(mine, it.lens) }

        /**
         * Closed: its watch ends, and what its camera says after -- a callback already on its way, the other camera
         * closed alone in the same open -- is no news: lost once, it is opened again once.
         */
        private var closed = false
        private var targets: List<Surface> = emptyList()
        private var device: CameraDevice? = null
        private var session: CameraCaptureSession? = null

        /** Its lenses' streams started and its camera opened, it among the cameras open; false when none started. */
        @SuppressLint("MissingPermission") // the screen asks for the camera before starting
        fun start(): Boolean {
            opened += this
            return startStreams().also { if (it) manager.openCamera(plan.cameraId, this, handler) }
        }

        /**
         * The lenses' streams, at the size and rate [chosen] or the nearest they all give -- opened again, a stream
         * kept at that format fed again ([KeptStreams]), one at another made anew --; false, said for each lens, when
         * they give none. A camera opened for its preview alone takes [chosen]. A lens whose encoder
         * will not start -- the phone has no more of them -- is left out alone, said; false when none started and
         * there is no preview to show.
         */
        @Suppress("TooGenericExceptionCaught") // whatever an encoder throws costs its lens alone
        private fun startStreams(): Boolean {
            val lensesFormats = plan.lenses.map { CameraFormats(context, plan.cameraId, it.physicalId) }
            val common = if (plan.lenses.isEmpty()) chosen else CameraFormats.common(lensesFormats, chosen)
            if (common == null) {
                plan.lenses.forEach { onStatus(it.target.lens, StreamerStatus.Failed("no size this lens streams")) }
                return false
            }
            format = common
            val named =
                plan.lenses.joinToString {
                    it.target.lens.code +
                        it.physicalId
                            ?.let { id ->
                                "/$id"
                            }.orEmpty()
                }
            val what = named.ifEmpty { "its preview" }
            val codec = if (common.codec == Codec.HEVC) ", H.265" else "" // specs/010-hevc
            log.info(null, "camera ${plan.cameraId}: $what at ${common.resolution}, ${common.fps} fps$codec")
            plan.lenses.forEach { planned ->
                val lens = planned.target.lens
                try {
                    val fits = { old: LensStream -> old.planned.sameStream(planned) && old.format == common }
                    val stream = keptStreams.feed(lens, fits) { startStream(planned, common) }
                    stream.planned = planned // its physical camera as the session streams it now
                    streams += stream
                } catch (error: Exception) {
                    log.error(lens.code, "its encoder would not start: ${Crashes.describe(error)}")
                    onStatus(lens, failed(error))
                    leaveOut(listOf(lens))
                }
            }
            return streams.isNotEmpty() || plan.lenses.isEmpty() || preview != null
        }

        override fun onOpened(camera: CameraDevice) {
            if (mine != generation || closed) return camera.close()
            device = camera
            configure(camera)
        }

        override fun onDisconnected(camera: CameraDevice) {
            camera.close()
            if (mine == generation) lost("the camera was taken by another app", CameraFailure.Taken)
        }

        override fun onError(
            camera: CameraDevice,
            error: Int,
        ) {
            camera.close()
            val failure = CameraFailure.Error(error, sinceStart)
            if (mine == generation) lost("camera error $error: ${meaning(error)}", failure)
        }

        /**
         * A camera lost: the one with the preview opens everything again in a moment; another -- the front beside
         * the back -- is closed alone and opened again alone ([LensFallback.aloneIn]), so the first streams on rather
         * than stopping with it each time it fails. A [failure] of the lenses' own in their first seconds leaves a
         * lens out from then on (LensFallback); a lens of the first camera that gave no frame, none left out, is
         * waited for, its camera kept.
         */
        private fun lost(
            reason: String,
            failure: CameraFailure?,
        ) {
            if (closed) return
            if (preview == null) return lostAlone(reason, failure)
            val own = ownLenses
            val made = again(reason, failure, own)
            // Waited for, as it may come yet: said on the screen and to the laptop, the lens's own word.
            val said = StreamerStatus.Failed(reason)
            val silent = if (made) emptyList() else fallback.waitedFor(mine, failure)
            silent.forEach { onStatus(it, said) }
            if (!made && silent.isEmpty()) say(said)
            checkSettled(mine) // the others may run together without the lens waited for
        }

        /** The other camera lost, for [reason]: closed alone, a lens of it left out, or it opened again alone. */
        private fun lostAlone(
            reason: String,
            failure: CameraFailure?,
        ) {
            val own = ownLenses
            val left = fallback.failedAlone(mine, streamed, own, failure) // streamed before this camera closes
            close() // first: no word of its uplinks comes after the one said here; their streams kept, idle
            opened -= this
            // Its lenses' word, those it streamed or, none started, those it was opened for; told to the laptop.
            val told = own.ifEmpty { plan.lenses.map { it.target.lens } }
            leaveOut(told)
            if (left != null) {
                log.warning(left.code, "left out from now on: its camera failed with it ($reason)")
                told.forEach { onStatus(it, StreamerStatus.Failed("$reason; left out")) }
                // Its other lenses come back in an open without the one left out; else the first camera streams on.
                if (own.size > 1) again(reason, failure, own) else checkSettled(mine)
                return
            }
            // Its first lens planned keeps its tries: one that would not open, no stream fed yet, is tried again too.
            val first = plan.lenses.firstOrNull() ?: return checkSettled(mine)
            val inMs = fallback.aloneIn(first.target.lens, OPEN_AGAIN_MS)
            val said = StreamerStatus.Failed("$reason; trying again in ${LensFallback.inWords(inMs)}")
            told.forEach { onStatus(it, said) }
            aloneTry = Runnable { if (mine == generation) openAlone() }.also { handler.postDelayed(it, inMs) }
            checkSettled(mine) // the first camera's lenses may run together without it
        }

        /**
         * This camera, lost and closed alone, opened again alone for the same open, its lenses' streams fed again --
         * the first camera's streaming on --; one the phone will not open now is lost again, tried again later.
         */
        @Suppress("TooGenericExceptionCaught") // a camera gone meanwhile, a permission taken back: lost again
        private fun openAlone() {
            val open = OpenCamera(null, mine, again, plan, chosen) // its lenses left out until their first frames
            try {
                // No stream started: each lens said why; tried again later, not left out.
                if (!open.start()) open.lost("no stream for its lenses", null)
            } catch (error: Exception) {
                log.error(null, "opening camera ${plan.cameraId} again: ${Crashes.describe(error)}")
                open.lost(error.message ?: error.javaClass.simpleName, null)
            }
        }

        // The list form serves Android 8, where a camera streams one lens; a camera gone meanwhile
        // throws, and is said on the screen.
        @Suppress("DEPRECATION", "TooGenericExceptionCaught")
        private fun configure(camera: CameraDevice) {
            val callback =
                object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(configured: CameraCaptureSession) {
                        if (mine != generation || closed) return configured.close() // an earlier open's, or closed
                        session = configured
                        startFrames(configured, camera)
                    }

                    override fun onConfigureFailed(failed: CameraCaptureSession) {
                        if (mine != generation || closed) return
                        val tried = format?.let { "${it.resolution} at ${it.fps} fps" }.orEmpty()
                        lost("the camera cannot give these lenses $tried together", CameraFailure.NotConfigured)
                    }
                }
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    // The rate asked goes with the session, and with the question whether the camera runs these
                    // lenses, from Android 15, which weighs it: a set it cannot run at that rate said no to
                    // beforehand. Earlier, sessions are made as they were: a phone that streamed them streams on.
                    val parameters =
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.VANILLA_ICE_CREAM) {
                            request(camera, format, streams.isNotEmpty()).also { asked = it }.build()
                        } else {
                            null // not asked of the camera for nothing
                        }
                    val (outputs, dropped) = SessionOutputs.choose(camera, preview, streams, executor, parameters)
                    dropped.forEach {
                        streams.remove(it)
                        keptStreams.drop(it.lens, SystemClock.elapsedRealtime()) // what it kept still sent
                        onStatus(it.lens, StreamerStatus.Left(LeftOut.NOT_WITH_THE_OTHERS))
                    }
                    leaveOut(dropped.map { it.lens })
                    targets = outputs.flatMap { it.surfaces }
                    camera.createCaptureSession(
                        SessionConfiguration(SessionConfiguration.SESSION_REGULAR, outputs, executor, callback).apply {
                            parameters?.let { sessionParameters = it }
                        },
                    )
                } else {
                    targets = listOfNotNull(preview) + streams.map { it.surface }
                    camera.createCaptureSession(targets, callback, handler)
                }
            } catch (error: Exception) {
                log.error(null, "configuring camera ${camera.id}: ${Crashes.describe(error)}")
                broke(error)
            }
        }

        /** The frames, one request repeated: at the stream's rate, without stabilisation. */
        @Suppress("TooGenericExceptionCaught") // a camera gone meanwhile, said on the screen
        private fun startFrames(
            configured: CameraCaptureSession,
            camera: CameraDevice,
        ) {
            if (format?.range == null) return
            try {
                val request =
                    (asked ?: request(camera, format, streams.isNotEmpty())).apply {
                        targets.forEach { addTarget(it) }
                    }
                configured.setRepeatingRequest(request.build(), null, handler)
                // A stream fed again: the camera's first frame a keyframe, the frames of the camera before all out.
                streams.forEach { it.keyframe() }
                startedMs = SystemClock.elapsedRealtime()
                if (streams.isNotEmpty()) handler.postDelayed({ watchFrames() }, WATCH_MS)
                // The camera gives frames: a failure said before, a camera lost and opened again, is over;
                // the camera with the preview says so for the cameras as a whole, the others' lenses by their links.
                previewStatus(preview, targets)?.let { onStatus(null, it) }
            } catch (error: Exception) {
                log.error(null, "starting camera ${camera.id}'s frames: ${Crashes.describe(error)}")
                broke(error)
            }
        }

        /**
         * The lenses' frames, watched each second while the camera streams: what [LensFallback.watch] finds -- a lens
         * that gave no frame, or stopped, saying nothing, the Xiaomi 17 Ultra's with four lenses -- is the camera lost,
         * as one that says so is; the watch goes on while the camera is kept.
         */
        private fun watchFrames() {
            val started = startedMs ?: return
            if (mine != generation || closed) return
            val seen = streams.map { Seen(it.lens, it.lastFrameMs) }
            val first = if (preview != null) streamed.firstOrNull() else null // the retry is its camera's
            val now = SystemClock.elapsedRealtime()
            fallback.watch(mine, seen, started, now, first)?.let { lost(it.reason, it.failure) }
            if (mine == generation && !closed) handler.postDelayed({ watchFrames() }, WATCH_MS)
        }

        /**
         * What this camera says: of its lenses when it streams some, else of the cameras as a whole --
         * with two cameras open, one's news does not overwrite the other's.
         */
        private fun say(status: StreamerStatus) {
            if (streams.isEmpty()) onStatus(null, status) else streams.forEach { onStatus(it.lens, status) }
            if (status is StreamerStatus.Failed) leaveOut(streams.map { it.lens }) // they give no frames
        }

        /**
         * Its session would not start, for [error]: said; the other camera's is its loss -- opened again alone, later
         * ([lostAlone]) --, as no word of its camera may follow to say so.
         */
        private fun broke(error: Exception) {
            val said = failed(error)
            if (preview == null) lost(said.reason, null) else say(said)
        }

        /** Its camera closed, its lenses' streams kept, idle ([KeptStreams]): an open for the same feeds them again. */
        fun close() {
            closed = true
            try {
                session?.close()
            } catch (_: IllegalStateException) {
                // already closed with its camera
            }
            session = null
            device?.close()
            device = null
            val now = SystemClock.elapsedRealtime()
            streams.forEach { keptStreams.idle(it.lens, now) }
            streams.clear()
            targets = emptyList() // the front's try put off holds none of it meanwhile
            asked = null
        }
    }

    companion object {
        private const val OPEN_AGAIN_MS = 2_000L
        private const val AWAY_WAIT_MS = 1_000L

        private const val WATCH_MS = 1_000L

        // The screen's words, the laptop's last word of the phone too: the error told whole, for whoever looks
        // into it, is logged beside them where it is caught (specs/008-phone-log, FR-001).
        private fun failed(error: Exception) = StreamerStatus.Failed(error.message ?: error.javaClass.simpleName)

        /** The request [camera] streams [format] by -- its lenses' when [streaming] --: at its rate, unstabilised. */
        private fun request(
            camera: CameraDevice,
            format: StreamFormat?,
            streaming: Boolean,
        ): CaptureRequest.Builder {
            val template = if (streaming) CameraDevice.TEMPLATE_RECORD else CameraDevice.TEMPLATE_PREVIEW
            return camera.createCaptureRequest(template).apply {
                format?.range?.let { set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, Range(it.lower, it.upper)) }
                // Electronic stabilisation warps the picture: not for a finish line.
                set(
                    CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE,
                    CameraMetadata.CONTROL_VIDEO_STABILIZATION_MODE_OFF,
                )
            }
        }

        /** What a camera's error code means, as Android names it. */
        private fun meaning(error: Int): String =
            when (error) {
                CameraDevice.StateCallback.ERROR_CAMERA_IN_USE -> "in use by another app"
                CameraDevice.StateCallback.ERROR_MAX_CAMERAS_IN_USE -> "too many cameras open"
                CameraDevice.StateCallback.ERROR_CAMERA_DISABLED -> "disabled by the phone's policy"
                CameraDevice.StateCallback.ERROR_CAMERA_DEVICE -> "the camera device failed"
                CameraDevice.StateCallback.ERROR_CAMERA_SERVICE -> "the camera service failed"
                else -> "unknown"
            }

        /** What to open: the lenses asked for, or else the main camera for its preview. */
        private fun plan(
            lenses: PhoneLenses,
            targets: List<LensTarget>,
        ): SessionPlan? {
            val main = lenses.mainCameraId ?: return null
            val physical = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
            val planned = SessionPlan.plan(targets, lenses.found, lenses::together, physical)
            return if (planned.cameras.isEmpty()) {
                planned.copy(
                    cameras = listOf(PlannedCamera(main, emptyList())),
                )
            } else {
                planned
            }
        }
    }
}
