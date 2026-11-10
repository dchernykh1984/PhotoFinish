package com.dchernykh.photofinish.camera.capture

import kotlin.math.abs

/** The clock a camera stamps its frames with. */
enum class TimestampBase {
    /** SystemClock.elapsedRealtimeNanos: counts sleep. */
    REALTIME,

    /** System.nanoTime: stops while the phone sleeps. */
    MONOTONIC,
    ;

    companion object {
        private const val NEAR_NS = 1_000_000_000L

        /**
         * The clock a frame stamped at [sensorNs] was stamped on, read against both
         * clocks as the frame arrives; null when neither is within a second of it.
         */
        fun detect(
            sensorNs: Long,
            realtimeNs: Long,
            monotonicNs: Long,
        ): TimestampBase? {
            val toRealtime = abs(realtimeNs - sensorNs)
            val toMonotonic = abs(monotonicNs - sensorNs)
            return when {
                minOf(toRealtime, toMonotonic) > NEAR_NS -> null
                toRealtime <= toMonotonic -> REALTIME
                else -> MONOTONIC
            }
        }
    }
}
