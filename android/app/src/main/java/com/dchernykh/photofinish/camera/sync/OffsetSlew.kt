package com.dchernykh.photofinish.camera.sync

import kotlin.math.abs

/**
 * The offset frames are stamped with. The best exchange changes as a shorter round trip comes
 * or the best one ages out, by up to half their delays; that is followed a millisecond for each
 * second of frames at most, so frame moments keep their steps. A change no network explains --
 * the recorder's clock started again or set -- is taken at once.
 */
class OffsetSlew {
    private var applied: Long? = null
    private var lastFrameUs = 0L

    /** The offset for the frame taken at [frameUs], the best exchange saying [best]. */
    fun at(
        frameUs: Long,
        best: Long,
    ): Long {
        val current = applied
        val most = maxOf(frameUs - lastFrameUs, 0) / SLEW_DIVISOR
        val next =
            if (current == null ||
                abs(best - current) > STEP_US
            ) {
                best
            } else {
                current + (best - current).coerceIn(-most, most)
            }
        applied = next
        lastFrameUs = maxOf(frameUs, lastFrameUs)
        return next
    }

    private companion object {
        /** A millisecond a second. */
        const val SLEW_DIVISOR = 1000L

        /** More than any half round trip on a network a race runs on. */
        const val STEP_US = 50_000L
    }
}
