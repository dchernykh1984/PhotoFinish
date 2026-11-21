package com.dchernykh.photofinish.camera.stream

/**
 * When a piece of the phone's sound was heard, on the clock its frames are stamped on (specs/013-sound): the
 * microphone's own timestamp -- a sample's position and when it was heard, on the monotonic clock -- carried to the
 * piece's first sample, then moved to the frames' clock, boot time or monotonic.
 */
object SoundTime {
    private const val NANOS = 1_000_000_000L

    /** When sample [position] was heard, ns on the monotonic clock: [stampNanos] was sample [stampPosition]'s. */
    fun heardNanos(
        position: Long,
        stampPosition: Long,
        stampNanos: Long,
        rate: Int,
    ): Long = stampNanos + (position - stampPosition) * NANOS / rate

    /** [monotonicUs] on the frames' clock, which reads [framesNowUs] as the monotonic one reads [monotonicNowUs]. */
    fun onFramesClock(
        monotonicUs: Long,
        framesNowUs: Long,
        monotonicNowUs: Long,
    ): Long = monotonicUs + framesNowUs - monotonicNowUs
}
