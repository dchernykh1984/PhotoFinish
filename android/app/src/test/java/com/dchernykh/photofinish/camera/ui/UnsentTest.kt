package com.dchernykh.photofinish.camera.ui

import org.junit.Assert.assertEquals
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
}
