package com.dchernykh.photofinish.camera

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SendingServiceTest {
    @Test
    fun `the screen starts the service whenever it is not running, with frames to send and the screen shown`() {
        assertFalse(SendingService.running)
        assertTrue(SendingService.wanted(sending = true, shown = true, nowMs = 0))
        assertFalse(SendingService.wanted(sending = true, shown = false, nowMs = 0)) // refused from the background
        assertFalse(SendingService.wanted(sending = false, shown = true, nowMs = 0))
    }

    @Test
    fun `refused the foreground, it is not asked again for a minute`() {
        SendingService.refusedMs = 10_000
        try {
            assertFalse(SendingService.wanted(sending = true, shown = true, nowMs = 69_999))
            assertTrue(SendingService.wanted(sending = true, shown = true, nowMs = 70_000))
        } finally {
            SendingService.refusedMs = Long.MIN_VALUE / 2
        }
    }
}
