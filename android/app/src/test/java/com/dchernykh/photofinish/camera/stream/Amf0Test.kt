package com.dchernykh.photofinish.camera.stream

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class Amf0Test {
    @Test
    fun `a command reads back as written`() {
        val bytes = Amf0.encode("connect", 1, mapOf("app" to "live", "fpad" to false), null)
        assertEquals(listOf("connect", 1.0, mapOf("app" to "live", "fpad" to false), null), Amf0.decode(bytes))
    }

    @Test
    fun `numbers are doubles and strings carry their length`() {
        assertArrayEquals(
            byteArrayOf(0, 0x3F, 0xF0.toByte(), 0, 0, 0, 0, 0, 0, 2, 0, 2, 'o'.code.toByte(), 'k'.code.toByte()),
            Amf0.encode(1, "ok"),
        )
    }

    @Test
    fun `onMetaData goes as an ECMA array, its count first`() {
        val bytes = Amf0.encode(Amf0.EcmaArray(mapOf("width" to 1920)))
        assertEquals(0x08, bytes[0].toInt())
        assertArrayEquals(byteArrayOf(0, 0, 0, 1), bytes.copyOfRange(1, 5))
        assertEquals(listOf(mapOf("width" to 1920.0)), Amf0.decode(bytes))
        assertArrayEquals(byteArrayOf(0, 0, 9), bytes.copyOfRange(bytes.size - 3, bytes.size))
    }

    @Test
    fun `undefined and strict arrays are read`() {
        val bytes = byteArrayOf(0x06, 0x0A, 0, 0, 0, 1, 0x05)
        assertEquals(listOf(null, listOf(null)), Amf0.decode(bytes))
    }

    @Test
    fun `what AMF0 cannot hold is refused`() {
        assertThrows(IllegalArgumentException::class.java) { Amf0.encode(Any()) }
        assertThrows(IllegalArgumentException::class.java) { Amf0.decode(byteArrayOf(0x11)) }
    }

    @Test
    fun `an array counted longer than its message is refused, not allocated`() {
        val strictArray = byteArrayOf(0x0A, 0x7F, -1, -1, -1) // 2^31 - 1 entries, none there
        assertThrows(IllegalArgumentException::class.java) { Amf0.decode(strictArray) }
    }
}
