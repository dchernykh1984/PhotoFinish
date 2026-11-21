package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens
import java.util.concurrent.CopyOnWriteArrayList

/**
 * The first lens first (specs/009, FR-007): of the lenses sending -- streams fed by a camera, or kept and sent
 * alone --, the first in [order] sends whenever it can; the others only while it is not connected, or within
 * [BEHIND_MS] of what it holds -- one camera near live and whole beats two behind, and the others' frames wait on
 * the phone, not lost. A first lens its laptop is gone for, connecting in vain, holds nobody back.
 */
class PriorityBoard {
    private class Sender(
        val lens: Lens,
        val connected: () -> Boolean,
        val behindMs: () -> Long,
    )

    private val senders = CopyOnWriteArrayList<Sender>()

    /** The lenses in the order the referee's code gave them; before any, the laptop's dialog's. */
    @Volatile var order: List<Lens> = DEFAULT_ORDER

    /**
     * A sender of [lens]: whether it is [connected], and how far behind it is -- the video it holds, ms. Returns
     * what takes it off the board again.
     */
    fun register(
        lens: Lens,
        connected: () -> Boolean,
        behindMs: () -> Long,
    ): () -> Unit {
        val sender = Sender(lens, connected, behindMs)
        senders += sender
        return { senders -= sender }
    }

    /** Whether [lens] may send now. */
    fun allows(lens: Lens): Boolean {
        val sending = senders.map { it.lens }.toSet()
        val first = (order + Lens.entries).firstOrNull { it in sending } ?: return true
        if (lens == first) return true
        return senders.none { it.lens == first && it.connected() && it.behindMs() > BEHIND_MS }
    }

    companion object {
        /** The first lens this far behind keeps the others waiting. */
        const val BEHIND_MS = 2_000L

        /** The order of the laptop's camera dialog. */
        val DEFAULT_ORDER = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.ULTRAWIDE, Lens.FRONT)
    }
}
