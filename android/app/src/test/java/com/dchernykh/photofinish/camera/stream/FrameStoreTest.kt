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

    private fun store(
        capBytes: Long = Long.MAX_VALUE,
        free: () -> Long = { Long.MAX_VALUE },
    ) = FrameStore(folder, capBytes, reserveBytes = 1_000, freeBytes = free)

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
        assertEquals(8, folder.listFiles()!!.size) // 4 s to 10 s, kept to be sent again; then 11 s
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
        assertEquals(12, folder.listFiles()!!.size) // 0.5 s on: none goes
        store.confirm(9_000_000)
        second(store, 12)
        assertEquals(6, folder.listFiles()!!.size) // the 7 runs ending before 7 s go
    }

    @Test
    fun `over its share the store drops its oldest frames not sent, from a keyframe on`() {
        val store = store(capBytes = 2_500)
        assertEquals(0, second(store, 0))
        assertEquals(0, second(store, 1))
        read(store, 3)
        assertEquals(0, second(store, 2)) // 3,000 bytes kept: the oldest goes at the next run
        assertEquals(7, second(store, 3)) // the 7 frames of 0 s not read
        assertEquals(1_000_000L, store.next(0)!!.ptsUs) // on from the oldest kept, a keyframe
    }

    @Test
    fun `a phone short of space keeps less, whatever the store's share`() {
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
    fun `clear removes what is kept and keeps nothing after`() {
        val store = store()
        second(store, 0)
        store.clear()
        assertTrue(folder.listFiles()!!.isEmpty())
        assertEquals(0, store.keep(frame(1_000_000, keyframe = true), null))
        assertNull(store.next(0))
        assertTrue(folder.listFiles()!!.isEmpty())
    }

    @Test
    fun `what an earlier store left is removed at the start`() {
        folder.mkdirs()
        File(folder, "0.h264").writeBytes(ByteArray(10))
        store()
        assertTrue(folder.listFiles()!!.isEmpty())
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
}
