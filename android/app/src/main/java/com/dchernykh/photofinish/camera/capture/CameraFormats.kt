package com.dchernykh.photofinish.camera.capture

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.MediaCodec
import android.media.MediaCodecList
import android.util.Size
import com.dchernykh.photofinish.camera.stream.Codec
import kotlin.math.roundToInt

/**
 * What a camera of the phone -- [cameraId], or one of its physical cameras -- and its H.264 encoder
 * offer: the sizes from the lens's own stream map when it has one, the rates from the camera, whose
 * one request sets them for all its lenses.
 */
class CameraFormats(
    context: Context,
    val cameraId: String?,
    physicalId: String? = null,
) {
    private val manager = context.getSystemService(CameraManager::class.java)

    private val characteristics = cameraId?.let { manager.getCameraCharacteristics(it) }

    // A physical camera the phone will not tell of gives the logical camera's sizes.
    private val map =
        physicalId
            ?.let { runCatching { manager.getCameraCharacteristics(it) }.getOrNull() }
            ?.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?: characteristics?.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)

    val sizes: List<Resolution> =
        map
            ?.getOutputSizes(MediaCodec::class.java)
            ?.map { Resolution(it.width, it.height) }
            .orEmpty()

    val ranges: List<FpsRange> =
        characteristics
            ?.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
            ?.map { FpsRange(it.lower, it.upper) }
            .orEmpty()

    private val codecs = MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.filter { it.isEncoder }

    /** Asked of the camera and the codecs once for each size, rate and codec: the screen asks at every redraw. */
    private val taken = HashMap<Triple<Resolution, Int, Codec>, Boolean>()

    /**
     * The camera gives [size] at [fps] -- its fastest for that size, not only its ranges -- and an encoder of
     * [codec] takes it.
     */
    fun takes(
        size: Resolution,
        fps: Int,
        codec: Codec = Codec.AVC,
    ): Boolean =
        taken.getOrPut(Triple(size, fps, codec)) {
            val fastestNs = map?.getOutputMinFrameDuration(MediaCodec::class.java, Size(size.width, size.height)) ?: 0L
            val cameraGives = fastestNs <= 0L || fps <= (1e9 / fastestNs).roundToInt()
            cameraGives &&
                codecs.any { info ->
                    info.supportedTypes.any { it.equals(codec.mime, ignoreCase = true) } &&
                        info
                            .getCapabilitiesForType(codec.mime)
                            .videoCapabilities
                            ?.areSizeAndRateSupported(size.width, size.height, fps.toDouble()) == true
                }
        }

    /**
     * The format to stream, chosen as H.264 gives it; in [codec] when an encoder of it takes the size and rate, else
     * in H.264 -- the screen says so (specs/010-hevc).
     */
    fun choose(
        wanted: Resolution? = null,
        wantedFps: Int? = null,
        codec: Codec = Codec.AVC,
    ): StreamFormat? {
        val chosen = FormatChoice.choose(sizes, ranges, { size, fps -> takes(size, fps) }, wanted, wantedFps)
        return chosen?.let { FormatChoice.inCodecIf(it, codec, ::takes) }
    }

    companion object {
        /**
         * The format several lenses of one camera all give: [wanted] when they do, else the nearest
         * offered -- a size every lens gives, at a rate every lens takes.
         */
        fun common(
            lenses: List<CameraFormats>,
            wanted: StreamFormat,
        ): StreamFormat? {
            val first = lenses.firstOrNull() ?: return null
            val sizes = lenses.map { it.sizes.toSet() }.reduce { all, these -> all intersect these }
            val takes = { size: Resolution, fps: Int -> lenses.all { it.takes(size, fps) } }
            return FormatChoice
                .choose(sizes, first.ranges, takes, wanted.resolution, wanted.fps)
                ?.let { common ->
                    // the size and rate fallen back to taken in the codec by every lens, else H.264
                    FormatChoice.inCodecIf(
                        common,
                        wanted.codec,
                    ) { size, fps, codec -> lenses.all { it.takes(size, fps, codec) } }
                }
        }
    }
}
