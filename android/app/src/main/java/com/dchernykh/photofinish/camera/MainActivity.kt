package com.dchernykh.photofinish.camera

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.dchernykh.photofinish.camera.capture.CameraFormats
import com.dchernykh.photofinish.camera.capture.CameraStreamer
import com.dchernykh.photofinish.camera.capture.FormatChoice
import com.dchernykh.photofinish.camera.capture.PhoneLenses
import com.dchernykh.photofinish.camera.capture.Resolution
import com.dchernykh.photofinish.camera.capture.Senders
import com.dchernykh.photofinish.camera.capture.StreamerStatus
import com.dchernykh.photofinish.camera.diagnostics.Diagnostics
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.status.PhoneStatusReader
import com.dchernykh.photofinish.camera.ui.CameraScreen
import com.dchernykh.photofinish.camera.ui.ScreenState
import java.io.File
import kotlin.math.roundToInt

class MainActivity : ComponentActivity() {
    private lateinit var streamer: CameraStreamer

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val settings = Settings(this)
        // A debug build takes its lenses from the front camera on asking: the emulator's front
        // camera is the logical one of two lenses (`--es facing front`).
        val swapped = BuildConfig.DEBUG && intent.getStringExtra(EXTRA_FACING) == "front"
        val trial = if (BuildConfig.DEBUG) intent.getStringExtra(EXTRA_SIZE)?.let { size(it) } else null
        FormatChoice.trial = trial
        val lenses = PhoneLenses(this, swapped)
        val state = ScreenState(settings, CameraFormats(this, lenses.mainCameraId), lenses.found)
        // A debug build takes an address and starts on its own, so the app can be tried with
        // PhotoFinish from a script: `adb shell am start ... --es address
        // rtmp://10.0.2.2:1935/live/phone --ez autostart true`; `|` parts the lines of a code
        // of several lenses.
        if (BuildConfig.DEBUG) {
            intent.getStringExtra(EXTRA_ADDRESS)?.let { state.enterAddress(it.replace('|', '\n')) }
            trial?.let { state.choose(it) }
            state.autostart = intent.getBooleanExtra(EXTRA_AUTOSTART, false)
        }
        // What the app meets goes to the recorders of the lenses the code names, streaming or not
        // (specs/008-phone-log): the laptop sees why a phone gives no video.
        val found =
            lenses.found.entries.joinToString { (lens, info) ->
                val physical = info.physicalId?.let { "/$it" }.orEmpty()
                "${lens.code}: camera ${info.cameraId}$physical, ${info.focalMm.roundToInt()} mm"
            }
        Diagnostics.start(this, "lenses: ${found.ifEmpty { "none" }}")
        val log = Diagnostics.log
        val statuses = Diagnostics.statuses
        // A lens's link while its camera is closed: in the log, the screen keeping the camera's word.
        val logged = { lens: Lens?, status: StreamerStatus -> statuses.heard(lens, status, shown = false) }
        val phone = PhoneStatusReader(this)
        // What a crash, Android or a dead battery left is sent before anything new, without Start (specs/009).
        Senders.start(
            File(filesDir, Senders.FOLDER),
            report = { lens, status -> logged(lens, StreamerStatus.Link(status)) },
            say = { lens, text -> log.info(lens.code, text) },
            status = { address, dropped ->
                val held = Senders.backlog.pendingFor(address)
                phone
                    .read()
                    .copy(dropped = dropped)
                    .holding(held.ms, held.bytes)
                    .line()
            },
        )
        streamer =
            CameraStreamer(this, lenses, phone, log, logged) { lens, status ->
                statuses.heard(lens, status)
                runOnUiThread { state.hear(lens, status) }
            }
        setContent { CameraScreen(state, streamer) }
    }

    override fun onDestroy() {
        streamer.release()
        super.onDestroy()
    }

    private companion object {
        const val EXTRA_ADDRESS = "address"
        const val EXTRA_AUTOSTART = "autostart"
        const val EXTRA_FACING = "facing"
        const val EXTRA_SIZE = "size"

        /** `WxH`, as the size extra gives it. */
        fun size(text: String): Resolution? {
            val (width, height) = text.split('x').mapNotNull { it.toIntOrNull() }.takeIf { it.size == 2 } ?: return null
            return Resolution(width, height)
        }
    }
}
