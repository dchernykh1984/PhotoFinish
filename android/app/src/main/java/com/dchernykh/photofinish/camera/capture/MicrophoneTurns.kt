package com.dchernykh.photofinish.camera.capture

import java.util.concurrent.atomic.AtomicBoolean

/**
 * When the phone's microphone reads (specs/013), [Microphone]'s glue aside: started and stopped as a camera feeds
 * its stream or not. One reader at a time in the app: a start while the reader of a stop before still reads --
 * ending, or the audio server stalled; another stream's, replaced, as much as its own -- is put off until that one
 * has let the microphone go, waited for on a thread of its own, never on the caller's, the camera's; one start put
 * off at a time, made then if still wanted, never after a stop. A refusal said once.
 */
internal class MicrophoneTurns<T : Any>(
    /** The microphone allowed, asked at each start: allowed after the stream began, it starts at the next. */
    private val allowed: () -> Boolean,
    /** The microphone and its encoder opened; null when they cannot be, which it says. */
    private val open: () -> T?,
    /** What [open] gave read on a thread of its own, started, until its word to go on is false: the thread. */
    private val read: (T, AtomicBoolean) -> Thread,
    /** Told whether it runs: as it starts, before its thread can fail, as it fails, and as it stops. */
    private val sounded: (Boolean) -> Unit,
    private val refused: () -> Unit,
    private val reader: Reader = Reader.shared,
) {
    /** The thread reading the microphone, whichever stream's: one at a time in the app. */
    class Reader {
        @Volatile var thread: Thread? = null

        companion object {
            val shared = Reader()
        }
    }

    /** Started and not stopped since: a start put off is made then. */
    @Volatile private var wanted = false

    /** Its refusal said already: once, not at each camera opened again. */
    private var refusalSaid = false

    /** Its reader's own word to go on: one stopped never runs again. */
    private var running: AtomicBoolean? = null

    /** A start put off waits for the reader before: one at a time. */
    private var putOff = false

    /**
     * Started, unless it runs: whether it runs now. The reader looked at and taken under the shared reader's lock:
     * two streams starting at once -- the camera's thread, and another's start put off -- open it once.
     */
    @Synchronized
    fun start(): Boolean {
        wanted = true
        if (running?.get() == true) return true
        if (!allowed()) {
            refuse()
            sounded(false)
            return false
        }
        return synchronized(reader) { begin() }
    }

    /** Opened and read, unless another's reader still reads; the caller holds both locks. */
    private fun begin(): Boolean {
        val before = reader.thread
        val opened =
            if (before?.isAlive == true) {
                later(before)
            } else {
                refusalSaid = false // allowed again: a refusal after it said again
                open()
            }
        if (opened == null) return false.also { sounded(false) }
        val going = AtomicBoolean(true)
        running = going
        sounded(true) // before its thread runs: a failure of its told after
        reader.thread = read(opened, going)
        return true
    }

    /** Stopped: its reader told to end, never waited for; its stream told it runs no more. */
    @Synchronized
    fun stop() {
        wanted = false
        running?.set(false)
        running = null
        sounded(false) // a connection made now waits for no sound's config
    }

    /** Not allowed the microphone: said the first time, the stream going without sound; nothing opened. */
    private fun refuse() {
        if (!refusalSaid) refused()
        refusalSaid = true
    }

    /** Started once [before] has stopped reading, if still wanted then; not two waiting at once. */
    private fun later(before: Thread): T? {
        if (putOff) return null
        putOff = true
        Thread(
            {
                before.join(LATER_MS)
                resume()
            },
            "microphone-later",
        ).apply {
            isDaemon = true
            start()
        }
        return null
    }

    /** Started if still wanted, asked under the lock a stop takes: a stop meanwhile is never undone. */
    @Synchronized
    private fun resume() {
        putOff = false
        if (wanted) start()
    }

    companion object {
        private const val LATER_MS = 5_000L
    }
}
