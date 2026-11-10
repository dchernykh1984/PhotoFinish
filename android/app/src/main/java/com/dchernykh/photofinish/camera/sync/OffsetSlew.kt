package com.dchernykh.photofinish.camera.sync

import kotlin.math.abs

/**
 * The offset frames are stamped with. The best exchange changes as a shorter round trip comes
 * or the best one ages out, by up to half their delays, and the recorder brings its clock near
 * its computer's a millisecond a second at most; that is followed two milliseconds for each
 * second of frames at most, so frame moments keep their steps and still catch up. A change no
 * network explains -- the recorder's clock started again or set -- is taken at once, and so is
 * every change over the first frames, as the first burst of exchanges finds a short round trip.
 */
class OffsetSlew {
    private var applied: Long? = null
    private var lastFrameUs = 0L
    private var firstFrameUs: Long? = null

    /** The offset for the frame taken at [frameUs], the best exchange saying [best]. */
    fun at(
        frameUs: Long,
        best: Long,
    ): Long {
        val current = applied
        val first = firstFrameUs ?: frameUs.also { firstFrameUs = it }
        val most = maxOf(frameUs - lastFrameUs, 0) / SLEW_DIVISOR
        val next =
            when {
                current == null || frameUs - first < SETTLE_US -> best
                abs(best - current) > STEP_US -> best
                else -> current + (best - current).coerceIn(-most, most)
            }
        applied = next
        lastFrameUs = maxOf(frameUs, lastFrameUs)
        return next
    }

    private companion object {
        /** Two milliseconds a second: twice what the recorder's own clock moves. */
        const val SLEW_DIVISOR = 500L

        /** More than any half round trip on a network a race runs on. */
        const val STEP_US = 50_000L

        /** The first burst of exchanges, five in half a second, with time to spare. */
        const val SETTLE_US = 2_000_000L
    }
}
