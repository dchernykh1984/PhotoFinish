package com.dchernykh.photofinish.camera.capture

import android.os.SystemClock
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.RtmpAddress
import com.dchernykh.photofinish.camera.stream.FrameStore
import com.dchernykh.photofinish.camera.stream.StreamHeader
import com.dchernykh.photofinish.camera.stream.Uplink
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import java.io.File

/**
 * The phone's senders for as long as the app's process lives (specs/009): the streams kept with no camera
 * ([backlog]), read back as it starts and handed over as streams stop, the first lens first ([board]), and the
 * second's tick that starts and ends the backlog's uplinks. Screens come and go; these stay, the foreground service
 * keeping the process while anything is unsent ([active]).
 */
object Senders {
    val board = PriorityBoard()

    /** This run of the app's: the end of its streams' folders, which the read back leaves alone. */
    val session: String =
        java.util.UUID
            .randomUUID()
            .toString()
            .take(SESSION_CHARS)

    @Volatile private var started: Backlog? = null

    val backlog: Backlog get() = started ?: error("the senders are not started")

    /** A lens streams, or the backlog holds a stream: the process has frames to send. */
    val active: Boolean get() = started?.active == true

    /**
     * Started once a process, on the stores' [root]: what a crash or a restart left is read back and sent. [report]
     * hears what a kept stream's link says; [status] gives the phone's status line a keyframe carries, of a lens
     * and its address, with the frames dropped.
     */
    @Synchronized
    fun start(
        root: File,
        report: (Lens, UplinkStatus) -> Unit,
        say: (Lens, String) -> Unit,
        status: (RtmpAddress, Long) -> String?,
    ): Backlog {
        started?.let { return it }
        val backlog = Backlog(root, send = { header, store -> send(header, store, report, status) }, say = say, session)
        started = backlog
        Thread({ tick(backlog) }, "backlog").apply {
            isDaemon = true
            start()
        }
        return backlog
    }

    private fun tick(backlog: Backlog) {
        backlog.readBack()
        while (true) {
            backlog.tick(SystemClock.elapsedRealtime())
            try {
                Thread.sleep(TICK_MS)
            } catch (_: InterruptedException) {
                return
            }
        }
    }

    private fun send(
        header: StreamHeader,
        store: FrameStore,
        report: (Lens, UplinkStatus) -> Unit,
        status: (RtmpAddress, Long) -> String?,
    ): Backlog.Sending {
        val lens = header.lens
        val uplink =
            Uplink(
                header.address,
                header.format,
                clock = { null },
                requestKeyframe = {},
                report = { report(lens, it) },
                store = store,
                alone = true,
                firstLens = { board.allows(lens) },
            )
        uplink.status = { dropped -> status(header.address, dropped) }
        uplink.configure(header.record)
        val off = board.register(lens, { uplink.connected }, { store.pending.ms })
        Thread({ uplink.run() }, "kept-${lens.code}").start()
        return Backlog.Sending(uplink) {
            uplink.stop()
            off()
        }
    }

    private const val TICK_MS = 1_000L
    private const val SESSION_CHARS = 8

    /** The stores' folder in the app's files. */
    const val FOLDER = "kept"
}
