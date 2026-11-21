package com.dchernykh.photofinish.camera.stream

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class HevcTest {
    // A phone encoder's units: VPS, an SPS of Main profile, level 4.1, one sub-layer, nesting; a PPS.
    private val vps = byteArrayOf(0x40, 0x01, 0x0C, 0x01, -1, -1)
    private val sps =
        byteArrayOf(
            0x42,
            0x01, // the SPS's header
            0x01, // vps 0, max sub-layers minus 1: 0, temporal id nesting: 1
            0x01, // profile space 0, tier 0, profile 1 (Main)
            0x60,
            0x00,
            0x00,
            0x03,
            0x00, // compatibility flags, an emulation prevention byte among them
            -0x50,
            0x00,
            0x00,
            0x03,
            0x00,
            0x00,
            0x03,
            0x00, // constraint flags, escaped too
            0x7B, // level 4.1 (123)
            -0x60,
            0x01,
        )
    private val pps = byteArrayOf(0x44, 0x01, -0x3F, 0x73)

    @Test
    fun `the configuration record takes its profile from the sps, then the three units an array each`() {
        val record = Hevc.configurationRecord(vps, sps, pps)
        assertEquals(1, record[0].toInt()) // version
        assertEquals(0x01, record[1].toInt()) // profile space, tier, profile
        assertArrayEquals(byteArrayOf(0x60, 0, 0, 0), record.copyOfRange(2, 6)) // compatibility, unescaped
        assertArrayEquals(byteArrayOf(-0x50, 0, 0, 0, 0, 0), record.copyOfRange(6, 12)) // constraints
        assertEquals(0x7B, record[12].toInt()) // level
        assertEquals(0xFD, record[16].toInt() and 0xFF) // 4:2:0
        assertEquals((1 shl 3) or (1 shl 2) or 3, record[21].toInt()) // one layer, nested, 4-byte lengths
        assertEquals(3, record[22].toInt()) // arrays
        assertEquals(0x80 or Hevc.NAL_VPS, record[23].toInt() and 0xFF)
        assertArrayEquals(byteArrayOf(0, 1, 0, vps.size.toByte()), record.copyOfRange(24, 28))
        assertArrayEquals(vps, record.copyOfRange(28, 28 + vps.size))
        assertArrayEquals(pps, record.copyOfRange(record.size - pps.size, record.size))
        assertEquals(23 + 3 * 5 + vps.size + sps.size + pps.size, record.size)
    }

    @Test
    fun `the tags are enhanced rtmp's, a sequence start and coded frames with no composition time`() {
        val hvc1 = "hvc1".toByteArray(Charsets.US_ASCII)
        assertArrayEquals(byteArrayOf(0x90.toByte()) + hvc1 + byteArrayOf(7), Hevc.sequenceHeaderTag(byteArrayOf(7)))
        val unit = byteArrayOf(0x26, 0x01, 0x55)
        assertArrayEquals(
            byteArrayOf(0x93.toByte()) + hvc1 + byteArrayOf(0, 0, 0, 3) + unit,
            Hevc.frameTag(true, listOf(unit)),
        )
        assertArrayEquals(
            byteArrayOf(0xA3.toByte()) + hvc1 + byteArrayOf(0, 0, 0, 3) + unit,
            Hevc.frameTag(false, listOf(unit)),
        )
        assertEquals(Hevc.NAL_SPS, Hevc.type(sps))
    }

    @Test
    fun `an h265 sei unit has the two header bytes of a prefix sei`() {
        val moment = Sei.frameMoment(123_456L, Codec.HEVC)
        assertArrayEquals(byteArrayOf(0x4E, 0x01), moment.copyOfRange(0, 2))
        assertArrayEquals(Sei.frameMoment(123_456L).copyOfRange(1, moment.size - 1), moment.copyOfRange(2, moment.size))
        assertEquals(Hevc.NAL_PREFIX_SEI, Hevc.type(Sei.phoneStatus("battery=9", Codec.HEVC)))
    }
}
