package com.dchernykh.photofinish.camera.status

import org.junit.Assert.assertEquals
import org.junit.Test

class RecentTest {
    @Test
    fun `a value is read again only once it is a second old`() {
        var now = 0L
        var reads = 0
        val recent = Recent(1_000_000_000L, { now }) { ++reads }
        assertEquals(1, recent.get())
        now = 999_999_999L
        assertEquals(1, recent.get()) // the three lenses of one keyframe: one read
        now = 1_000_000_000L
        assertEquals(2, recent.get())
    }
}
