package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import com.dchernykh.photofinish.camera.stream.EncodedFrame
import com.dchernykh.photofinish.camera.stream.FrameStore
import com.dchernykh.photofinish.camera.stream.StreamHeader
import com.dchernykh.photofinish.camera.stream.Uplink
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class BacklogTest {
    @get:Rule
    val temporary = TemporaryFolder()

    private val root: File get() = File(temporary.root, "kept")
    private val first = RtmpAddress("10.0.0.2", 1935, "live", "cam1")
    private val second = RtmpAddress("10.0.0.2", 1936, "live", "cam2")
    private val format = StreamFormat(Resolution(1920, 1080), 10, FpsRange(10, 10), 5_000_000)

    /** The stores the backlog sent, in the order it started them, and those it stopped. */
    private val started = mutableListOf<FrameStore>()
    private val stopped = mutableListOf<FrameStore>()
    private val said = mutableListOf<String>()

    private val backlog by lazy {
        Backlog(
            root,
            send = { header, store ->
                started += store
                val uplink = Uplink(header.address, header.format, { null }, {}, {}, store, alone = true)
                Backlog.Sending(uplink) { stopped += store }
            },
            say = { lens, text -> said += "${lens.code}: $text" },
        )
    }

    /** A stream kept in `<lens>-<began>`, [seconds] of frames at 10 fps with their moments, its header beside. */
    private fun kept(
        began: Long,
        address: RtmpAddress = first,
        seconds: Int = 1,
        header: Boolean = true,
        lens: Lens = Lens.MAIN,
    ): File {
        val folder = File(root, "${lens.code}-$began")
        val store = FrameStore(folder, freeBytes = { Long.MAX_VALUE })
        repeat(seconds * 10) { k ->
            store.keep(EncodedFrame(ByteArray(100), k * 100_000L, k % 10 == 0), 5_000_000L + k * 100_000L)
        }
        store.close()
        if (header) StreamHeader(lens, address, format, byteArrayOf(1, 2, 3)).write(folder)
        return folder
    }

    /** What [store] holds sent and confirmed: nothing unsent. */
    private fun sendAll(store: FrameStore) {
        var last = 0L
        while (true) last = store.next(0)?.ptsUs ?: break
        store.confirm(last + 5_000_000)
    }

    @Test
    fun `streams kept are read back, the oldest of an address sent first, one an address at a time`() {
        kept(began = 300)
        kept(began = 100)
        kept(began = 200, address = second, lens = Lens.TELEPHOTO)
        backlog.readBack()
        backlog.tick(0)
        assertEquals(listOf("main-100", "telephoto-200"), started.map { it.folder.name })
        backlog.tick(1_000)
        assertEquals(2, started.size) // the first address's next waits for its oldest
        assertTrue(backlog.holds(first))
        assertTrue(backlog.holds(second))
    }

    @Test
    fun `a stream sent whole is removed after a quiet while, and the next of its address starts`() {
        kept(began = 100)
        kept(began = 200)
        backlog.readBack()
        backlog.tick(0)
        sendAll(started.single())
        backlog.tick(1_000) // nothing unsent from now
        backlog.tick(1_000 + Backlog.DONE_MS - 1)
        assertEquals(1, started.size)
        backlog.tick(1_000 + Backlog.DONE_MS)
        assertEquals(listOf("main-100"), stopped.map { it.folder.name })
        assertFalse(File(root, "main-100").exists())
        assertEquals(listOf("main-100", "main-200"), started.map { it.folder.name })
        assertTrue(said.any { it.startsWith("main: all it kept sent") })
    }

    @Test
    fun `folders with no header or nothing to send are removed as they are read back`() {
        kept(began = 100, header = false)
        val empty = File(root, "main-200").apply { mkdirs() }
        StreamHeader(Lens.MAIN, first, format, byteArrayOf(1)).write(empty)
        backlog.readBack()
        backlog.tick(0)
        assertTrue(started.isEmpty())
        assertTrue(root.listFiles()!!.isEmpty())
        assertFalse(backlog.holds(first))
    }

    @Test
    fun `a stream handed over is taken once, and what the phone holds is told by address`() {
        val folder = kept(began = 100, seconds = 2)
        backlog.adopt(folder)
        backlog.adopt(folder)
        assertEquals(FrameStore.Pending(1_900, 2_000), backlog.pendingFor(first))
        val live = FrameStore(File(root, "main-900"), freeBytes = { Long.MAX_VALUE })
        live.keep(EncodedFrame(ByteArray(50), 0, true), 1)
        val off = backlog.live(first, live)
        assertEquals(FrameStore.Pending(1_900, 2_050), backlog.pendingFor(first))
        assertEquals(FrameStore.Pending(0, 0), backlog.pendingFor(second))
        assertEquals(FrameStore.Pending(1_900, 2_050), backlog.pending())
        off()
        assertEquals(FrameStore.Pending(1_900, 2_000), backlog.pending())
        backlog.tick(0)
        assertEquals(1, started.size)
    }

    @Test
    fun `every address is held until what was kept is read back, and a stream fed or kept is activity`() {
        assertTrue(backlog.holds(second))
        assertFalse(backlog.active)
        backlog.readBack()
        assertFalse(backlog.holds(second))
        val off = backlog.live(second, FrameStore(File(root, "main-900"), freeBytes = { Long.MAX_VALUE }))
        assertTrue(backlog.active)
        off()
        assertFalse(backlog.active)
        backlog.adopt(kept(began = 100))
        assertTrue(backlog.active)
    }

    @Test
    fun `a stream handed over is kept before its live count goes, never idle in between`() {
        backlog.readBack()
        val folder = File(root, "main-900")
        val store = FrameStore(folder, freeBytes = { Long.MAX_VALUE })
        store.keep(EncodedFrame(ByteArray(10), 0, true), 1)
        StreamHeader(Lens.MAIN, first, format, byteArrayOf(1)).write(folder)
        val off = backlog.live(first, store)
        var activeAtOff: Boolean? = null
        backlog.handOver(store) {
            activeAtOff = backlog.active
            off()
        }
        assertEquals(true, activeAtOff)
        assertTrue(backlog.active)
        assertTrue(backlog.holds(first))
    }

    @Test
    fun `discard stops and drops every stream kept`() {
        kept(began = 100)
        kept(began = 200, address = second)
        backlog.readBack()
        backlog.tick(0)
        backlog.discard()
        assertEquals(2, stopped.size)
        assertTrue(root.listFiles()!!.isEmpty())
        assertFalse(backlog.holds(first))
        assertEquals(FrameStore.Pending(0, 0), backlog.pending())
    }
}
