package com.dchernykh.photofinish.camera.stream

import org.junit.Assert.assertEquals
import org.junit.Test

class SoundTimeTest {
    @Test
    fun `a sample is heard by the microphone's timestamp, as far after it as it lies`() {
        // Sample 48 000 heard at 10 s: sample 72 000 half a second later, sample 24 000 half a second before.
        assertEquals(10_500_000_000L, SoundTime.heardNanos(72_000, 48_000, 10_000_000_000L, 48_000))
        assertEquals(9_500_000_000L, SoundTime.heardNanos(24_000, 48_000, 10_000_000_000L, 48_000))
    }

    @Test
    fun `a moment on the monotonic clock goes to the frames' clock by where the two stand now`() {
        // Boot time ahead of monotonic by the 3 s the phone slept.
        assertEquals(13_000_100L, SoundTime.onFramesClock(10_000_100L, 23_000_000L, 20_000_000L))
        assertEquals(10_000_100L, SoundTime.onFramesClock(10_000_100L, 20_000_000L, 20_000_000L))
    }
}
