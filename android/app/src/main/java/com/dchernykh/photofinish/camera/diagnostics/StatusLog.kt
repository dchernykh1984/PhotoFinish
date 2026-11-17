package com.dchernykh.photofinish.camera.diagnostics

import com.dchernykh.photofinish.camera.capture.LeftOut
import com.dchernykh.photofinish.camera.capture.StreamerStatus
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import java.util.Locale

/**
 * What the screen shows of the cameras and of each lens, into [log] once a change (specs/008-phone-log,
 * FR-001): a stream's rates each second are not news, its start and its losses are. A word said again
 * within [QUIET_MS] -- a connection made and lost every few seconds while a recorder is down, a camera
 * failing and opened again -- is counted, and told with the next time it is said: the log keeps the start
 * and the first error, not a thousand times the same.
 */
class StatusLog(
    private val log: PhoneLog,
    private val nowMs: () -> Long = { System.nanoTime() / NANOS_PER_MS },
) {
    private class Said(
        val atMs: Long,
    ) {
        var again = 0
    }

    private val last = HashMap<Lens?, String>()
    private val said = HashMap<Pair<Lens?, String>, Said>()

    /** [status], said of [lens] -- of the cameras as a whole for null -- the cameras' and the uplinks' threads. */
    @Synchronized
    fun heard(
        lens: Lens?,
        status: StreamerStatus,
    ) {
        val (level, text, kind) = said(status)
        if (last[lens] == kind) return
        last[lens] = kind
        val now = nowMs()
        val before = said[lens to kind]
        if (before != null && now - before.atMs < QUIET_MS) {
            before.again++
            return
        }
        val more =
            before
                ?.again
                ?.takeIf { it > 0 }
                ?.let { " ($it times more in the minute before)" }
                .orEmpty()
        said[lens to kind] = Said(now)
        log.add(level, lens?.code, text + more)
    }

    private companion object {
        const val RATES = "streaming at %.1f fps, %.1f Mbit/s"
        const val QUIET_MS = 60_000L
        const val NANOS_PER_MS = 1_000_000L

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
                // Its reason names the phone's port of each try: the loss is the news, not the port.
                is UplinkStatus.Reconnecting ->
                    Triple(PhoneLog.WARNING, "connection lost: ${status.reason}; connecting again", "connection lost")
            }
    }
}
