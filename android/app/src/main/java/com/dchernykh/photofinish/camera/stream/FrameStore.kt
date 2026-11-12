package com.dchernykh.photofinish.camera.stream

import java.io.Closeable
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.RandomAccessFile
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
 * A lens's frames on the phone's own storage, from the encoder to the uplink (specs/007), so that a break,
 * a slow network or a recorder starting again costs no frame while there is room. The frames of one
 * keyframe's run share a file; their index -- place, capture time, moment -- is in memory, as the store does
 * not outlive the app (FR-004). The uplink reads at a cursor; a frame read stays until the server has
 * confirmed reading it ([confirm]), [CONFIRMED_MARGIN_US] more, to be sent again after a loss ([rewind]) --
 * or [KEEP_SENT_US] after the newest frame read, from a server that confirms nothing. Over [capBytes], or
 * with less than [reserveBytes] left on the phone -- then none of the last [KEPT_ANYWAY_US] -- the oldest run
 * goes, its frames not read yet dropped.
 */
class FrameStore(
    private val folder: File,
    private val capBytes: Long,
    private val reserveBytes: Long = RESERVE_BYTES,
    private val freeBytes: () -> Long = { folder.usableSpace },
) {
    private class Entry(
        val offset: Long,
        val size: Int,
        val ptsUs: Long,
        val keyframe: Boolean,
        val momentUs: Long?,
    )

    private class Run(
        val file: File,
    ) {
        val frames = ArrayList<Entry>()
        var bytes = 0L
    }

    private val lock = ReentrantLock()
    private val more = lock.newCondition()
    private val runs = ArrayDeque<Run>()

    /** The newest run's file, open until a write to it fails. */
    private var writer: FileOutputStream? = null
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

    init {
        empty(folder)
    }

    /**
     * Keeps [frame] with its [momentUs]; returns the frames dropped meanwhile: the oldest not read yet, for
     * room, and this one when it cannot be written or has no keyframe before it to start from.
     */
    fun keep(
        frame: EncodedFrame,
        momentUs: Long?,
    ): Int {
        lock.withLock {
            if (cleared) return 0
            var dropped = 0
            if (frame.keyframe) {
                val safe = safeBefore(confirmedUs, lastReadUs)
                while (runs.size > 1 && sent(runs.first(), cursorRun, safe)) removeOldest()
                while (runs.isNotEmpty() && full(frame.ptsUs)) dropped += removeOldest()
            }
            return dropped + if (append(frame, momentUs)) 0 else 1
        }
    }

    /** The next frame to send, waiting up to [waitMs] for one; null when none came, or the store was cleared. */
    fun next(waitMs: Long): KeptFrame? {
        lock.withLock {
            var left = TimeUnit.MILLISECONDS.toNanos(waitMs)
            while (!cleared) {
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

    /** The server has read the frame taken at [ptsUs], and every one before it. */
    fun confirm(ptsUs: Long) {
        lock.withLock { confirmedUs = maxOf(confirmedUs ?: ptsUs, ptsUs) }
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

    /**
     * The cursor on to the first keyframe kept with a moment, at or after it, so that a connection's frames
     * all carry their moments; past every frame kept when none has one yet: on to the next keyframe.
     */
    fun skipToStamped() {
        lock.withLock {
            val at = cursorRun ?: runs.firstOrNull() ?: return
            val ahead = runs.drop(runs.indexOf(at)).filter { it !== at || cursorFrame == 0 }
            val stamped = ahead.firstOrNull { it.frames.first().momentUs != null }
            cursorRun = stamped ?: runs.last()
            cursorFrame = if (stamped != null) 0 else runs.last().frames.size
        }
    }

    /** How long the frame the cursor is at has been kept: [nowUs], on the frames' clock, minus its capture. */
    fun heldMs(nowUs: Long?): Long {
        lock.withLock {
            val run = cursorRun ?: runs.firstOrNull()
            val entry = run?.frames?.getOrNull(cursorFrame) ?: run?.let { following(runs, it) }?.frames?.first()
            return if (nowUs == null || entry == null) 0 else maxOf((nowUs - entry.ptsUs) / 1000, 0)
        }
    }

    /** Everything kept removed, and nothing kept from now on: the stream has ended (FR-004). */
    fun clear() {
        lock.withLock {
            cleared = true
            close(writer)
            writer = null
            close(reader)
            reader = null
            readerRun = null
            runs.clear()
            total = 0
            cursorRun = null
            cursorFrame = 0
            lastReadUs = null
            empty(folder)
            more.signalAll()
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
            close(writer)
            writer = null
            val file = File(folder, "${named++}.h264")
            try {
                writer = FileOutputStream(file)
                runs += Run(file)
            } catch (_: IOException) {
                file.delete() // no run: this keyframe and its frames are dropped
            }
        }
        val run = runs.lastOrNull()
        val out = writer
        if (run == null || out == null) return false
        try {
            out.write(frame.data)
        } catch (_: IOException) {
            close(out)
            writer = null
            if (run.frames.isEmpty()) {
                runs.removeLast()
                run.file.delete()
            }
            return false
        }
        run.frames += Entry(run.bytes, frame.data.size, frame.ptsUs, frame.keyframe, momentUs)
        run.bytes += frame.data.size
        total += frame.data.size
        more.signalAll()
        return true
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
     * No room for a run more at [nowUs]: over the share, or the phone short of space -- which takes no run of
     * the last [KEPT_ANYWAY_US], as the queue before the store did not: a full phone still rides out a hiccup.
     */
    private fun full(nowUs: Long): Boolean =
        total > capBytes || (freeBytes() < reserveBytes && runs.first().frames.last().ptsUs < nowUs - KEPT_ANYWAY_US)

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

        /**
         * How far before the newest frame read it begins when the server confirms nothing: a send hangs 5 s before
         * the uplink gives the connection up, and keyframes come every second.
         */
        const val KEEP_SENT_US = 6_000_000L

        /** All the lenses' stores together. */
        const val SHARE_BYTES = 2L shl 30

        /** Left free on the phone, whatever the store's share. */
        const val RESERVE_BYTES = 1L shl 30

        /** Kept however short of space the phone is: the two seconds the uplink's queue held before the store. */
        const val KEPT_ANYWAY_US = 2_000_000L

        /** [folder] made, and emptied of what an earlier store left: a killed app's frames are not sent. */
        fun empty(folder: File) {
            folder.mkdirs()
            folder.listFiles()?.forEach { it.delete() }
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
