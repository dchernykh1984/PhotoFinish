package com.dchernykh.photofinish.camera.diagnostics

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ProcessLogTest {
    @Test
    fun `the system log's warnings and errors are read, with their tag`() {
        val device = "CameraDevice-JV-0: Device error received, code 4"
        assertEquals('w' to device, ProcessLog.read("1794918339.123  1234  1301 W $device"))
        val codec = "MediaCodec: Codec reported err 0x80001001, actionCode 0, while in state 6"
        assertEquals('e' to codec, ProcessLog.read("1794918339.456  1234  1350 E $codec"))
        assertEquals('e', ProcessLog.read("1794918339.456  1234  1350 F libc    : Fatal signal 6")?.first)
        assertEquals(
            "libc: Fatal signal 6",
            ProcessLog.read("1794918339.456  1234  1350 F libc    : Fatal signal 6")?.second,
        )
    }

    @Test
    fun `lines of no use are not`() {
        assertNull(ProcessLog.read("--------- beginning of main"))
        assertNull(ProcessLog.read("1794918339.123  1234  1301 I Camera: opened"))
        assertNull(ProcessLog.read(""))
    }

    @Test
    fun `a system log that cannot be read is said`() {
        val log = PhoneLog()
        ProcessLog.follow(log, 1) // a computer has no logcat
        val deadline = System.currentTimeMillis() + 5_000
        while (log.newest == 0L && System.currentTimeMillis() < deadline) Thread.sleep(20)
        val said = log.after(0).single()
        assertEquals('w', said.level)
        assertTrue(said.text, said.text.startsWith("the system log cannot be read: "))
    }

    @Test
    fun `a system log that ends is said, and read again for its new lines`() {
        val log = PhoneLog()
        val asked = mutableListOf<Boolean>()
        val line = "1794918339.123  1234  1301 W CameraDevice-JV-0: Device error received, code 4"
        ProcessLog.follow(log, 1, { again -> listOf("echo", line).also { asked += again } }, pauseMs = 50)
        val deadline = System.currentTimeMillis() + 5_000
        while (log.newest < 4 && System.currentTimeMillis() < deadline) Thread.sleep(20)
        val said = log.after(0).take(4).map { "${it.level} ${it.text}" }
        assertEquals("w CameraDevice-JV-0: Device error received, code 4", said[0])
        assertEquals("w the system log ended: read again, its new lines, in 0 s", said[1]) // no last word
        assertEquals(said[0], said[2])
        assertEquals(listOf(false, true), asked.take(2))
    }
}
