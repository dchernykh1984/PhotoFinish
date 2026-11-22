package com.dchernykh.photofinish.camera.stream

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class FrameStoreTest {
    @get:Rule
    val temporary = TemporaryFolder()

    private val folder: File get() = File(temporary.root, "kept")

    private var wallMs = 1_000_000L

    private fun store(
        floorBytes: Long = Long.MAX_VALUE,
        free: () -> Long = { Long.MAX_VALUE },
    ) = FrameStore(folder, floorBytes, reserveBytes = 10_000, minFreeBytes = 1_000, freeBytes = free, wallClock = {
        wallMs
    })

    /** The runs kept, by their frames' files. */
    private fun runs(): Int = folder.listFiles()!!.count { it.name.endsWith(".h264") }

    /** A frame of [size] bytes, each its capture second's low byte: what is read back can be told apart. */
    private fun frame(
        ptsUs: Long,
        keyframe: Boolean,
        size: Int = 100,
    ) = EncodedFrame(ByteArray(size) { (ptsUs / 1000).toByte() }, ptsUs, keyframe)

    /** A second of frames at 10 fps from [second], a keyframe first; returns the frames dropped. */
    private fun second(
        store: FrameStore,
        second: Int,
        moment: Boolean = true,
        size: Int = 100,
    ): Int =
        (0 until 10).sumOf { k ->
            val pts = second * 1_000_000L + k * 100_000L
            store.keep(frame(pts, keyframe = k == 0, size = size), if (moment) pts + 5_000_000 else null)
        }

    private fun read(
        store: FrameStore,
        count: Int,
    ): List<Long> = List(count) { store.next(0)?.ptsUs ?: error("frame ${it + 1} of $count missing") }

    @Test
    fun `frames come back in order, with their bytes and moments, and none is waited for long`() {
        val store = store()
        assertEquals(0, store.keep(frame(0, keyframe = true), 5_000_000))
        assertEquals(0, store.keep(frame(100_000, keyframe = false), null))
        val first = store.next(0)!!
        assertTrue(first.keyframe)
        assertEquals(5_000_000L, first.momentUs)
        assertArrayEquals(frame(0, keyframe = true).data, first.data)
        val second = store.next(0)!!
        assertFalse(second.keyframe)
        assertNull(second.momentUs)
        assertEquals(100_000L, second.ptsUs)
        val since = System.nanoTime()
        assertNull(store.next(50))
        assertTrue((System.nanoTime() - since) / 1_000_000 >= 40)
    }

    @Test
    fun `a frame with no keyframe before it to start from is dropped`() {
        val store = store()
        assertEquals(1, store.keep(frame(0, keyframe = false), null))
        assertNull(store.next(0))
        store.keep(frame(100_000, keyframe = true), null)
        assertEquals(100_000L, store.next(0)!!.ptsUs)
    }

    @Test
    fun `after a loss a connection begins two seconds before the newest frame the server read`() {
        val store = store()
        repeat(11) { second(store, it) }
        read(store, 105) // up to 10.4 s sent: the buffers on the way took the rest
        store.confirm(3_500_000)
        store.confirm(2_000_000) // an older word: the newest stands
        store.rewind()
        assertEquals(1_000_000L, store.next(0)!!.ptsUs) // 1.5 s, back to its second's keyframe
    }

    @Test
    fun `from a server that confirms nothing it begins six seconds before the newest frame read`() {
        val store = store()
        repeat(11) { second(store, it) }
        read(store, 105) // up to 10.4 s
        store.rewind()
        assertEquals(4_000_000L, store.next(0)!!.ptsUs) // 4.4 s back to its second's keyframe
        read(store, 3)
        store.rewind() // a loss after a loss: from the newest read, not further and further back
        assertEquals(4_000_000L, store.next(0)!!.ptsUs)
    }

    @Test
    fun `before anything is read a connection begins at the oldest frame kept`() {
        val store = store()
        second(store, 0)
        second(store, 1)
        store.rewind()
        assertEquals(0L, store.next(0)!!.ptsUs)
    }

    @Test
    fun `runs read and older than six seconds go with their files, the rest stays`() {
        val store = store()
        repeat(3) { second(store, it) }
        read(store, 30)
        repeat(8) { second(store, it + 3) } // read on to 10.9 s
        read(store, 80)
        second(store, 11) // its keyframe makes room
        assertEquals(8, runs()) // 4 s to 10 s, kept to be sent again; then 11 s
        store.rewind()
        assertEquals(4_000_000L, store.next(0)!!.ptsUs)
    }

    @Test
    fun `runs after the newest the server confirmed stay, however long ago they were read`() {
        val store = store()
        repeat(11) { second(store, it) }
        read(store, 110)
        store.confirm(2_500_000) // the server stopped reading there: the rest may be lost
        second(store, 11)
        assertEquals(12, runs()) // 0.5 s on: none goes
        store.confirm(9_000_000)
        assertEquals(5, runs()) // the 7 runs ending before 7 s go as the server says so
        second(store, 12)
        assertEquals(6, runs())
    }

    @Test
    fun `over its floor, the phone short of the reserve, the store drops its oldest frames not sent`() {
        val store = store(floorBytes = 2_500, free = { 5_000 })
        assertEquals(0, second(store, 0))
        assertEquals(0, second(store, 1))
        read(store, 3)
        assertEquals(0, second(store, 2)) // 3,000 bytes kept: the oldest goes at the next run
        assertEquals(7, second(store, 3)) // the 7 frames of 0 s not read
        assertEquals(1_000_000L, store.next(0)!!.ptsUs) // on from the oldest kept, a keyframe
    }

    @Test
    fun `under its floor the store keeps all, the phone short of the reserve but not of its last free space`() {
        val store = store(floorBytes = 10_000, free = { 5_000 })
        (0..4).forEach { assertEquals(0, second(store, it)) }
        assertEquals(0L, store.next(0)!!.ptsUs)
    }

    @Test
    fun `a phone short of space keeps less, whatever the store's floor`() {
        var free = Long.MAX_VALUE
        val store = store(free = { free })
        (0..3).forEach { second(store, it) }
        free = 500 // under the reserve
        assertEquals(20, second(store, 4)) // the runs of 0 s and 1 s go; the last two seconds stay
        assertEquals(2_000_000L, store.next(0)!!.ptsUs)
    }

    @Test
    fun `a phone short of space from the start still keeps the last two seconds not sent`() {
        val store = store(free = { 500 })
        assertEquals(0, second(store, 0))
        assertEquals(0, second(store, 1))
        assertEquals(0, second(store, 2)) // a hiccup of two seconds costs no frame, as before the store
        assertEquals(10, second(store, 3)) // the run of 0 s goes, now three seconds old
        assertEquals(listOf(1_000_000L, 1_100_000L), read(store, 2))
    }

    @Test
    fun `a connection's frames begin at the first keyframe kept with a moment`() {
        val store = store()
        second(store, 0, moment = false)
        second(store, 1)
        store.skipToStamped()
        assertEquals(1_000_000L, store.next(0)!!.ptsUs)
    }

    @Test
    fun `with no moment kept yet a connection waits for the next keyframe`() {
        val store = store()
        second(store, 0, moment = false)
        store.skipToStamped()
        assertNull(store.next(0))
        second(store, 1)
        assertEquals(1_000_000L, store.next(0)!!.ptsUs)
    }

    @Test
    fun `a connection without moments skips what was kept, on to the next keyframe`() {
        val store = store()
        second(store, 0, moment = false)
        store.keep(frame(950_000, keyframe = false), null) // the last run's: past it too
        store.skipKept()
        assertNull(store.next(0))
        second(store, 1, moment = false)
        assertEquals(1_000_000L, store.next(0)!!.ptsUs)
    }

    @Test
    fun `a frame read and not sent is read again`() {
        val store = store()
        second(store, 0)
        read(store, 2)
        store.back()
        assertEquals(listOf(100_000L, 200_000L), read(store, 2))
    }

    @Test
    fun `a frame not sent yet, or sent and not confirmed, is told unsent`() {
        val store = store()
        assertEquals(false, store.unsent)
        second(store, 0)
        read(store, 9)
        assertEquals(true, store.unsent) // one frame left, not sent
        read(store, 1)
        assertEquals(true, store.unsent) // none confirmed: perhaps swallowed by a dead connection
        store.confirm(0)
        assertEquals(true, store.unsent) // 0.9 s past the newest confirmed: the recorder may not have it
        store.confirm(900_000)
        assertEquals(false, store.unsent)
    }

    @Test
    fun `frames read and not confirmed are not taken for sent, however near the newest confirmed`() {
        val store = store()
        second(store, 0)
        second(store, 1)
        second(store, 2)
        read(store, 30) // up to 2.9 s, written to a connection that died
        store.confirm(2_000_000)
        assertEquals(true, store.unsent) // its last 0.9 s may never reach the recorder
        store.confirm(2_900_000)
        assertEquals(false, store.unsent)
    }

    @Test
    fun `a newest frame the storage will not read holds the stream unsent for nothing`() {
        val store = store()
        second(store, 0)
        store.keep(frame(1_000_000, keyframe = true), 1) // the newest, in a run of its own
        File(folder, "1.h264").setReadable(false)
        read(store, 10)
        assertNull(store.next(0)) // passed over
        store.confirm(900_000) // all it could send confirmed
        assertFalse(store.unsent)
        File(folder, "1.h264").setReadable(true)
    }

    @Test
    fun `frames before a connection's keyframe are passed over, never read to be confirmed`() {
        val store = store()
        second(store, 0)
        assertEquals(0L, store.next(0)?.ptsUs) // the keyframe sent
        store.confirm(0)
        assertNull(store.next(0, fromKeyframe = true)) // a new connection: no keyframe after it yet
        assertFalse(store.unsent) // the frames passed over will never be sent: nothing left unconfirmed
        second(store, 1)
        assertEquals(1_000_000L, store.next(0, fromKeyframe = true)?.ptsUs)
    }

    @Test
    fun `how long the frame to send next has been kept is told`() {
        val store = store()
        assertEquals(0L, store.heldMs(9_000_000))
        second(store, 0)
        assertEquals(9_000L, store.heldMs(9_000_000))
        read(store, 10)
        second(store, 1)
        assertEquals(8_000L, store.heldMs(9_000_000)) // the next run's first frame
        assertEquals(0L, store.heldMs(null)) // the frames' clock unknown
    }

    @Test
    fun `clear removes what is kept, its folder too, and keeps nothing after`() {
        val store = store()
        second(store, 0)
        store.clear()
        assertFalse(folder.exists())
        assertEquals(0, store.keep(frame(1_000_000, keyframe = true), null))
        assertNull(store.next(0))
        assertFalse(folder.exists())
    }

    @Test
    fun `what a store before left is read back, frames, moments and all, and sent`() {
        val before = store()
        second(before, 0)
        second(before, 1, moment = false)
        before.close()
        val store = store()
        val first = store.next(0)!!
        assertTrue(first.keyframe)
        assertEquals(5_000_000L, first.momentUs)
        assertArrayEquals(frame(0, keyframe = true).data, first.data)
        assertEquals((1 until 20).map { it * 100_000L }, read(store, 19))
        assertNull(store.next(0))
        assertEquals(2, runs())
    }

    @Test
    fun `a store made on a folder goes on numbering after the runs it read back`() {
        val before = store()
        second(before, 0)
        before.close()
        val store = store()
        second(store, 5)
        assertEquals(listOf("0.h264", "1.h264"), folder.list()!!.filter { it.endsWith(".h264") }.sorted())
        assertEquals(listOf(0L, 100_000L), read(store, 2))
    }

    @Test
    fun `a frame not all written is not read back, nor anything after it in its run`() {
        val before = store()
        second(before, 0)
        second(before, 1)
        before.close()
        val data = File(folder, "0.h264")
        data.writeBytes(data.readBytes().copyOf(450)) // a power cut in the fifth frame's bytes
        val store = store()
        assertEquals(listOf(0L, 100_000L, 200_000L, 300_000L, 1_000_000L), read(store, 5))
    }

    @Test
    fun `an index record cut short or not marked ends its run`() {
        val before = store()
        second(before, 0)
        second(before, 1)
        before.close()
        val index = File(folder, "0.idx")
        val records = index.readBytes()
        index.writeBytes(records.copyOf(records.size / 10 * 3 + 7)) // three records and a piece
        File(folder, "1.idx").writeBytes(ByteArray(records.size)) // zeros, as a power cut may leave
        val store = store()
        assertEquals(listOf(0L, 100_000L, 200_000L), read(store, 3))
        assertNull(store.next(0))
        assertEquals(1, runs()) // the run with no frame read back is removed
    }

    @Test
    fun `a run without its index is removed at the start`() {
        val before = store()
        second(before, 0)
        before.close()
        File(folder, "0.idx").delete()
        val store = store()
        assertNull(store.next(0))
        assertEquals(0, runs())
    }

    @Test
    fun `frames read back are held by the wall clock, their capture clock started again since`() {
        val before = store()
        second(before, 0)
        before.close()
        wallMs += 90_000 // the phone restarted: its frames' clock is no clock to go by
        val store = store()
        assertEquals(90_000L, store.heldMs(5L))
        assertEquals(90_000L, store.heldMs(null))
    }

    @Test
    fun `a store handed over keeps its files while anything is unsent, and removes them once all is sent`() {
        val holding = store()
        second(holding, 0)
        assertTrue(holding.handOver())
        assertEquals(1, runs())
        val sent = store() // reads the run back
        read(sent, 10)
        sent.confirm(5_000_000)
        assertFalse(sent.handOver())
        assertFalse(folder.exists())
    }

    @Test
    fun `a store closed waits for what was asked of the stores' thread before it, the stream's header among it`() {
        val store = store()
        second(store, 0)
        val gate = java.util.concurrent.CountDownLatch(1)
        store.syncOff(Runnable { gate.await(5, java.util.concurrent.TimeUnit.SECONDS) }) // a slow flash's sync
        val written =
            java.util.concurrent.atomic
                .AtomicBoolean(false)
        store.syncOff(Runnable { written.set(true) }) // the stream's header, asked after it
        val closing = Thread { store.close() }.apply { start() }
        closing.join(300)
        assertTrue(closing.isAlive) // the hand-over would read the folder back before its header is there
        gate.countDown()
        closing.join(5_000)
        assertTrue(written.get())
    }

    @Test
    fun `a while no camera fed the stream is not counted as video held`() {
        val store = store()
        second(store, 0)
        second(store, 600) // the screen away ten minutes, the stream fed again
        assertEquals(2_800L, store.pending.ms) // two seconds of frames and a second for the gap, not ten minutes
        assertEquals(2_800L, store.behindMs) // as the other lenses ask it, its bytes not counted
        read(store, 10)
        assertEquals(900L, store.pending.ms)
        assertEquals(900L, store.behindMs)
        read(store, 10)
        assertEquals(0L, store.behindMs)
    }

    @Test
    fun `a store closed closes its newest run's files`() {
        val stores =
            List(50) {
                FrameStore(File(temporary.root, "store-$it"), freeBytes = { Long.MAX_VALUE }).apply {
                    keep(frame(0, keyframe = true), 1)
                }
            }
        val before = File("/dev/fd").list()!!.size
        stores.forEach { it.close() }
        val closed = before - File("/dev/fd").list()!!.size
        assertTrue("$closed files closed", closed > 50) // two a store, 100; the test's other threads open a few
    }

    @Test
    fun `runs waiting for a slow flash's sync hold no file open`() {
        val store = store()
        val gate = java.util.concurrent.CountDownLatch(1)
        store.syncFile = { gate.await(5, java.util.concurrent.TimeUnit.SECONDS) }
        val before = File("/dev/fd").list()!!.size
        repeat(100) { second(store, it) }
        val open = File("/dev/fd").list()!!.size - before
        gate.countDown()
        // The newest run's two, not two for each run waiting its sync: 200; the test's other threads open a few.
        assertTrue("$open files open", open < 50)
    }

    @Test
    fun `a run is synced outside the store's lock, holding no reader up`() {
        val store = store()
        val syncing = java.util.concurrent.CountDownLatch(1)
        val release = java.util.concurrent.CountDownLatch(1)
        store.syncFile = {
            syncing.countDown()
            release.await(5, java.util.concurrent.TimeUnit.SECONDS)
        }
        second(store, 0) // the first run: none before it to sync
        val since = System.nanoTime()
        store.keep(frame(1_000_000, keyframe = true), 1) // the encoder's thread: on at once
        assertTrue(System.nanoTime() - since < 1_000_000_000)
        assertTrue(syncing.await(5, java.util.concurrent.TimeUnit.SECONDS)) // the run of 0 s being synced elsewhere
        assertEquals(1_000L, store.pending.ms) // not held up by the sync
        release.countDown()
        assertEquals(2, runs())
    }

    @Test
    fun `a run of more frames than its first room grows, and reads back whole`() {
        val before = store()
        repeat(150) { before.keep(frame(it * 16_667L, keyframe = it % 70 == 0), it * 16_667L + 5) }
        assertEquals((0 until 150).map { it * 16_667L }, read(before, 150))
        before.close()
        val store = store()
        val back = (0 until 150).map { store.next(0)!! }
        assertEquals((0 until 150).map { it * 16_667L }, back.map { it.ptsUs })
        assertEquals((0 until 150).map { it * 16_667L + 5 }, back.map { it.momentUs })
        assertEquals(listOf(0, 70, 140), back.withIndex().filter { it.value.keyframe }.map { it.index })
    }

    @Test
    fun `a closed store keeps its files, its clear not the next store's to suffer`() {
        val store = store()
        second(store, 0)
        store.close()
        store.clear()
        assertEquals(0, store.keep(frame(1_000_000, keyframe = true), null))
        assertNull(store.next(0))
        assertEquals(1, runs())
    }

    @Test
    fun `what is pending is the span from the next frame to the newest and its bytes`() {
        val store = store()
        assertEquals(FrameStore.Pending(0, 0), store.pending)
        second(store, 0, size = 10)
        second(store, 1, size = 10)
        assertEquals(FrameStore.Pending(1_900, 200), store.pending)
        read(store, 12)
        assertEquals(FrameStore.Pending(700, 80), store.pending)
        read(store, 8)
        assertEquals(FrameStore.Pending(0, 0), store.pending)
    }

    @Test
    fun `a run whose file cannot be made is dropped, its frames too, until a keyframe can be`() {
        val store = store()
        folder.deleteRecursively()
        folder.writeBytes(ByteArray(0)) // a file where the folder was: nothing can be written
        assertEquals(1, store.keep(frame(0, keyframe = true), null))
        assertEquals(1, store.keep(frame(100_000, keyframe = false), null))
        folder.delete()
        folder.mkdirs()
        assertEquals(0, store.keep(frame(200_000, keyframe = true), null))
        assertEquals(200_000L, store.next(0)!!.ptsUs)
    }

    @Test
    fun `a frame whose file went is skipped`() {
        val store = store()
        second(store, 0)
        second(store, 1)
        folder.listFiles()!!.single { it.name == "0.h264" }.delete()
        assertNull(store.next(0)) // the first frame's file is gone
        repeat(9) { store.next(0) }
        assertEquals(1_000_000L, store.next(0)!!.ptsUs)
    }

    private fun piece(ptsUs: Long) = EncodedFrame(ByteArray(10) { 7 }, ptsUs, keyframe = false, sound = true)

    @Test
    fun `a piece of sound goes in the run of the frames it was heard with, read back as sound`() {
        val store = store()
        assertEquals(0, store.keep(piece(0), null)) // before any keyframe: no run, and no frame dropped
        store.keep(frame(100_000, keyframe = true), 105_000)
        assertEquals(0, store.keep(piece(110_000), null))
        store.keep(frame(200_000, keyframe = false), 205_000)
        val read = List(3) { store.next(0)!! }
        assertEquals(listOf(false, true, false), read.map { it.sound })
        assertEquals(listOf(100_000L, 110_000L, 200_000L), read.map { it.ptsUs })
        assertNull(read[1].momentUs)
        store.close()
        val again = store() // the app started again: its sound with its frames
        assertEquals(listOf(false, true, false), List(3) { again.next(0)!!.sound })
    }

    @Test
    fun `a piece read before a frame taken earlier confirms nothing past it, which a rewind never skips`() {
        // A piece encoded sooner than a frame taken before it is kept, and read, first: the server's word on the
        // piece says nothing of the frame. A connection held for the first lens begins from the newest confirmed.
        val store = store()
        store.keep(frame(100_000, keyframe = true), 105_000)
        store.keep(piece(150_000), null)
        store.keep(frame(133_333, keyframe = false), 138_333) // taken before the piece, encoded after it
        store.keep(frame(140_000, keyframe = true), 145_000) // a run of its own
        read(store, 2) // the keyframe and the piece, sent
        store.confirm(150_000)
        store.rewind(0)
        val again = List(4) { store.next(0, fromKeyframe = it == 0)!!.ptsUs }
        assertEquals(listOf(100_000L, 150_000L, 133_333L, 140_000L), again)
    }

    @Test
    fun `a run ending on a piece of sound taken before its last frame tells that frame its newest`() {
        // The encoder behind the microphone: a run's last entry a piece older than its last frame. How far behind
        // the stream is goes by its newest frame, never by that piece.
        val store = store()
        store.keep(frame(100_000, keyframe = true), 105_000)
        store.keep(frame(200_000, keyframe = false), 205_000)
        store.keep(frame(1_000_000, keyframe = true), 1_005_000) // the newest run
        store.keep(piece(950_000), null) // heard before its frame, kept after it
        store.next(0)
        assertEquals(800L, store.behindMs) // from the next frame, 200 ms, to the newest, 1000 ms
        assertEquals(800L, store.pending.ms)
    }

    @Test
    fun `a connection's start passes over the sound before its keyframe`() {
        val store = store()
        store.keep(frame(0, keyframe = true), 5_000)
        store.keep(piece(10_000), null)
        store.keep(frame(100_000, keyframe = false), 105_000)
        store.keep(frame(1_000_000, keyframe = true), 1_005_000)
        store.keep(piece(1_010_000), null)
        store.next(0)
        assertEquals(1_000_000L, store.next(0, fromKeyframe = true)?.ptsUs)
        assertTrue(store.next(0)!!.sound)
    }

    @Test
    fun `a run let go for room counts its frames dropped, not its pieces of sound`() {
        var free = Long.MAX_VALUE
        val store = store(floorBytes = 0, free = { free })
        store.keep(frame(0, keyframe = true), 5_000)
        repeat(4) { store.keep(piece(10_000L + it * 21_000), null) }
        store.keep(frame(100_000, keyframe = false), 105_000)
        free = 0 // no room: the oldest run goes for the next
        assertEquals(2, store.keep(frame(3_000_000, keyframe = true), 3_005_000))
    }
}
