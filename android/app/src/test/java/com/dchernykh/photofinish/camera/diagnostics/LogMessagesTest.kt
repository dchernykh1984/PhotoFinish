package com.dchernykh.photofinish.camera.diagnostics

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LogMessagesTest {
    private fun line(
        seq: Long,
        text: String = "camera error 4: the camera device failed",
        lens: String? = "main",
    ) = LogLine(seq, 1_794_918_339_000 + seq, 'E', lens, text)

    @Test
    fun `a message is its run and a line a line`() {
        val (bytes, count) = LogMessages.message("0123456789abcdef", 5, 6, listOf(line(7), line(8, "started", null)))
        assertEquals(2, count)
        assertEquals(
            "PFLG 1 0123456789abcdef 5 6\n" +
                "7 1794918339007 E main camera error 4: the camera device failed\n" +
                "8 1794918339008 E - started\n",
            String(bytes, Charsets.UTF_8),
        )
    }

    @Test
    fun `a message holds what the network takes whole, the rest left for the next`() {
        val lines = (1L..20L).map { line(it, "x".repeat(PhoneLog.MAX_BYTES)) }
        val (bytes, count) = LogMessages.message("0123456789abcdef", 1, 0, lines)
        assertTrue(bytes.size <= LogMessages.MAX_BYTES)
        assertEquals(2, count)
        val (_, one) = LogMessages.message("0123456789abcdef", 1, 0, lines.take(1))
        assertEquals(1, one)
    }

    @Test
    fun `an answer of the run is read, any other is not`() {
        fun read(text: String) = text.toByteArray().let { LogMessages.answered(it, it.size, "0123456789abcdef") }
        assertEquals(42L, read("PFLG 1 0123456789abcdef 42\n"))
        assertNull(read("PFLG 1 fedcba9876543210 42\n")) // an earlier run's
        assertNull(read("PFLG 2 0123456789abcdef 42\n"))
        assertNull(read("PFTS whatever"))
        assertNull(read("PFLG 1 0123456789abcdef -1"))
        assertNull(read("PFLG 1 0123456789abcdef many"))
    }
}
