package com.dchernykh.photofinish.camera.capture

import android.hardware.camera2.CameraDevice
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.LensTarget

/** How a camera of an open failed, as [LensFallback] weighs it: none for the cameras that would not open. */
sealed interface CameraFailure {
    /** A camera's error [code], [sinceStartMs] after its lenses started: null before they did. */
    data class Error(
        val code: Int,
        val sinceStartMs: Long?,
    ) : CameraFailure

    /** A camera another app took: none of the lenses' doing. */
    data object Taken : CameraFailure

    /** A camera that could not run the session of its lenses, which the phone said beforehand it runs. */
    data object NotConfigured : CameraFailure

    /** A camera that gave its [silent] lenses no frame, [sinceStartMs] after they started. */
    data class NoFrame(
        val silent: List<Lens>,
        val sinceStartMs: Long,
    ) : CameraFailure

    /**
     * A camera that gave [lens] frames and then none for a while, saying nothing: [sinceStartMs] after the start,
     * at [atMs] on the watch's clock.
     */
    data class Stalled(
        val lens: Lens,
        val sinceStartMs: Long,
        val atMs: Long,
    ) : CameraFailure
}

/** One lens as the frames' watch sees it: [lastFrameMs], its encoder's last frame on the watch's clock, 0 for none. */
data class Seen(
    val lens: Lens,
    val lastFrameMs: Long,
)

/** What the frames' watch takes its camera for lost by: [failure] -- none for a lens tried again --, for [reason]. */
data class Watched(
    val reason: String,
    val failure: CameraFailure?,
)

/**
 * The lenses the cameras failed with, left out until the referee starts again (specs/004-phone-lenses,
 * FR-005): a phone may say it streams lenses together and then not -- the Xiaomi 17 Ultra, asked for four at
 * 2560x1440 and 60 fps, gave no frame and its camera failed in 1.5 s, again each time it was opened. Cameras
 * that fail, give a lens no frame, or stop giving one frames, within [EARLY_MS] of their lenses' start are
 * opened again with one lens fewer: the last of the code's order -- for a lens that gave no frame, the last of
 * those, never one that streams; a lens that stopped, itself --, as a session the phone says it cannot run
 * drops them, never the first.
 * The cameras failing together -- the front's and the back's at once -- are one failure: an open leaves one
 * lens out at most. Cameras lost later, having streamed a while, or taken by another app, are opened again
 * with all their lenses -- but a lens that stops again within [AGAIN_MS] of its last stop goes, the cameras
 * opened again not bringing it back; the first, which never goes, is waited for while another lens streams that
 * opening them again would cut.
 */
@Suppress("TooManyFunctions") // the rules of FR-005, each a question of a few lines
class LensFallback {
    private val left = linkedSetOf<Lens>()

    /** The open that left a lens out already: its other camera's failure is the same one. */
    private var paid: Int? = null

    /**
     * The lenses streamed a while since the start ([settle]): a camera failing early after it is one opened again
     * mid-race, its service still settling, not the lenses'.
     */
    private val settled: Boolean get() = settledAtMs != Long.MAX_VALUE

    /** When the lenses first settled, on the watch's clock: never, before. */
    private var settledAtMs = Long.MAX_VALUE

    /** The lenses left out so far, in the order they were. */
    val leftOut: Set<Lens> get() = left.toSet()

    /** The lenses waited for, silent, in open [waitingIn]: its others run together without them. */
    private val waiting = mutableSetOf<Lens>()
    private var waitingIn: Int? = null

    /** What the last start asked for: the cameras started again for the same keep what was left out. */
    private var asked: Pair<StreamFormat, List<LensTarget>>? = null

    /** When each lens last stopped giving frames, on the watch's clock, until the referee starts again. */
    private val stops = mutableMapOf<Lens, Long>()

    /** The last stop that came within [AGAIN_MS] of its lens's one before: the lens's own doing. */
    private var stoppedAgain: CameraFailure.Stalled? = null

    /**
     * The stop waited for, the cameras not made again for it: the first lens's come again beside a lens that streams,
     * or a lens of the other camera stopping later -- its first camera's lenses not cut for it.
     */
    private var waitStop: CameraFailure.Stalled? = null

    /** The open's first lens as [retry] first saw it waited for, and when, on the watch's clock: its wait from then. */
    private var firstWaited: Pair<Lens, Long>? = null

    /** The first lens's retries since the referee's start: each doubles the wait for the next, a minute first. */
    private var retries = 0

    /** Since when the first lens gave frames at every watch, on the watch's clock: a minute forgets its retries. */
    private var firstGivingSinceMs: Long? = null

    /**
     * The cameras started for [targets] at [format]: the lenses left out forgotten when either is not the last
     * start's -- the referee's choice, a stop in between asking for the preview alone --, kept when the same come
     * again: the preview's surface made again, the screen back from another app.
     */
    fun start(
        format: StreamFormat,
        targets: List<LensTarget>,
    ) {
        if (asked == format to targets) return
        asked = format to targets
        left.clear()
        waiting.clear()
        waitingIn = null
        paid = null
        settledAtMs = Long.MAX_VALUE
        stops.clear()
        retries = 0
        firstGivingSinceMs = null
        stoppedAgain = null
        waitStop = null
        firstWaited = null
    }

    /**
     * The lenses gave their frames for [EARLY_MS] since they started: whatever fails from now on -- or closes, the
     * screen away, and comes back for the same -- is a camera lost, not the lenses', until the referee starts again.
     */
    fun settle(atMs: Long) {
        if (!settled) settledAtMs = atMs
    }

    /**
     * [failure] the lenses', early, before they streamed a while -- a lens that stopped before they first settled
     * too, the watch seeing it seconds after -- or a lens stopping again too soon.
     */
    private fun counts(failure: CameraFailure?): Boolean =
        if (failure is CameraFailure.Stalled) {
            failure == stoppedAgain || early(failure) && failure.atMs < settledAtMs
        } else {
            !settled && early(failure)
        }

    /**
     * [failure]'s stop kept for its lens, taken for its own doing when its last came within [AGAIN_MS]: the same stop
     * heard again -- by both cameras' paths -- is no other.
     */
    private fun heard(failure: CameraFailure.Stalled) {
        val before = stops.put(failure.lens, failure.atMs) ?: return
        if (before != failure.atMs && failure.atMs - before < AGAIN_MS) stoppedAgain = failure
    }

    /**
     * The camera of [own] lenses failed, of open [open] streaming [streamed] in the code's order: the lens left
     * out from now on, or null -- a failure not the lenses', or late, one this open paid for already, or a lens
     * streamed alone. After a lens gave no frame, the last of those goes, never one that streams for it: the
     * first alone silent, none goes, waited for. A lens that stopped giving frames goes itself; the first, which
     * never goes, lightens the load as an error does the first time, and stopping again too soon leaves none out.
     * Else its own go first; another camera's when it streams the first lens alone, their load lightened.
     */
    fun failed(
        open: Int,
        streamed: List<Lens>,
        own: List<Lens>,
        failure: CameraFailure?,
    ): Lens? = choose(open, failure, streamed.drop(1), own)

    /**
     * Whether the cameras of open [open] are made again after [failure]. A lens left out by either camera makes
     * another open without it. Else a lens that gave no frame is waited for, the lenses that give frames streaming
     * on, as before the watch -- made again, they would be cut every few seconds for as long as it stays silent --;
     * and a session the camera could not make is said, not made again, while the lenses never ran together -- made
     * the same way, it would fail the same way --, made again once they did, as a camera lost mid-race is. A lens
     * that stopped is made again, but the first stopping again too soon while another lens streams: waited for, as
     * one that gave no frame -- alone, it is made again each time, as nothing streams that it would cut.
     */
    fun madeAgain(
        open: Int,
        failure: CameraFailure?,
    ): Boolean =
        open == paid ||
            when (failure) {
                is CameraFailure.NoFrame -> false
                is CameraFailure.Stalled -> failure != waitStop
                CameraFailure.NotConfigured -> settled
                else -> true
            }

    /**
     * The lenses that gave no frame, waited for after [failure] when open [open] left none out: they may come yet,
     * the others streaming on, as before the watch -- either camera's, the other not closed for the race --; none
     * after another failure, or once a lens is left out. A lens stopping again too soon, so, the first.
     */
    fun waitedFor(
        open: Int,
        failure: CameraFailure?,
    ): List<Lens> {
        val silent =
            when {
                open == paid -> emptyList()
                failure is CameraFailure.NoFrame -> failure.silent
                failure is CameraFailure.Stalled && failure == waitStop -> listOf(failure.lens)
                else -> emptyList()
            }
        if (silent.isEmpty()) return silent
        if (open != waitingIn) waiting.clear()
        waitingIn = open
        return silent.also { waiting += it }
    }

    /**
     * Whether [lens] is waited for in open [open], silent: the lenses settle without it -- the others giving frames
     * for [EARLY_MS] run together --, a camera lost mid-race after then not costing one of them; and a failure of the
     * open leaves out none that streams for it.
     */
    fun waitsFor(
        open: Int,
        lens: Lens,
    ): Boolean = open == waitingIn && lens in waiting

    /**
     * The other camera of open [open] -- the front beside the back -- failed alone and was closed, its [lenses]
     * left out of this open: one of them left out from now on, as the first camera's path does -- after a lens gave
     * no frame the last of those, else its last, never the first of [streamed], the open's in the code's order --, the
     * others tried again in the next open, made for them. The lens left out, or null: a lens of it that stopped and
     * is not left out is waited for, as one that gave no frame, not closed for the open -- a pause that passes then
     * passes, and opening the cameras again for it would cut the first camera's lenses.
     */
    fun failedAlone(
        open: Int,
        streamed: List<Lens>,
        lenses: List<Lens>,
        failure: CameraFailure?,
    ): Lens? =
        choose(open, failure, streamed.drop(1).filter { it in lenses }, lenses).also {
            if (it == null && failure is CameraFailure.Stalled && open != paid) waitStop = failure // else closed
        }

    /**
     * One of [candidates] left out of open [open] after [failure] when it counts and the open has paid none: after
     * a lens gave no frame, the last of those, never one that streams -- left out, it could leave none streaming --;
     * a lens that stopped giving frames, itself -- the first stopping again too soon, none, waited for while another
     * streams --; with a lens waited for in the open, the last waited for, so; else the last of [own], else the
     * last: the first stopping early lightens the load as an error does.
     */
    private fun choose(
        open: Int,
        failure: CameraFailure?,
        candidates: List<Lens>,
        own: List<Lens>,
    ): Lens? {
        if (failure is CameraFailure.Stalled) heard(failure)
        if (!counts(failure) || open == paid) return null
        val lens = pick(open, failure, candidates, own) ?: return null
        paid = open
        return lens.also { left += it }
    }

    /** Which of [candidates] goes after [failure], as [choose] says. */
    private fun pick(
        open: Int,
        failure: CameraFailure?,
        candidates: List<Lens>,
        own: List<Lens>,
    ): Lens? =
        when {
            failure is CameraFailure.NoFrame -> candidates.lastOrNull { it in failure.silent }
            failure is CameraFailure.Stalled && failure.lens in candidates -> failure.lens
            // The first lens stopping again: none left out, waited for while another lens streams, not waited for.
            failure is CameraFailure.Stalled && failure == stoppedAgain ->
                null.also { if (candidates.any { !waitsFor(open, it) }) waitStop = failure }
            open == waitingIn -> candidates.lastOrNull { it in waiting }
            else -> candidates.lastOrNull { it in own } ?: candidates.lastOrNull()
        }

    /**
     * Open [open]'s camera, its lenses [seen] started at [startedMs], watched at [nowMs], the lenses keeping a frame
     * unsent [keptMs]: a lens waited for that gives frames again is watched again ([heardFrom]); the open's [first]
     * lens, given the camera with the preview, tried again ([retry]); else lenses that gave no frame [NO_FRAME_MS]
     * after the start, or one that stopped ([stall]) -- the last of those, in the code's order: the camera stopping
     * every lens at once costs its least lens when it comes again, as a failure does, not its first --: what its
     * camera is taken for lost by, or null.
     */
    fun watch(
        open: Int,
        seen: List<Seen>,
        startedMs: Long,
        nowMs: Long,
        kept: () -> Long,
        first: Lens?,
    ): Watched? {
        val keptMs by lazy(kept) // the stores' locks taken only when a stop or a retry asks
        seen.forEach { heardFrom(open, it.lens, it.lastFrameMs, nowMs) }
        val since = nowMs - startedMs
        if (first != null) forgetRetries(open, seen.find { it.lens == first }, nowMs)
        val watched = seen.filterNot { waitsFor(open, it.lens) }
        val silent =
            watched
                .filter { it.lastFrameMs == 0L }
                .map { it.lens }
                .takeIf { since >= NO_FRAME_MS }
                .orEmpty()
        // Put off while the lenses keep a frame unsent [KEPT_MS] or more, the cameras opened again dropping it -- a
        // lens silent meanwhile as before the watch --, [KEPT_WAIT_MS] at most: a slow Wi-Fi keeps none silent.
        val stales = watched.mapNotNull { stall(it.lens, it.lastFrameMs, startedMs, nowMs) }
        val stale = stales.lastOrNull()
        // The cap from the oldest stop: a lens stopping later puts none off past it.
        val stopped = stale?.takeIf { nowMs - stales.minOf { it.atMs } >= KEPT_WAIT_MS || keptMs < KEPT_MS }
        val named = silent.joinToString { it.code }
        val noFrame = CameraFailure.NoFrame(silent, since)
        // A failure first, weighed as the lenses' own when early; the retry the next tick, none while a stop is put
        // off -- its reopen would pass the stop by uncounted. The other camera's watch has no first lens to try.
        return when {
            silent.isNotEmpty() -> Watched("the camera gave $named no frame in ${NO_FRAME_MS / MS_PER_S} s", noFrame)
            stopped != null -> { // silent as long as it was, a stop put off for the frames kept longer than 3 s
                val silentS = (nowMs - stopped.atMs) / MS_PER_S
                Watched("the camera gave ${stopped.lens.code} no frame for $silentS s", stopped)
            }
            stale != null -> null
            else -> {
                val waitedS = firstWaited?.let { (nowMs - it.second) / MS_PER_S } // a minute, two, four...
                first
                    ?.let { retry(open, it, nowMs) { keptMs } }
                    ?.let { Watched("${it.code} waited for $waitedS s: tried again", null) } // silent or stopped
            }
        }
    }

    /**
     * The open's [first] lens, waited for in open [open] -- silent from the start, or stopped again beside others --
     * [AGAIN_MS] since this was first asked it, at [nowMs], the lenses keeping no frame unsent [KEPT_MS] or more
     * ([keptMs], how much they span) -- opening the cameras again drops what they keep -- or [KEPT_WAIT_MS] more gone
     * by, a slow Wi-Fi not keeping the first lens silent for good: tried again, the lens
     * returned for the cameras to be opened again, a moment of the others' frames a minute for a chance of it; its
     * next stop within a minute of this waited for again. Else null.
     */
    fun retry(
        open: Int,
        first: Lens,
        nowMs: Long,
        keptMs: () -> Long,
    ): Lens? {
        if (!waitsFor(open, first)) {
            firstWaited = null
            return null
        }
        val since = firstWaited?.takeIf { it.first == first }?.second ?: nowMs.also { firstWaited = first to it }
        val waited = nowMs - since
        // A minute, then two, four... up to 32: a first lens that stays broken costs the others a cut seldom.
        val due = AGAIN_MS shl retries.coerceAtMost(MOST_DOUBLINGS)
        if (waited < due || waited < due + KEPT_WAIT_MS && keptMs() >= KEPT_MS) return null
        retries++
        firstWaited = null
        waitStop = null
        resumed(first, nowMs)
        return first
    }

    /**
     * The first lens, [first] as seen in open [open] at [nowMs], giving frames at every watch for [AGAIN_MS] -- no
     * gap of [STALL_MS] --: its retries so far forgotten, its next wait a minute again; hours after a bad start it is
     * not left half an hour, and a lens that sputters forgets none.
     */
    private fun forgetRetries(
        open: Int,
        first: Seen?,
        nowMs: Long,
    ) {
        val giving = first != null && first.lastFrameMs != 0L && nowMs - first.lastFrameMs <= STALL_MS
        if (!giving || waitsFor(open, first.lens)) {
            firstGivingSinceMs = null
            return
        }
        val since = firstGivingSinceMs ?: nowMs.also { firstGivingSinceMs = it }
        if (nowMs - since >= AGAIN_MS) retries = 0
    }

    /** [lens] no longer waited for at [nowMs] -- tried again, or back --, kept as a stop: stopping soon, it goes. */
    private fun resumed(
        lens: Lens,
        nowMs: Long,
    ) {
        waiting -= lens
        if (waiting.isEmpty()) waitingIn = null // none waited for now: a failure leaves a lens out as any
        stops[lens] = nowMs
        if (firstWaited?.first == lens) firstWaited = null // its next wait counted from its own start
    }

    /**
     * [lens], waited for in open [open], gave a frame lately -- its last at [lastFrameMs], [nowMs] now --: no longer
     * waited for, its frames watched again as any lens's, its coming back kept as a stop: stopping again within
     * [AGAIN_MS], it goes, not every lens cut for a lens that was silent.
     */
    fun heardFrom(
        open: Int,
        lens: Lens,
        lastFrameMs: Long,
        nowMs: Long,
    ) {
        if (!waitsFor(open, lens) || lastFrameMs == 0L || nowMs - lastFrameMs > STALL_MS) return
        resumed(lens, nowMs)
    }

    companion object {
        /** How soon a failure is the lenses' own: a camera that streamed longer was lost, not unable. */
        const val EARLY_MS = 10_000L

        /** A lens stopping again this soon after its last stop: the cameras opened again did not bring it back. */
        const val AGAIN_MS = 60_000L

        /** The first lens's retries wait at most 2^5 minutes, half an hour, one from the next. */
        private const val MOST_DOUBLINGS = 5

        /** Frames kept unsent this long put a stop or a retry off: opening the cameras again would drop them. */
        const val KEPT_MS = 1_000L

        /** How long after its last frame a lens's stop is put off at most for the frames kept to be sent. */
        const val KEPT_WAIT_MS = 30_000L

        /** How long a lens that gave frames may give none, whatever its rate: at 15 fps, 45 frames missed. */
        const val STALL_MS = 3_000L

        /** How long after the lenses' start one that gave no frame is a failure: the Xiaomi's gave none in 80 s. */
        const val NO_FRAME_MS = 5_000L

        private const val MS_PER_S = 1_000L

        /**
         * [lens] stopped at [nowMs] -- its last frame at [lastFrameMs], 0 for none yet, more than [STALL_MS] before --,
         * the lenses started at [startedMs]: the failure, timed when it stopped, the watch seeing it seconds later.
         */
        fun stall(
            lens: Lens,
            lastFrameMs: Long,
            startedMs: Long,
            nowMs: Long,
        ): CameraFailure.Stalled? =
            if (lastFrameMs != 0L && nowMs - lastFrameMs > STALL_MS) {
                CameraFailure.Stalled(lens, lastFrameMs - startedMs, lastFrameMs)
            } else {
                null // most ticks: nothing made to be dropped
            }

        /**
         * A camera's errors of the lenses asked of it: not another app's holding the camera, nor too many cameras
         * open -- another app's as likely as ours, which the phone said it runs together --, nor the phone's policy.
         */
        private val LENSES_ERRORS =
            setOf(
                CameraDevice.StateCallback.ERROR_CAMERA_DEVICE,
                CameraDevice.StateCallback.ERROR_CAMERA_SERVICE,
            )

        /** A failure of the lenses asked, in their first seconds: none is another app's taking the camera. */
        private fun early(failure: CameraFailure?): Boolean =
            when (failure) {
                null, CameraFailure.Taken -> false
                // Before its lenses started, a camera's error is no sign of them: its service may be starting again.
                is CameraFailure.Error ->
                    failure.code in LENSES_ERRORS && failure.sinceStartMs != null && failure.sinceStartMs < EARLY_MS
                is CameraFailure.NoFrame -> failure.sinceStartMs < EARLY_MS
                is CameraFailure.Stalled -> failure.sinceStartMs < EARLY_MS
                CameraFailure.NotConfigured -> true
            }
    }
}
