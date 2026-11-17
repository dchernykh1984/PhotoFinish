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
    fun `the system log is kept to its limit a second, how many were left out said, the app's lines whole`() {
        val log = log(perSecond = 2)
        repeat(5) { log.system('e', "mapper: unsupported metadata $it") }
        log.error("main", "camera error 4: the camera device failed") // never left out
        assertEquals(3, log.after(0).size)
        now += 1_000
        log.system('w', "the next second")
        val lines = log.after(0).map { "${it.level} ${it.text}" }
        assertEquals("E camera error 4: the camera device failed", lines[2])
        assertEquals("w 3 lines of the system log left out: more than 2 a second", lines[3])
        assertEquals("w the next second", lines[4])
    }

    @Test
    fun `a full log lets the system log's oldest line go before the app's own`() {
        val log = log(capacity = 3)
        log.error(null, "the camera failed")
        log.system('e', "driver: one")
        log.system('e', "driver: two")
        log.system('e', "driver: three")
        log.system('e', "driver: four")
        assertEquals(listOf("the camera failed", "driver: three", "driver: four"), log.after(0).map { it.text })
        repeat(3) { log.info(null, "own $it") }
        assertEquals(listOf("own 0", "own 1", "own 2"), log.after(0).map { it.text }) // none of the system's left
        log.system('e', "driver: five") // the newest is kept: the oldest of the app's goes
        assertEquals(listOf("own 1", "own 2", "driver: five"), log.after(0).map { it.text })
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
