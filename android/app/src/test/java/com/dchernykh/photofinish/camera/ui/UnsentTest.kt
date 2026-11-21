package com.dchernykh.photofinish.camera.ui

import com.dchernykh.photofinish.camera.stream.FrameStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UnsentTest {
    @Test
    fun `video held is told as a clock says it, hours once there are any`() {
        assertEquals("0:00", span(0))
        assertEquals("0:59", span(59_999))
        assertEquals("12:30", span(750_000))
        assertEquals("1:02:03", span(3_723_000))
        assertEquals("0:00", span(-5))
    }

    @Test
    fun `a little video held is a megabyte, not none`() {
        assertEquals(0L, megabytes(0))
        assertEquals(1L, megabytes(250_000))
        assertEquals(1L, megabytes(1_000_000))
        assertEquals(2L, megabytes(1_000_001))
    }

    @Test
    fun `a frame or two on their way is not said while streaming, anything held once stopped`() {
        val onItsWay = FrameStore.Pending(ms = 33, bytes = 400_000)
        assertFalse(said(onItsWay, stopped = false))
        assertTrue(said(onItsWay, stopped = true)) // there to discard
        assertTrue(said(FrameStore.Pending(ms = SAID_MS, bytes = 9_000_000), stopped = false))
        assertFalse(said(FrameStore.Pending(ms = 0, bytes = 0), stopped = true))
    }
}
