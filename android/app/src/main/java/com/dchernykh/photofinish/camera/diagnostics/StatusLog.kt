package com.dchernykh.photofinish.camera.diagnostics

import com.dchernykh.photofinish.camera.capture.LeftOut
import com.dchernykh.photofinish.camera.capture.StreamerStatus
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import java.util.Locale

/**
 * What the screen shows of the cameras and of each lens, into [log] once a change (specs/008-phone-log,
 * FR-001): a stream's rates each second are not news, its start and its losses are.
 */
class StatusLog(
    private val log: PhoneLog,
) {
    private val last = HashMap<Lens?, String>()

    /** [status], said of [lens] -- of the cameras as a whole for null -- the cameras' and the uplinks' threads. */
    @Synchronized
    fun heard(
        lens: Lens?,
        status: StreamerStatus,
    ) {
        val (level, text, kind) = said(status)
        if (last[lens] == kind) return
        last[lens] = kind
        log.add(level, lens?.code, text)
    }

    private companion object {
        const val RATES = "streaming at %.1f fps, %.1f Mbit/s"

        /** How grave [status] is, its words, and what makes it news: its words but a stream's rates. */
        fun said(status: StreamerStatus): Triple<Char, String, String> =
            when (status) {
                is StreamerStatus.Previewing -> Triple(PhoneLog.INFO, "the camera gives frames", "previewing")
                is StreamerStatus.Failed -> status.reason.let { Triple(PhoneLog.ERROR, it, it) }
                is StreamerStatus.NoClock ->
                    Triple(PhoneLog.WARNING, "the frames have no clock: sent without their moments", "no clock")
                is StreamerStatus.Left -> {
                    val why =
                        when (status.why) {
                            LeftOut.NOT_ON_THIS_PHONE -> "the phone has no such lens"
                            LeftOut.NOT_WITH_THE_OTHERS -> "the phone cannot stream it beside the others"
                        }
                    Triple(PhoneLog.WARNING, "left out: $why", "left out: $why")
                }
                is StreamerStatus.Link -> link(status.status)
            }

        fun link(status: UplinkStatus): Triple<Char, String, String> =
            when (status) {
                is UplinkStatus.Connecting -> "connecting to ${status.address}".let { Triple(PhoneLog.INFO, it, it) }
                is UplinkStatus.Streaming ->
                    Triple(PhoneLog.INFO, String.format(Locale.ROOT, RATES, status.fps, status.mbps), "streaming")
                is UplinkStatus.Reconnecting ->
                    "connection lost: ${status.reason}; connecting again".let { Triple(PhoneLog.WARNING, it, it) }
            }
    }
}
