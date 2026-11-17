package com.dchernykh.photofinish.camera.diagnostics

import com.dchernykh.photofinish.camera.capture.LeftOut
import com.dchernykh.photofinish.camera.capture.StreamerStatus
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import org.junit.Assert.assertEquals
import org.junit.Test

class StatusLogTest {
    private val log = PhoneLog()
    private val statuses = StatusLog(log)

    private fun said() = log.after(0).map { "${it.level} ${it.lens ?: "-"} ${it.text}" }

    @Test
    fun `what the screen shows is logged once a change, with its level and lens`() {
        statuses.heard(null, StreamerStatus.Previewing)
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Connecting("rtmp://10.0.0.5:1935/live/cam7")))
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Streaming(59.94, 21.3, 2.0)))
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Streaming(60.0, 20.9, 1.9))) // its rates: no news
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Reconnecting("Broken pipe")))
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Reconnecting("Broken pipe")))
        statuses.heard(Lens.MAIN, StreamerStatus.Link(UplinkStatus.Reconnecting("Connection refused")))
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
                "W main connection lost: Connection refused; connecting again",
                "W front left out: the phone cannot stream it beside the others",
                "W telephoto the frames have no clock: sent without their moments",
                "E - camera error 4: the camera device failed; trying again",
                "W ultrawide left out: the phone has no such lens",
            ),
            said(),
        )
    }
}
