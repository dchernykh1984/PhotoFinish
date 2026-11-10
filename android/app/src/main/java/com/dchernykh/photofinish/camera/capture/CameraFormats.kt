package com.dchernykh.photofinish.camera.capture

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.media.MediaCodec
import android.media.MediaCodecList
import android.media.MediaFormat
import android.util.Size
import kotlin.math.roundToInt

/** What the phone's back camera and its H.264 encoder offer. */
class CameraFormats(
    context: Context,
) {
    private val manager = context.getSystemService(CameraManager::class.java)

    /** The back camera, or null on a phone without one. */
    val cameraId: String? =
        manager.cameraIdList.firstOrNull {
            manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) ==
                CameraMetadata.LENS_FACING_BACK
        }

    private val characteristics = cameraId?.let { manager.getCameraCharacteristics(it) }

    private val map = characteristics?.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)

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
}
