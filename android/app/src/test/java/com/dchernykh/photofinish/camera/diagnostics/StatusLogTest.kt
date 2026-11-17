package com.dchernykh.photofinish.camera.diagnostics

import com.dchernykh.photofinish.camera.capture.LeftOut
import com.dchernykh.photofinish.camera.capture.StreamerStatus
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import org.junit.Assert.assertEquals
import org.junit.Test

class StatusLogTest {
    private var now = 0L
    private val log = PhoneLog()
    private val statuses = StatusLog(log) { now }

    private fun said() = log.after(0).map { "${it.level} ${it.lens ?: "-"} ${it.text}" }

    @Test
    fun `what the screen shows is logged once a change, with its level and lens`() {
        statuses.heard(null, StreamerStatus.Previewing)
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Connecting("rtmp://10.0.0.5:1935/live/cam7")))
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Streaming(59.94, 21.3, 2.0)))
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Streaming(60.0, 20.9, 1.9))) // its rates: no news
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Reconnecting("Broken pipe")))
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Reconnecting("Broken pipe")))
        statuses.heard(Lens.FRONT, StreamerStatus.Left(LeftOut.NOT_WITH_THE_OTHERS))
        statuses.heard(Lens.TELEPHOTO, StreamerStatus.NoClock)
        statuses.heard(null, StreamerStatus.Failed("camera error 4: the camera device failed; trying again"))
        statuses.heard(Lens.ULTRAWIDE, StreamerStatus.Left(LeftOut.NOT_ON_THIS_PHONE))
        assertEquals(
            listOf(
                "I - the camera gives frames",
                "I main connecting to rtmp://10.0.0.5:1935/live/cam7",
                "I main streaming at 59.9 fps, 21.3 Mbit/s",
                "W main connection lost: Broken pipe; connecting again",
                "W front left out: the phone cannot stream it beside the others",
                "W telephoto the frames have no clock: sent without their moments",
                "E - camera error 4: the camera device failed; trying again",
                "W ultrawide left out: the phone has no such lens",
            ),
            said(),
        )
    }

    @Test
    fun `a word said again within a minute is counted, and told with the next time it is said`() {
        // A recorder down: a connection made and lost every few seconds, the port of each try in its reason.
        repeat(20) { attempt ->
            statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Connecting("rtmp://10.0.0.5:1935/live/cam7")))
            statuses.heard(
                Lens.MAIN,
                StreamerStatus.Link(UplinkStatus.Reconnecting("refused from port ${40_000 + attempt}")),
            )
            now += 4_000
        }
        assertEquals(
            listOf(
                "I main connecting to rtmp://10.0.0.5:1935/live/cam7",
                "W main connection lost: refused from port 40000; connecting again",
                "I main connecting to rtmp://10.0.0.5:1935/live/cam7 (14 times more in the minute before)",
                "W main connection lost: refused from port 40015; connecting again" +
                    " (14 times more in the minute before)",
            ),
            said(),
        )
    }

    @Test
    fun `the log ends with where a lens came to rest, a word said again within a minute told then`() {
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Streaming(30.0, 6.0, 1.0)))
        now += 10_000
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Reconnecting("Broken pipe")))
        now += 2_000
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Streaming(30.0, 6.0, 1.0))) // within the minute
        now += 4_000
        statuses.settle()
        assertEquals("W main connection lost: Broken pipe; connecting again", said().last()) // not at rest yet
        now += 1_000
        statuses.settle()
        assertEquals("I main streaming at 30.0 fps, 6.0 Mbit/s (1 times more in the minute before)", said().last())
        statuses.settle()
        assertEquals(3, said().size) // told once
    }

    @Test
    fun `failures whose words all differ are told, the oldest of them forgotten as more come`() {
        repeat(200) {
            statuses.heard(null, StreamerStatus.Failed("camera error at frame $it; trying again"))
            statuses.heard(null, StreamerStatus.Previewing)
            now += 61_000
        }
        assertEquals(400, said().size) // each told: a minute apart
        assertEquals(64, wordsKept(statuses))
    }

    private fun wordsKept(statuses: StatusLog): Int =
        StatusLog::class.java.getDeclaredField("said").let {
            it.isAccessible = true
            (it.get(statuses) as Map<*, *>).size
        }
}
