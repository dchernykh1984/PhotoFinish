package com.dchernykh.photofinish.camera.capture

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaFormat
import android.os.Build
import android.os.Bundle
import android.view.Surface
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.stream.Avc
import com.dchernykh.photofinish.camera.stream.EncodedFrame
import com.dchernykh.photofinish.camera.stream.Uplink
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import com.dchernykh.photofinish.camera.sync.ClockSync
import java.util.concurrent.atomic.AtomicReference

/**
 * One lens's stream (specs/004-phone-lenses, FR-005): an H.264 encoder the camera feeds through
 * its input [surface], an uplink to the lens's address, a thread draining the encoder into the
 * uplink, and the clock exchange with the lens's recorder, made once the first frame tells which
 * clock the frames are stamped on.
 */
internal class LensStream private constructor(
    val planned: PlannedLens,
    private val codec: MediaCodec,
    val surface: Surface,
    private val uplink: Uplink,
    private val sync: AtomicReference<ClockSync?>,
) {
    private var drainer: Thread? = null

    /** Stopped: a first frame heard after this starts no clock exchange. */
    @Volatile private var stopped = false

    val lens: Lens get() = planned.target.lens

    /** The clock exchange with the lens's recorder, on [clock], unless one runs or the stream ended. */
    fun startClock(clock: () -> Long) {
        if (stopped || sync.get() != null) return
        val address = planned.target.address
        sync.set(ClockSync(address.host, address.port, clock).also { it.start() })
    }

    fun stop() {
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
         * [planned]'s stream at [format], started: [report] hears its uplink, [onFirstFrame] the
         * first frame's presentation time.
         */
        fun start(
            planned: PlannedLens,
            format: StreamFormat,
            report: (UplinkStatus) -> Unit,
            onFirstFrame: (LensStream, Long) -> Unit,
        ): LensStream {
            val media = mediaFormat(format)
            val codec = encoderFor(media)
            val surface =
                try {
                    codec.configure(media, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
                    codec.createInputSurface().also { codec.start() }
                } catch (error: IllegalStateException) {
                    codec.release()
                    throw error
                } catch (error: IllegalArgumentException) {
                    codec.release()
                    throw error
                }
            val sync = AtomicReference<ClockSync?>()
            val uplink =
                Uplink(
                    address = planned.target.address,
                    format = format,
                    clock = { sync.get()?.offset?.best() },
                    requestKeyframe = { requestKeyframe(codec) },
                    report = report,
                )
            val stream = LensStream(planned, codec, surface, uplink, sync)
            val name = planned.target.lens.code
            Thread({ uplink.run() }, "uplink-$name").start()
            stream.drainer =
                Thread({ drain(codec, uplink) { onFirstFrame(stream, it) } }, "encoder-$name").apply { start() }
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
