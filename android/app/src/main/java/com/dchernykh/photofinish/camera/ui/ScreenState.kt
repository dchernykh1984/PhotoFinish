package com.dchernykh.photofinish.camera.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.dchernykh.photofinish.camera.Settings
import com.dchernykh.photofinish.camera.capture.CameraFormats
import com.dchernykh.photofinish.camera.capture.FormatChoice
import com.dchernykh.photofinish.camera.capture.Resolution
import com.dchernykh.photofinish.camera.capture.StreamFormat
import com.dchernykh.photofinish.camera.capture.StreamerStatus
import com.dchernykh.photofinish.camera.pairing.RtmpAddress

/** The screen's state: what is chosen and kept, and what the camera last said. */
class ScreenState(
    private val settings: Settings,
    private val formats: CameraFormats,
) {
    /** The sizes the phone gives the app, 1080p first. */
    val resolutions: List<Resolution> = FormatChoice.resolutions(formats.sizes, formats::takes)

    var address by mutableStateOf(settings.address)
        private set

    var resolution by mutableStateOf(settings.resolution?.takeIf { it in resolutions } ?: resolutions.firstOrNull())
        private set

    var fps by mutableStateOf(settings.fps)
        private set

    var streaming by mutableStateOf(false)

    var dimmed by mutableStateOf(false)

    var status by mutableStateOf<StreamerStatus?>(null)

    /** A debug build's request to start once the camera is allowed. */
    var autostart = false

    /** The rates the phone gives at the chosen size, the fastest first. */
    val rates: List<Int> get() =
        resolution
            ?.let {
                FormatChoice.rates(
                    formats.ranges,
                    it,
                    formats::takes,
                )
            }.orEmpty()

    val parsedAddress: RtmpAddress? get() = RtmpAddress.parse(address)

    /** What to stream: the chosen size and rate, the fastest rate when the chosen one is gone. */
    val format: StreamFormat? get() = formats.choose(resolution, fps)

    fun enterAddress(text: String) {
        address = text.trim()
        settings.address = address
    }

    fun choose(size: Resolution) {
        resolution = size
        settings.resolution = size
    }

    fun chooseFps(rate: Int) {
        fps = rate
        settings.fps = rate
    }
}
