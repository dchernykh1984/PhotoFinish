package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotSame
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
        override var alive = true

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
        assertSame(other, feed(Lens.MAIN, format = 2)) // the new one kept
    }

    @Test
    fun `a stream whose encoder stopped is not fed again but stopped, a new one made, as before`() {
        val main = feed(Lens.MAIN)
        kept.idle(Lens.MAIN, 1_000)
        main.alive = false // its encoder failed mid-race: what a camera gives it goes nowhere
        val again = feed(Lens.MAIN)
        assertEquals(listOf("idle", "stopped"), main.said)
        assertSame(again, feed(Lens.MAIN)) // the new one kept
    }

    @Test
    fun `a lens whose stream will not start is left none, the one before stopped`() {
        val main = feed(Lens.MAIN, format = 1)
        assertThrows(IllegalStateException::class.java) {
            kept.feed(Lens.MAIN, { false }) { throw IllegalStateException("no encoder") }
        }
        assertEquals(listOf("stopped"), main.said)
        assertNotSame(main, feed(Lens.MAIN)) // none kept: the next feed makes one
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
        assertEquals(emptyList<Lens>(), kept.sweep(60_000)) // the telephoto kept while it sends
        tele.unsent = false
        assertEquals(listOf(Lens.TELEPHOTO), kept.sweep(60_000))
        assertNotSame(main, feed(Lens.MAIN)) // the main lens's next open makes a new one
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
    fun `the lenses with a stream are told, the idle among them, not those stopped`() {
        feed(Lens.MAIN)
        feed(Lens.TELEPHOTO).unsent = true
        kept.idle(Lens.TELEPHOTO, 0) // left out, still sending what it kept: its room still taken
        kept.idle(Lens.MAIN, 0)
        assertEquals(setOf(Lens.MAIN, Lens.TELEPHOTO), kept.lenses)
        kept.sweep(KeptStreams.IDLE_MS)
        assertEquals(setOf(Lens.TELEPHOTO), kept.lenses)
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
        assertNotSame(tele, feed(Lens.TELEPHOTO))
        assertEquals(emptyList<Lens>(), kept.sweep(60_000)) // nothing left to stop again
    }
}

/** [FedFrames]: a lens's frames as each feed sees them. */
class FedFramesTest {
    @Test
    fun `a frame the camera before took, drained late after the feed, is not the feed's first`() {
        val frames = FedFrames()
        assertEquals(true, frames.heard(1_000_000, 100)) // a new stream's first frame
        assertEquals(false, frames.heard(1_033_000, 133))
        frames.feed(5_000_000) // the camera opened again: its frames from 5 s on the frames' clock
        assertEquals(0L, frames.lastFrameMs)
        assertEquals(false, frames.heard(1_066_000, 4_100)) // the encoder's last of the camera before
        assertEquals(0L, frames.lastFrameMs) // not taken for the new camera's frames
        assertEquals(true, frames.heard(5_100_000, 4_200)) // the new camera's first
        assertEquals(4_200L, frames.lastFrameMs)
        assertEquals(false, frames.heard(5_133_000, 4_233))
    }

    @Test
    fun `a feed with the frames' clock unknown takes every frame as its own`() {
        val frames = FedFrames()
        frames.feed(null)
        assertEquals(true, frames.heard(1_000, 50))
        assertEquals(50L, frames.lastFrameMs)
    }
}
