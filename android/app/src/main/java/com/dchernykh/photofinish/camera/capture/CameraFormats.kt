package com.dchernykh.photofinish.camera.capture

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.MediaCodec
import android.media.MediaCodecList
import android.media.MediaFormat
import android.util.Size
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

    private val map =
        physicalId
            ?.let { manager.getCameraCharacteristics(it).get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) }
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

    private val encoders =
        MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.filter { info ->
            info.isEncoder && info.supportedTypes.any { it.equals(MediaFormat.MIMETYPE_VIDEO_AVC, ignoreCase = true) }
        }

    /** Asked of the camera and the codecs once for each size and rate: the screen asks at every redraw. */
    private val taken = HashMap<Pair<Resolution, Int>, Boolean>()

    /**
     * The camera gives [size] at [fps] -- its fastest for that size, not only its ranges -- and
     * an H.264 encoder takes it.
     */
    fun takes(
        size: Resolution,
        fps: Int,
    ): Boolean =
        taken.getOrPut(size to fps) {
            val fastestNs = map?.getOutputMinFrameDuration(MediaCodec::class.java, Size(size.width, size.height)) ?: 0L
            val cameraGives = fastestNs <= 0L || fps <= (1e9 / fastestNs).roundToInt()
            cameraGives &&
                encoders.any { info ->
                    info
                        .getCapabilitiesForType(MediaFormat.MIMETYPE_VIDEO_AVC)
                        .videoCapabilities
                        ?.areSizeAndRateSupported(size.width, size.height, fps.toDouble()) == true
                }
        }

    fun choose(
        wanted: Resolution? = null,
        wantedFps: Int? = null,
    ): StreamFormat? = FormatChoice.choose(sizes, ranges, ::takes, wanted, wantedFps)

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
            return FormatChoice.choose(sizes, first.ranges, takes, wanted.resolution, wanted.fps)
        }
    }
}
