package com.dchernykh.photofinish.camera.stream

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.EOFException

class RtmpChunksTest {
    private fun roundTrip(
        message: RtmpMessage,
        chunkSize: Int,
    ): Pair<ByteArray, RtmpMessage> {
        val out = ByteArrayOutputStream()
        RtmpChunkWriter(out).apply { this.chunkSize = chunkSize }.write(message)
        val reader = RtmpChunkReader(ByteArrayInputStream(out.toByteArray())).apply { this.chunkSize = chunkSize }
        return out.toByteArray() to reader.read()
    }

    @Test
    fun `a message longer than a chunk is split and put back together`() {
        val payload = ByteArray(300) { it.toByte() }
        val (bytes, read) = roundTrip(RtmpMessage(6, 1234, RtmpType.VIDEO, 1, payload), 128)
        assertEquals(12 + 300 + 2, bytes.size) // a full header, then two one-byte headers
        assertEquals(0xC6.toByte(), bytes[12 + 128])
        assertArrayEquals(payload, read.payload)
        assertEquals(1234L, read.timestamp)
        assertEquals(1, read.streamId)
        assertEquals(RtmpType.VIDEO, read.typeId)
    }

    @Test
    fun `the message stream id is little-endian`() {
        val (bytes, _) = roundTrip(RtmpMessage(3, 0, RtmpType.COMMAND_AMF0, 0x01020304, byteArrayOf(1)), 128)
        assertArrayEquals(byteArrayOf(4, 3, 2, 1), bytes.copyOfRange(8, 12))
    }

    @Test
    fun `past 4_6 hours timestamps are extended, on every chunk of the message`() {
        val fiveHours = 5L * 3600 * 1000
        val payload = ByteArray(200) { 7 }
        val (bytes, read) = roundTrip(RtmpMessage(6, fiveHours, RtmpType.VIDEO, 1, payload), 128)
        assertArrayEquals(byteArrayOf(-1, -1, -1), bytes.copyOfRange(1, 4))
        val extended = byteArrayOf(0x01, 0x12, 0xA8.toByte(), 0x80.toByte())
        assertArrayEquals(extended, bytes.copyOfRange(12, 16))
        val continuation = 16 + 128
        assertEquals(0xC6.toByte(), bytes[continuation])
        assertArrayEquals(extended, bytes.copyOfRange(continuation + 1, continuation + 5))
        assertEquals(fiveHours, read.timestamp)
        assertArrayEquals(payload, read.payload)
    }

    @Test
    fun `compressed headers carry on from the last one of their chunk stream`() {
        val bytes =
            byteArrayOf(
                0x03,
                0,
                0,
                10,
                0,
                0,
                1,
                20,
                0,
                0,
                0,
                0,
                1, // full header, timestamp 10, one byte
                0x43,
                0,
                0,
                5,
                0,
                0,
                2,
                20,
                2,
                3, // type 1: +5 ms, two bytes
                0x83.toByte(),
                0,
                0,
                7,
                4,
                5, // type 2: +7 ms, the same length
                0xC3.toByte(),
                6,
                7, // type 3: +7 ms again
            )
        val reader = RtmpChunkReader(ByteArrayInputStream(bytes))
        val read = List(4) { reader.read() }
        assertEquals(listOf(10L, 15L, 22L, 29L), read.map { it.timestamp })
        assertArrayEquals(byteArrayOf(6, 7), read[3].payload)
    }

    @Test
    fun `a set chunk size changes the size read from then on`() {
        val out = ByteArrayOutputStream()
        val writer = RtmpChunkWriter(out)
        writer.write(RtmpMessage(2, 0, RtmpType.SET_CHUNK_SIZE, 0, byteArrayOf(0, 0, 1, 0)))
        writer.chunkSize = 256
        writer.write(RtmpMessage(6, 0, RtmpType.VIDEO, 1, ByteArray(200)))
        val reader = RtmpChunkReader(ByteArrayInputStream(out.toByteArray()))
        reader.read()
        assertEquals(256, reader.chunkSize)
        assertEquals(200, reader.read().payload.size)
    }

    @Test
    fun `two- and three-byte chunk stream ids are read`() {
        val bytes =
            byteArrayOf(0x00, 6, 0, 0, 1, 0, 0, 1, 9, 0, 0, 0, 0, 9, 0x01, 1, 1, 0, 0, 0, 0, 0, 1, 9, 0, 0, 0, 0, 8)
        val reader = RtmpChunkReader(ByteArrayInputStream(bytes))
        assertEquals(70, reader.read().chunkStreamId)
        assertEquals(64 + 1 + 256, reader.read().chunkStreamId)
    }

    @Test
    fun `a connection closed mid-message says so`() {
        val reader = RtmpChunkReader(ByteArrayInputStream(byteArrayOf(0x03, 0, 0, 0, 0, 0, 5, 20)))
        assertThrows(EOFException::class.java) { reader.read() }
    }

    @Test
    fun `chunk streams beyond one byte are not written`() {
        val writer = RtmpChunkWriter(ByteArrayOutputStream())
        assertThrows(IllegalArgumentException::class.java) {
            writer.write(RtmpMessage(64, 0, RtmpType.VIDEO, 1, byteArrayOf(1)))
        }
    }
}
