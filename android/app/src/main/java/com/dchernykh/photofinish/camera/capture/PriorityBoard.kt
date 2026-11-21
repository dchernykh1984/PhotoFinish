package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList

/**
 * The first lens first (specs/009, FR-007): of the lenses sending to a laptop -- streams fed by a camera, or kept
 * and sent alone --, the first in [order] sends whenever it can; the others only while it is not connected, or
 * within [BEHIND_MS] of what it holds -- one camera near live and whole beats two behind, and the others' frames
 * wait on the phone, not lost. A first lens its laptop is gone for, connecting in vain, holds nobody back; nor does
 * one sending what it kept for another laptop, the phone paired again since. A lens held waits until the first is
 * within [RESUME_MS], not just under [BEHIND_MS]: on a network the lenses overrun, one let go at the line would push
 * the first back over it at once, connecting again and again.
 */
class PriorityBoard {
    private class Sender(
        val lens: Lens,
        val host: String,
        val connected: () -> Boolean,
        val behindMs: () -> Long,
    )

    private val senders = CopyOnWriteArrayList<Sender>()

    /** The lenses held back, by laptop: they wait for the first to be within [RESUME_MS]. */
    private val held = ConcurrentHashMap.newKeySet<Pair<Lens, String>>()

    /** The lenses in the order the referee's code gave them; before any, the laptop's dialog's. */
    @Volatile var order: List<Lens> = DEFAULT_ORDER

    /**
     * A sender of [lens] to the laptop at [host]: whether it is [connected], and how far behind it is -- the video it
     * holds, ms. Returns what takes it off the board again.
     */
    fun register(
        lens: Lens,
        host: String,
        connected: () -> Boolean,
        behindMs: () -> Long,
    ): () -> Unit {
        val sender = Sender(lens, host, connected, behindMs)
        senders += sender
        return { senders -= sender }
    }

    /** Whether a sender is connected: a laptop takes what the phone sends. */
    fun anyConnected(): Boolean = senders.any { it.connected() }

    /** Whether [lens] may send now to the laptop at [host]. */
    fun allows(
        lens: Lens,
        host: String,
    ): Boolean {
        val same = senders.filter { it.host == host }
        val sending = same.map { it.lens }.toSet()
        val first = (order + DEFAULT_ORDER + Lens.entries).firstOrNull { it in sending } ?: return true
        if (lens == first) return true
        val key = lens to host
        val limit = if (key in held) RESUME_MS else BEHIND_MS
        val holds = same.any { it.lens == first && it.connected() && it.behindMs() > limit }
        if (holds) held += key else held -= key
        return !holds
    }

    companion object {
        /** The first lens this far behind keeps the others waiting. */
        const val BEHIND_MS = 2_000L

        /** A lens held waits until the first is this near live again. */
        const val RESUME_MS = 1_000L

        /** The order of the laptop's camera dialog. */
        val DEFAULT_ORDER = listOf(Lens.MAIN, Lens.TELEPHOTO, Lens.ULTRAWIDE, Lens.FRONT)
    }
}
