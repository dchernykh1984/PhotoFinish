package com.dchernykh.photofinish.camera.ui

import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.dchernykh.photofinish.camera.R
import com.dchernykh.photofinish.camera.capture.LeftOut
import com.dchernykh.photofinish.camera.capture.LensInfo
import com.dchernykh.photofinish.camera.capture.StreamFormat
import com.dchernykh.photofinish.camera.capture.StreamerStatus
import com.dchernykh.photofinish.camera.pairing.Lens
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import kotlin.math.roundToInt

// What the screen says: the cameras as a whole, each lens streamed, and the lenses found.

/** The lenses the phone gives the app, with their 35 mm-equivalent focal lengths (FR-004). */
@Composable
internal fun lensesText(lenses: Map<Lens, LensInfo>): String {
    val named =
        lenses.map { (lens, info) ->
            stringResource(R.string.lens_focal, lensName(lens), info.focalMm.roundToInt())
        }
    return stringResource(R.string.lenses_found, named.joinToString(", "))
}

@Composable
private fun lensName(lens: Lens): String =
    stringResource(
        when (lens) {
            Lens.MAIN -> R.string.lens_main
            Lens.ULTRAWIDE -> R.string.lens_ultrawide
            Lens.TELEPHOTO -> R.string.lens_telephoto
            Lens.FRONT -> R.string.lens_front
        },
    )

@Composable
internal fun statusText(
    state: ScreenState,
    granted: Boolean,
    format: StreamFormat?,
): String {
    if (!granted || format == null) return stringResource(if (granted) R.string.no_format else R.string.need_camera)
    val camera = (state.status as? StreamerStatus.Failed)?.let { stringResource(R.string.camera_failed, it.reason) }
    if (!state.streaming) return camera ?: stringResource(R.string.ready, format.resolution.toString(), format.fps)
    // While streaming, a line per lens: the lens named when there are several.
    val targets = state.pairing.targets
    val lines =
        targets.map { target ->
            val said = lensText(state.lensStatus[target.lens])
            if (targets.size > 1) stringResource(R.string.lens_status, lensName(target.lens), said) else said
        }
    return (listOfNotNull(camera) + lines).joinToString("\n")
}

@Composable
private fun lensText(status: StreamerStatus?): String =
    when (status) {
        is StreamerStatus.Failed -> stringResource(R.string.camera_failed, status.reason)
        is StreamerStatus.NoClock -> stringResource(R.string.no_clock)
        is StreamerStatus.Link -> linkText(status.status)
        is StreamerStatus.Left ->
            stringResource(
                if (status.why ==
                    LeftOut.NOT_ON_THIS_PHONE
                ) {
                    R.string.left_missing
                } else {
                    R.string.left_together
                },
            )
        StreamerStatus.Previewing, null -> stringResource(R.string.starting)
    }

@Composable
private fun linkText(status: UplinkStatus): String =
    when (status) {
        is UplinkStatus.Connecting -> stringResource(R.string.connecting, status.address)
        is UplinkStatus.Reconnecting -> stringResource(R.string.reconnecting, status.reason)
        is UplinkStatus.Streaming ->
            if (status.clockMs != null) {
                stringResource(R.string.streaming_clock, status.fps, status.mbps, status.clockMs)
            } else {
                stringResource(R.string.streaming_no_clock, status.fps, status.mbps)
            }
    }
