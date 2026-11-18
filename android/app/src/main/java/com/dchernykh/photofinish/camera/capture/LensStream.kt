package com.dchernykh.photofinish.camera.capture

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaFormat
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.view.Surface
import com.dchernykh.photofinish.camera.diagnostics.Crashes
import com.dchernykh.photofinish.camera.diagnostics.PhoneLog
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.stream.Avc
import com.dchernykh.photofinish.camera.stream.EncodedFrame
import com.dchernykh.photofinish.camera.stream.FrameStore
import com.dchernykh.photofinish.camera.stream.Uplink
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import com.dchernykh.photofinish.camera.sync.ClockSync
import java.util.concurrent.atomic.AtomicReference

/**
 * One lens's stream (specs/004-phone-lenses, FR-005): an H.264 encoder the camera feeds through
 * its input [surface], an uplink to the lens's address, a thread draining the encoder into the
 * uplink, and the clock exchange with the lens's recorder, made once the first frame tells which
 * clock the frames are stamped on. It outlives the cameras' opens ([KeptStreams]): a camera opened again feeds
 * the same encoder's [surface] at its [format].
 */
internal class LensStream private constructor(
    val planned: PlannedLens,
    val format: StreamFormat,
    private val codec: MediaCodec,
    val surface: Surface,
    private val uplink: Uplink,
    private val sync: AtomicReference<ClockSync?>,
) : KeptStream {
    private var drainer: Thread? = null

    /** Fed by a camera: what its link does is said, an idle one's words not ([KeptStream.idle]). Read by the uplink. */
    @Volatile private var fed = true

    /** Stopped, its stream over: a first frame heard after this starts no clock exchange, and says nothing. */
    @Volatile var stopped = false
        private set

    /** When its encoder last gave a frame, on [SystemClock.elapsedRealtime]: 0 before the first since it was fed. */
    @Volatile var lastFrameMs = 0L
        private set

    val lens: Lens get() = planned.target.lens

    /**
     * The clock exchange with the lens's recorder, on [clock], unless one runs or the stream ended; the
     * uplink tells by it how long a connection's first frame was kept.
     */
    fun startClock(clock: () -> Long) {
        if (stopped || sync.get() != null) return
        uplink.captureClock = clock
        val address = planned.target.address
        sync.set(ClockSync(address.host, address.port, clock).also { it.start() })
    }

    /** How much its frames kept and not sent yet span, ms ([Uplink.keptMs]). */
    val keptMs: Long get() = uplink.keptMs

    override val unsent: Boolean get() = uplink.unsent

    override fun feed() {
        fed = true
        lastFrameMs = 0L // its frames watched from the camera's next: the first since tells the camera gives it
        requestKeyframe(codec) // the recorder decodes from it, whatever came before the gap
    }

    override fun idle() {
        fed = false
    }

    override fun stop() {
        stopped = true
        drainer?.let {
            it.interrupt() // seen within one dequeue's wait
            it.join(DRAIN_JOIN_MS)
        }
        uplink.stop()
        sync.getAndSet(null)?.close()
        try {
            codec.stop()
        } catch (_: IllegalStateException) {
            // never started, or already stopped
        }
        codec.release()
        surface.release()
    }

    companion object {
        private const val DEQUEUE_TIMEOUT_US = 10_000L
        private const val DRAIN_JOIN_MS = 500L

        /**
         * [planned]'s stream at [format], started, fed: [report] hears its uplink while a camera feeds it,
         * [onFirstFrame] the presentation time of the first frame each feed; [status] gives the phone's status
         * line for each keyframe;
         * [store] keeps the frames until they are sent; [log] hears of an encoder that fails while it streams
         * (specs/008-phone-log).
         */
        @Suppress("LongParameterList") // a stream's parts, each its own: the camera streamer's to give
        fun start(
            planned: PlannedLens,
            format: StreamFormat,
            report: (UplinkStatus) -> Unit,
            onFirstFrame: (LensStream, Long) -> Unit,
            status: (Long) -> String?,
            store: FrameStore,
            log: PhoneLog,
        ): LensStream {
            val media = mediaFormat(format)
            val codec = encoderFor(media)
            var input: Surface? = null // released with the codec when its start fails
            val surface =
                try {
                    codec.configure(media, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
                    codec.createInputSurface().also {
                        input = it
                        codec.start()
                    }
                } catch (error: IllegalStateException) {
                    input?.release()
                    codec.release()
                    throw error
                } catch (error: IllegalArgumentException) {
                    input?.release()
                    codec.release()
                    throw error
                }
            val sync = AtomicReference<ClockSync?>()
            lateinit var stream: LensStream // made before the uplink's thread, the one to report, starts
            val uplink =
                Uplink(
                    address = planned.target.address,
                    format = format,
                    clock = { sync.get()?.offset?.best() },
                    requestKeyframe = { requestKeyframe(codec) },
                    report = { if (stream.fed) report(it) },
                    store = store,
                )
            uplink.status = status
            stream = LensStream(planned, format, codec, surface, uplink, sync)
            val name = planned.target.lens.code
            Thread({ uplink.run() }, "uplink-$name").start()
            val failed = { error: IllegalStateException ->
                if (!stream.stopped) log.error(name, "its encoder stopped: ${Crashes.describe(error)}")
            }
            val heard = {
                val first = stream.lastFrameMs == 0L
                stream.lastFrameMs = SystemClock.elapsedRealtime()
                first
            }
            stream.drainer =
                Thread({ drain(codec, uplink, failed, heard) { onFirstFrame(stream, it) } }, "encoder-$name")
                    .apply { start() }
            return stream
        }

        private fun mediaFormat(format: StreamFormat): MediaFormat =
            MediaFormat
                .createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, format.resolution.width, format.resolution.height)
                .apply {
                    setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
                    setInteger(MediaFormat.KEY_BIT_RATE, format.bitrate)
                    setInteger(MediaFormat.KEY_FRAME_RATE, format.fps)
                    setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
                    setInteger(MediaFormat.KEY_BITRATE_MODE, MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_VBR)
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0)
                }

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
         * The encoder's output, to the uplink: the stream's header, then the frames, until interrupted; [heard]
         * hears of each frame, true for the first since a camera fed the stream, [onFirstFrame] of its time.
         */
        private fun drain(
            codec: MediaCodec,
            link: Uplink,
            failed: (IllegalStateException) -> Unit,
            heard: () -> Boolean,
            onFirstFrame: (Long) -> Unit,
        ) {
            val info = MediaCodec.BufferInfo()
            val offer: (EncodedFrame) -> Unit = { frame ->
                if (heard()) onFirstFrame(frame.ptsUs)
                link.offer(frame)
            }
            var more = true
            try {
                while (more && !Thread.currentThread().isInterrupted) more = deliver(codec, link, info, offer)
            } catch (error: IllegalStateException) {
                failed(error) // the encoder was stopped, the stream over -- or it failed, and is said
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
