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
import com.dchernykh.photofinish.camera.stream.FrameStore
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executor

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
class CameraStreamer(
    private val context: Context,
    private val lenses: PhoneLenses,
    private val phone: PhoneStatusReader,
    /** Where what is opened, and what fails and why, is told whole (specs/008-phone-log). */
    private val log: PhoneLog,
    private val onStatus: (Lens?, StreamerStatus) -> Unit,
) {
    private val manager = context.getSystemService(CameraManager::class.java)
    private val thread = HandlerThread("camera").apply { start() }
    private val handler = Handler(thread.looper)
    private val executor = Executor { handler.post(it) }
    private val opened = mutableListOf<OpenCamera>()

    /** The lenses the cameras failed with since the referee's start, left out of each open: the cameras' thread's. */
    private val fallback = LensFallback()

    /** The lenses asked for and not streamed, as the status tells the laptop; read from the uplinks' threads. */
    @Volatile private var leftOut: List<String> = emptyList()

    /** Counts the opens: a callback of an earlier one says nothing. Read from the uplinks' threads too. */
    @Volatile private var generation = 0

    /** Where the lenses keep their frames until sent (specs/007), and each one's share of the room. */
    private val kept = File(context.filesDir, KEPT)
    private var share = FrameStore.SHARE_BYTES

    /** The cameras into [preview]; with [targets], each lens into its encoder and up to PhotoFinish too. */
    fun start(
        preview: Surface,
        format: StreamFormat,
        targets: List<LensTarget>,
    ) {
        handler.post {
            fallback.start(format, targets) // a start of the referee's tries every lens again
            open(preview, format, targets)
        }
    }

    fun stop() {
        handler.post { close() }
    }

    fun release() {
        handler.post {
            close()
            thread.quitSafely()
        }
    }

    // Whatever opening throws -- a camera gone or refused, an encoder that will not take the
    // format -- is said on the screen: an exception left to escape would end the app.
    @Suppress("TooGenericExceptionCaught")
    @SuppressLint("MissingPermission") // the screen asks for the camera before starting
    private fun open(
        preview: Surface,
        format: StreamFormat,
        targets: List<LensTarget>,
    ) {
        close()
        val mine = ++generation
        // shortcut: a camera opened again drops what its lenses kept, as their streams start anew; keep the
        // stores across an open if a camera lost in the middle of a network break is seen to cost frames.
        kept.deleteRecursively() // what a killed app kept, too: never sent
        val failedWith = fallback.leftOut
        val plan =
            plan(lenses, targets.filter { it.lens !in failedWith })
                ?: return onStatus(null, StreamerStatus.Failed("no back camera"))
        // The room shared by the lenses streamed: one left out leaves the others its share.
        share = FrameStore.SHARE_BYTES / plan.cameras.sumOf { it.lenses.size }.coerceAtLeast(1)
        failedWith.forEach { onStatus(it, StreamerStatus.Left(LeftOut.NOT_WITH_THE_OTHERS)) }
        plan.left.forEach { (lens, why) -> onStatus(lens, StreamerStatus.Left(why)) }
        leftOut = (failedWith + plan.left.keys).map { it.code }
        // A failure of the lenses' own -- early, by its kind -- leaves one out of the next open (LensFallback).
        val again = { reason: String, failure: CameraFailure?, own: List<Lens> ->
            val left = failedEarly(mine, targets, reason, failure, own)
            fallback.madeAgain(failure, left).also { if (it) openAgain(preview, format, targets, reason) }
        }
        try {
            val shown =
                startInTurn(plan.cameras) { camera, withPreview ->
                    val open = OpenCamera(if (withPreview) preview else null, mine, again)
                    opened += open
                    open.startStreams(camera, format).also { started ->
                        if (started) {
                            manager.openCamera(camera.cameraId, open, handler)
                        } else {
                            leaveOut(camera.lenses.map { it.target.lens })
                        }
                    }
                }
            if (!shown) { // no camera streams: the first opened for its preview alone, to aim by
                val first = plan.cameras.first().cameraId
                val open = OpenCamera(preview, mine, again)
                opened += open
                if (open.startStreams(PlannedCamera(first, emptyList()), format)) {
                    manager.openCamera(first, open, handler)
                }
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
     * if any, said -- the lenses streaming taken in [targets]' order, before they are closed.
     */
    private fun failedEarly(
        open: Int,
        targets: List<LensTarget>,
        reason: String,
        failure: CameraFailure?,
        own: List<Lens>,
    ): Lens? {
        val streaming = opened.flatMap { it.lenses }.toSet()
        val streamed = targets.map { it.lens }.filter { it in streaming }
        return fallback.failed(open, streamed, own, failure)?.also {
            log.warning(it.code, "left out from now on: the cameras failed with it ($reason)")
        }
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
        close()
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
        mine: Int,
    ) {
        val clock: (() -> Long)? =
            when (TimestampBase.detect(ptsUs * 1000, SystemClock.elapsedRealtimeNanos(), System.nanoTime())) {
                TimestampBase.REALTIME -> ({ SystemClock.elapsedRealtimeNanos() / 1000 })
                TimestampBase.MONOTONIC -> ({ System.nanoTime() / 1000 })
                null -> null
            }
        handler.post {
            when {
                mine != generation -> Unit // closed meanwhile
                clock == null -> onStatus(stream.lens, StreamerStatus.NoClock)
                else -> stream.startClock(clock)
            }
        }
    }

    /** Lenses that do not stream after all, told to the laptop with the next status. */
    private fun leaveOut(lenses: List<Lens>) {
        leftOut = (leftOut + lenses.map { it.code }).distinct()
    }

    private fun close() {
        generation++
        opened.forEach { it.close() }
        opened.clear()
    }

    /**
     * One camera device opened: the lenses it streams at one format, in one capture session, and
     * the [preview] it shows -- the first camera's that streams. [again] opens everything again after a loss.
     */
    private inner class OpenCamera(
        private val preview: Surface?,
        private val mine: Int,
        /**
         * Opens everything again after a loss, told the failure -- the lenses' own, perhaps -- and its lenses: false
         * when it does not, the same made again to fail the same way.
         */
        private val again: (String, CameraFailure?, List<Lens>) -> Boolean,
    ) : CameraDevice.StateCallback() {
        private val streams = mutableListOf<LensStream>()
        private var format: StreamFormat? = null

        /** When the lenses started, on the clock of [SystemClock.elapsedRealtime]: null before. */
        private var startedMs: Long? = null

        /** How long ago the lenses started; null before. */
        private val sinceStart: Long? get() = startedMs?.let { SystemClock.elapsedRealtime() - it }

        /** The lenses it streams. */
        val lenses: List<Lens> get() = streams.map { it.lens }

        /** The lenses whose encoder has given a frame: the encoders' threads add, the cameras' reads. */
        private val framed = ConcurrentHashMap.newKeySet<Lens>()

        /** Closed: its uplinks' words after it are the stopped streams', and dropped. */
        @Volatile private var closed = false
        private var targets: List<Surface> = emptyList()
        private var device: CameraDevice? = null
        private var session: CameraCaptureSession? = null

        /**
         * The lenses' streams, at the size and rate [chosen] or the nearest they all give; false,
         * said for each lens, when they give none. A camera opened for its preview alone takes [chosen].
         * A lens whose encoder will not start -- the phone has no more of them -- is left out alone,
         * said; false when none started and there is no preview to show.
         */
        @Suppress("TooGenericExceptionCaught") // whatever an encoder throws costs its lens alone
        fun startStreams(
            camera: PlannedCamera,
            chosen: StreamFormat,
        ): Boolean {
            val lensesFormats = camera.lenses.map { CameraFormats(context, camera.cameraId, it.physicalId) }
            val common = if (camera.lenses.isEmpty()) chosen else CameraFormats.common(lensesFormats, chosen)
            if (common == null) {
                camera.lenses.forEach { onStatus(it.target.lens, StreamerStatus.Failed("no size this lens streams")) }
                return false
            }
            format = common
            val named =
                camera.lenses.joinToString {
                    it.target.lens.code +
                        it.physicalId
                            ?.let { id ->
                                "/$id"
                            }.orEmpty()
                }
            val what = named.ifEmpty { "its preview" }
            log.info(null, "camera ${camera.cameraId}: $what at ${common.resolution}, ${common.fps} fps")
            camera.lenses.forEach { planned ->
                val lens = planned.target.lens
                try {
                    streams +=
                        LensStream.start(
                            planned,
                            common,
                            report = { status ->
                                if (mine == generation && !closed) onStatus(lens, StreamerStatus.Link(status))
                            },
                            onFirstFrame = { stream, ptsUs ->
                                framed += stream.lens
                                clockOfFrames(stream, ptsUs, mine)
                            },
                            status = { dropped -> phone.read().copy(dropped = dropped, left = leftOut).line() },
                            store = FrameStore(File(kept, lens.code), share),
                            log = log,
                        )
                } catch (error: Exception) {
                    log.error(lens.code, "its encoder would not start: ${Crashes.describe(error)}")
                    onStatus(lens, failed(error))
                    leaveOut(listOf(lens))
                }
            }
            return streams.isNotEmpty() || camera.lenses.isEmpty() || preview != null
        }

        override fun onOpened(camera: CameraDevice) {
            if (mine != generation) return camera.close()
            device = camera
            configure(camera)
        }

        override fun onDisconnected(camera: CameraDevice) {
            camera.close()
            if (mine == generation) lost("the camera was taken by another app", CameraFailure.Taken(sinceStart))
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
         * A camera lost: the one with the preview opens everything again in a moment; another --
         * the front beside the back -- is closed alone, its lenses said left out, so the first
         * streams on rather than stopping with it each time it fails. A [failure] of the lenses'
         * own in their first seconds leaves a lens out from then on (LensFallback).
         */
        private fun lost(
            reason: String,
            failure: CameraFailure?,
        ) {
            val lenses = lenses
            if (preview != null) {
                when {
                    again(reason, failure, lenses) -> Unit
                    failure is CameraFailure.NoFrame -> log.warning(null, reason) // waited for: it may come yet
                    else -> say(StreamerStatus.Failed(reason))
                }
                return
            }
            close() // first: no word of its uplinks comes after the one said here
            fallback.failedAlone(mine, lenses, failure).forEach {
                log.warning(it.code, "left out from now on: its camera failed with it ($reason)")
            }
            lenses.forEach { onStatus(it, StreamerStatus.Failed("$reason; left out")) }
            leaveOut(lenses) // told to the laptop
        }

        // The list form serves Android 8, where a camera streams one lens; a camera gone meanwhile
        // throws, and is said on the screen.
        @Suppress("DEPRECATION", "TooGenericExceptionCaught")
        private fun configure(camera: CameraDevice) {
            val callback =
                object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(configured: CameraCaptureSession) {
                        if (mine != generation) return configured.close() // an earlier open's
                        session = configured
                        startFrames(configured, camera)
                    }

                    override fun onConfigureFailed(failed: CameraCaptureSession) {
                        if (mine != generation) return
                        val asked = format?.let { "${it.resolution} at ${it.fps} fps" }.orEmpty()
                        // The preview's surface gone -- the screen leaving -- failed it, not the lenses.
                        val failure = CameraFailure.NotConfigured.takeIf { preview?.isValid != false }
                        lost("the camera cannot give these lenses $asked together", failure)
                    }
                }
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    // The rate asked goes with the session, and with the question whether the camera runs these
                    // lenses, from Android 15, which weighs it: a set it cannot run at that rate said no to
                    // beforehand. Earlier, sessions are made as they were: a phone that streamed them streams on.
                    val parameters =
                        request(camera, format, streams.isNotEmpty())
                            .build()
                            .takeIf { Build.VERSION.SDK_INT >= Build.VERSION_CODES.VANILLA_ICE_CREAM }
                    val (outputs, dropped) = SessionOutputs.choose(camera, preview, streams, executor, parameters)
                    dropped.forEach {
                        streams.remove(it)
                        it.stop()
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
                say(failed(error))
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
                val request = request(camera, format, streams.isNotEmpty()).apply { targets.forEach { addTarget(it) } }
                configured.setRepeatingRequest(request.build(), null, handler)
                startedMs = SystemClock.elapsedRealtime()
                if (streams.isNotEmpty()) handler.postDelayed({ checkFrames() }, NO_FRAME_MS)
                // The camera gives frames: a failure said before, a camera lost and opened again, is over;
                // the camera with the preview says so for the cameras as a whole, the others' lenses by their links.
                previewStatus(preview, targets)?.let { onStatus(null, it) }
            } catch (error: Exception) {
                log.error(null, "starting camera ${camera.id}'s frames: ${Crashes.describe(error)}")
                say(failed(error))
            }
        }

        /**
         * A camera that has given a lens no frame [NO_FRAME_MS] after they started -- the Xiaomi 17 Ultra's
         * stalled with four lenses, saying nothing -- failed, the lenses' doing: lost, as one that says so is.
         */
        private fun checkFrames() {
            if (mine != generation || closed) return
            val silent = lenses.filter { it !in framed }
            if (silent.isEmpty()) return
            val reason = "the camera gave ${silent.joinToString { it.code }} no frame in ${NO_FRAME_MS / MS_PER_S} s"
            lost(reason, CameraFailure.NoFrame(silent, sinceStart ?: 0L))
        }

        /**
         * What this camera says: of its lenses when it streams some, else of the cameras as a whole --
         * with two cameras open, one's news does not overwrite the other's.
         */
        private fun say(status: StreamerStatus) {
            if (streams.isEmpty()) onStatus(null, status) else streams.forEach { onStatus(it.lens, status) }
            if (status is StreamerStatus.Failed) leaveOut(streams.map { it.lens }) // they give no frames
        }

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
            streams.forEach { it.stop() }
            streams.clear()
        }
    }

    companion object {
        private const val OPEN_AGAIN_MS = 2_000L
        private const val NO_FRAME_MS = 5_000L
        private const val MS_PER_S = 1_000L

        private const val KEPT = "kept"

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
