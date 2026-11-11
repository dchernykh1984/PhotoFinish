package com.dchernykh.photofinish.camera.capture

import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.os.Build
import android.view.Surface
import androidx.annotation.RequiresApi
import java.util.concurrent.Executor

/** The outputs of one camera's capture session: its lenses' encoders and the preview (Android 9). */
@RequiresApi(Build.VERSION_CODES.P)
internal object SessionOutputs {
    /**
     * The outputs to configure, and the lenses dropped to get there (specs/004-phone-lenses,
     * FR-005): the preview on the first lens, then the camera's own picture as the preview, then
     * no preview -- the first set the camera says it supports (Android 10), dropping lenses from the
     * last while it supports none. Where the camera cannot say, the fullest set is tried; where it
     * supports none at all, the first lens alone.
     */
    fun choose(
        camera: CameraDevice,
        preview: Surface?,
        streams: List<LensStream>,
        executor: Executor,
    ): Pair<List<OutputConfiguration>, List<LensStream>> {
        val (chosen, dropped) = firstSupported(streams, { options(preview, it) }) { supports(camera, it, executor) }
        return chosen.orEmpty() to dropped
    }

    private fun options(
        preview: Surface?,
        streams: List<LensStream>,
    ): List<List<OutputConfiguration>> {
        val lensOutputs = streams.map { output(it.surface, it.planned.physicalId) }
        val first = streams.firstOrNull()?.planned?.physicalId
        return buildList {
            if (preview != null) {
                add(lensOutputs + output(preview, first))
                if (first != null) add(lensOutputs + output(preview, null))
            }
            if (lensOutputs.isNotEmpty()) add(lensOutputs)
        }
    }

    private fun output(
        surface: Surface,
        physicalId: String?,
    ): OutputConfiguration = OutputConfiguration(surface).apply { physicalId?.let { setPhysicalCameraId(it) } }

    private fun supports(
        camera: CameraDevice,
        outputs: List<OutputConfiguration>,
        executor: Executor,
    ): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return true
        val asked = SessionConfiguration(SessionConfiguration.SESSION_REGULAR, outputs, executor, Unused)
        return try {
            camera.isSessionConfigurationSupported(asked)
        } catch (_: UnsupportedOperationException) {
            true // the camera cannot say: tried
        } catch (_: IllegalArgumentException) {
            false
        }
    }

    /** The callback a configuration only asked about needs, never called. */
    private object Unused : CameraCaptureSession.StateCallback() {
        override fun onConfigured(session: CameraCaptureSession) = Unit

        override fun onConfigureFailed(session: CameraCaptureSession) = Unit
    }
}
