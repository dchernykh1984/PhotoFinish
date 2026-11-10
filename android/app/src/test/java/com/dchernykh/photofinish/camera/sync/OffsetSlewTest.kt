package com.dchernykh.photofinish.camera.sync

import org.junit.Assert.assertEquals
import org.junit.Test

class OffsetSlewTest {
    @Test
    fun `the first exchanges are taken as they come, a later better one followed two milliseconds a second`() {
        val slew = OffsetSlew()
        assertEquals(500L, slew.at(frameUs = 0, best = 500))
        assertEquals(40_500L, slew.at(frameUs = 500_000, best = 40_500)) // the first burst still settling
        val settled = 3_000_000L
        assertEquals(40_500L, slew.at(frameUs = settled, best = 40_500))
        assertEquals(40_533L, slew.at(frameUs = settled + 16_667, best = 45_500)) // a 60 fps frame: 33 us
        assertEquals(42_533L, slew.at(frameUs = settled + 1_016_667, best = 45_500)) // a second on
        assertEquals(41_000L, slew.at(frameUs = settled + 2_016_667, best = 41_000)) // and back, as far
    }

    @Test
    fun `a recorder clock slewing a millisecond a second is caught up with`() {
        val slew = OffsetSlew()
        val settled = 3_000_000L
        slew.at(frameUs = settled, best = 0)
        var applied = 0L
        for (frame in 1..600) { // ten seconds at 60 fps; the recorder's clock 5 ms on, gaining 1 ms/s
            val frameUs = settled + frame * 16_667L
            applied = slew.at(frameUs, best = 5_000 + (frameUs - settled) / 1000)
        }
        assertEquals(15_000.0, applied.toDouble(), 100.0)
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
        slew.at(frameUs = 0, best = 500)
        slew.at(frameUs = 3_000_000, best = 500) // settled
        assertEquals(500L, slew.at(frameUs = 2_500_000, best = 5_500))
    }
}
