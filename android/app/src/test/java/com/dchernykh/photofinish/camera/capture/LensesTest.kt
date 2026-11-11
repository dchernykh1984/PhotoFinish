package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.LensTarget
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import org.junit.Assert.assertEquals
import org.junit.Test

class LensesTest {
    // A phone like the Xiaomi 15 Ultra: a logical back camera of four, and a front camera.
    private val back = LensInfo("0", null, 23.0)
    private val wide = LensInfo("0", "2", 14.0)
    private val main = LensInfo("0", "3", 23.4)
    private val tele = LensInfo("0", "4", 70.0)
    private val periscope = LensInfo("0", "5", 100.0)
    private val front = LensInfo("1", null, 21.0)
    private val lenses = LensChoice.classify(back, listOf(wide, main, tele, periscope), front)
    private val anyTogether: (Set<String>) -> Boolean = { true }

    private fun target(
        lens: Lens,
        port: Int,
    ) = LensTarget(lens, RtmpAddress("10.0.0.5", port, "live", "cam$port"))

    @Test
    fun `the lenses are told apart by their focal lengths`() {
        assertEquals(
            mapOf(Lens.MAIN to main, Lens.ULTRAWIDE to wide, Lens.TELEPHOTO to periscope, Lens.FRONT to front),
            lenses,
        )
    }

    @Test
    fun `a back camera of one lens is the main one, and lenses close to it are neither wide nor tele`() {
        assertEquals(mapOf(Lens.MAIN to back), LensChoice.classify(back, emptyList(), null))
        val near = listOf(LensInfo("0", "2", 19.0), main, LensInfo("0", "4", 34.0))
        assertEquals(mapOf(Lens.MAIN to main), LensChoice.classify(back, near, null))
        assertEquals(mapOf(Lens.FRONT to front), LensChoice.classify(null, emptyList(), front))
    }

    @Test
    fun `the main lens alone is the camera's own picture, as before`() {
        val plan = SessionPlan.plan(listOf(target(Lens.MAIN, 1935)), lenses, anyTogether, physicalStreams = true)
        assertEquals(listOf(PlannedCamera("0", listOf(PlannedLens(target(Lens.MAIN, 1935), main, null)))), plan.cameras)
    }

    @Test
    fun `lenses of one camera share its session, each named by its physical camera`() {
        val asked = listOf(target(Lens.TELEPHOTO, 1935), target(Lens.MAIN, 1936), target(Lens.FRONT, 1937))
        val plan = SessionPlan.plan(asked, lenses, anyTogether, physicalStreams = true)
        assertEquals(
            listOf(
                PlannedCamera(
                    "0",
                    listOf(PlannedLens(asked[0], periscope, "5"), PlannedLens(asked[1], main, "3")),
                ),
                PlannedCamera("1", listOf(PlannedLens(asked[2], front, null))),
            ),
            plan.cameras,
        )
        assertEquals(emptyMap<Lens, LeftOut>(), plan.left)
    }

    @Test
    fun `a telephoto alone is its physical camera`() {
        val plan = SessionPlan.plan(listOf(target(Lens.TELEPHOTO, 1935)), lenses, anyTogether, physicalStreams = true)
        assertEquals(
            "5",
            plan.cameras
                .single()
                .lenses
                .single()
                .physicalId,
        )
    }

    @Test
    fun `a lens the phone lacks, or a camera it cannot run beside the first, is left out`() {
        val plain = LensChoice.classify(back, emptyList(), front)
        val asked = listOf(target(Lens.FRONT, 1935), target(Lens.TELEPHOTO, 1936), target(Lens.MAIN, 1937))
        val plan = SessionPlan.plan(asked, plain, { it.size < 2 }, physicalStreams = true)
        assertEquals(listOf(PlannedCamera("1", listOf(PlannedLens(asked[0], front, null)))), plan.cameras)
        assertEquals(
            mapOf(Lens.TELEPHOTO to LeftOut.NOT_ON_THIS_PHONE, Lens.MAIN to LeftOut.NOT_WITH_THE_OTHERS),
            plan.left,
        )
    }

    @Test
    fun `a phone that names no physical camera streams each camera's own picture alone`() {
        val asked = listOf(target(Lens.TELEPHOTO, 1935), target(Lens.MAIN, 1936), target(Lens.ULTRAWIDE, 1937))
        val plan = SessionPlan.plan(asked, lenses, anyTogether, physicalStreams = false)
        assertEquals(listOf(PlannedCamera("0", listOf(PlannedLens(asked[1], main, null)))), plan.cameras)
        assertEquals(
            mapOf(Lens.TELEPHOTO to LeftOut.NOT_ON_THIS_PHONE, Lens.ULTRAWIDE to LeftOut.NOT_ON_THIS_PHONE),
            plan.left,
        )
    }

    @Test
    fun `the preview goes to the first camera that starts`() {
        val given = mutableListOf<Pair<String, Boolean>>()
        startInTurn(listOf("front", "back", "other")) { camera, preview ->
            given += camera to preview
            camera != "front" // no size in common with the format chosen
        }
        assertEquals(listOf("front" to true, "back" to true, "other" to false), given)
    }

    @Test
    fun `the preview is said shown only when its session has room for it`() {
        assertEquals(StreamerStatus.Previewing, previewStatus("preview", listOf("lens", "preview")))
        assertEquals(StreamerStatus.Failed(NO_PREVIEW), previewStatus("preview", listOf("lens")))
        assertEquals(null, previewStatus(null, listOf("lens")))
    }

    @Test
    fun `a camera's focal length is the one nearest a main lens's, as 35 mm-equivalent`() {
        // A logical camera listing its lenses', the ultra-wide's first, on a 9.8 mm sensor.
        assertEquals(30.5, LensChoice.equivalentFocal(listOf(2.2, 6.9, 15.0), 9.8), 0.1)
        assertEquals(66.2, LensChoice.equivalentFocal(listOf(15.0), 9.8), 0.1) // one: its own
        assertEquals(24.0, LensChoice.equivalentFocal(listOf(24.0), 0.0), 0.0) // no sensor size
        assertEquals(0.0, LensChoice.equivalentFocal(emptyList(), 9.8), 0.0)
    }

    @Test
    fun `a session drops the preview first, then lenses from the last, until one is supported`() {
        val options = { lenses: List<String> -> listOf(lenses + "preview", lenses) }
        val lenses = listOf("main", "wide", "tele")
        val asked = mutableListOf<List<String>>()
        val twoAlone =
            firstSupported(lenses, options) {
                asked += it
                it == listOf("main", "wide")
            }
        assertEquals(listOf("main", "wide") to listOf("tele"), twoAlone)
        assertEquals(
            listOf(
                listOf("main", "wide", "tele", "preview"),
                listOf("main", "wide", "tele"),
                listOf("main", "wide", "preview"),
                listOf("main", "wide"),
            ),
            asked,
        )
        val noneTaken = firstSupported(lenses, options) { false } // one lens, as it is seen
        assertEquals(listOf("main", "preview") to listOf("wide", "tele"), noneTaken)
        val previewAlone = { _: List<String> -> listOf(listOf("preview")) }
        assertEquals(listOf("preview") to emptyList<String>(), firstSupported(emptyList(), previewAlone) { false })
    }

    @Test
    fun `a lens whose focal length the phone does not tell is no ultra-wide nor telephoto`() {
        val untold = LensInfo("0", "2", 0.0)
        val alsoUntold = LensInfo("0", "3", 0.0)
        val none = LensChoice.classify(LensInfo("0", null, 0.0), listOf(untold, alsoUntold), null)
        assertEquals(mapOf(Lens.MAIN to untold), none)
        val told = LensInfo("0", "3", 24.0)
        val one = LensChoice.classify(LensInfo("0", null, 24.0), listOf(untold, told), null)
        assertEquals(mapOf(Lens.MAIN to told), one)
    }

    @Test
    fun `a back camera that tells no focal length has the lens nearest a main lens's as main`() {
        val ultra = LensInfo("0", "2", 13.0)
        val main = LensInfo("0", "3", 24.0)
        val long = LensInfo("0", "4", 70.0)
        val found = LensChoice.classify(LensInfo("0", null, 0.0), listOf(ultra, main, long), null)
        assertEquals(mapOf(Lens.MAIN to main, Lens.ULTRAWIDE to ultra, Lens.TELEPHOTO to long), found)
    }
}
