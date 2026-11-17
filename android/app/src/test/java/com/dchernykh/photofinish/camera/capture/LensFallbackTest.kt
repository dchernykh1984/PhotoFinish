package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LensFallbackTest {
    private val four = listOf(Lens.MAIN, Lens.ULTRAWIDE, Lens.TELEPHOTO, Lens.FRONT)

    @Test
    fun `cameras failing in their first seconds leave the last lens out, one an open, never the first`() {
        val fallback = LensFallback()
        assertEquals(Lens.FRONT, fallback.failed(1, four, 1_500)) // the Xiaomi 17 Ultra's camera error 4
        assertNull(fallback.failed(1, four, 1_510)) // the other camera's error is the same failure
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, four - Lens.FRONT, 5_000)) // no frame in 5 s
        assertEquals(Lens.ULTRAWIDE, fallback.failed(3, listOf(Lens.MAIN, Lens.ULTRAWIDE), 0))
        assertNull(fallback.failed(4, listOf(Lens.MAIN), 1_000)) // the first lens streams on, tried again
        assertEquals(listOf(Lens.FRONT, Lens.TELEPHOTO, Lens.ULTRAWIDE), fallback.leftOut.toList())
    }

    @Test
    fun `the code's order says which lens goes`() {
        val fallback = LensFallback()
        assertEquals(Lens.MAIN, fallback.failed(1, listOf(Lens.FRONT, Lens.MAIN), 2_000))
    }

    @Test
    fun `cameras lost after streaming a while are opened again with all their lenses`() {
        val fallback = LensFallback()
        assertNull(fallback.failed(1, four, LensFallback.EARLY_MS))
        fallback.failedAlone(1, listOf(Lens.FRONT), 60_000)
        assertEquals(emptySet<Lens>(), fallback.leftOut)
    }

    @Test
    fun `the front failing alone early stays left out, the back failing in the same open costing nothing more`() {
        val fallback = LensFallback()
        fallback.failedAlone(1, listOf(Lens.FRONT), 1_500)
        assertNull(fallback.failed(1, four - Lens.FRONT, 1_510))
        assertEquals(setOf(Lens.FRONT), fallback.leftOut)
        assertEquals(Lens.TELEPHOTO, fallback.failed(2, four - Lens.FRONT, 1_500)) // the next open's own
    }
}
