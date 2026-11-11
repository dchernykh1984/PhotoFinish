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
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.LensTarget
import com.dchernykh.photofinish.camera.status.PhoneStatusReader
import com.dchernykh.photofinish.camera.stream.UplinkStatus
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
    private val onStatus: (Lens?, StreamerStatus) -> Unit,
) {
    private val manager = context.getSystemService(CameraManager::class.java)
    private val thread = HandlerThread("camera").apply { start() }
    private val handler = Handler(thread.looper)
    private val executor = Executor { handler.post(it) }
    private val opened = mutableListOf<OpenCamera>()

    /** The lenses asked for and not streamed, as the status tells the laptop; read from the uplinks' threads. */
    @Volatile private var leftOut: List<String> = emptyList()

    /** Counts the opens: a callback of an earlier one says nothing. Read from the uplinks' threads too. */
    @Volatile private var generation = 0

    /** The cameras into [preview]; with [targets], each lens into its encoder and up to PhotoFinish too. */
    fun start(
        preview: Surface,
        format: StreamFormat,
        targets: List<LensTarget>,
    ) {
        handler.post { open(preview, format, targets) }
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
        val plan = plan(lenses, targets) ?: return onStatus(null, StreamerStatus.Failed("no back camera"))
        plan.left.forEach { (lens, why) -> onStatus(lens, StreamerStatus.Left(why)) }
        leftOut = plan.left.keys.map { it.code }
        val again = { reason: String -> openAgain(preview, format, targets, reason) }
        try {
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
        } catch (error: Exception) {
            close()
            onStatus(null, failed(error))
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
        private val again: (String) -> Unit,
    ) : CameraDevice.StateCallback() {
        private val streams = mutableListOf<LensStream>()
        private var format: StreamFormat? = null
        private var targets: List<Surface> = emptyList()
        private var device: CameraDevice? = null
        private var session: CameraCaptureSession? = null

        /**
         * The lenses' streams, at the size and rate [chosen] or the nearest they all give; false,
         * said for each lens, when they give none. A camera opened for its preview alone takes [chosen].
         */
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
            camera.lenses.forEach { planned ->
                val lens = planned.target.lens
                streams +=
                    LensStream.start(
                        planned,
                        common,
                        report = { status -> if (mine == generation) onStatus(lens, StreamerStatus.Link(status)) },
                        onFirstFrame = { stream, ptsUs -> clockOfFrames(stream, ptsUs, mine) },
                        status = { dropped -> phone.read().copy(dropped = dropped, left = leftOut).line() },
                    )
            }
            return true
        }

        override fun onOpened(camera: CameraDevice) {
            if (mine != generation) return camera.close()
            device = camera
            configure(camera)
        }

        override fun onDisconnected(camera: CameraDevice) {
            camera.close()
            if (mine == generation) again("the camera was taken by another app")
        }

        override fun onError(
            camera: CameraDevice,
            error: Int,
        ) {
            camera.close()
            if (mine == generation) again("camera error $error")
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
                        say(StreamerStatus.Failed("the camera cannot give these lenses $asked together"))
                    }
                }
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    val (outputs, dropped) = SessionOutputs.choose(camera, preview, streams, executor)
                    dropped.forEach {
                        streams.remove(it)
                        it.stop()
                        onStatus(it.lens, StreamerStatus.Left(LeftOut.NOT_WITH_THE_OTHERS))
                    }
                    leaveOut(dropped.map { it.lens })
                    targets = outputs.flatMap { it.surfaces }
                    camera.createCaptureSession(
                        SessionConfiguration(SessionConfiguration.SESSION_REGULAR, outputs, executor, callback),
                    )
                } else {
                    targets = listOfNotNull(preview) + streams.map { it.surface }
                    camera.createCaptureSession(targets, callback, handler)
                }
            } catch (error: Exception) {
                say(failed(error))
            }
        }

        /** The frames, one request repeated: at the stream's rate, without stabilisation. */
        @Suppress("TooGenericExceptionCaught") // a camera gone meanwhile, said on the screen
        private fun startFrames(
            configured: CameraCaptureSession,
            camera: CameraDevice,
        ) {
            val range = format?.range ?: return
            try {
                val streaming = streams.isNotEmpty()
                val template = if (streaming) CameraDevice.TEMPLATE_RECORD else CameraDevice.TEMPLATE_PREVIEW
                val request =
                    camera.createCaptureRequest(template).apply {
                        targets.forEach { addTarget(it) }
                        set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, Range(range.lower, range.upper))
                        // Electronic stabilisation warps the picture: not for a finish line.
                        set(
                            CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE,
                            CameraMetadata.CONTROL_VIDEO_STABILIZATION_MODE_OFF,
                        )
                    }
                configured.setRepeatingRequest(request.build(), null, handler)
                // The camera gives frames: a failure said before, a camera lost and opened again, is over;
                // the camera with the preview says so for the cameras as a whole, the others' lenses by their links.
                previewStatus(preview, targets)?.let { onStatus(null, it) }
            } catch (error: Exception) {
                say(failed(error))
            }
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

        private fun failed(error: Exception) = StreamerStatus.Failed(error.message ?: error.javaClass.simpleName)

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
