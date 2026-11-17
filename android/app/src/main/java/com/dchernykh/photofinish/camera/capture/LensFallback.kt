package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens

/**
 * The lenses the cameras failed with, left out until the referee starts again (specs/004-phone-lenses,
 * FR-005): a phone may say it streams lenses together and then not -- the Xiaomi 17 Ultra, asked for four at
 * 2560x1440 and 60 fps, gave no frame and its camera failed in 1.5 s, again each time it was opened. A camera
 * that fails, or gives its lenses no frame, within [EARLY_MS] of their start is opened again with one lens
 * fewer: the last of the code's order, as a session the phone says it cannot run drops them, never the first.
 * The cameras failing together -- the front's and the back's at once -- are one failure: an open leaves one
 * lens out at most. A camera lost later, having streamed a while, is opened again with all its lenses.
 */
class LensFallback {
    private val left = linkedSetOf<Lens>()

    /** The open that left a lens out already: its other camera's failure is the same one. */
    private var paid: Int? = null

    /** The lenses left out so far, in the order they were. */
    val leftOut: Set<Lens> get() = left.toSet()

    /**
     * The cameras of open [open] failed [sinceStartMs] after its lenses started, [streamed] in the code's
     * order: the lens left out from now on, or null -- a failure late, one this open paid for already, or a
     * lens streamed alone.
     */
    fun failed(
        open: Int,
        streamed: List<Lens>,
        sinceStartMs: Long,
    ): Lens? {
        if (sinceStartMs >= EARLY_MS || open == paid || streamed.size < 2) return null
        paid = open
        return streamed.last().also { left += it }
    }

    /**
     * The other camera of open [open] -- the front beside the back -- failed alone [sinceStartMs] after its
     * lenses started, and was closed: its [lenses], left out of this open, are left out from now on when it
     * failed early.
     */
    fun failedAlone(
        open: Int,
        lenses: List<Lens>,
        sinceStartMs: Long,
    ) {
        if (sinceStartMs >= EARLY_MS || lenses.isEmpty()) return
        paid = open
        left += lenses
    }

    companion object {
        /** How soon a failure is the lenses' own: a camera that streamed longer was lost, not unable. */
        const val EARLY_MS = 10_000L
    }
}
