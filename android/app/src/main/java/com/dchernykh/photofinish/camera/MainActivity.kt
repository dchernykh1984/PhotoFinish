package com.dchernykh.photofinish.camera

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.dchernykh.photofinish.camera.capture.CameraFormats
import com.dchernykh.photofinish.camera.capture.CameraStreamer
import com.dchernykh.photofinish.camera.capture.PhoneLenses
import com.dchernykh.photofinish.camera.status.PhoneStatusReader
import com.dchernykh.photofinish.camera.ui.CameraScreen
import com.dchernykh.photofinish.camera.ui.ScreenState

class MainActivity : ComponentActivity() {
    private lateinit var streamer: CameraStreamer

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val settings = Settings(this)
        // A debug build takes its lenses from the front camera on asking: the emulator's front
        // camera is the logical one of two lenses (`--es facing front`).
        val swapped = BuildConfig.DEBUG && intent.getStringExtra(EXTRA_FACING) == "front"
        val lenses = PhoneLenses(this, swapped)
        val state = ScreenState(settings, CameraFormats(this, lenses.mainCameraId), lenses.found)
        // A debug build takes an address and starts on its own, so the app can be tried with
        // PhotoFinish from a script: `adb shell am start ... --es address
        // rtmp://10.0.2.2:1935/live/phone --ez autostart true`; `|` parts the lines of a code
        // of several lenses.
        if (BuildConfig.DEBUG) {
            intent.getStringExtra(EXTRA_ADDRESS)?.let { state.enterAddress(it.replace('|', '\n')) }
            state.autostart = intent.getBooleanExtra(EXTRA_AUTOSTART, false)
        }
        streamer =
            CameraStreamer(this, lenses, PhoneStatusReader(this)) { lens, status ->
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
    }
}
