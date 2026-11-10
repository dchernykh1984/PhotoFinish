package com.dchernykh.photofinish.camera.sync

import org.junit.Assert.assertEquals
import org.junit.Test

class OffsetSlewTest {
    @Test
    fun `the first offset is taken, a better exchange followed a millisecond a second`() {
        val slew = OffsetSlew()
        assertEquals(500L, slew.at(frameUs = 0, best = 500))
        assertEquals(516L, slew.at(frameUs = 16_667, best = 5_500)) // a 60 fps frame: 16 us
        assertEquals(1_516L, slew.at(frameUs = 1_016_667, best = 5_500)) // a second on
        assertEquals(1_000L, slew.at(frameUs = 2_016_667, best = 1_000)) // and back, as far
    }

    @Test
    fun `a change no network explains is taken at once`() {
        val slew = OffsetSlew()
        slew.at(frameUs = 0, best = 500)
        assertEquals(2_000_500L, slew.at(frameUs = 16_667, best = 2_000_500))
    }

    @Test
    fun `a frame earlier than the last moves nothing`() {
        val slew = OffsetSlew()
        slew.at(frameUs = 1_000_000, best = 500)
        assertEquals(500L, slew.at(frameUs = 0, best = 5_500))
    }
}
