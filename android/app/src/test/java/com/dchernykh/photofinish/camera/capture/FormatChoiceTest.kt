package com.dchernykh.photofinish.camera.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FormatChoiceTest {
    private val hd = Resolution(1280, 720)
    private val fullHd = Resolution(1920, 1080)
    private val qhd = Resolution(2560, 1440)
    private val anything: (Resolution, Int) -> Boolean = { _, _ -> true }

    @Test
    fun `a phone with 60 fps at 1080p streams 1080p at 60, about 10 Mbit_s`() {
        val chosen =
            FormatChoice.choose(
                listOf(hd, fullHd, qhd, Resolution(4000, 3000)),
                listOf(FpsRange(15, 30), FpsRange(30, 60), FpsRange(60, 60)),
                anything,
            )!!
        assertEquals(StreamFormat(fullHd, 60, FpsRange(60, 60), 10_000_000), chosen)
    }

    @Test
    fun `a phone with 30 only streams 30`() {
        val chosen = FormatChoice.choose(listOf(fullHd), listOf(FpsRange(15, 30), FpsRange(30, 30)), anything)!!
        assertEquals(30, chosen.fps)
        assertEquals(FpsRange(30, 30), chosen.range)
        assertEquals(5_000_000, chosen.bitrate)
    }

    @Test
    fun `a wanted size and rate are taken when given, else the first that fits`() {
        val ranges = listOf(FpsRange(30, 30), FpsRange(60, 60))
        assertEquals(
            StreamFormat(hd, 30, FpsRange(30, 30), 2_200_000),
            FormatChoice.choose(listOf(hd, fullHd), ranges, anything, hd, 30),
        )
        assertEquals(
            fullHd,
            FormatChoice.choose(listOf(hd, fullHd), ranges, anything, Resolution(3840, 2160), 120)!!.resolution,
        )
    }

    @Test
    fun `the encoder's limits count`() {
        val noSixtyAtQhd: (Resolution, Int) -> Boolean = { size, fps -> size != qhd || fps <= 30 }
        assertEquals(
            listOf(60, 30),
            FormatChoice.rates(listOf(FpsRange(30, 30), FpsRange(60, 60)), fullHd, noSixtyAtQhd),
        )
        assertEquals(listOf(30), FormatChoice.rates(listOf(FpsRange(30, 30), FpsRange(60, 60)), qhd, noSixtyAtQhd))
        val noQhd: (Resolution, Int) -> Boolean = { size, _ -> size != qhd }
        assertEquals(listOf(fullHd, hd), FormatChoice.resolutions(listOf(hd, fullHd, qhd), noQhd))
    }

    @Test
    fun `the bitrate is capped for Wi-Fi`() {
        assertEquals(16_000_000, FormatChoice.bitrate(qhd, 60))
        assertEquals(4_400_000, FormatChoice.bitrate(hd, 60))
    }

    @Test
    fun `the range for a rate is a fixed one, else the highest floor`() {
        assertEquals(
            FpsRange(24, 30),
            FormatChoice.rangeFor(30, listOf(FpsRange(15, 30), FpsRange(24, 30), FpsRange(30, 60))),
        )
        assertNull(FormatChoice.rangeFor(50, listOf(FpsRange(15, 30))))
    }

    @Test
    fun `nothing fits, nothing is chosen`() {
        assertNull(FormatChoice.choose(listOf(Resolution(640, 480)), listOf(FpsRange(30, 30)), anything))
        assertNull(FormatChoice.choose(listOf(fullHd), listOf(FpsRange(15, 24)), anything))
    }
}
