package com.dchernykh.photofinish.camera.capture

import android.annotation.SuppressLint
import android.content.Context
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaFormat
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Range
import android.view.Surface
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import com.dchernykh.photofinish.camera.stream.Avc
import com.dchernykh.photofinish.camera.stream.EncodedFrame
import com.dchernykh.photofinish.camera.stream.Uplink
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import com.dchernykh.photofinish.camera.sync.ClockSync

/** What the camera side says to the screen. */
sealed interface StreamerStatus {
    data object Previewing : StreamerStatus

    data class Failed(
        val reason: String,
    ) : StreamerStatus

    data class Link(
        val status: UplinkStatus,
    ) : StreamerStatus

    data object NoClock : StreamerStatus
}

/**
 * The back camera into the preview and, while streaming, straight into the H.264
 * encoder's input surface: the encoder's presentation times are then the camera's
 * sensor timestamps, which the clock exchange maps onto the recorder's clock.
 * Every call is posted to the camera's own thread.
 */
class CameraStreamer(
    context: Context,
    private val formats: CameraFormats,
    private val onStatus: (StreamerStatus) -> Unit,
) {
    private val manager = context.getSystemService(CameraManager::class.java)
    private val thread = HandlerThread("camera").apply { start() }
    private val handler = Handler(thread.looper)

    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var encoder: MediaCodec? = null
    private var encoderSurface: Surface? = null
    private var uplink: Uplink? = null
    private var drainer: Thread? = null

    @Volatile private var sync: ClockSync? = null
    private var address: RtmpAddress? = null
    private var generation = 0

    /** The camera into [preview]; with an [address], into the encoder and up to PhotoFinish too. */
    fun start(
        preview: Surface,
        format: StreamFormat,
        address: RtmpAddress?,
    ) {
        handler.post { open(preview, format, address) }
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

    // Whatever opening throws -- the camera gone or refused, an encoder that will not take the
    // format -- is said on the screen: an exception left to escape would end the app.
    @Suppress("TooGenericExceptionCaught")
    @SuppressLint("MissingPermission") // the screen asks for the camera before starting
    private fun open(
        preview: Surface,
        format: StreamFormat,
        address: RtmpAddress?,
    ) {
        close()
        val id = formats.cameraId ?: return onStatus(StreamerStatus.Failed("no back camera"))
        val mine = ++generation
        this.address = address
        try {
            if (address != null) startEncoder(format, address, mine)
            manager.openCamera(
                id,
                object : CameraDevice.StateCallback() {
                    override fun onOpened(camera: CameraDevice) {
                        if (mine != generation) return camera.close()
                        device = camera
                        configure(camera, preview, format)
                    }

                    override fun onDisconnected(camera: CameraDevice) {
                        camera.close()
                        if (mine == generation) onStatus(StreamerStatus.Failed("the camera was taken by another app"))
                    }

                    override fun onError(
                        camera: CameraDevice,
                        error: Int,
                    ) {
                        camera.close()
                        if (mine == generation) onStatus(StreamerStatus.Failed("camera error $error"))
                    }
                },
                handler,
            )
        } catch (error: Exception) {
            close()
            onStatus(failed(error))
        }
    }

    // The list form serves minSdk 26 as well as SessionConfiguration; a camera gone meanwhile
    // throws, and is said on the screen.
    @Suppress("DEPRECATION", "TooGenericExceptionCaught")
    private fun configure(
        camera: CameraDevice,
        preview: Surface,
        format: StreamFormat,
    ) {
        val targets = listOfNotNull(preview, encoderSurface)
        try {
            camera.createCaptureSession(
                targets,
                object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(configured: CameraCaptureSession) {
                        session = configured
                        startFrames(configured, camera, targets, format)
                    }

                    override fun onConfigureFailed(failed: CameraCaptureSession) {
                        onStatus(
                            StreamerStatus.Failed("the camera cannot give ${format.resolution} at ${format.fps} fps"),
                        )
                    }
                },
                handler,
            )
        } catch (error: Exception) {
            onStatus(failed(error))
        }
    }

    /** The frames, one request repeated: at the stream's rate, without stabilisation. */
    @Suppress("TooGenericExceptionCaught") // a camera gone meanwhile, said on the screen
    private fun startFrames(
        configured: CameraCaptureSession,
        camera: CameraDevice,
        targets: List<Surface>,
        format: StreamFormat,
    ) {
        try {
            val template = if (encoderSurface == null) CameraDevice.TEMPLATE_PREVIEW else CameraDevice.TEMPLATE_RECORD
            val request =
                camera.createCaptureRequest(template).apply {
                    targets.forEach { addTarget(it) }
                    set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, Range(format.range.lower, format.range.upper))
                    // Electronic stabilisation warps the picture: not for a finish line.
                    set(
                        CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE,
                        CameraMetadata.CONTROL_VIDEO_STABILIZATION_MODE_OFF,
                    )
                }
            configured.setRepeatingRequest(request.build(), null, handler)
            if (encoderSurface == null) onStatus(StreamerStatus.Previewing)
        } catch (error: Exception) {
            onStatus(failed(error))
        }
    }

    /**
     * The clock the frames are stamped on, read from the first one the encoder gives: Android
     * moves an encoder's frames from boot time to monotonic time, whatever the camera says of
     * its own clock. Neither clock: the frames go without their moments, and the screen says so.
     */
    private fun clockOfFrames(
        ptsUs: Long,
        mine: Int,
    ) {
        val found = TimestampBase.detect(ptsUs * 1000, SystemClock.elapsedRealtimeNanos(), System.nanoTime())
        handler.post {
            when {
                mine != generation -> Unit // closed meanwhile
                found == null -> onStatus(StreamerStatus.NoClock)
                else -> startClock(found)
            }
        }
    }

    private fun startClock(base: TimestampBase) {
        val target = address ?: return
        if (sync != null) return
        val clock: () -> Long =
            when (base) {
                TimestampBase.REALTIME -> ({ SystemClock.elapsedRealtimeNanos() / 1000 })
                TimestampBase.MONOTONIC -> ({ System.nanoTime() / 1000 })
            }
        sync = ClockSync(target.host, target.port, clock).also { it.start() }
    }

    private fun startEncoder(
        format: StreamFormat,
        address: RtmpAddress,
        mine: Int,
    ) {
        val media =
            MediaFormat
                .createVideoFormat(
                    MediaFormat.MIMETYPE_VIDEO_AVC,
                    format.resolution.width,
                    format.resolution.height,
                ).apply {
                    setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
                    setInteger(MediaFormat.KEY_BIT_RATE, format.bitrate)
                    setInteger(MediaFormat.KEY_FRAME_RATE, format.fps)
                    setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
                    setInteger(MediaFormat.KEY_BITRATE_MODE, MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_VBR)
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0)
                }
        val codec = encoderFor(media)
        encoder = codec
        codec.configure(media, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        encoderSurface = codec.createInputSurface()
        codec.start()
        val link =
            Uplink(
                address = address,
                format = format,
                clock = { sync?.offset?.best() },
                requestKeyframe = { requestKeyframe(codec) },
                report = { onStatus(StreamerStatus.Link(it)) },
            )
        uplink = link
        Thread({ link.run() }, "uplink").start()
        drainer = Thread({ drain(codec, link) { clockOfFrames(it, mine) } }, "encoder").apply { start() }
    }

    private fun close() {
        generation++
        try {
            session?.close()
        } catch (_: IllegalStateException) {
            // already closed with its camera
        }
        session = null
        device?.close()
        device = null
        drainer?.let {
            it.interrupt() // seen within one dequeue's wait
            it.join(DRAIN_JOIN_MS)
        }
        drainer = null
        uplink?.stop()
        uplink = null
        sync?.close()
        sync = null
        encoder?.let { codec ->
            try {
                codec.stop()
            } catch (_: IllegalStateException) {
                // never started, or already stopped
            }
            codec.release()
        }
        encoder = null
        encoderSurface?.release()
        encoderSurface = null
    }

    companion object {
        private const val DEQUEUE_TIMEOUT_US = 10_000L
        private const val DRAIN_JOIN_MS = 500L

        private fun failed(error: Exception) = StreamerStatus.Failed(error.message ?: error.javaClass.simpleName)

        /** An encoder that takes [format] -- the phone's default one may not -- else that default. */
        private fun encoderFor(format: MediaFormat): MediaCodec =
            MediaCodecList(MediaCodecList.REGULAR_CODECS)
                .findEncoderForFormat(format)
                ?.let { MediaCodec.createByCodecName(it) }
                ?: MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)

        private fun requestKeyframe(codec: MediaCodec) {
            try {
                codec.setParameters(Bundle().apply { putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0) })
            } catch (_: IllegalStateException) {
                // the encoder was stopped meanwhile
            }
        }

        /**
         * The encoder's output, to the uplink: the stream's header, then the frames, until
         * interrupted; [onFirstFrame] hears of the first frame's presentation time.
         */
        private fun drain(
            codec: MediaCodec,
            link: Uplink,
            onFirstFrame: (Long) -> Unit,
        ) {
            val info = MediaCodec.BufferInfo()
            var waiting = true
            val offer: (EncodedFrame) -> Unit = { frame ->
                if (waiting) onFirstFrame(frame.ptsUs)
                waiting = false
                link.offer(frame)
            }
            var more = true
            try {
                while (more && !Thread.currentThread().isInterrupted) more = deliver(codec, link, info, offer)
            } catch (_: IllegalStateException) {
                // the encoder was stopped: the stream is over
            }
        }

        /** One output of the encoder to the uplink; false once the stream has ended. */
        private fun deliver(
            codec: MediaCodec,
            link: Uplink,
            info: MediaCodec.BufferInfo,
            offer: (EncodedFrame) -> Unit,
        ): Boolean {
            val index = codec.dequeueOutputBuffer(info, DEQUEUE_TIMEOUT_US)
            if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) configureLink(link, codec.outputFormat)
            if (index < 0) return true
            val bytes = ByteArray(info.size)
            codec.getOutputBuffer(index)?.apply {
                position(info.offset)
                get(bytes)
            }
            codec.releaseOutputBuffer(index, false)
            val flags = info.flags
            when {
                flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0 -> configureFromUnits(link, Avc.splitAnnexB(bytes))
                bytes.isNotEmpty() -> {
                    val keyframe = flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0
                    offer(EncodedFrame(bytes, info.presentationTimeUs, keyframe))
                }
            }
            return flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM == 0
        }

        private fun configureLink(
            link: Uplink,
            format: MediaFormat,
        ) {
            val units =
                listOf("csd-0", "csd-1").mapNotNull { key ->
                    format.getByteBuffer(key)?.let { buffer -> ByteArray(buffer.remaining()).also { buffer.get(it) } }
                }
            configureFromUnits(link, units.flatMap { Avc.splitAnnexB(it) })
        }

        private fun configureFromUnits(
            link: Uplink,
            units: List<ByteArray>,
        ) {
            val sps = units.firstOrNull { Avc.type(it) == Avc.NAL_SPS }
            val pps = units.firstOrNull { Avc.type(it) == Avc.NAL_PPS }
            if (sps != null && pps != null) link.configure(sps, pps)
        }
    }
}
