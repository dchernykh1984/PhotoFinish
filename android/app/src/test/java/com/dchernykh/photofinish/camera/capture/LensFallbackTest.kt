package com.dchernykh.photofinish.camera.capture

import android.hardware.camera2.CameraDevice
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.LensTarget
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LensFallbackTest {
    private val four = listOf(Lens.MAIN, Lens.ULTRAWIDE, Lens.TELEPHOTO, Lens.FRONT)

    private fun error(sinceStartMs: Long?) =
        CameraFailure.Error(CameraDevice.StateCallback.ERROR_CAMERA_DEVICE, sinceStartMs)

    @Test
    fun `cameras failing in their first seconds leave the last lens out, one an open, never the first`() {
        val fallback = LensFallback()
        assertEquals(Lens.FRONT, fallback.failed(1, four, four, error(1_500))) // the Xiaomi 17 Ultra's camera error 4
        assertNull(fallback.failed(1, four, four, error(1_510))) // the other camera's error is the same failure
        val stalled = CameraFailure.NoFrame(four - Lens.FRONT, 5_000) // no frame in 5 s
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, four - Lens.FRONT, four - Lens.FRONT, stalled))
        val two = listOf(Lens.MAIN, Lens.ULTRAWIDE)
        assertEquals(Lens.ULTRAWIDE, fallback.failed(3, two, two, error(0)))
        val main = listOf(Lens.MAIN)
        assertNull(fallback.failed(4, main, main, error(1_000))) // the first lens streams on, tried again
        assertEquals(listOf(Lens.FRONT, Lens.TELEPHOTO, Lens.ULTRAWIDE), fallback.leftOut.toList())
    }

    @Test
    fun `a camera failing before its lenses started leaves none out, its service starting again perhaps`() {
        val fallback = LensFallback()
        assertNull(fallback.failed(1, four, four, error(null)))
        assertNull(fallback.failedAlone(2, four, listOf(Lens.FRONT), error(null)))
        assertEquals(emptySet<Lens>(), fallback.leftOut)
    }

    @Test
    fun `a lens that gave no frame goes, never one that streams for it, the first kept and waited for`() {
        val fallback = LensFallback()
        val streamed = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.FRONT)
        assertEquals(
            Lens.TELEPHOTO,
            fallback.failed(1, streamed, streamed, CameraFailure.NoFrame(listOf(Lens.TELEPHOTO), 5_000)),
        )
        // The first lens silent, the front streaming: none left out for it, which could leave none streaming.
        val firstSilent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        assertNull(fallback.failed(2, streamed - Lens.TELEPHOTO, streamed - Lens.TELEPHOTO, firstSilent))
        assertEquals(false, fallback.madeAgain(2, firstSilent))
        assertEquals(listOf(Lens.MAIN), fallback.waitedFor(2, firstSilent))
        assertEquals(setOf(Lens.TELEPHOTO), fallback.leftOut)
    }

    @Test
    fun `a session the camera said it runs and then could not leaves the last lens out`() {
        val fallback = LensFallback()
        assertEquals(Lens.FRONT, fallback.failed(1, four, four, CameraFailure.NotConfigured))
        assertEquals(
            Lens.TELEPHOTO,
            fallback.failedAlone(2, four, listOf(Lens.TELEPHOTO), CameraFailure.NotConfigured),
        )
    }

    @Test
    fun `the lenses left out are kept while the same are asked at the same format, the screen back from another app`() {
        val fullHd = StreamFormat(Resolution(1920, 1080), 60, FpsRange(60, 60), 16_000_000)
        val targets = four.map { LensTarget(it, RtmpAddress("10.0.0.5", 1935, "live", it.code)) }
        val fallback = LensFallback()
        fallback.start(fullHd, targets)
        fallback.failed(1, four, four, error(1_500))
        fallback.start(fullHd, targets) // the preview's surface made again
        assertEquals(setOf(Lens.FRONT), fallback.leftOut)
        fallback.start(fullHd, emptyList()) // the referee stopped: the preview alone
        fallback.start(fullHd, targets) // and started again: every lens tried
        assertEquals(emptySet<Lens>(), fallback.leftOut)
        fallback.failed(2, four, four, error(1_500))
        fallback.start(fullHd.copy(fps = 30, range = FpsRange(30, 30)), targets) // another rate chosen
        assertEquals(emptySet<Lens>(), fallback.leftOut)
    }

    @Test
    fun `a lens of the camera that failed goes before another camera's, the others' when it streams the first alone`() {
        val fallback = LensFallback()
        val streamed = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.FRONT)
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        assertEquals(Lens.TELEPHOTO, fallback.failed(1, streamed, back, error(1_500))) // the front streams on
        assertEquals(Lens.FRONT, fallback.failed(2, listOf(Lens.MAIN, Lens.FRONT), listOf(Lens.MAIN), error(1_500)))
    }

    @Test
    fun `a session the camera could not make, no lens left out, is said, not made again to fail the same way`() {
        val fallback = LensFallback()
        val main = listOf(Lens.MAIN)
        fallback.failed(1, main, main, CameraFailure.NotConfigured)
        assertEquals(false, fallback.madeAgain(1, CameraFailure.NotConfigured))
        val streamed = listOf(Lens.MAIN, Lens.TELEPHOTO)
        fallback.failed(2, streamed, streamed, CameraFailure.NotConfigured)
        assertEquals(true, fallback.madeAgain(2, CameraFailure.NotConfigured))
        // Settled, the lenses ran together: a session not made now is the camera service settling, made again.
        fallback.settle(0)
        fallback.failed(4, streamed, streamed, CameraFailure.NotConfigured)
        assertEquals(true, fallback.madeAgain(4, CameraFailure.NotConfigured))
        assertEquals(true, fallback.madeAgain(5, error(1_500))) // a camera lost: opened again, as ever
        assertEquals(true, fallback.madeAgain(6, null))
    }

    @Test
    fun `a lens that gave no frame with none to leave out, or once they ran together, is waited for, not made again`() {
        val fallback = LensFallback()
        val stalled = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        fallback.failed(1, listOf(Lens.MAIN), listOf(Lens.MAIN), stalled)
        assertEquals(false, fallback.madeAgain(1, stalled))
        val two = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val telephoto = CameraFailure.NoFrame(listOf(Lens.TELEPHOTO), 5_000)
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, two, two, telephoto))
        assertEquals(true, fallback.madeAgain(2, telephoto)) // one left out: made again without it
        fallback.settle(0) // they ran together: one silent after a reopen mid-race is waited for, the other on
        assertNull(fallback.failed(3, two, two, telephoto))
        assertEquals(false, fallback.madeAgain(3, telephoto)) // not the main cut every 7 s for as long
    }

    @Test
    fun `the back camera stalled, the front left out first in the same open, is made again without it`() {
        val fallback = LensFallback()
        fallback.failedAlone(1, four, listOf(Lens.FRONT), CameraFailure.NoFrame(listOf(Lens.FRONT), 5_000))
        val back = listOf(Lens.MAIN, Lens.ULTRAWIDE, Lens.TELEPHOTO)
        val stalled = CameraFailure.NoFrame(back, 5_000)
        assertNull(fallback.failed(1, back, back, stalled)) // the open paid already
        assertEquals(true, fallback.madeAgain(1, stalled)) // but its lenses are not the same: tried again
    }

    @Test
    fun `lenses that streamed a while keep their place, whatever fails or closes the cameras after`() {
        val fallback = LensFallback()
        assertEquals(Lens.FRONT, fallback.failed(1, four, four, error(1_500))) // before: the lenses' doing
        fallback.settle(0) // every lens's frames for 10 s
        assertNull(fallback.failed(2, four - Lens.FRONT, four - Lens.FRONT, error(3_600_000))) // the service again
        assertNull(fallback.failed(3, four - Lens.FRONT, four - Lens.FRONT, error(2_000))) // the open after, settling
        assertNull(fallback.failed(4, four - Lens.FRONT, four - Lens.FRONT, CameraFailure.Taken)) // a call
        assertNull(fallback.failedAlone(5, four - Lens.FRONT, listOf(Lens.TELEPHOTO), error(2_000))) // screen back
        assertEquals(setOf(Lens.FRONT), fallback.leftOut)
    }

    @Test
    fun `the other camera failing alone leaves one lens out, the one that gave no frame before one that did`() {
        val fallback = LensFallback()
        val other = listOf(Lens.MAIN, Lens.TELEPHOTO) // the back beside the front, the code's first
        val streamed = listOf(Lens.FRONT) + other
        assertEquals(
            Lens.MAIN,
            fallback.failedAlone(1, streamed, other, CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)),
        )
        assertEquals(setOf(Lens.MAIN), fallback.leftOut) // the telephoto, which streamed, tried again
    }

    @Test
    fun `the other camera's silent lens with none to leave out is waited for, not closed for the race`() {
        val streamed = listOf(Lens.MAIN, Lens.FRONT)
        val stalled = CameraFailure.NoFrame(listOf(Lens.FRONT), 5_000)
        val fallback = LensFallback()
        fallback.settle(0) // they ran together; opened again mid-race, the front slow to its first frame
        assertNull(fallback.failedAlone(1, streamed, listOf(Lens.FRONT), stalled))
        assertEquals(listOf(Lens.FRONT), fallback.waitedFor(1, stalled))
        assertEquals(emptyList<Lens>(), fallback.waitedFor(1, error(1_500))) // an error: closed alone, as ever
        val first = LensFallback() // the front the only lens streamed: none to leave out
        assertNull(first.failedAlone(1, listOf(Lens.FRONT), listOf(Lens.FRONT), stalled))
        assertEquals(listOf(Lens.FRONT), first.waitedFor(1, stalled))
        val early = LensFallback() // before they ran together: left out, not waited for
        assertEquals(Lens.FRONT, early.failedAlone(1, streamed, listOf(Lens.FRONT), stalled))
        assertEquals(emptyList<Lens>(), early.waitedFor(1, stalled))
    }

    @Test
    fun `the other camera failing alone never leaves out the first lens streamed, nor a lens streamed alone`() {
        val fallback = LensFallback()
        // The first camera's encoders would not start: the other camera streams the only lens.
        assertNull(fallback.failedAlone(1, listOf(Lens.TELEPHOTO), listOf(Lens.TELEPHOTO), error(1_500)))
        val streamed = listOf(Lens.TELEPHOTO, Lens.FRONT)
        assertEquals(Lens.FRONT, fallback.failedAlone(2, streamed, streamed, error(1_500))) // never the first
        assertEquals(setOf(Lens.FRONT), fallback.leftOut)
    }

    @Test
    fun `a lens waited for is told apart until the referee starts again, the others settling without it`() {
        val fullHd = StreamFormat(Resolution(1920, 1080), 60, FpsRange(60, 60), 16_000_000)
        val two = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val targets = two.map { LensTarget(it, RtmpAddress("10.0.0.5", 1935, "live", it.code)) }
        val fallback = LensFallback()
        fallback.start(fullHd, targets)
        val firstSilent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        assertNull(fallback.failed(1, two, two, firstSilent)) // none left out for the first
        assertEquals(false, fallback.waitsFor(1, Lens.MAIN))
        assertEquals(listOf(Lens.MAIN), fallback.waitedFor(1, firstSilent))
        assertEquals(true, fallback.waitsFor(1, Lens.MAIN)) // the telephoto settles without it
        assertEquals(false, fallback.waitsFor(1, Lens.TELEPHOTO))
        assertEquals(false, fallback.waitsFor(2, Lens.MAIN)) // the next open watches it anew
        fallback.start(fullHd, emptyList()) // the referee stopped: every lens tried again
        assertEquals(false, fallback.waitsFor(1, Lens.MAIN))
    }

    @Test
    fun `a camera failing beside the first lens waited for leaves out none that streams, not leaving none streaming`() {
        val fallback = LensFallback()
        val two = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val firstSilent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        assertNull(fallback.failed(1, two, two, firstSilent))
        fallback.waitedFor(1, firstSilent)
        assertNull(fallback.failed(1, two, two, error(7_000))) // the telephoto, streaming, kept
        assertEquals(true, fallback.madeAgain(1, error(7_000))) // both made again
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, two, two, error(1_500))) // none waited for in the next yet
    }

    @Test
    fun `the code's order says which lens goes`() {
        val fallback = LensFallback()
        val frontFirst = listOf(Lens.FRONT, Lens.MAIN)
        assertEquals(Lens.MAIN, fallback.failed(1, frontFirst, frontFirst, error(2_000)))
    }

    @Test
    fun `cameras lost after streaming a while, taken by another app, or refused by its policy keep their lenses`() {
        val fallback = LensFallback()
        assertNull(fallback.failed(1, four, four, error(LensFallback.EARLY_MS)))
        assertNull(fallback.failed(2, four, four, CameraFailure.Taken)) // another app took the camera
        assertNull(fallback.failed(6, four, four, null)) // the cameras would not open
        val disabled = CameraFailure.Error(CameraDevice.StateCallback.ERROR_CAMERA_DISABLED, 1_000)
        assertNull(fallback.failed(3, four, four, disabled))
        // Too many cameras open: another app's as likely as ours, which the phone said it runs together.
        val many = CameraFailure.Error(CameraDevice.StateCallback.ERROR_MAX_CAMERAS_IN_USE, 1_000)
        assertNull(fallback.failed(5, four, four, many))
        assertNull(fallback.failedAlone(4, four, listOf(Lens.FRONT), error(60_000)))
        assertEquals(emptySet<Lens>(), fallback.leftOut)
    }

    @Test
    fun `the front failing alone early stays left out, the back failing in the same open costing nothing more`() {
        val fallback = LensFallback()
        assertEquals(Lens.FRONT, fallback.failedAlone(1, four, listOf(Lens.FRONT), error(1_500)))
        assertNull(fallback.failed(1, four - Lens.FRONT, four - Lens.FRONT, error(1_510)))
        assertEquals(setOf(Lens.FRONT), fallback.leftOut)
        val back = four - Lens.FRONT
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, back, back, error(1_500))) // the next open's own
    }

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
        assertEquals(listOf(Lens.FRONT), fallback.waitedFor(1, front)) // waited for, as the other camera's
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
        assertNull(fallback.retry(2, Lens.MAIN, 231_000) { 0 }) // the wait seen: its minute starts
        assertNull(fallback.retry(2, Lens.MAIN, 231_000 + LensFallback.AGAIN_MS - 1) { 0 }) // not yet
        assertEquals(Lens.MAIN, fallback.retry(2, Lens.MAIN, 231_000 + LensFallback.AGAIN_MS) { 0 })
        assertEquals(false, fallback.waitsFor(2, Lens.MAIN))
        assertNull(fallback.retry(2, Lens.MAIN, 400_000) { 0 }) // once a wait
        val soon = CameraFailure.Stalled(Lens.MAIN, 4_000, 300_000) // stopping soon after it was tried again
        assertNull(fallback.failed(3, withFront, listOf(Lens.MAIN), soon))
        assertEquals(false, fallback.madeAgain(3, soon)) // waited for again, the front on
    }

    @Test
    fun `the other camera's lens stopping later is waited for, not closed for the open, the first camera not cut`() {
        val fallback = LensFallback()
        fallback.settle(0)
        val streamed = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.FRONT)
        val front = CameraFailure.Stalled(Lens.FRONT, 30_000, 100_000)
        assertNull(fallback.failedAlone(1, streamed, listOf(Lens.FRONT), front))
        assertEquals(listOf(Lens.FRONT), fallback.waitedFor(1, front)) // a pause may pass
        val again = CameraFailure.Stalled(Lens.FRONT, 5_000, 140_000) // stopping again within a minute
        assertEquals(Lens.FRONT, fallback.failedAlone(2, streamed, listOf(Lens.FRONT), again))
        assertEquals(emptyList<Lens>(), fallback.waitedFor(2, again)) // left out: closed
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
        assertNull(fallback.retry(1, Lens.MAIN, 10_000) { 0 })
        // Frames kept unsent -- a network slow -- put it off, a reopen dropping them: 30 s at most, not for good.
        val kept = { LensFallback.KEPT_MS }
        val due = 10_000 + LensFallback.AGAIN_MS
        assertNull(fallback.retry(1, Lens.MAIN, due, kept))
        assertNull(fallback.retry(1, Lens.MAIN, due + LensFallback.KEPT_WAIT_MS - 1, kept))
        assertEquals(Lens.MAIN, fallback.retry(1, Lens.MAIN, due + LensFallback.KEPT_WAIT_MS, kept))
        val teleSilent = CameraFailure.NoFrame(listOf(Lens.TELEPHOTO), 5_000)
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, back, back, teleSilent)) // early: left out, not waited for
        val third = LensFallback()
        third.settle(0)
        third.failed(1, back, back, teleSilent)
        assertEquals(listOf(Lens.TELEPHOTO), third.waitedFor(1, teleSilent))
        assertNull(third.retry(1, Lens.MAIN, 10_000) { 0 })
        assertNull(third.retry(1, Lens.MAIN, 10_000 + LensFallback.AGAIN_MS) { 0 }) // not the first's: none
    }

    @Test
    fun `the watch tells a lens silent 5 s after the start, then a lens that stopped, one waited for no news`() {
        val fallback = LensFallback()
        val tele = Seen(Lens.TELEPHOTO, 0)
        assertNull(fallback.watch(1, listOf(Seen(Lens.MAIN, 4_000), tele), 0, 4_999, { 0 }, Lens.MAIN)) // not yet
        val silent = fallback.watch(1, listOf(Seen(Lens.MAIN, 4_000), tele), 0, 5_000, { 0 }, Lens.MAIN)
        assertEquals(CameraFailure.NoFrame(listOf(Lens.TELEPHOTO), 5_000), silent?.failure)
        assertEquals("the camera gave telephoto no frame in 5 s", silent?.reason)
        fallback.waitedFor(1, silent?.failure) // none to leave out: waited for
        assertNull(fallback.watch(1, listOf(Seen(Lens.MAIN, 5_500), tele), 0, 6_000, { 0 }, Lens.MAIN))
        val stopped = fallback.watch(1, listOf(Seen(Lens.MAIN, 6_000), tele), 0, 9_500, { 0 }, Lens.MAIN)
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
        assertNull(fallback.watch(1, seen, 0, 5_000, { 0 }, Lens.MAIN)) // the wait seen: its minute starts
        assertNull(fallback.watch(1, seen, 0, 65_000, { 0 }, null)) // the other camera's watch tries none
        val retried = fallback.watch(1, seen, 0, 65_000, { 0 }, Lens.MAIN)
        assertEquals(null, retried?.failure)
        assertEquals("main waited for 60 s: tried again", retried?.reason) // silent from the start, not stopped
    }

    @Test
    fun `a camera stopping every lens at once is told by its last lens, not its first`() {
        val fallback = LensFallback()
        val seen = listOf(Seen(Lens.MAIN, 6_000), Seen(Lens.TELEPHOTO, 6_000))
        val stopped = fallback.watch(1, seen, 0, 9_500, { 0 }, Lens.MAIN)
        assertEquals(CameraFailure.Stalled(Lens.TELEPHOTO, 6_000, 6_000), stopped?.failure)
    }

    @Test
    fun `a stop waits for the frames kept to be sent, 30 s after its last frame at most`() {
        val fallback = LensFallback()
        val seen = listOf(Seen(Lens.MAIN, 6_000), Seen(Lens.TELEPHOTO, 6_000))
        val kept = { LensFallback.KEPT_MS } // a Wi-Fi slow or gone: a reopen would drop them
        assertNull(fallback.watch(1, seen, 0, 9_500, kept, Lens.MAIN))
        assertNull(fallback.watch(1, seen, 0, 6_000 + LensFallback.KEPT_WAIT_MS - 1, kept, Lens.MAIN))
        val late = fallback.watch(1, seen, 0, 6_000 + LensFallback.KEPT_WAIT_MS, kept, Lens.MAIN)
        assertEquals(CameraFailure.Stalled(Lens.TELEPHOTO, 6_000, 6_000), late?.failure) // not silent for good
        assertEquals("the camera gave telephoto no frame for 30 s", late?.reason) // as long as it was
        var asked = 0L
        assertNull(fallback.watch(1, listOf(Seen(Lens.MAIN, 9_000)), 0, 9_500, { asked++ }, Lens.MAIN))
        assertEquals(0L, asked) // nothing stopped, no retry due: the stores not asked
    }

    @Test
    fun `a lens failing as the first lens's retry falls due is told first, the retry the tick after`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val mainSilent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        fallback.failed(1, back, back, mainSilent)
        fallback.waitedFor(1, mainSilent)
        val streaming = listOf(Seen(Lens.MAIN, 0), Seen(Lens.TELEPHOTO, 5_900))
        assertNull(fallback.watch(1, streaming, 0, 6_000, { 0 }, Lens.MAIN)) // the wait seen: its minute starts
        val both = listOf(Seen(Lens.MAIN, 0), Seen(Lens.TELEPHOTO, 9_000)) // the telephoto stopped at 9 s
        val told = fallback.watch(1, both, 0, 66_000, { 0 }, Lens.MAIN)
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
    fun `no retry while a stop is put off for the frames kept, the stop not passed by uncounted`() {
        val fallback = LensFallback()
        val back = listOf(Lens.MAIN, Lens.TELEPHOTO)
        val mainSilent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        fallback.failed(1, back, back, mainSilent)
        fallback.waitedFor(1, mainSilent)
        val streaming = listOf(Seen(Lens.MAIN, 0), Seen(Lens.TELEPHOTO, 5_900))
        assertNull(fallback.watch(1, streaming, 0, 6_000, { 0 }, Lens.MAIN)) // the wait seen: its minute starts
        val seen = listOf(Seen(Lens.MAIN, 0), Seen(Lens.TELEPHOTO, 90_000)) // the telephoto stopped at 90 s
        val kept = { LensFallback.KEPT_MS } // a slow Wi-Fi: its stop put off, the retry due past its 30 s
        assertNull(fallback.watch(1, seen, 0, 100_000, kept, Lens.MAIN)) // neither, the stop pending
        assertEquals(true, fallback.waitsFor(1, Lens.MAIN)) // the retry not spent
        val stop = fallback.watch(1, seen, 0, 90_000 + LensFallback.KEPT_WAIT_MS, kept, Lens.MAIN)
        assertEquals(CameraFailure.Stalled(Lens.TELEPHOTO, 90_000, 90_000), stop?.failure) // counted
    }

    @Test
    fun `the other camera's lens stopping in an open that left a lens out is closed, no wait kept for it`() {
        val fallback = LensFallback()
        val streamed = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.FRONT)
        assertEquals(Lens.TELEPHOTO, fallback.failed(1, streamed, streamed - Lens.FRONT, error(1_500))) // paid
        val front = CameraFailure.Stalled(Lens.FRONT, 30_000, 100_000)
        assertNull(fallback.failedAlone(1, streamed, listOf(Lens.FRONT), front))
        assertEquals(emptyList<Lens>(), fallback.waitedFor(1, front)) // closed alone
        assertEquals(true, fallback.madeAgain(2, front)) // no stale wait left for it
    }

    @Test
    fun `a stop is put off 30 s from the oldest stop, a lens stopping later putting none off further`() {
        val fallback = LensFallback()
        val seen = listOf(Seen(Lens.MAIN, 10_000), Seen(Lens.TELEPHOTO, 30_000)) // main stopped first
        val kept = { LensFallback.KEPT_MS }
        val due = fallback.watch(1, seen, 0, 10_000 + LensFallback.KEPT_WAIT_MS, kept, Lens.MAIN)
        assertEquals(CameraFailure.Stalled(Lens.TELEPHOTO, 30_000, 30_000), due?.failure) // 30 s after main's
    }

    @Test
    fun `the first lens waited for again after coming back gets its own minute, not the last wait's`() {
        val fallback = LensFallback()
        val withFront = listOf(Lens.MAIN, Lens.FRONT)
        val mainSilent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        fallback.failed(1, withFront, listOf(Lens.MAIN), mainSilent)
        fallback.waitedFor(1, mainSilent)
        assertNull(fallback.retry(1, Lens.MAIN, 10_000) { 0 }) // its minute from 10 s
        fallback.heardFrom(1, Lens.MAIN, 60_000, 60_100) // back at 60 s, no retry asked that tick
        val again = CameraFailure.Stalled(Lens.MAIN, 61_000, 61_000) // and stopped again
        fallback.failed(1, withFront, listOf(Lens.MAIN), again)
        assertEquals(listOf(Lens.MAIN), fallback.waitedFor(1, again))
        assertNull(fallback.retry(1, Lens.MAIN, 75_000) { 0 }) // a new minute from here, not the old one's
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
            assertNull(fallback.retry(1, Lens.MAIN, now) { 0 }) // the wait seen
            val due = now + minutes * 60_000
            assertNull(fallback.retry(1, Lens.MAIN, due - 1) { 0 })
            assertEquals(Lens.MAIN, fallback.retry(1, Lens.MAIN, due) { 0 })
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
        assertNull(fallback.retry(1, Lens.MAIN, 5_000) { 0 }) // its minute from 5 s
        fallback.heardFrom(1, Lens.TELEPHOTO, 55_000, 55_100) // the telephoto back at 55 s
        assertEquals(Lens.MAIN, fallback.retry(1, Lens.MAIN, 65_000) { 0 }) // the first's minute still from 5 s
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
            fallback.retry(1, Lens.MAIN, now) { 0 }
            now += minutes * 60_000
            assertEquals(Lens.MAIN, fallback.retry(1, Lens.MAIN, now) { 0 })
        }
        val streaming = listOf(Seen(Lens.MAIN, now + 59_900), Seen(Lens.TELEPHOTO, now + 59_900))
        assertNull(fallback.watch(2, streaming, now, now + 60_000, { 0 }, Lens.MAIN)) // a minute of frames
        val silent = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        fallback.failed(3, back, back, silent)
        fallback.waitedFor(3, silent)
        val later = now + 200_000
        assertNull(fallback.retry(3, Lens.MAIN, later) { 0 })
        assertEquals(Lens.MAIN, fallback.retry(3, Lens.MAIN, later + 60_000) { 0 }) // a minute again, not four
    }
}
