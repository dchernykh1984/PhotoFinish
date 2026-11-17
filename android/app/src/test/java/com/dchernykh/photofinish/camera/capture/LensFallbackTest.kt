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
        assertEquals(emptyList<Lens>(), fallback.failedAlone(2, listOf(Lens.FRONT), error(null)))
        assertEquals(emptySet<Lens>(), fallback.leftOut)
    }

    @Test
    fun `a lens that gave no frame goes before one that streams, the first lens kept`() {
        val fallback = LensFallback()
        val streamed = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.FRONT)
        assertEquals(
            Lens.TELEPHOTO,
            fallback.failed(1, streamed, streamed, CameraFailure.NoFrame(listOf(Lens.TELEPHOTO), 5_000)),
        )
        // The first lens silent: the others' load lightened, from the last.
        assertEquals(
            Lens.FRONT,
            fallback.failed(
                2,
                streamed - Lens.TELEPHOTO,
                streamed - Lens.TELEPHOTO,
                CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000),
            ),
        )
    }

    @Test
    fun `a session the camera said it runs and then could not leaves the last lens out`() {
        val fallback = LensFallback()
        assertEquals(Lens.FRONT, fallback.failed(1, four, four, CameraFailure.NotConfigured))
        assertEquals(
            listOf(Lens.TELEPHOTO),
            fallback.failedAlone(2, listOf(Lens.TELEPHOTO), CameraFailure.NotConfigured),
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
        // Settled, a session that cannot be made leaves none out: said, not made again for ever.
        fallback.settle()
        fallback.failed(4, streamed, streamed, CameraFailure.NotConfigured)
        assertEquals(false, fallback.madeAgain(4, CameraFailure.NotConfigured))
        assertEquals(true, fallback.madeAgain(5, error(1_500))) // a camera lost: opened again, as ever
        assertEquals(true, fallback.madeAgain(6, null))
    }

    @Test
    fun `a lens that gave no frame with none to leave out is waited for, not the camera made again every 7 s`() {
        val fallback = LensFallback()
        val stalled = CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)
        fallback.failed(1, listOf(Lens.MAIN), listOf(Lens.MAIN), stalled)
        assertEquals(false, fallback.madeAgain(1, stalled))
        val two = listOf(Lens.MAIN, Lens.TELEPHOTO)
        fallback.failed(2, two, two, stalled)
        assertEquals(true, fallback.madeAgain(2, stalled))
    }

    @Test
    fun `the back camera stalled, the front left out first in the same open, is made again without it`() {
        val fallback = LensFallback()
        fallback.failedAlone(1, listOf(Lens.FRONT), CameraFailure.NoFrame(listOf(Lens.FRONT), 5_000))
        val back = listOf(Lens.MAIN, Lens.ULTRAWIDE, Lens.TELEPHOTO)
        val stalled = CameraFailure.NoFrame(back, 5_000)
        assertNull(fallback.failed(1, back, back, stalled)) // the open paid already
        assertEquals(true, fallback.madeAgain(1, stalled)) // but its lenses are not the same: tried again
    }

    @Test
    fun `lenses that streamed a while keep their place, whatever fails or closes the cameras after`() {
        val fallback = LensFallback()
        assertEquals(Lens.FRONT, fallback.failed(1, four, four, error(1_500))) // before: the lenses' doing
        fallback.settle() // every lens's frames for 10 s
        assertNull(fallback.failed(2, four - Lens.FRONT, four - Lens.FRONT, error(3_600_000))) // the service again
        assertNull(fallback.failed(3, four - Lens.FRONT, four - Lens.FRONT, error(2_000))) // the open after, settling
        assertNull(fallback.failed(4, four - Lens.FRONT, four - Lens.FRONT, CameraFailure.Taken(1_000))) // a call
        assertEquals(emptyList<Lens>(), fallback.failedAlone(5, listOf(Lens.TELEPHOTO), error(2_000))) // screen back
        assertEquals(setOf(Lens.FRONT), fallback.leftOut)
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
        assertNull(fallback.failed(2, four, four, CameraFailure.Taken(1_000))) // another app took the camera
        assertNull(fallback.failed(6, four, four, null)) // the cameras would not open
        val disabled = CameraFailure.Error(CameraDevice.StateCallback.ERROR_CAMERA_DISABLED, 1_000)
        assertNull(fallback.failed(3, four, four, disabled))
        // Too many cameras open: another app's as likely as ours, which the phone said it runs together.
        val many = CameraFailure.Error(CameraDevice.StateCallback.ERROR_MAX_CAMERAS_IN_USE, 1_000)
        assertNull(fallback.failed(5, four, four, many))
        assertEquals(emptyList<Lens>(), fallback.failedAlone(4, listOf(Lens.FRONT), error(60_000)))
        assertEquals(emptySet<Lens>(), fallback.leftOut)
    }

    @Test
    fun `the front failing alone early stays left out, the back failing in the same open costing nothing more`() {
        val fallback = LensFallback()
        assertEquals(listOf(Lens.FRONT), fallback.failedAlone(1, listOf(Lens.FRONT), error(1_500)))
        assertNull(fallback.failed(1, four - Lens.FRONT, four - Lens.FRONT, error(1_510)))
        assertEquals(setOf(Lens.FRONT), fallback.leftOut)
        val back = four - Lens.FRONT
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, back, back, error(1_500))) // the next open's own
    }
}
