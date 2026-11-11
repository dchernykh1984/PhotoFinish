package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.LensTarget
import kotlin.math.abs

/** A camera the phone gives an app: a camera device, or one physical camera of a logical one. */
data class LensInfo(
    val cameraId: String,
    val physicalId: String?,
    /** The 35 mm-equivalent focal length, mm. */
    val focalMm: Double,
)

/** The phone's lenses by role (specs/004-phone-lenses, FR-004). */
object LensChoice {
    private const val WIDE_AT_MOST = 0.8
    private const val TELE_AT_LEAST = 1.5

    /**
     * Of the [back] camera's [physical] cameras, the one nearest its own focal length is main, the
     * shortest at four fifths of that or less ultra-wide, the longest at one and a half times or more
     * telephoto; without physical cameras the back camera alone is main. [front] is the front.
     */
    fun classify(
        back: LensInfo?,
        physical: List<LensInfo>,
        front: LensInfo?,
    ): Map<Lens, LensInfo> {
        val found = linkedMapOf<Lens, LensInfo>()
        if (back != null) {
            val main = physical.minByOrNull { abs(it.focalMm - back.focalMm) } ?: back
            found[Lens.MAIN] = main
            physical
                .filter { it.focalMm <= main.focalMm * WIDE_AT_MOST }
                .minByOrNull { it.focalMm }
                ?.let { found[Lens.ULTRAWIDE] = it }
            physical
                .filter { it.focalMm >= main.focalMm * TELE_AT_LEAST }
                .maxByOrNull { it.focalMm }
                ?.let { found[Lens.TELEPHOTO] = it }
        }
        front?.let { found[Lens.FRONT] = it }
        return found
    }
}

/** A lens to stream: what it is asked for, where it is, and its physical camera when named. */
data class PlannedLens(
    val target: LensTarget,
    val info: LensInfo,
    val physicalId: String?,
)

/** A camera device to open, and the lenses its one capture session streams. */
data class PlannedCamera(
    val cameraId: String,
    val lenses: List<PlannedLens>,
)

/** Why a lens asked for is not streamed. */
enum class LeftOut { NOT_ON_THIS_PHONE, NOT_WITH_THE_OTHERS }

/** The cameras to open for the lenses asked, and the lenses left out (FR-005). */
data class SessionPlan(
    val cameras: List<PlannedCamera>,
    val left: Map<Lens, LeftOut>,
) {
    companion object {
        /**
         * The cameras to open for [targets], in their order: the lenses of one camera in one session,
         * each named by its physical camera when the session streams several, or when it is not the
         * camera's own picture. Left out: a lens the phone lacks; one that needs a physical camera
         * named where the phone cannot ([physicalStreams], Android 9); one on a camera the phone
         * cannot run beside those before it ([together]).
         */
        fun plan(
            targets: List<LensTarget>,
            lenses: Map<Lens, LensInfo>,
            together: (Set<String>) -> Boolean,
            physicalStreams: Boolean,
        ): SessionPlan {
            val left = linkedMapOf<Lens, LeftOut>()
            val byCamera = linkedMapOf<String, MutableList<Pair<LensTarget, LensInfo>>>()
            for (target in targets) {
                val info = lenses[target.lens]
                if (info == null) {
                    left[target.lens] = LeftOut.NOT_ON_THIS_PHONE
                } else {
                    byCamera.getOrPut(info.cameraId) { mutableListOf() } += target to info
                }
            }
            val cameras = mutableListOf<PlannedCamera>()
            for ((cameraId, asked) in byCamera) {
                val lensesHere = named(asked, physicalStreams, left)
                when {
                    lensesHere.isEmpty() -> Unit
                    cameras.isNotEmpty() && !together(cameras.map { it.cameraId }.toSet() + cameraId) ->
                        lensesHere.forEach { left[it.target.lens] = LeftOut.NOT_WITH_THE_OTHERS }
                    else -> cameras += PlannedCamera(cameraId, lensesHere)
                }
            }
            return SessionPlan(cameras, left)
        }

        /**
         * The lenses of one camera with their physical cameras named where they must be. Where the
         * phone names none, the camera's own picture alone: its main lens, or a camera of one lens.
         */
        private fun named(
            asked: List<Pair<LensTarget, LensInfo>>,
            physicalStreams: Boolean,
            left: MutableMap<Lens, LeftOut>,
        ): List<PlannedLens> {
            val own = { pair: Pair<LensTarget, LensInfo> ->
                pair.first.lens == Lens.MAIN ||
                    pair.second.physicalId == null
            }
            if (!physicalStreams) {
                val kept = asked.firstOrNull(own)
                asked.filter { it !== kept }.forEach { left[it.first.lens] = LeftOut.NOT_ON_THIS_PHONE }
                return listOfNotNull(kept?.let { PlannedLens(it.first, it.second, null) })
            }
            val alone = asked.size == 1 && own(asked[0])
            return asked.map { (target, info) -> PlannedLens(target, info, if (alone) null else info.physicalId) }
        }
    }
}
