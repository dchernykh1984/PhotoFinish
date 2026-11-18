package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens

/** A lens's stream as [KeptStreams] keeps it: fed by a camera or by none, asked what it keeps, stopped. */
internal interface KeptStream {
    /** A camera feeds it again: its frames watched from the next, the first a keyframe; its link's words said. */
    fun feed()

    /** No camera feeds it: it sends what it kept, its link's words not said -- its camera's stand. */
    fun idle()

    /** A frame kept and not sent yet, or sent and not confirmed by the recorder. */
    val unsent: Boolean

    /** Stopped, what it kept dropped. */
    fun stop()
}

/**
 * The lenses' streams, one a lens, kept across the cameras' opens while the referee's choice lasts
 * (specs/007-store-and-forward, FR-014): a camera opened again -- lost, a lens left out, the screen back -- feeds
 * the stream it fed, what it kept still sent, its connection and clock exchange going on. A stream no camera has
 * fed for [IDLE_MS] -- the screen away, its lens left out -- is stopped once it keeps nothing unsent: an open
 * coming 2 s after a loss feeds it again before.
 */
internal class KeptStreams<S : KeptStream> {
    private val streams = linkedMapOf<Lens, S>()

    /** Since when no camera feeds each idle lens's stream. */
    private val idleSince = mutableMapOf<Lens, Long>()

    /** [lens]'s stream, kept or not. */
    operator fun get(lens: Lens): S? = streams[lens]

    /**
     * [lens]'s stream, fed by a camera: the one kept when it [fits] -- the same lens, place and format --, else
     * that one stopped and a new one [start]ed; a start that throws leaves the lens none.
     */
    fun feed(
        lens: Lens,
        fits: (S) -> Boolean,
        start: () -> S,
    ): S {
        idleSince -= lens
        val kept = streams[lens]
        if (kept != null && fits(kept)) return kept.also { it.feed() }
        streams.remove(lens)?.stop() // one stream a lens: the store's folder and the recorder are the lens's
        return start().also { streams[lens] = it }
    }

    /** No camera feeds [lens]'s stream from [nowMs]: it sends what it kept. */
    fun idle(
        lens: Lens,
        nowMs: Long,
    ) {
        val stream = streams[lens] ?: return
        if (idleSince.putIfAbsent(lens, nowMs) == null) stream.idle()
    }

    /** The streams idle [IDLE_MS] at [nowMs] that keep nothing unsent, stopped: their lenses. */
    fun sweep(nowMs: Long): List<Lens> {
        val done = idleSince.filter { (lens, since) -> nowMs - since >= IDLE_MS && streams[lens]?.unsent == false }
        done.keys.forEach {
            idleSince -= it
            streams.remove(it)?.stop()
        }
        return done.keys.toList()
    }

    /** Every stream stopped, what they kept dropped: the referee's choice changed, or the app ends (FR-004). */
    fun stopAll() {
        streams.values.forEach { it.stop() }
        streams.clear()
        idleSince.clear()
    }

    companion object {
        /** How long a stream no camera feeds is kept with nothing unsent: longer than an open 2 s after a loss. */
        const val IDLE_MS = 5_000L
    }
}
