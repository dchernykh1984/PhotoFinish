package com.dchernykh.photofinish.camera.stream

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class AvcTest {
    private val sps = byteArrayOf(0x67, 0x64, 0x00, 0x28, 0xAC.toByte())
    private val pps = byteArrayOf(0x68, 0xEE.toByte(), 0x3C, 0x80.toByte())

    @Test
    fun `annex B splits on three- and four-byte start codes`() {
        val data = byteArrayOf(0, 0, 0, 1) + sps + byteArrayOf(0, 0, 1) + pps + byteArrayOf(0, 0, 0, 1, 0x65, 1, 2)
        val units = Avc.splitAnnexB(data)
        assertEquals(3, units.size)
        assertArrayEquals(sps, units[0])
        assertArrayEquals(pps, units[1])
        assertArrayEquals(byteArrayOf(0x65, 1, 2), units[2])
        assertEquals(listOf(Avc.NAL_SPS, Avc.NAL_PPS, Avc.NAL_IDR), units.map { Avc.type(it) })
    }

    @Test
    fun `a buffer without start codes is one unit, an empty one none`() {
        assertEquals(1, Avc.splitAnnexB(byteArrayOf(0x41, 2)).size)
        assertEquals(0, Avc.splitAnnexB(ByteArray(0)).size)
    }

    @Test
    fun `the configuration record holds the profile, four-byte lengths, the SPS and the PPS`() {
        val record = Avc.configurationRecord(sps, pps)
        assertArrayEquals(
            byteArrayOf(1, 0x64, 0x00, 0x28, 0xFF.toByte(), 0xE1.toByte(), 0, 5),
            record.copyOfRange(0, 8),
        )
        assertArrayEquals(sps, record.copyOfRange(8, 13))
        assertArrayEquals(byteArrayOf(1, 0, 4) + pps, record.copyOfRange(13, record.size))
    }

    @Test
    fun `tags say key or inter frame, and carry each unit after its length`() {
        assertArrayEquals(byteArrayOf(0x17, 0, 0, 0, 0, 9), Avc.sequenceHeaderTag(byteArrayOf(9)))
        val tag = Avc.frameTag(keyframe = false, nalUnits = listOf(byteArrayOf(6, 1), byteArrayOf(0x41)))
        assertArrayEquals(byteArrayOf(0x27, 1, 0, 0, 0, 0, 0, 0, 2, 6, 1, 0, 0, 0, 1, 0x41), tag)
    }
}
