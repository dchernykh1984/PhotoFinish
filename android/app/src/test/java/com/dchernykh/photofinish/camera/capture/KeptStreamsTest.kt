package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Test

/** [KeptStreams]: a lens's stream across the cameras' opens, and its end once it keeps nothing to send. */
class KeptStreamsTest {
    private class Fake(
        val format: Int,
    ) : KeptStream {
        val said = mutableListOf<String>()
        override var unsent = false

        override fun feed() {
            said += "fed"
        }

        override fun idle() {
            said += "idle"
        }

        override fun stop() {
            said += "stopped"
        }
    }

    private val kept = KeptStreams<Fake>()

    private fun feed(
        lens: Lens,
        format: Int = 1,
    ): Fake = kept.feed(lens, { it.format == format }) { Fake(format) }

    @Test
    fun `a camera opened again feeds the stream it fed, none started, what it kept still to send`() {
        val main = feed(Lens.MAIN)
        kept.idle(Lens.MAIN, 1_000) // the camera lost
        main.unsent = true
        assertSame(main, feed(Lens.MAIN)) // opened again 2 s on
        assertEquals(listOf("idle", "fed"), main.said)
        assertSame(main, kept[Lens.MAIN])
    }

    @Test
    fun `a stream that does not fit is stopped before its lens's new one starts`() {
        val main = feed(Lens.MAIN, format = 1)
        val order = mutableListOf<String>()
        val other =
            kept.feed(Lens.MAIN, { it.format == 2 }) {
                order += main.said
                Fake(2)
            }
        assertEquals(listOf("stopped"), order) // one stream a lens: its folder and its recorder
        assertSame(other, kept[Lens.MAIN])
    }

    @Test
    fun `a lens whose stream will not start is left none, the one before stopped`() {
        val main = feed(Lens.MAIN, format = 1)
        assertThrows(IllegalStateException::class.java) {
            kept.feed(Lens.MAIN, { false }) { throw IllegalStateException("no encoder") }
        }
        assertEquals(listOf("stopped"), main.said)
        assertNull(kept[Lens.MAIN])
    }

    @Test
    fun `a stream no camera feeds is stopped 5 s on once it keeps nothing unsent, not before`() {
        val main = feed(Lens.MAIN)
        val tele = feed(Lens.TELEPHOTO)
        kept.idle(Lens.MAIN, 10_000)
        kept.idle(Lens.TELEPHOTO, 10_000)
        tele.unsent = true // a Wi-Fi slow: what it kept still going
        assertEquals(emptyList<Lens>(), kept.sweep(10_000 + KeptStreams.IDLE_MS - 1))
        assertEquals(listOf(Lens.MAIN), kept.sweep(10_000 + KeptStreams.IDLE_MS))
        assertEquals(listOf("idle", "stopped"), main.said)
        assertNull(kept[Lens.MAIN])
        assertEquals(emptyList<Lens>(), kept.sweep(60_000)) // the telephoto kept while it sends
        tele.unsent = false
        assertEquals(listOf(Lens.TELEPHOTO), kept.sweep(60_000))
    }

    @Test
    fun `a stream fed again before its 5 s, or fed throughout, is not stopped`() {
        val main = feed(Lens.MAIN)
        feed(Lens.TELEPHOTO) // fed throughout: never idle
        kept.idle(Lens.MAIN, 10_000)
        feed(Lens.MAIN) // opened again 2 s on
        kept.idle(Lens.MAIN, 20_000) // lost again: its 5 s from here, not the first loss
        assertEquals(emptyList<Lens>(), kept.sweep(24_999))
        assertEquals(listOf(Lens.MAIN), kept.sweep(25_000))
        assertEquals(listOf("idle", "fed", "idle", "stopped"), main.said)
    }

    @Test
    fun `a stream told idle twice keeps its first moment, and a lens with none is no news`() {
        val main = feed(Lens.MAIN)
        kept.idle(Lens.MAIN, 10_000)
        kept.idle(Lens.MAIN, 14_000) // the screen away after the camera was lost: idle since the loss
        kept.idle(Lens.FRONT, 10_000) // never streamed
        assertEquals(listOf(Lens.MAIN), kept.sweep(15_000))
        assertEquals(listOf("idle", "stopped"), main.said)
    }

    @Test
    fun `another choice stops every stream once, what they kept dropped`() {
        val main = feed(Lens.MAIN)
        val tele = feed(Lens.TELEPHOTO)
        tele.unsent = true
        kept.idle(Lens.TELEPHOTO, 0)
        kept.stopAll()
        assertEquals(listOf("stopped"), main.said)
        assertEquals(listOf("idle", "stopped"), tele.said)
        assertNull(kept[Lens.TELEPHOTO])
        assertEquals(emptyList<Lens>(), kept.sweep(60_000)) // nothing left to stop again
    }
}
