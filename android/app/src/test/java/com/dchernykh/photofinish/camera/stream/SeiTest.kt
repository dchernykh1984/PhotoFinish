package com.dchernykh.photofinish.camera.stream

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import java.nio.ByteBuffer

class SeiTest {
    @Test
    fun `the unit is user data under PhotoFinish's UUID with the moment`() {
        val moment = 1_794_316_135_221_000L
        val nal = Sei.frameMoment(moment)
        assertEquals(Avc.NAL_SEI, Avc.type(nal))
        val rbsp = unescape(nal.copyOfRange(1, nal.size))
        assertEquals(5, rbsp[0].toInt()) // user_data_unregistered
        assertEquals(28, rbsp[1].toInt())
        val payload = ByteBuffer.wrap(rbsp, 2, 28)
        assertEquals(Sei.uuid.mostSignificantBits, payload.getLong())
        assertEquals(Sei.uuid.leastSignificantBits, payload.getLong())
        assertArrayEquals("PFT1".toByteArray(), ByteArray(4).also { payload.get(it) })
        assertEquals(moment, payload.getLong())
        assertEquals(0x80.toByte(), rbsp[30])
    }

    @Test
    fun `two zeros before a byte up to 3 get an emulation-prevention byte`() {
        assertArrayEquals(
            byteArrayOf(0, 0, 3, 1, 0, 0, 3, 0, 0, 3, 3, 4),
            Sei.escape(byteArrayOf(0, 0, 1, 0, 0, 0, 0, 3, 4)),
        )
        assertArrayEquals(byteArrayOf(0, 0, 4), Sei.escape(byteArrayOf(0, 0, 4)))
    }

    @Test
    fun `a moment full of zeros still reads back`() {
        val nal = Sei.frameMoment(0x0000_0100_0000_0003L)
        val rbsp = unescape(nal.copyOfRange(1, nal.size))
        assertEquals(0x0000_0100_0000_0003L, ByteBuffer.wrap(rbsp, 22, 8).getLong())
        var zeros = 0
        for (byte in nal) { // no start code can appear inside the unit
            // 00 00 03 is the prevention byte itself; 00 00 00, 01 and 02 must not appear.
            if (zeros >= 2) assert(byte.toInt() and 0xFF >= 3) { "emulated start code" }
            zeros = if (byte.toInt() == 0) zeros + 1 else 0
        }
    }
}
