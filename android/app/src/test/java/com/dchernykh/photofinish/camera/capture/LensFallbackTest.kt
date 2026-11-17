package com.dchernykh.photofinish.camera.capture

import android.hardware.camera2.CameraDevice
import com.dchernykh.photofinish.camera.pairing.Lens
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
        assertEquals(Lens.FRONT, fallback.failed(1, four, error(1_500))) // the Xiaomi 17 Ultra's camera error 4
        assertNull(fallback.failed(1, four, error(1_510))) // the other camera's error is the same failure
        val stalled = CameraFailure.NoFrame(four - Lens.FRONT, 5_000) // no frame in 5 s
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, four - Lens.FRONT, stalled))
        assertEquals(Lens.ULTRAWIDE, fallback.failed(3, listOf(Lens.MAIN, Lens.ULTRAWIDE), error(0)))
        assertNull(fallback.failed(4, listOf(Lens.MAIN), error(1_000))) // the first lens streams on, tried again
        assertEquals(listOf(Lens.FRONT, Lens.TELEPHOTO, Lens.ULTRAWIDE), fallback.leftOut.toList())
    }

    @Test
    fun `a camera failing before its lenses started leaves none out, its service starting again perhaps`() {
        val fallback = LensFallback()
        assertNull(fallback.failed(1, four, error(null)))
        assertEquals(emptyList<Lens>(), fallback.failedAlone(2, listOf(Lens.FRONT), error(null)))
        assertEquals(emptySet<Lens>(), fallback.leftOut)
    }

    @Test
    fun `a lens that gave no frame goes before one that streams, the first lens kept`() {
        val fallback = LensFallback()
        val streamed = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.FRONT)
        assertEquals(Lens.TELEPHOTO, fallback.failed(1, streamed, CameraFailure.NoFrame(listOf(Lens.TELEPHOTO), 5_000)))
        // The first lens silent: the others' load lightened, from the last.
        assertEquals(
            Lens.FRONT,
            fallback.failed(2, streamed - Lens.TELEPHOTO, CameraFailure.NoFrame(listOf(Lens.MAIN), 5_000)),
        )
    }

    @Test
    fun `a session the camera said it runs and then could not leaves the last lens out`() {
        val fallback = LensFallback()
        assertEquals(Lens.FRONT, fallback.failed(1, four, CameraFailure.NotConfigured))
        assertEquals(
            listOf(Lens.TELEPHOTO),
            fallback.failedAlone(2, listOf(Lens.TELEPHOTO), CameraFailure.NotConfigured),
        )
    }

    @Test
    fun `the code's order says which lens goes`() {
        val fallback = LensFallback()
        assertEquals(Lens.MAIN, fallback.failed(1, listOf(Lens.FRONT, Lens.MAIN), error(2_000)))
    }

    @Test
    fun `cameras lost after streaming a while, taken by another app, or refused by its policy keep their lenses`() {
        val fallback = LensFallback()
        assertNull(fallback.failed(1, four, error(LensFallback.EARLY_MS)))
        assertNull(fallback.failed(2, four, null)) // another app took the camera
        val disabled = CameraFailure.Error(CameraDevice.StateCallback.ERROR_CAMERA_DISABLED, 1_000)
        assertNull(fallback.failed(3, four, disabled))
        // Too many cameras open: another app's as likely as ours, which the phone said it runs together.
        val many = CameraFailure.Error(CameraDevice.StateCallback.ERROR_MAX_CAMERAS_IN_USE, 1_000)
        assertNull(fallback.failed(5, four, many))
        assertEquals(emptyList<Lens>(), fallback.failedAlone(4, listOf(Lens.FRONT), error(60_000)))
        assertEquals(emptySet<Lens>(), fallback.leftOut)
    }

    @Test
    fun `the front failing alone early stays left out, the back failing in the same open costing nothing more`() {
        val fallback = LensFallback()
        assertEquals(listOf(Lens.FRONT), fallback.failedAlone(1, listOf(Lens.FRONT), error(1_500)))
        assertNull(fallback.failed(1, four - Lens.FRONT, error(1_510)))
        assertEquals(setOf(Lens.FRONT), fallback.leftOut)
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, four - Lens.FRONT, error(1_500))) // the next open's own
    }
}
