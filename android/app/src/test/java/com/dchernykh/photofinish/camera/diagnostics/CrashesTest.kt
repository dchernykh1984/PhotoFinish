package com.dchernykh.photofinish.camera.diagnostics

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class CrashesTest {
    @get:Rule
    val temporary = TemporaryFolder()

    private fun thrown(): IllegalStateException =
        try {
            try {
                error("camera 0 is gone")
            } catch (inner: IllegalStateException) {
                throw IllegalStateException("the session could not be made", inner)
            }
        } catch (outer: IllegalStateException) {
            outer
        }

    @Test
    fun `an error is told on one line, where it was thrown and what caused it`() {
        val told = Crashes.describe(thrown())
        assertTrue(told, told.startsWith("IllegalStateException: the session could not be made at CrashesTest.thrown:"))
        assertTrue(told, "; caused by IllegalStateException: camera 0 is gone at CrashesTest.thrown:" in told)
        assertFalse(told, '\n' in told)
        assertEquals("RuntimeException", Crashes.describe(RuntimeException().apply { stackTrace = emptyArray() }))
    }

    @Test
    fun `an error no thread catches is kept for the next start, which tells it once`() {
        val file = File(temporary.root, "crash.txt")
        val before = Thread.getDefaultUncaughtExceptionHandler()
        val ended = mutableListOf<Throwable>()
        Thread.setDefaultUncaughtExceptionHandler { _, error -> ended += error }
        try {
            Crashes.keep(file)
            val error = thrown()
            Thread.getDefaultUncaughtExceptionHandler()!!.uncaughtException(Thread.currentThread(), error)
            assertEquals(listOf<Throwable>(error), ended) // the app ends as it would have
        } finally {
            Thread.setDefaultUncaughtExceptionHandler(before)
        }
        val log = PhoneLog()
        Crashes.tell(file, log)
        val said = log.after(0).single()
        assertEquals('E', said.level)
        assertTrue(said.text, said.text.startsWith("the app ended on an error in thread "))
        assertFalse(file.exists())
        Crashes.tell(file, log) // no file: nothing to tell
        assertEquals(1, log.after(0).size)
    }
}
