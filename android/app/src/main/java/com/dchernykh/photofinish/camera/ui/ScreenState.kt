package com.dchernykh.photofinish.camera.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.dchernykh.photofinish.camera.Settings
import com.dchernykh.photofinish.camera.capture.CameraFormats
import com.dchernykh.photofinish.camera.capture.FormatChoice
import com.dchernykh.photofinish.camera.capture.LensInfo
import com.dchernykh.photofinish.camera.capture.Resolution
import com.dchernykh.photofinish.camera.capture.StreamFormat
import com.dchernykh.photofinish.camera.capture.StreamerStatus
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.pairing.Pairing

/** The screen's state: what is chosen and kept, and what the cameras last said. */
class ScreenState(
    private val settings: Settings,
    private val formats: CameraFormats,
    /** The lenses the phone gives the app, for the screen to list. */
    val lenses: Map<Lens, LensInfo>,
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

    /** What the cameras as a whole last said. */
    var status by mutableStateOf<StreamerStatus?>(null)

    /** What each lens streamed last said. */
    val lensStatus = mutableStateMapOf<Lens, StreamerStatus>()

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

    /** The lenses and addresses the code asks for (specs/004-phone-lenses). */
    val pairing: Pairing get() = Pairing.parse(address)

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

    /**
     * What a camera said: of the cameras as a whole, or of one lens while streaming -- a lens's word
     * heard after Stop is the stopped stream's, said before its camera closed, and not the next one's.
     */
    fun hear(
        lens: Lens?,
        said: StreamerStatus,
    ) {
        if (lens == null) {
            status = said
        } else if (streaming) {
            lensStatus[lens] = said
        }
    }

    /** Streaming on or off; what the cameras and the lenses said before is forgotten. */
    fun toggleStreaming() {
        status = null
        lensStatus.clear()
        streaming = !streaming
    }
}
