package com.dchernykh.photofinish.camera.capture

import android.hardware.camera2.CameraDevice
import com.dchernykh.photofinish.camera.pairing.Lens

/** How the cameras of an open failed, as [LensFallback] weighs it: none for another app taking them. */
sealed interface CameraFailure {
    /** A camera's error [code], [sinceStartMs] after its lenses started. */
    data class Error(
        val code: Int,
        val sinceStartMs: Long?,
    ) : CameraFailure

    /** A camera that gave a lens no frame, [sinceStartMs] after they started. */
    data class NoFrame(
        val sinceStartMs: Long,
    ) : CameraFailure
}

/**
 * The lenses the cameras failed with, left out until the referee starts again (specs/004-phone-lenses,
 * FR-005): a phone may say it streams lenses together and then not -- the Xiaomi 17 Ultra, asked for four at
 * 2560x1440 and 60 fps, gave no frame and its camera failed in 1.5 s, again each time it was opened. Cameras
 * that fail, or give a lens no frame, within [EARLY_MS] of their lenses' start are opened again with one lens
 * fewer: the last of the code's order, as a session the phone says it cannot run drops them, never the first.
 * The cameras failing together -- the front's and the back's at once -- are one failure: an open leaves one
 * lens out at most. Cameras lost later, having streamed a while, or taken by another app, are opened again
 * with all their lenses.
 */
class LensFallback {
    private val left = linkedSetOf<Lens>()

    /** The open that left a lens out already: its other camera's failure is the same one. */
    private var paid: Int? = null

    /** The lenses left out so far, in the order they were. */
    val leftOut: Set<Lens> get() = left.toSet()

    /**
     * The cameras of open [open] failed, [streamed] in the code's order: the lens left out from now on, or null
     * -- a failure not the lenses', or late, one this open paid for already, or a lens streamed alone.
     */
    fun failed(
        open: Int,
        streamed: List<Lens>,
        failure: CameraFailure?,
    ): Lens? {
        if (!early(failure) || open == paid || streamed.size < 2) return null
        paid = open
        return streamed.last().also { left += it }
    }

    /**
     * The other camera of open [open] -- the front beside the back -- failed alone and was closed: its [lenses],
     * left out of this open, are left out from now on when the failure was the lenses' and early. The lenses
     * newly left out.
     */
    fun failedAlone(
        open: Int,
        lenses: List<Lens>,
        failure: CameraFailure?,
    ): List<Lens> {
        if (!early(failure) || lenses.isEmpty()) return emptyList()
        paid = open
        return lenses.filter { left.add(it) }
    }

    companion object {
        /** How soon a failure is the lenses' own: a camera that streamed longer was lost, not unable. */
        const val EARLY_MS = 10_000L

        /** A camera's errors of the lenses asked of it, not of another app or the phone's policy. */
        private val LENSES_ERRORS =
            setOf(
                CameraDevice.StateCallback.ERROR_MAX_CAMERAS_IN_USE,
                CameraDevice.StateCallback.ERROR_CAMERA_DEVICE,
                CameraDevice.StateCallback.ERROR_CAMERA_SERVICE,
            )

        /** A failure of the lenses asked, in their first seconds: none is another app's taking the camera. */
        private fun early(failure: CameraFailure?): Boolean =
            when (failure) {
                null -> false
                is CameraFailure.Error -> failure.code in LENSES_ERRORS && (failure.sinceStartMs ?: 0L) < EARLY_MS
                is CameraFailure.NoFrame -> failure.sinceStartMs < EARLY_MS
            }
    }
}
