package com.dchernykh.photofinish.camera.capture

import android.hardware.camera2.CameraDevice
import com.dchernykh.photofinish.camera.pairing.Lens
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** The stops of [LensFallback]: a lens that gave frames and then none, the waits and retries, the frames' watch. */
class LensStopTest {
    private fun error(sinceStartMs: Long?) =
        CameraFailure.Error(CameraDevice.StateCallback.ERROR_CAMERA_DEVICE, sinceStartMs)

    @Test
    fun `a lens that gave frames and then none goes early itself, the cameras made again without it`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.ULTRAWIDE)
        val telephoto = CameraFailure.Stalled(Lens.TELEPHOTO, 4_000, 104_000)
        assertEquals(Lens.TELEPHOTO, fallback.failed(1, back, back, telephoto)) // not the camera's last
        assertEquals(true, fallback.madeAgain(1, telephoto))
        assertEquals(emptyList<Lens>(), fallback.waitedFor(1, telephoto)) // it gave frames: not waited for
        // The first lens never goes: its camera's last lightens the load, as for an error, the first time.
        val main = CameraFailure.Stalled(Lens.MAIN, 3_000, 203_000)
        assertEquals(Lens.ULTRAWIDE, fallback.failed(2, back - Lens.TELEPHOTO, back - Lens.TELEPHOTO, main))
        assertEquals(true, fallback.madeAgain(2, main)) // made again without it
        val front = CameraFailure.Stalled(Lens.FRONT, 2_000, 302_000)
        assertEquals(Lens.FRONT, fallback.failedAlone(3, listOf(Lens.MAIN, Lens.FRONT), listOf(Lens.FRONT), front))
    }

    @Test
    fun `a lens that stops later, or once the lenses ran together, makes the cameras again with every lens`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val late = CameraFailure.Stalled(Lens.TELEPHOTO, LensFallback.EARLY_MS, 110_000)
        assertNull(fallback.failed(1, back, back, late)) // past its first seconds: a camera lost, not the lenses'
        assertEquals(true, fallback.madeAgain(1, late))
        fallback.settle(0)
        val soon = CameraFailure.Stalled(Lens.TELEPHOTO, 2_000, 302_000) // soon after a reopen mid-race
        assertNull(fallback.failed(2, back, back, soon))
        assertEquals(true, fallback.madeAgain(2, soon))
        assertEquals(emptySet<Lens>(), fallback.leftOut)
    }

    @Test
    fun `a lens stopping again within a minute goes, the first waited for, nothing made again for it`() {
        val fallback = LensFallback()
        fallback.settle(0) // streaming a while: a stop is a camera lost
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val first = CameraFailure.Stalled(Lens.TELEPHOTO, 30_000, 100_000)
        assertNull(fallback.failed(1, back, back, first))
        assertEquals(true, fallback.madeAgain(1, first)) // every lens tried again
        val again = CameraFailure.Stalled(Lens.TELEPHOTO, 2_000, 105_000) // the reopen did not bring it back
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, back, back, again))
        assertEquals(true, fallback.madeAgain(2, again)) // without it, the others streaming
        // The first lens cannot go: stopping again it is waited for, the front streaming on, nothing made again.
        val withFront = listOf(Lens.MAIN, Lens.FRONT)
        val mainStops = CameraFailure.Stalled(Lens.MAIN, 20_000, 200_000)
        assertNull(fallback.failed(3, withFront, listOf(Lens.MAIN), mainStops))
        assertEquals(true, fallback.madeAgain(3, mainStops))
        val mainAgain = CameraFailure.Stalled(Lens.MAIN, 3_000, 230_000)
        assertNull(fallback.failed(4, withFront, listOf(Lens.MAIN), mainAgain))
        assertEquals(false, fallback.madeAgain(4, mainAgain))
        assertEquals(listOf(Lens.MAIN), fallback.waitedFor(4, mainAgain))
        assertEquals(true, fallback.waitsFor(4, Lens.MAIN))
    }

    @Test
    fun `the first lens streamed alone and stopping again is opened again each time, none streaming to cut`() {
        val fallback = LensFallback()
        fallback.settle(0)
        val main = listOf(Lens.MAIN)
        assertNull(fallback.failed(1, main, main, CameraFailure.Stalled(Lens.MAIN, 20_000, 200_000)))
        val again = CameraFailure.Stalled(Lens.MAIN, 3_000, 205_000)
        assertNull(fallback.failed(2, main, main, again))
        assertEquals(true, fallback.madeAgain(2, again))
        assertEquals(emptyList<Lens>(), fallback.waitedFor(2, again))
    }

    @Test
    fun `a lens waited for that gives frames again is watched again, as any lens`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val silent = CameraFailure.NoFrame(listOf(Lens.TELEPHOTO), 5_000)
        assertNull(fallback.failed(1, back - Lens.TELEPHOTO, back, silent)) // none to leave out: waited for
        assertEquals(listOf(Lens.TELEPHOTO), fallback.waitedFor(1, silent))
        fallback.heardFrom(1, Lens.TELEPHOTO, 0, 6_000) // still silent
        assertEquals(true, fallback.waitsFor(1, Lens.TELEPHOTO))
        fallback.heardFrom(1, Lens.TELEPHOTO, 7_000, 7_100) // its first frame at 7 s
        assertEquals(false, fallback.waitsFor(1, Lens.TELEPHOTO)) // a stop of it now seen
    }

    @Test
    fun `a stop heard by both cameras' paths is one stop, not a stop come again`() {
        val fallback = LensFallback()
        fallback.settle(0)
        val streamed = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.FRONT)
        val front = CameraFailure.Stalled(Lens.FRONT, 30_000, 100_000)
        assertNull(fallback.failedAlone(1, streamed, listOf(Lens.FRONT), front))
        assertNull(fallback.failed(1, streamed, listOf(Lens.FRONT), front)) // the same stop, again: no repeat
        assertEquals(emptyList<Lens>(), fallback.waitedFor(1, front)) // the other camera's: opened again alone
        assertEquals(emptySet<Lens>(), fallback.leftOut)
    }

    @Test
    fun `a lens stopping a minute or more after its last stop has every lens opened again, as the first time`() {
        val fallback = LensFallback()
        fallback.settle(0)
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        assertNull(fallback.failed(1, back, back, CameraFailure.Stalled(Lens.TELEPHOTO, 30_000, 100_000)))
        val later = CameraFailure.Stalled(Lens.TELEPHOTO, 50_000, 100_000 + LensFallback.AGAIN_MS)
        assertNull(fallback.failed(2, back, back, later))
        assertEquals(true, fallback.madeAgain(2, later))
        assertEquals(emptyList<Lens>(), fallback.waitedFor(2, later))
        assertEquals(emptySet<Lens>(), fallback.leftOut)
    }

    @Test
    fun `a lens is taken for stopped once it gave a frame and then none for 3 s, timed by its last`() {
        assertNull(LensFallback.stall(Lens.MAIN, 0, 0, 60_000)) // none yet: no frame, not a stop
        assertNull(LensFallback.stall(Lens.MAIN, 1_000, 0, 1_000 + LensFallback.STALL_MS)) // not yet
        val stopped = LensFallback.stall(Lens.MAIN, 7_500, 500, 7_501 + LensFallback.STALL_MS)
        assertEquals(CameraFailure.Stalled(Lens.MAIN, 7_000, 7_500), stopped) // when it stopped, not when seen
    }

    @Test
    fun `a lens that stopped before the lenses settled is their doing, the watch seeing it after`() {
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val fallback = LensFallback().apply { settle(10_000) } // every lens framed at once: settled 10 s on
        val telephoto = LensFallback.stall(Lens.TELEPHOTO, 7_500, 0, 10_600) // stopped at 7.5 s, seen after
        assertEquals(Lens.TELEPHOTO, fallback.failed(1, back, back, telephoto))
        // Settled before: a camera lost, every lens opened again -- an open mid-race stopping 3 s in.
        val midRace = LensFallback().apply { settle(10_000) }
        assertNull(midRace.failed(2, back, back, CameraFailure.Stalled(Lens.TELEPHOTO, 3_000, 53_000)))
    }

    @Test
    fun `the first lens waited for after stopping again is tried again a minute on, waited for if it stops soon`() {
        val fallback = LensFallback()
        fallback.settle(0)
        val withFront = listOf(Lens.MAIN, Lens.FRONT)
        fallback.failed(1, withFront, listOf(Lens.MAIN), CameraFailure.Stalled(Lens.MAIN, 20_000, 200_000))
        val again = CameraFailure.Stalled(Lens.MAIN, 3_000, 230_000)
        assertNull(fallback.failed(2, withFront, listOf(Lens.MAIN), again))
        assertEquals(listOf(Lens.MAIN), fallback.waitedFor(2, again))
        assertNull(fallback.retry(2, Lens.MAIN, 231_000)) // the wait seen: its minute starts
        assertNull(fallback.retry(2, Lens.MAIN, 231_000 + LensFallback.AGAIN_MS - 1)) // not yet
        assertEquals(Lens.MAIN, fallback.retry(2, Lens.MAIN, 231_000 + LensFallback.AGAIN_MS))
        assertEquals(false, fallback.waitsFor(2, Lens.MAIN))
        assertNull(fallback.retry(2, Lens.MAIN, 400_000)) // once a wait
        val soon = CameraFailure.Stalled(Lens.MAIN, 4_000, 300_000) // stopping soon after it was tried again
        assertNull(fallback.failed(3, withFront, listOf(Lens.MAIN), soon))
        assertEquals(false, fallback.madeAgain(3, soon)) // waited for again, the front on
    }

    @Test
    fun `the other camera's lens stopping later, and again soon, is opened again alone, never left out for it`() {
        val fallback = LensFallback()
        fallback.settle(0)
        val streamed = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.FRONT)
        val front = CameraFailure.Stalled(Lens.FRONT, 30_000, 100_000)
        assertNull(fallback.failedAlone(1, streamed, listOf(Lens.FRONT), front))
        assertEquals(2_000L, fallback.aloneIn(Lens.FRONT, 2_000)) // 2 s on, as any camera lost
        val again = CameraFailure.Stalled(Lens.FRONT, 5_000, 140_000) // stopping again within a minute
        assertNull(fallback.failedAlone(1, streamed, listOf(Lens.FRONT), again)) // it cuts no other lens
        assertEquals(60_000L, fallback.aloneIn(Lens.FRONT, 2_000)) // its own doing: a minute on
        assertEquals(emptySet<Lens>(), fallback.leftOut)
        // The first camera's lens stopping again so goes: its reopen would cut the others.
        val tele = CameraFailure.Stalled(Lens.TELEPHOTO, 30_000, 200_000)
        assertNull(fallback.failed(1, streamed, streamed - Lens.FRONT, tele))
        val teleAgain = CameraFailure.Stalled(Lens.TELEPHOTO, 3_000, 210_000)
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, streamed, streamed - Lens.FRONT, teleAgain))
    }

    @Test
    fun `the other camera opened again alone waits 2 s, then a minute, two, four, up to half an hour`() {
        val fallback = LensFallback()
        val waits = List(8) { fallback.aloneIn(Lens.FRONT, 2_000) }
        val minutes = listOf(1L, 2L, 4L, 8L, 16L, 32L, 32L).map { it * 60_000 }
        assertEquals(listOf(2_000L) + minutes, waits)
    }

    @Test
    fun `the front's tries alone and a first lens's waits are counted apart, one not doubling the other`() {
        val fallback = LensFallback()
        repeat(4) { fallback.aloneIn(Lens.FRONT, 2_000) } // the front opened alone four times
        // An open where the front is the first lens -- the back would not start --, silent: waited for.
        val silent = CameraFailure.NoFrame(listOf(Lens.FRONT), 5_000)
        fallback.failed(1, listOf(Lens.FRONT), listOf(Lens.FRONT), silent)
        fallback.waitedFor(1, silent)
        assertNull(fallback.retry(1, Lens.FRONT, 10_000)) // the wait seen
        assertEquals(Lens.FRONT, fallback.retry(1, Lens.FRONT, 70_000)) // a minute on, not sixteen
    }

    @Test
    fun `the other camera's wait is said in seconds under a minute, in minutes from one`() {
        assertEquals("2 s", LensFallback.inWords(2_000))
        assertEquals("1 min", LensFallback.inWords(60_000))
        assertEquals("32 min", LensFallback.inWords(32 * 60_000L))
    }

    @Test
    fun `the other camera giving frames a minute after it opened alone has its tries forgotten, 2 s again`() {
        val fallback = LensFallback()
        fallback.aloneIn(Lens.FRONT, 2_000)
        fallback.aloneIn(Lens.FRONT, 2_000) // two tries: the next would wait two minutes
        fallback.watch(1, listOf(Seen(Lens.FRONT, 100_900)), 100_000, 101_000, null) // giving from 101 s
        fallback.watch(1, listOf(Seen(Lens.FRONT, 160_900)), 100_000, 161_000, null) // a minute of frames
        assertEquals(2_000L, fallback.aloneIn(Lens.FRONT, 2_000))
    }

    @Test
    fun `the other camera's minute of frames is counted from its open alone, not from before it was lost`() {
        val fallback = LensFallback()
        fallback.watch(1, listOf(Seen(Lens.FRONT, 900)), 0, 1_000, null) // giving from 1 s
        assertEquals(2_000L, fallback.aloneIn(Lens.FRONT, 2_000)) // lost at 50 s, its camera closed: no watch
        fallback.watch(1, listOf(Seen(Lens.FRONT, 61_400)), 52_000, 61_500, null) // opened again, giving
        assertEquals(60_000L, fallback.aloneIn(Lens.FRONT, 2_000)) // lost again soon: a minute on, not 2 s
    }

    @Test
    fun `the first lens stopping again beside lenses waited for alone is opened again, none streaming to cut`() {
        val fallback = LensFallback()
        fallback.settle(0)
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val silent = CameraFailure.NoFrame(listOf(Lens.TELEPHOTO), 5_000)
        fallback.failed(1, back, back, silent)
        assertEquals(listOf(Lens.TELEPHOTO), fallback.waitedFor(1, silent)) // the telephoto silent, waited for
        fallback.failed(1, back, back, CameraFailure.Stalled(Lens.MAIN, 20_000, 200_000))
        val again = CameraFailure.Stalled(Lens.MAIN, 40_000, 220_000)
        assertNull(fallback.failed(1, back, back, again))
        assertEquals(true, fallback.madeAgain(1, again)) // nothing streams that a reopen would cut
    }

    @Test
    fun `the first lens silent from the start is tried again a minute on, another lens waited for not`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val mainSilent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        assertNull(fallback.failed(1, back, back, mainSilent))
        assertEquals(listOf(Lens.MAIN), fallback.waitedFor(1, mainSilent))
        assertNull(fallback.retry(1, Lens.MAIN, 10_000))
        // Due a minute on, whatever the lenses keep to send: opened again, they keep it (KeptStreams).
        assertNull(fallback.retry(1, Lens.MAIN, 10_000 + LensFallback.AGAIN_MS - 1))
        assertEquals(Lens.MAIN, fallback.retry(1, Lens.MAIN, 10_000 + LensFallback.AGAIN_MS))
        val teleSilent = CameraFailure.NoFrame(listOf(Lens.TELEPHOTO), 5_000)
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, back, back, teleSilent)) // early: left out, not waited for
        val third = LensFallback()
        third.settle(0)
        third.failed(1, back, back, teleSilent)
        assertEquals(listOf(Lens.TELEPHOTO), third.waitedFor(1, teleSilent))
        assertNull(third.retry(1, Lens.MAIN, 10_000))
        assertNull(third.retry(1, Lens.MAIN, 10_000 + LensFallback.AGAIN_MS)) // not the first's: none
    }

    @Test
    fun `the watch tells a lens silent 5 s after the start, then a lens that stopped, one waited for no news`() {
        val fallback = LensFallback()
        val tele = Seen(Lens.TELEPHOTO, 0)
        assertNull(fallback.watch(1, listOf(Seen(Lens.MAIN, 4_000), tele), 0, 4_999, Lens.MAIN)) // not yet
        val silent = fallback.watch(1, listOf(Seen(Lens.MAIN, 4_000), tele), 0, 5_000, Lens.MAIN)
        assertEquals(CameraFailure.NoFrame(listOf(Lens.TELEPHOTO), 5_000), silent?.failure)
        assertEquals("the camera gave telephoto no frame in 5 s", silent?.reason)
        fallback.waitedFor(1, silent?.failure) // none to leave out: waited for
        assertNull(fallback.watch(1, listOf(Seen(Lens.MAIN, 5_500), tele), 0, 6_000, Lens.MAIN))
        val stopped = fallback.watch(1, listOf(Seen(Lens.MAIN, 6_000), tele), 0, 9_500, Lens.MAIN)
        assertEquals(CameraFailure.Stalled(Lens.MAIN, 6_000, 6_000), stopped?.failure)
        assertEquals("the camera gave main no frame for 3 s", stopped?.reason)
    }

    @Test
    fun `the watch tries the first lens waited for again a minute on, before anything else, its camera's alone`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val mainSilent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        fallback.failed(1, back, back, mainSilent)
        fallback.waitedFor(1, mainSilent)
        val seen = listOf(Seen(Lens.MAIN, 0), Seen(Lens.TELEPHOTO, 64_000))
        assertNull(fallback.watch(1, seen, 0, 5_000, Lens.MAIN)) // the wait seen: its minute starts
        assertNull(fallback.watch(1, seen, 0, 65_000, null)) // the other camera's watch tries none
        val retried = fallback.watch(1, seen, 0, 65_000, Lens.MAIN)
        assertEquals(null, retried?.failure)
        assertEquals("main waited for 60 s: tried again", retried?.reason) // silent from the start, not stopped
    }

    @Test
    fun `a camera stopping every lens at once is told by its last lens, not its first`() {
        val fallback = LensFallback()
        val seen = listOf(Seen(Lens.MAIN, 6_000), Seen(Lens.TELEPHOTO, 6_000))
        val stopped = fallback.watch(1, seen, 0, 9_500, Lens.MAIN)
        assertEquals(CameraFailure.Stalled(Lens.TELEPHOTO, 6_000, 6_000), stopped?.failure)
    }

    @Test
    fun `a lens failing as the first lens's retry falls due is told first, the retry the tick after`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val mainSilent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        fallback.failed(1, back, back, mainSilent)
        fallback.waitedFor(1, mainSilent)
        val streaming = listOf(Seen(Lens.MAIN, 0), Seen(Lens.TELEPHOTO, 5_900))
        assertNull(fallback.watch(1, streaming, 0, 6_000, Lens.MAIN)) // the wait seen: its minute starts
        val both = listOf(Seen(Lens.MAIN, 0), Seen(Lens.TELEPHOTO, 9_000)) // the telephoto stopped at 9 s
        val told = fallback.watch(1, both, 0, 66_000, Lens.MAIN)
        assertEquals(CameraFailure.Stalled(Lens.TELEPHOTO, 9_000, 9_000), told?.failure)
        assertEquals(true, fallback.waitsFor(1, Lens.MAIN)) // the retry not spent on it
    }

    @Test
    fun `a lens waited for that comes back and stops within a minute goes, not every lens cut for it`() {
        val fallback = LensFallback()
        fallback.settle(0)
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val silent = CameraFailure.NoFrame(listOf(Lens.TELEPHOTO), 5_000)
        fallback.failed(1, back, back, silent)
        fallback.waitedFor(1, silent)
        fallback.heardFrom(1, Lens.TELEPHOTO, 100_000, 100_100) // back at 100 s
        val pause = CameraFailure.Stalled(Lens.TELEPHOTO, 101_000, 101_000) // and paused
        assertEquals(Lens.TELEPHOTO, fallback.failed(1, back, back, pause))
    }

    @Test
    fun `the lens waited for back, an early failure lightens the load again, not leaving none out`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val mainSilent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        assertNull(fallback.failed(1, back, back, mainSilent)) // the first: none goes, waited for
        fallback.waitedFor(1, mainSilent)
        fallback.heardFrom(1, Lens.MAIN, 6_000, 6_100) // its frames at 6 s
        assertEquals(Lens.TELEPHOTO, fallback.failed(1, back, back, error(8_000))) // the camera's last, as any error
    }

    @Test
    fun `the other camera's lens stopping in an open that left a lens out is closed, no wait kept for it`() {
        val fallback = LensFallback()
        val streamed = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.FRONT)
        assertEquals(Lens.TELEPHOTO, fallback.failed(1, streamed, streamed - Lens.FRONT, error(1_500))) // paid
        val front = CameraFailure.Stalled(Lens.FRONT, 30_000, 100_000)
        assertNull(fallback.failedAlone(1, streamed, listOf(Lens.FRONT), front))
        assertEquals(emptyList<Lens>(), fallback.waitedFor(1, front)) // opened again alone
        assertEquals(true, fallback.madeAgain(2, front)) // no stale wait left for it
    }

    @Test
    fun `the first lens waited for again after coming back gets its own minute, not the last wait's`() {
        val fallback = LensFallback()
        val withFront = listOf(Lens.MAIN, Lens.FRONT)
        val mainSilent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        fallback.failed(1, withFront, listOf(Lens.MAIN), mainSilent)
        fallback.waitedFor(1, mainSilent)
        assertNull(fallback.retry(1, Lens.MAIN, 10_000)) // its minute from 10 s
        fallback.heardFrom(1, Lens.MAIN, 60_000, 60_100) // back at 60 s, no retry asked that tick
        val again = CameraFailure.Stalled(Lens.MAIN, 61_000, 61_000) // and stopped again
        fallback.failed(1, withFront, listOf(Lens.MAIN), again)
        assertEquals(listOf(Lens.MAIN), fallback.waitedFor(1, again))
        assertNull(fallback.retry(1, Lens.MAIN, 75_000)) // a new minute from here, not the old one's
    }

    @Test
    fun `the first lens tried again waits twice as long each time, half an hour at most, the others cut seldom`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        var now = 0L
        for (minutes in listOf(1L, 2L, 4L, 8L, 16L, 32L, 32L)) {
            val silent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
            fallback.failed(1, back, back, silent)
            fallback.waitedFor(1, silent)
            assertNull(fallback.retry(1, Lens.MAIN, now)) // the wait seen
            val due = now + minutes * 60_000
            assertNull(fallback.retry(1, Lens.MAIN, due - 1))
            assertEquals(Lens.MAIN, fallback.retry(1, Lens.MAIN, due))
            now = due + 1_000
        }
    }

    @Test
    fun `another lens back does not restart the first lens's wait`() {
        val fallback = LensFallback()
        fallback.settle(0) // opened again mid-race: both silent, none left out, both waited for
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val bothSilent = CameraFailure.NoFrame(listOf(Lens.MAIN, Lens.TELEPHOTO), 5_000)
        fallback.failed(1, back, back, bothSilent)
        assertEquals(back, fallback.waitedFor(1, bothSilent))
        assertNull(fallback.retry(1, Lens.MAIN, 5_000)) // its minute from 5 s
        fallback.heardFrom(1, Lens.TELEPHOTO, 55_000, 55_100) // the telephoto back at 55 s
        assertEquals(Lens.MAIN, fallback.retry(1, Lens.MAIN, 65_000)) // the first's minute still from 5 s
    }

    @Test
    fun `the first lens streaming a minute after its retries has them forgotten, its next wait a minute`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        var now = 0L
        for (minutes in listOf(1L, 2L)) { // two retries: the next would wait four minutes
            val silent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
            fallback.failed(1, back, back, silent)
            fallback.waitedFor(1, silent)
            fallback.retry(1, Lens.MAIN, now)
            now += minutes * 60_000
            assertEquals(Lens.MAIN, fallback.retry(1, Lens.MAIN, now))
        }
        val opened = listOf(Seen(Lens.MAIN, now + 900), Seen(Lens.TELEPHOTO, now + 900))
        assertNull(fallback.watch(2, opened, now, now + 1_000, Lens.MAIN)) // giving frames from 1 s
        val gap = listOf(Seen(Lens.MAIN, now + 900), Seen(Lens.TELEPHOTO, now + 5_000))
        val sputter = fallback.watch(2, gap, now, now + 5_000, Lens.MAIN)?.failure // its minute starts over
        assertEquals(Lens.MAIN, (sputter as? CameraFailure.Stalled)?.lens)
        val again = listOf(Seen(Lens.MAIN, now + 5_900), Seen(Lens.TELEPHOTO, now + 5_900))
        assertNull(fallback.watch(2, again, now, now + 6_000, Lens.MAIN)) // giving frames again from 6 s
        val streaming = listOf(Seen(Lens.MAIN, now + 65_900), Seen(Lens.TELEPHOTO, now + 65_900))
        assertNull(fallback.watch(2, streaming, now, now + 66_000, Lens.MAIN)) // a minute of frames since
        val silent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        fallback.failed(3, back, back, silent)
        fallback.waitedFor(3, silent)
        val later = now + 200_000
        assertNull(fallback.retry(3, Lens.MAIN, later))
        assertEquals(Lens.MAIN, fallback.retry(3, Lens.MAIN, later + 60_000)) // a minute again, not four
    }

    @Test
    fun `the first lens giving one frame a minute into its open keeps its retries, its next wait doubled`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        var now = 0L
        for (minutes in listOf(1L, 2L)) { // two retries: the next waits four minutes
            val silent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
            fallback.failed(1, back, back, silent)
            fallback.waitedFor(1, silent)
            fallback.retry(1, Lens.MAIN, now)
            now += minutes * 60_000
            assertEquals(Lens.MAIN, fallback.retry(1, Lens.MAIN, now))
        }
        val once = listOf(Seen(Lens.MAIN, now + 60_900), Seen(Lens.TELEPHOTO, now + 60_900)) // its first frame
        fallback.watch(2, once, now, now + 61_000, Lens.MAIN)
        val silent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        fallback.failed(3, back, back, silent)
        fallback.waitedFor(3, silent)
        val waited = now + 70_000
        assertNull(fallback.retry(3, Lens.MAIN, waited))
        assertNull(fallback.retry(3, Lens.MAIN, waited + 60_000)) // not a minute: one frame forgets nothing
        assertEquals(Lens.MAIN, fallback.retry(3, Lens.MAIN, waited + 240_000))
    }
}
