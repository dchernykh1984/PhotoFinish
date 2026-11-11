package com.dchernykh.photofinish.camera.stream

/**
 * The frames dropped for the network in the last minute, which a keyframe tells (specs/005): one
 * blip does not colour the rest of the day. [nanos] is the clock they are timed on.
 */
internal class RecentDrops(
    private val nanos: () -> Long,
) {
    private val drops = ArrayDeque<Pair<Long, Long>>()

    @Synchronized
    fun add(count: Long) {
        drops.addLast(nanos() to count)
    }

    @Synchronized
    fun lately(): Long {
        val since = nanos() - RECENT_NS
        while (drops.isNotEmpty() && drops.first().first < since) drops.removeFirst()
        return drops.sumOf { it.second }
    }

    private companion object {
        const val RECENT_NS = 60_000_000_000L
    }
}
