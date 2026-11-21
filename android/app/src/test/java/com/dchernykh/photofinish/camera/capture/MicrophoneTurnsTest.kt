package com.dchernykh.photofinish.camera.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

class MicrophoneTurnsTest {
    /** A microphone whose reader ends as told -- or, stalled, only once let go, as an audio server that hangs. */
    private class Mic(
        val reader: MicrophoneTurns.Reader,
        var allowed: Boolean = true,
    ) {
        val opened = AtomicInteger()
        val refusals = AtomicInteger()
        val sounded = mutableListOf<Boolean>()
        val stall = AtomicBoolean(false)
        val letGo = CountDownLatch(1)

        val turns =
            MicrophoneTurns(
                { allowed },
                { opened.incrementAndGet() },
                { _, going ->
                    Thread {
                        while (going.get()) Thread.sleep(5)
                        if (stall.get()) letGo.await(10, TimeUnit.SECONDS)
                    }.apply { start() }
                },
                { synchronized(sounded) { sounded += it } },
                { refusals.incrementAndGet() },
                reader,
            )
    }

    private fun waitFor(condition: () -> Boolean) {
        val until = System.nanoTime() + 5_000_000_000L
        while (!condition() && System.nanoTime() < until) Thread.sleep(10)
        assertTrue(condition())
    }

    @Test
    fun `a start reads once, a stop ends it, and a start after opens it again`() {
        val mic = Mic(MicrophoneTurns.Reader())
        assertTrue(mic.turns.start())
        assertTrue(mic.turns.start()) // running: not opened twice
        assertEquals(1, mic.opened.get())
        mic.turns.stop()
        waitFor { mic.reader.thread?.isAlive == false }
        assertTrue(mic.turns.start())
        assertEquals(2, mic.opened.get())
        mic.turns.stop()
    }

    @Test
    fun `a stream replaced while the reader before still reads opens the microphone once it has let it go`() {
        // KeptStreams replaces a stream at once: its new microphone never opens beside the one still reading.
        val shared = MicrophoneTurns.Reader()
        val old = Mic(shared)
        assertTrue(old.turns.start())
        old.stall.set(true)
        old.turns.stop() // its reader stuck in a stalled audio server
        val new = Mic(shared)
        assertFalse(new.turns.start())
        Thread.sleep(200)
        assertEquals(0, new.opened.get()) // two would read at once
        old.letGo.countDown()
        waitFor { new.opened.get() == 1 }
        new.turns.stop()
    }

    @Test
    fun `a start put off and a stop before the reader ends never opens the microphone`() {
        val shared = MicrophoneTurns.Reader()
        val old = Mic(shared)
        old.turns.start()
        old.stall.set(true)
        old.turns.stop()
        val new = Mic(shared)
        new.turns.start()
        new.turns.stop() // the stream ended while it waited
        old.letGo.countDown()
        Thread.sleep(300)
        assertEquals(0, new.opened.get())
    }

    @Test
    fun `starts during a stall put off one start, not one each`() {
        val shared = MicrophoneTurns.Reader()
        val old = Mic(shared)
        old.turns.start()
        old.stall.set(true)
        old.turns.stop()
        val new = Mic(shared)
        repeat(10) { new.turns.start() } // the screen off and on, again and again
        val waiting = Thread.getAllStackTraces().keys.count { it.name == "microphone-later" && it.isAlive }
        assertEquals(1, waiting)
        old.letGo.countDown()
        waitFor { new.opened.get() == 1 }
        new.turns.stop()
    }

    @Test
    fun `a refusal is said once, then again after the microphone was allowed and refused anew`() {
        val mic = Mic(MicrophoneTurns.Reader(), allowed = false)
        assertFalse(mic.turns.start())
        assertFalse(mic.turns.start())
        assertEquals(1, mic.refusals.get())
        mic.allowed = true
        assertTrue(mic.turns.start())
        mic.turns.stop()
        waitFor { mic.reader.thread?.isAlive == false }
        mic.allowed = false
        mic.turns.start()
        assertEquals(2, mic.refusals.get())
        assertEquals(listOf(false, false, true, false), synchronized(mic.sounded) { mic.sounded.toList() })
    }
}
