package com.dchernykh.photofinish.camera.diagnostics

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneLogTest {
    private var now = 1_000_000L

    private fun log(
        capacity: Int = 1_000,
        perSecond: Int = 20,
        mirror: (LogLine) -> Unit = {},
    ) = PhoneLog(capacity, perSecond, { now }, mirror)

    @Test
    fun `lines are numbered from one, with their time, level and lens`() {
        val log = log()
        log.info(null, "PhotoFinish Camera 0.8.0")
        now += 5
        log.error("telephoto", "its encoder stopped")
        val lines = log.after(0)
        assertEquals(listOf(1L, 2L), lines.map { it.seq })
        assertEquals(listOf(now - 5, now), lines.map { it.atMs })
        assertEquals(listOf('I', 'E'), lines.map { it.level })
        assertEquals(listOf(null, "telephoto"), lines.map { it.lens })
        assertEquals(2L, log.newest)
        assertEquals(listOf(2L), log.after(1).map { it.seq })
    }

    @Test
    fun `the last lines alone are kept for recorders that have not answered`() {
        val log = log(capacity = 3)
        repeat(5) { log.info(null, "line $it") }
        assertEquals(listOf(3L, 4L, 5L), log.after(0).map { it.seq })
        assertEquals(5L, log.newest)
    }

    @Test
    fun `a burst is kept to its limit a second, and how many were left out is said`() {
        val log = log(perSecond = 2)
        repeat(5) { log.warning(null, "again $it") }
        assertEquals(2, log.after(0).size)
        now += 1_000
        log.info(null, "the next second")
        val lines = log.after(0).map { it.text }
        assertEquals("3 lines left out: more than 2 a second", lines[2])
        assertEquals("the next second", lines[3])
    }

    @Test
    fun `a line is one line, cut where it would be too long, whole characters`() {
        assertEquals("first | second", PhoneLog.cut("first\r\n  second\n"))
        val long = PhoneLog.cut("\u0436".repeat(300)) // two bytes each
        assertTrue(long.endsWith(" [cut]"))
        assertTrue(long.toByteArray(Charsets.UTF_8).size <= PhoneLog.MAX_BYTES)
        assertEquals(197, long.removeSuffix(" [cut]").length) // 394 bytes of whole characters
        val short = "x".repeat(PhoneLog.MAX_BYTES)
        assertEquals(short, PhoneLog.cut(short))
    }

    @Test
    fun `each line kept is written on as well, and every run is its own`() {
        val mirrored = mutableListOf<String>()
        val log = log(mirror = { mirrored += it.text })
        log.info("main", "camera 0 opened")
        assertEquals(listOf("camera 0 opened"), mirrored)
        assertEquals(16, log.run.length)
        assertNotEquals(log.run, log().run)
    }
}
