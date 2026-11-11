package com.dchernykh.photofinish.camera.pairing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PairingTest {
    private val main = RtmpAddress("192.168.31.106", 1935, "live", "cam1")
    private val tele = RtmpAddress("192.168.31.106", 1936, "live", "cam2")

    @Test
    fun `an address alone is the main lens, as any app's code`() {
        val pairing = Pairing.parse(" rtmp://192.168.31.106:1935/live/cam1 ")
        assertEquals(listOf(LensTarget(Lens.MAIN, main)), pairing.targets)
        assertEquals(emptyList<String>(), pairing.unread)
    }

    @Test
    fun `a line per lens, read in order`() {
        val text = "main rtmp://192.168.31.106:1935/live/cam1\r\nTELEPHOTO  rtmp://192.168.31.106:1936/live/cam2\n\n"
        assertEquals(listOf(LensTarget(Lens.MAIN, main), LensTarget(Lens.TELEPHOTO, tele)), Pairing.parse(text).targets)
    }

    @Test
    fun `a line that cannot be read, or a lens named again, is said`() {
        val text =
            "front rtmp://192.168.31.106:1935/live/cam1\nzoom rtmp://192.168.31.106:1936/live/cam2\n" +
                "front rtmp://192.168.31.106:1937/live/cam3\nfront http://x"
        val pairing = Pairing.parse(text)
        assertEquals(listOf(LensTarget(Lens.FRONT, main)), pairing.targets)
        assertEquals(
            listOf(
                "zoom rtmp://192.168.31.106:1936/live/cam2",
                "front rtmp://192.168.31.106:1937/live/cam3",
                "front http://x",
            ),
            pairing.unread,
        )
    }

    @Test
    fun `nothing typed asks for nothing`() {
        assertEquals(Pairing(emptyList(), emptyList()), Pairing.parse(""))
    }

    @Test
    fun `lenses are named as the code names them`() {
        assertEquals(Lens.ULTRAWIDE, Lens.named("UltraWide"))
        assertNull(Lens.named("wide"))
    }
}
