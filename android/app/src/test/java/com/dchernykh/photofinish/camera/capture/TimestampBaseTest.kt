package com.dchernykh.photofinish.camera.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TimestampBaseTest {
    private val second = 1_000_000_000L

    @Test
    fun `a frame is on the clock it is nearest`() {
        // The phone has slept 50 s since it started: the two clocks are that far apart.
        val monotonic = 1_000 * second
        val realtime = monotonic + 50 * second
        assertEquals(TimestampBase.REALTIME, TimestampBase.detect(realtime - 30_000_000, realtime, monotonic))
        assertEquals(TimestampBase.MONOTONIC, TimestampBase.detect(monotonic - 30_000_000, realtime, monotonic))
    }

    @Test
    fun `a frame near neither clock is on an unknown one`() {
        assertNull(TimestampBase.detect(5 * second, 100 * second, 200 * second))
    }
}
