package com.dchernykh.photofinish.camera.capture

import kotlin.math.abs

/** The clock an encoder's frames are stamped on. */
enum class TimestampBase {
    /** SystemClock.elapsedRealtimeNanos: counts sleep. */
    REALTIME,

    /** System.nanoTime: stops while the phone sleeps. */
    MONOTONIC,
    ;

    companion object {
        private const val NEAR_NS = 1_000_000_000L

        /**
         * The clock a frame stamped at [sensorNs] was stamped on, read against both clocks
         * as the frame arrives; null when neither is within a second of it. Clocks not yet
         * apart -- a phone that has not slept -- give monotonic, the clock Android moves an
         * encoder's frames to, so the choice holds once the phone has slept.
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
                toMonotonic <= toRealtime -> MONOTONIC
                else -> REALTIME
            }
        }
    }
}
