package com.dchernykh.photofinish.camera.capture

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.media.MediaCodec
import android.media.MediaCodecList
import android.media.MediaFormat

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

    val sizes: List<Resolution> =
        characteristics
            ?.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?.getOutputSizes(MediaCodec::class.java)
            ?.map { Resolution(it.width, it.height) }
            .orEmpty()

    val ranges: List<FpsRange> =
        characteristics
            ?.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
            ?.map { FpsRange(it.lower, it.upper) }
            .orEmpty()

    /** The camera stamps its frames on elapsedRealtimeNanos; otherwise it is found at the first frame. */
    val realtimeTimestamps: Boolean =
        characteristics?.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) ==
            CameraMetadata.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME

    private val encoders =
        MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.filter { info ->
            info.isEncoder && info.supportedTypes.any { it.equals(MediaFormat.MIMETYPE_VIDEO_AVC, ignoreCase = true) }
        }

    /** Asked of the codecs once for each size and rate: the screen asks at every redraw. */
    private val takes = HashMap<Pair<Resolution, Int>, Boolean>()

    fun encoderTakes(
        size: Resolution,
        fps: Int,
    ): Boolean =
        takes.getOrPut(size to fps) {
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
    ): StreamFormat? = FormatChoice.choose(sizes, ranges, ::encoderTakes, wanted, wantedFps)
}
