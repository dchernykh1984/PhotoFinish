package com.dchernykh.photofinish.camera

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SendingServiceTest {
    @Test
    fun `the screen starts the service whenever it is not running, with frames to send and the screen shown`() {
        assertFalse(SendingService.running)
        assertTrue(SendingService.wanted(sending = true, shown = true))
        assertFalse(SendingService.wanted(sending = true, shown = false)) // Android refuses one from the background
        assertFalse(SendingService.wanted(sending = false, shown = true))
    }
}
