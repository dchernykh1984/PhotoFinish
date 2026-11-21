package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import com.dchernykh.photofinish.camera.stream.FrameStore
import com.dchernykh.photofinish.camera.stream.StreamHeader
import com.dchernykh.photofinish.camera.stream.Uplink
import java.io.File

/**
 * The streams kept with no encoder left to feed them (specs/009): read back from the stores' [root] as the app
 * starts -- what a crash, Android or a dead battery left --, or handed over by a stream that stopped -- Stop,
 * another choice, the app closing, its encoder failing. Each is sent by an uplink of its own ([send]), alone:
 * one an address at a time, the oldest first, and a stream fed by a camera waits for its address to be free
 * ([holds]), so the recorder gets a camera's frames in the order taken. A stream sent whole -- nothing unsent for
 * [DONE_MS] -- is removed with its folder; [discard] drops them all.
 */
@Suppress("TooManyFunctions") // its steps: read back, hand over, tick, the counts, discard
class Backlog(
    private val root: File,
    /** An uplink for a kept stream, started on a thread of its own, and what stops it. */
    private val send: (StreamHeader, FrameStore) -> Sending,
    /** What the backlog says to the phone's log, of a lens. */
    private val say: (Lens, String) -> Unit = { _, _ -> },
    /**
     * The app's run it belongs to, the end of the folders the streams of this run make -- `<lens>-<ms>-<session>` --:
     * those are live streams', not to read back, whatever the phone's clock did meanwhile.
     */
    private val session: String = "",
) {
    /** A kept stream's uplink, running, and how it is stopped. */
    class Sending(
        val uplink: Uplink,
        val stop: () -> Unit,
    )

    private class Kept(
        val folder: File,
        val header: StreamHeader,
        val store: FrameStore,
    ) {
        var sending: Sending? = null
        var quietSince: Long? = null
    }

    private val kept = mutableListOf<Kept>()

    /** The stores of streams a camera feeds, by address: what the phone holds for a camera, all told. */
    private val live = mutableListOf<Pair<RtmpAddress, FrameStore>>()

    /** Read back: until then every address is held ([holds]), so nothing a camera feeds goes before what was kept. */
    @Volatile private var ready = false

    /** A lens streams, or a stream is kept: there are frames to send. */
    val active: Boolean @Synchronized get() = kept.isNotEmpty() || live.isNotEmpty()

    /**
     * What the stores' root holds from the app's runs before, read back: streams to send, or folders of nothing to
     * send, removed. A folder of this run is a stream a camera feeds, perhaps its header not written yet: not its.
     */
    @Synchronized
    fun readBack() {
        try {
            val folders =
                root
                    .listFiles { file ->
                        file.isDirectory && !(session.isNotEmpty() && file.name.endsWith("-$session"))
                    }?.sortedBy { began(it) } ?: return
            folders.filter { folder -> kept.none { it.folder == folder } }.forEach { take(it) }
        } finally {
            ready = true
        }
    }

    /**
     * A stream that stopped: its [store] handed over -- sent alone when it holds anything unsent, else removed --
     * before [off] takes its live count away, so the backlog never looks idle in between and the foreground
     * service is not let go (specs/009, FR-006).
     */
    @Synchronized
    fun handOver(
        store: FrameStore,
        off: () -> Unit,
    ) {
        if (store.handOver()) adopt(store.folder)
        off()
    }

    /** A stream handed over, its store closed: sent if it holds anything unsent, else removed. */
    @Synchronized
    fun adopt(folder: File) {
        if (kept.none { it.folder == folder }) take(folder)
    }

    private fun take(folder: File) {
        val header = StreamHeader.read(folder)
        if (header == null && hasFrames(folder)) {
            // Frames whose header a power cut took: not sent, not removed either -- Discard alone removes them.
            val lens = Lens.named(folder.name.substringBefore('-')) ?: Lens.MAIN
            say(lens, "${folder.name}: frames kept with no header to send them with; left on the phone")
            return
        }
        val store = header?.let { FrameStore(folder) }
        if (header == null || store == null || !store.unsent) {
            folder.deleteRecursively() // nothing to send
            return
        }
        kept += Kept(folder, header, store)
        val (ms, bytes) = store.pending
        say(header.lens, "kept to send to ${header.address}: ${ms / MS_PER_S} s of video, ${bytes / BYTES_PER_MB} MB")
    }

    /**
     * Each second, at [nowMs]: streams sent whole removed; the oldest of each address with none sending started.
     */
    @Synchronized
    fun tick(nowMs: Long) {
        kept.removeAll { done(it, nowMs) }
        kept
            .groupBy { it.header.address }
            .values
            .forEach { streams ->
                val oldest = streams.first()
                if (streams.none { it.sending != null }) oldest.sending = send(oldest.header, oldest.store)
            }
    }

    private fun done(
        stream: Kept,
        nowMs: Long,
    ): Boolean {
        val sending = stream.sending
        if (sending == null || sending.uplink.unsent) {
            stream.quietSince = null
            return false
        }
        val since = stream.quietSince ?: nowMs.also { stream.quietSince = it }
        if (nowMs - since < DONE_MS) return false
        sending.stop()
        stream.store.clear()
        say(stream.header.lens, "all it kept sent to ${stream.header.address}: removed")
        return true
    }

    /** Streams kept for [address], sending or waiting -- or not read back yet: a stream a camera feeds waits. */
    @Synchronized
    fun holds(address: RtmpAddress): Boolean = !ready || kept.any { it.header.address == address }

    /** A store a camera feeds, for [address]: counted in what the phone holds for it. Returns what takes it off. */
    @Synchronized
    fun live(
        address: RtmpAddress,
        store: FrameStore,
    ): () -> Unit {
        val entry = address to store
        live += entry
        return { synchronized(this) { live -= entry } }
    }

    /** What the phone holds for [address], kept and fed. */
    @Synchronized
    fun pendingFor(address: RtmpAddress): FrameStore.Pending =
        sum(
            kept.filter { it.header.address == address }.map { it.store } +
                live.filter { it.first == address }.map { it.second },
        )

    /** What the phone holds, kept and fed, all told. */
    @Synchronized
    fun pending(): FrameStore.Pending = sum(kept.map { it.store } + live.map { it.second })

    /**
     * Every stream kept stopped and dropped, and whatever else the stores' root holds but the streams a camera feeds
     * -- frames whose header was lost --: the referee's Discard (specs/009, FR-004).
     */
    @Synchronized
    fun discard() {
        kept.forEach {
            it.sending?.stop()
            it.store.clear()
            say(it.header.lens, "what it kept for ${it.header.address} discarded")
        }
        kept.clear()
        val fed = live.map { it.second.folder }.toSet()
        root.listFiles { file -> file.isDirectory && file !in fed }?.forEach { it.deleteRecursively() }
    }

    companion object {
        /** How long a stream kept has had nothing unsent before it is removed: its last acknowledgements in. */
        const val DONE_MS = 5_000L
        private const val MS_PER_S = 1_000
        private const val BYTES_PER_MB = 1_000_000

        /** Whether [folder] holds a run of frames. */
        private fun hasFrames(folder: File): Boolean = folder.list()?.any { it.endsWith(".h264") } == true

        /** When the stream of [folder] began, from its name: `<lens>-<ms>[-<session>]`; one named otherwise first. */
        private fun began(folder: File): Long =
            folder.name
                .split('-')
                .getOrNull(1)
                ?.toLongOrNull() ?: 0L

        private fun sum(stores: List<FrameStore>): FrameStore.Pending =
            stores.map { it.pending }.fold(FrameStore.Pending(0, 0)) { all, one ->
                FrameStore.Pending(all.ms + one.ms, all.bytes + one.bytes)
            }
    }
}
