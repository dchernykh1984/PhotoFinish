package com.dchernykh.photofinish.camera.stream

import java.io.Closeable
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/** A frame as the store gives it back: its bytes, when it was taken, and its moment on the recorder's clock. */
class KeptFrame(
    val data: ByteArray,
    val ptsUs: Long,
    val keyframe: Boolean,
    val momentUs: Long?,
)

/**
 * A stream's frames on the phone's own storage, from the encoder to the uplink (specs/007), so that a break,
 * a slow network or a recorder starting again costs no frame while there is room. The frames of one
 * keyframe's run share a file, their index -- capture time, keyframe, moment, when kept on the wall clock --
 * another beside it, written after each frame and synced with it as the next run begins: the store outlives
 * the app and the phone (specs/009, FR-001), and a store made on a folder reads back what one before left
 * there, up to the first frame not all written. The uplink reads at a cursor; a frame read stays until the
 * server has confirmed reading it ([confirm]), [CONFIRMED_MARGIN_US] more, to be sent again after a loss
 * ([rewind]) -- or [KEEP_SENT_US] after the newest frame read, from a server that confirms nothing. It takes the
 * phone's free space less [reserveBytes] (specs/009, FR-005), and [floorBytes] whatever, as long as the phone keeps
 * [minFreeBytes] free: past that the oldest run goes -- never one of the last [KEPT_ANYWAY_US] --, its frames not
 * read yet dropped.
 */
@Suppress("TooManyFunctions") // the uplink's steps through the store, each a few lines
class FrameStore(
    val folder: File,
    private val floorBytes: Long = FLOOR_BYTES,
    private val reserveBytes: Long = RESERVE_BYTES,
    private val minFreeBytes: Long = MIN_FREE_BYTES,
    private val freeBytes: () -> Long = { folder.usableSpace },
    private val wallClock: () -> Long = System::currentTimeMillis,
) {
    @Suppress("LongParameterList") // a frame's index record, field by field
    private class Entry(
        val offset: Long,
        val size: Int,
        val ptsUs: Long,
        val keyframe: Boolean,
        val momentUs: Long?,
        /** When it was kept, on the phone's wall clock: how long it was held, across a restart too. */
        val wallMs: Long,
        /** Read back from what a store before left: its capture clock may have started again since. */
        val readBack: Boolean = false,
    )

    private class Run(
        val file: File,
    ) {
        val index = File(file.parentFile, file.name.removeSuffix(DATA) + INDEX)
        val frames = Frames()
        var bytes = 0L
    }

    /**
     * A run's frames field by field, in arrays: some 33 bytes a frame, not an object's 90 -- a long break's hours of
     * them held in memory (specs/009). An [Entry] is made of one as it is asked for; the wall clock is the run's
     * first frame's, which is what a connection's first frame -- a keyframe, a run's first -- is held by.
     */
    private class Frames {
        private var count = 0
        private var offsets = IntArray(FIRST_ROOM)
        private var sizes = IntArray(FIRST_ROOM)
        private var pts = LongArray(FIRST_ROOM)
        private var moments = LongArray(FIRST_ROOM)
        private var flags = ByteArray(FIRST_ROOM)
        private var wallMs = 0L

        val size: Int get() = count

        fun isEmpty(): Boolean = count == 0

        operator fun get(index: Int): Entry {
            val flag = flags[index].toInt()
            val moment = moments[index].takeIf { it != NO_MOMENT }
            return Entry(
                offsets[index].toLong(),
                sizes[index],
                pts[index],
                flag and KEYFRAME != 0,
                moment,
                wallMs,
                flag and READ_BACK != 0,
            )
        }

        fun getOrNull(index: Int): Entry? = if (index in 0 until count) get(index) else null

        fun first(): Entry = get(0)

        fun last(): Entry = get(count - 1)

        fun firstOrNull(): Entry? = getOrNull(0)

        /** The bytes of the frames before [index]: where the one at it begins. */
        fun bytesBefore(index: Int): Long =
            if (index <
                count
            ) {
                offsets[index].toLong()
            } else {
                (if (count == 0) 0L else offsets[count - 1].toLong() + sizes[count - 1])
            }

        operator fun plusAssign(entry: Entry) {
            if (count == sizes.size) grow()
            if (count == 0) wallMs = entry.wallMs
            offsets[count] = entry.offset.toInt()
            sizes[count] = entry.size
            pts[count] = entry.ptsUs
            moments[count] = entry.momentUs ?: NO_MOMENT
            flags[count] = ((if (entry.keyframe) KEYFRAME else 0) or (if (entry.readBack) READ_BACK else 0)).toByte()
            count++
        }

        private fun grow() = resize(sizes.size * 2)

        /** The run done: its arrays cut to its frames, no room kept for more. */
        fun trim() = resize(count)

        private fun resize(room: Int) {
            offsets = offsets.copyOf(room)
            sizes = sizes.copyOf(room)
            pts = pts.copyOf(room)
            moments = moments.copyOf(room)
            flags = flags.copyOf(room)
        }
    }

    /** The video kept and not sent yet: its span from the next frame to the newest, ms, and its bytes. */
    data class Pending(
        val ms: Long,
        val bytes: Long,
    )

    private val lock = ReentrantLock()
    private val more = lock.newCondition()
    private val runs = ArrayDeque<Run>()

    /** The newest run's file and its index, open until a write to either fails. */
    private var writer: FileOutputStream? = null
    private var indexWriter: FileOutputStream? = null

    /** The run before's, to be synced and closed once the lock is let go ([retire]). */
    private val retired = ArrayList<FileOutputStream>()

    /** How a run's file is written through to the storage; a test's waits. */
    internal var syncFile: (FileOutputStream) -> Unit = ::sync
    private var reader: RandomAccessFile? = null
    private var readerRun: Run? = null

    /** The run and the frame the uplink reads next; no run: the oldest one's first frame. */
    private var cursorRun: Run? = null
    private var cursorFrame = 0

    /** The newest frame read so far, and the newest the server has confirmed reading. */
    private var lastReadUs: Long? = null
    private var confirmedUs: Long? = null
    private var total = 0L
    private var named = 0
    private var cleared = false

    /** Closed: handed over, its files left for a store made on the folder to send. */
    private var closed = false

    /** A run the storage would not read back, its files left as they are: the folder not to be removed for it. */
    var unreadable = false
        private set

    init {
        folder.mkdirs()
        readBack()
    }

    /**
     * Keeps [frame] with its [momentUs]; returns the frames dropped meanwhile: the oldest not read yet, for
     * room, and this one when it cannot be written or has no keyframe before it to start from.
     */
    fun keep(
        frame: EncodedFrame,
        momentUs: Long?,
    ): Int {
        val dropped =
            lock.withLock {
                if (cleared || closed) return 0
                var dropped = 0
                if (frame.keyframe) {
                    prune()
                    while (runs.isNotEmpty() && full(frame.ptsUs)) dropped += removeOldest()
                }
                dropped + if (append(frame, momentUs)) 0 else 1
            }
        retire()
        return dropped
    }

    /**
     * The run before's files, the new one begun, synced to the storage and closed outside the lock: an fsync of a
     * slow flash holds up no reader -- the uplink, the other lenses asking the first, the screen counting.
     */
    private fun retire() {
        val files = lock.withLock { retired.toList().also { retired.clear() } }
        files.forEach {
            syncFile(it)
            close(it)
        }
    }

    /** The next frame to send, waiting up to [waitMs] for one; null when none came, or the store was cleared. */
    fun next(waitMs: Long): KeptFrame? {
        lock.withLock {
            var left = TimeUnit.MILLISECONDS.toNanos(waitMs)
            while (!cleared && !closed) {
                val run = cursorRun ?: runs.firstOrNull()
                val after = run?.let { following(runs, it) }
                when {
                    run != null && cursorFrame < run.frames.size -> return read(run)
                    after != null -> {
                        cursorRun = after
                        cursorFrame = 0
                    }
                    left <= 0 -> return null
                    else -> left = more.awaitNanos(left)
                }
            }
            return null
        }
    }

    /** The server has read the frame taken at [ptsUs], and every one before it: the runs sent go. */
    fun confirm(ptsUs: Long) {
        lock.withLock {
            confirmedUs = maxOf(confirmedUs ?: ptsUs, ptsUs)
            if (!cleared && !closed) prune()
        }
    }

    /**
     * After a loss: the cursor back to the last keyframe before what a dead connection may have swallowed --
     * [CONFIRMED_MARGIN_US] before the newest frame the server confirmed, or [KEEP_SENT_US] before the newest
     * read when it confirmed none -- the oldest kept when none is that old.
     */
    fun rewind() {
        lock.withLock {
            val safe = safeBefore(confirmedUs, lastReadUs) ?: return
            cursorRun = runs.lastOrNull { it.frames.first().ptsUs <= safe } ?: runs.firstOrNull()
            cursorFrame = 0
        }
    }

    /** A run kept begins with a frame with its moment: something a connection of kept frames can send. */
    val stamped: Boolean get() = lock.withLock { runs.any { it.frames.first().momentUs != null } }

    /**
     * The cursor on to the first keyframe kept with a moment, at or after it, so that a connection's frames
     * all carry their moments; past every frame kept when none has one yet: on to the next keyframe.
     */

    fun skipToStamped() {
        lock.withLock {
            val at = cursorRun ?: runs.firstOrNull() ?: return
            val ahead = runs.drop(runs.indexOf(at)).filter { it !== at || cursorFrame == 0 }
            val stamped = ahead.firstOrNull { it.frames.first().momentUs != null }
            if (stamped == null) return skipAll()
            cursorRun = stamped
            cursorFrame = 0
        }
    }

    /**
     * The cursor past every frame kept, on to the next keyframe: for a connection without moments, whose
     * recorder places frames by their arrival -- what was kept would be placed late, what was sent again twice.
     */
    fun skipKept() {
        lock.withLock { skipAll() }
    }

    /** The frame read last to be read again: one a connection read and did not send. */
    fun back() {
        lock.withLock { if (cursorFrame > 0) cursorFrame-- }
    }

    /**
     * How long the frame the cursor is at has been kept: [nowUs], on the frames' clock, minus its capture -- or,
     * read back from a store before, the wall clock now minus when it was kept, its capture clock perhaps started
     * again with the phone since.
     */
    fun heldMs(nowUs: Long?): Long {
        lock.withLock {
            val entry = nextEntry() ?: return 0
            return when {
                entry.readBack -> maxOf(wallClock() - entry.wallMs, 0)
                nowUs == null -> 0
                else -> maxOf((nowUs - entry.ptsUs) / 1000, 0)
            }
        }
    }

    /** The video kept and not sent yet ([Pending]). */
    val pending: Pending
        get() =
            lock.withLock {
                val next = nextEntry() ?: return Pending(0, 0)
                val newest = runs.last().frames.last()
                var before = 0L
                val at = cursorRun
                if (at != null) {
                    for (run in runs) {
                        if (run === at) {
                            before += run.frames.bytesBefore(cursorFrame)
                            break
                        }
                        before += run.bytes
                    }
                }
                Pending(maxOf((newest.ptsUs - next.ptsUs) / 1000, 0), total - before)
            }

    /**
     * A frame kept and not sent yet -- one as much as many -- or sent and not confirmed, [UNCONFIRMED_US] or more past
     * the newest the server confirmed: a dead connection may have swallowed it, to be sent again from there. The
     * acknowledgements' own window, under it, is not waited for, no frame coming after to bring them.
     */
    val unsent: Boolean
        get() =
            lock.withLock {
                val read = lastReadUs
                nextEntry() != null || read != null && read - (confirmedUs ?: Long.MIN_VALUE / 2) >= UNCONFIRMED_US
            }

    /** The frame the uplink reads next, if one is kept; the caller holds the lock. */
    private fun nextEntry(): Entry? {
        val run = cursorRun ?: runs.firstOrNull()
        return run?.frames?.getOrNull(cursorFrame) ?: run?.let { following(runs, it) }?.frames?.firstOrNull()
    }

    /**
     * Everything kept removed with its folder, and nothing kept from now on: the stream sent whole, or dropped at
     * the referee's word (specs/009, FR-004). A store closed has handed its files over: they are not its to remove.
     */
    fun clear() {
        lock.withLock {
            if (closed) return
            cleared = true
            closeFiles()
            runs.clear()
            total = 0
            cursorRun = null
            cursorFrame = 0
            lastReadUs = null
            more.signalAll()
        }
        folder.deleteRecursively() // outside the lock: a store of GBs holds no reader up as it goes
    }

    /**
     * The stream over: its files kept for a store made on the folder to send when it holds anything unsent --
     * true --, else removed with the folder, all of it sent: a store made on it would send its last run again, and
     * a new stream to the camera would wait for that (specs/009, FR-003).
     */
    fun handOver(): Boolean {
        val keep = lock.withLock { unsent } // its uplink stopped: nothing changes it now
        if (keep) close() else clear()
        return keep
    }

    /**
     * Its files synced and closed, kept for a store made on the folder to send (specs/009, FR-003): nothing is
     * kept or read from now on.
     */
    fun close() {
        val open =
            lock.withLock {
                if (cleared || closed) return
                closed = true
                val open = retired + listOfNotNull(writer, indexWriter)
                retired.clear()
                writer = null
                indexWriter = null
                closeFiles()
                more.signalAll()
                open
            }
        open.forEach {
            // synced outside the lock, as a run is ([retire])
            syncFile(it)
            close(it)
        }
    }

    private fun closeFiles() {
        retired.forEach { close(it) }
        retired.clear()
        close(writer)
        writer = null
        close(indexWriter)
        indexWriter = null
        close(reader)
        reader = null
        readerRun = null
    }

    /** The runs read past and wholly before what a connection after a loss would begin with, removed. */
    private fun prune() {
        val safe = safeBefore(confirmedUs, lastReadUs)
        while (runs.size > 1 && sent(runs.first(), cursorRun, safe)) removeOldest()
    }

    /**
     * What a store before left in the folder, read back: each run's frames up to the first whose index record or
     * bytes are not all there -- a crash, a power cut mid-write --, a run that holds none, or does not begin with a
     * keyframe, removed.
     */
    private fun readBack() {
        val files = folder.listFiles { file -> file.name.endsWith(DATA) } ?: return
        val numbered =
            files.mapNotNull { file ->
                file.name
                    .removeSuffix(DATA)
                    .toIntOrNull()
                    ?.let { it to file }
            }
        for ((number, file) in numbered.sortedBy { it.first }) {
            named = maxOf(named, number + 1)
            val run = Run(file)
            val read = readIndex(run)
            when {
                run.frames.firstOrNull()?.keyframe == true -> {
                    run.frames.trim()
                    runs += run
                    total += run.bytes
                }
                read -> {
                    file.delete()
                    run.index.delete()
                }
                else -> unreadable = true // the storage failing it: left, not taken for torn
            }
        }
    }

    /** [run]'s frames from its index; false when the storage would not read it -- not torn, failing. */
    private fun readIndex(run: Run): Boolean {
        val records =
            try {
                if (run.index.isFile) run.index.readBytes() else null
            } catch (_: IOException) {
                return false
            }
        if (records != null) parse(run, records)
        return true
    }

    /** The index's records into [run]'s frames, up to the first not marked, or whose bytes are not all there. */
    private fun parse(
        run: Run,
        records: ByteArray,
    ) {
        val length = run.file.length()
        val buffer = ByteBuffer.wrap(records)
        var whole = true
        while (whole && buffer.remaining() >= RECORD) {
            val marked = buffer.get() == MARK
            val flags = buffer.get().toInt()
            val size = buffer.int
            val ptsUs = buffer.long
            val momentUs = buffer.long
            val wallMs = buffer.long
            whole = marked && size > 0 && run.bytes + size <= length
            if (whole) {
                val moment = momentUs.takeIf { flags and HAS_MOMENT != 0 }
                run.frames += Entry(run.bytes, size, ptsUs, flags and KEYFRAME != 0, moment, wallMs, readBack = true)
                run.bytes += size
            }
        }
    }

    /**
     * [frame] written: a keyframe begins a run of its own, its file opened, the others go into the newest; false
     * when there is no run to take it -- no file for its keyframe -- or the write fails.
     */
    private fun append(
        frame: EncodedFrame,
        momentUs: Long?,
    ): Boolean {
        if (frame.keyframe) {
            runs.lastOrNull()?.frames?.trim() // the run before done: no room kept in it
            retired += listOfNotNull(writer, indexWriter) // synced once the lock is let go: a power cut costs a run
            writer = null
            indexWriter = null
            val run = Run(File(folder, "${named++}$DATA"))
            try {
                writer = FileOutputStream(run.file)
                indexWriter = FileOutputStream(run.index)
                runs += run
            } catch (_: IOException) {
                close(writer) // no run: this keyframe and its frames are dropped
                writer = null
                run.file.delete()
                run.index.delete()
            }
        }
        val run = runs.lastOrNull()
        val out = writer
        val index = indexWriter
        if (run == null || out == null || index == null) return false
        val entry = Entry(run.bytes, frame.data.size, frame.ptsUs, frame.keyframe, momentUs, wallClock())
        try {
            out.write(frame.data)
            index.write(record(entry)) // after its bytes: an index record names a frame all written
        } catch (_: IOException) {
            close(out)
            close(index)
            writer = null
            indexWriter = null
            if (run.frames.isEmpty()) {
                runs.removeLast()
                run.file.delete()
                run.index.delete()
            }
            return false
        }
        run.frames += entry
        run.bytes += frame.data.size
        total += frame.data.size
        more.signalAll()
        return true
    }

    private fun skipAll() {
        val last = runs.lastOrNull() ?: return
        cursorRun = last
        cursorFrame = last.frames.size
    }

    /** The frame at the cursor in [run], the cursor past it; null when its file cannot be read. */
    private fun read(run: Run): KeptFrame? {
        val entry = run.frames[cursorFrame]
        cursorRun = run
        cursorFrame++
        lastReadUs = maxOf(lastReadUs ?: entry.ptsUs, entry.ptsUs)
        val data = ByteArray(entry.size)
        return try {
            val file =
                reader.takeIf { readerRun === run } ?: RandomAccessFile(run.file, "r").also {
                    close(reader)
                    reader = it
                    readerRun = run
                }
            file.seek(entry.offset)
            file.readFully(data)
            KeptFrame(data, entry.ptsUs, entry.keyframe, entry.momentUs)
        } catch (_: IOException) {
            null // its file gone: the uplink asks for the next frame
        }
    }

    /**
     * No room for a run more at [nowUs]: the phone under [minFreeBytes] free, or the store over [floorBytes] with the
     * phone under [reserveBytes] free -- and the oldest run older than [KEPT_ANYWAY_US]: a full phone still rides out
     * a hiccup, as with the queue before the store.
     */
    private fun full(nowUs: Long): Boolean {
        val oldest = runs.first().frames.last()
        if (oldest.ptsUs >= nowUs - KEPT_ANYWAY_US) return false
        val free = freeBytes()
        return free < minFreeBytes || total > floorBytes && free < reserveBytes
    }

    /** The oldest run removed with its file; returns its frames not read yet. */
    private fun removeOldest(): Int {
        val run = runs.removeFirst()
        total -= run.bytes
        if (readerRun === run) {
            close(reader)
            reader = null
            readerRun = null
        }
        run.file.delete()
        run.index.delete()
        val unread =
            when {
                cursorRun == null -> run.frames.size
                cursorRun === run -> run.frames.size - cursorFrame
                else -> 0
            }
        if (cursorRun === run) {
            cursorRun = null
            cursorFrame = 0
        }
        return unread
    }

    companion object {
        /**
         * How far before the newest frame the server confirmed a connection after a loss begins: what a recorder
         * killed after it confirmed had not written yet.
         */
        const val CONFIRMED_MARGIN_US = 2_000_000L

        /** Frames read and not confirmed this far past the newest confirmed: perhaps swallowed, not taken for sent. */
        const val UNCONFIRMED_US = 1_000_000L

        /**
         * How far before the newest frame read it begins when the server confirms nothing: a send hangs 5 s before
         * the uplink gives the connection up, and keyframes come every second.
         */
        const val KEEP_SENT_US = 6_000_000L

        /** Left free on the phone (specs/009, FR-005): the stores take the rest. */
        const val RESERVE_BYTES = 10L shl 30

        /** What a store holds however short of the reserve the phone is, while it keeps [MIN_FREE_BYTES] free. */
        const val FLOOR_BYTES = 1L shl 30

        /** Left free on the phone whatever: a phone full to the brim fails more than the stream. */
        const val MIN_FREE_BYTES = 1L shl 30

        /** Kept however short of space the phone is: the two seconds the uplink's queue held before the store. */
        const val KEPT_ANYWAY_US = 2_000_000L

        private const val DATA = ".h264"
        private const val INDEX = ".idx"

        /** An index record: its mark, flags, the frame's size, capture time, moment and wall-clock time. */
        private const val RECORD = 1 + 1 + Int.SIZE_BYTES + 3 * Long.SIZE_BYTES
        private const val MARK = 'F'.code.toByte()
        private const val KEYFRAME = 1
        private const val HAS_MOMENT = 2
        private const val READ_BACK = 4
        private const val NO_MOMENT = Long.MIN_VALUE
        private const val FIRST_ROOM = 32 // a second's run at 30 fps; at 60, grown once

        private fun record(entry: Entry): ByteArray {
            val flags = (if (entry.keyframe) KEYFRAME else 0) or (if (entry.momentUs != null) HAS_MOMENT else 0)
            return ByteBuffer
                .allocate(RECORD)
                .put(MARK)
                .put(flags.toByte())
                .putInt(entry.size)
                .putLong(entry.ptsUs)
                .putLong(entry.momentUs ?: 0)
                .putLong(entry.wallMs)
                .array()
        }

        /** [out] written through to the storage; a sync that fails leaves it to the system. */
        private fun sync(out: FileOutputStream?) {
            try {
                out?.fd?.sync()
            } catch (_: IOException) {
                // the storage failing: the frames are in the system's hands, as they were
            }
        }

        private fun following(
            runs: ArrayDeque<Run>,
            run: Run,
        ): Run? = runs.getOrNull(runs.indexOf(run) + 1)

        /** Where a connection after a loss begins: before what the server may not have; null before any read. */
        private fun safeBefore(
            confirmedUs: Long?,
            lastReadUs: Long?,
        ): Long? = confirmedUs?.minus(CONFIRMED_MARGIN_US) ?: lastReadUs?.minus(KEEP_SENT_US)

        /** [run] read past, and wholly before [safeUs]: not to be sent again. */
        private fun sent(
            run: Run,
            cursor: Run?,
            safeUs: Long?,
        ): Boolean {
            if (cursor == null || safeUs == null || run === cursor) return false
            return run.frames.last().ptsUs < safeUs
        }

        private fun close(closeable: Closeable?) {
            try {
                closeable?.close()
            } catch (_: IOException) {
                // a file that will not close is dropped with its run
            }
        }
    }
}
