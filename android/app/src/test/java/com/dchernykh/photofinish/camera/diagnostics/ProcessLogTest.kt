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
    fun `a system log that ends is said, and read again from after its newest line`() {
        val log = PhoneLog()
        val asked = mutableListOf<String?>()
        val line = "1794918339.123  1234  1301 W CameraDevice-JV-0: Device error received, code 4"
        ProcessLog.follow(log, 1, { since -> listOf("echo", line).also { asked += since } }, pauseMs = 50)
        val deadline = System.currentTimeMillis() + 5_000
        while (log.newest < 3 && System.currentTimeMillis() < deadline) Thread.sleep(20)
        val said = log.after(0).take(2).map { "${it.level} ${it.text}" }
        assertEquals("w CameraDevice-JV-0: Device error received, code 4", said[0])
        assertEquals("w the system log ended: read again in 0 s", said[1]) // never the phone's last word
        assertEquals(listOf(null, "1794918339.124"), asked.take(2)) // none of the lines read again
    }

    @Test
    fun `a system log that ends at once, nothing read, is said once and not read again`() {
        val log = PhoneLog()
        var asked = 0
        val refusal = "logcat: unknown option -- T" // logcat's own words, no line of the log
        ProcessLog.follow(log, 1, { listOf("echo", refusal).also { asked++ } }, pauseMs = 10)
        val deadline = System.currentTimeMillis() + 5_000
        while (log.newest == 0L && System.currentTimeMillis() < deadline) Thread.sleep(20)
        Thread.sleep(200)
        assertEquals(listOf("the system log ends at once: not read again"), log.after(0).map { it.text })
        assertEquals(1, asked)
    }

    @Test
    fun `a system log read before is read again however quiet it was when it ended`() {
        val log = PhoneLog()
        var asked = 0
        val line = "1794918339.123  1234  1301 W CameraDevice-JV-0: Device error received, code 4"
        val reading = { _: String? -> (if (asked++ == 0) listOf("echo", line) else listOf("true")) }
        ProcessLog.follow(log, 1, reading, pauseMs = 10)
        val deadline = System.currentTimeMillis() + 5_000
        while (asked < 4 && System.currentTimeMillis() < deadline) Thread.sleep(20)
        assertTrue(asked >= 4) // a quiet reading after one that read: read again
    }
}
