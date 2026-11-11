package com.dchernykh.photofinish.camera.capture

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraMetadata
import android.os.Build
import com.dchernykh.photofinish.camera.pairing.Lens
import kotlin.math.hypot

/**
 * The lenses Camera2 gives this app (specs/004-phone-lenses, FR-004): the back camera, its physical
 * cameras when it is a logical camera of several, and the front camera. [swapped], a debug build's
 * for the emulator, takes the lenses from the front camera, whose emulated camera is the logical one,
 * and gives the back camera the front's role.
 */
class PhoneLenses(
    context: Context,
    swapped: Boolean = false,
) {
    private val manager = context.getSystemService(CameraManager::class.java)
    private val backFacing = if (swapped) CameraMetadata.LENS_FACING_FRONT else CameraMetadata.LENS_FACING_BACK
    private val frontFacing = if (swapped) CameraMetadata.LENS_FACING_BACK else CameraMetadata.LENS_FACING_FRONT

    /** The camera the app shows and streams alone: the back one, or null on a phone without. */
    val mainCameraId: String? = facing(backFacing)

    val found: Map<Lens, LensInfo> =
        LensChoice.classify(
            mainCameraId?.let { info(it, null) },
            mainCameraId?.let { physical(it) }.orEmpty(),
            facing(frontFacing)?.let { info(it, null) },
        )

    /** The cameras of [ids] can run at once: one camera always, more where Android 11 lists them so. */
    fun together(ids: Set<String>): Boolean =
        ids.size < 2 ||
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
            manager.concurrentCameraIds.any { it.containsAll(ids) }

    private fun facing(wanted: Int): String? =
        manager.cameraIdList.firstOrNull {
            manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == wanted
        }

    private fun physical(cameraId: String): List<LensInfo> {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) return emptyList()
        val characteristics = manager.getCameraCharacteristics(cameraId)
        val capabilities = characteristics.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ?: IntArray(0)
        if (CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA !in capabilities) return emptyList()
        return characteristics.physicalCameraIds.map { info(cameraId, it) }
    }

    /** The lens with its 35 mm-equivalent focal length: by the diagonal, as phone makers give it. */
    private fun info(
        cameraId: String,
        physicalId: String?,
    ): LensInfo {
        val characteristics = manager.getCameraCharacteristics(physicalId ?: cameraId)
        val focals = characteristics.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)
        val sensor = characteristics.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE)
        val diagonal = sensor?.let { hypot(it.width.toDouble(), it.height.toDouble()) } ?: 0.0
        val equivalent = LensChoice.equivalentFocal(focals?.map { it.toDouble() }.orEmpty(), diagonal)
        return LensInfo(cameraId, physicalId, equivalent)
    }
}
