package com.dchernykh.photofinish.camera.stream

import com.dchernykh.photofinish.camera.capture.FpsRange
import com.dchernykh.photofinish.camera.capture.Resolution
import com.dchernykh.photofinish.camera.capture.StreamFormat
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class StreamHeaderTest {
    @get:Rule
    val temporary = TemporaryFolder()

    private val header =
        StreamHeader(
            Lens.TELEPHOTO,
            RtmpAddress("192.168.31.89", 1936, "live", "cam22"),
            StreamFormat(Resolution(2560, 1440), 60, FpsRange(60, 60), 11_200_000, Codec.HEVC),
            byteArrayOf(1, 0x64, 0, 0x28, -1),
        )

    @Test
    fun `a header written is read back whole`() {
        val folder = temporary.newFolder()
        assertTrue(header.write(folder))
        val read = StreamHeader.read(folder)!!
        assertEquals(Lens.TELEPHOTO, read.lens)
        assertEquals(header.address, read.address)
        assertEquals(header.format.resolution, read.format.resolution)
        assertEquals(60, read.format.fps)
        assertEquals(11_200_000, read.format.bitrate)
        assertEquals(Codec.HEVC, read.format.codec)
        assertArrayEquals(header.record, read.record)
        assertEquals(listOf(StreamHeader.FILE), folder.list()!!.toList()) // the file written beside goes
    }

    @Test
    fun `a header is written on the stores' thread, and again as it comes again after the storage refused it`() {
        val folder = temporary.newFolder()
        val queued = ArrayDeque<Runnable>()
        var failures = 0
        val keep = StreamHeader.keeper({ header }, folder, { queued += it }) { failures++ }
        assertFalse(keep(header.record)) // asked of the stores' thread: nothing written on the encoder's
        assertNull(StreamHeader.read(folder))
        folder.setWritable(false) // the storage refuses it
        queued.removeFirst().run()
        assertEquals(1, failures)
        folder.setWritable(true)
        assertFalse(keep(header.record)) // given again: written again
        queued.removeFirst().run()
        assertTrue(keep(header.record)) // kept: nothing more asked
        assertTrue(queued.isEmpty())
        assertArrayEquals(header.record, StreamHeader.read(folder)!!.record)
    }

    @Test
    fun `no header, one of another version, or one cut short is none`() {
        val folder = temporary.newFolder()
        assertNull(StreamHeader.read(folder))
        header.write(folder)
        val file = File(folder, StreamHeader.FILE)
        val text = file.readText()
        file.writeText(text.replace("version=1", "version=2"))
        assertNull(StreamHeader.read(folder))
        file.writeText(text.substringBefore("record="))
        assertNull(StreamHeader.read(folder))
        file.writeText(text.replace(Regex("record=.*"), "record=abc"))
        assertNull(StreamHeader.read(folder))
        file.writeText(text.replace("lens=telephoto", "lens=fisheye"))
        assertNull(StreamHeader.read(folder))
        file.writeText(text.replace("codec=hevc", "codec=vp9"))
        assertNull(StreamHeader.read(folder))
    }
}
