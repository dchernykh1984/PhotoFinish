package com.dchernykh.photofinish.camera.ui

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.view.Surface
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.WindowManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.dchernykh.photofinish.camera.R
import com.dchernykh.photofinish.camera.capture.CameraStreamer
import com.dchernykh.photofinish.camera.capture.Resolution
import com.dchernykh.photofinish.camera.capture.StreamFormat
import com.dchernykh.photofinish.camera.capture.StreamerStatus
import com.dchernykh.photofinish.camera.stream.UplinkStatus
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions

/** The preview's surface, once it has the size asked of it. */
private class PreviewSurface(
    val surface: Surface,
    val size: Resolution,
)

@Composable
fun CameraScreen(
    state: ScreenState,
    streamer: CameraStreamer,
) {
    val granted = rememberCameraPermission()
    val started = rememberStarted()
    var preview by remember { mutableStateOf<PreviewSurface?>(null) }
    val format = state.format
    val target = if (state.streaming) state.parsedAddress else null
    // The camera starts once the preview has the stream's size, and again on every change.
    val surface = preview?.takeIf { started && granted && it.size == format?.resolution }?.surface
    LaunchedEffect(surface, format, target) {
        streamer.stop()
        if (surface != null && format != null) streamer.start(surface, format, target)
    }
    LaunchedEffect(granted) {
        if (state.autostart && granted && state.parsedAddress != null) {
            state.autostart = false
            state.streaming = true
        }
    }
    DimScreen(state.dimmed)
    MaterialTheme(colorScheme = darkColorScheme()) {
        Surface(modifier = Modifier.fillMaxSize(), color = Color.Black) {
            Row(modifier = Modifier.fillMaxSize().safeDrawingPadding().padding(8.dp)) {
                Box(modifier = Modifier.weight(1f).fillMaxHeight(), contentAlignment = Alignment.Center) {
                    CameraPreview(format?.resolution) { preview = it }
                }
                ControlPanel(state, granted, format)
            }
            if (state.dimmed) {
                Box(modifier = Modifier.fillMaxSize().background(Color.Black).clickable { state.dimmed = false })
            }
        }
    }
}

@Composable
private fun rememberCameraPermission(): Boolean {
    val context = LocalContext.current
    var granted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED,
        )
    }
    val askCamera = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    LaunchedEffect(Unit) { if (!granted) askCamera.launch(Manifest.permission.CAMERA) }
    return granted
}

/**
 * The screen is on view: from ON_START to ON_STOP, not only while resumed, so a system dialog
 * over the screen -- a pause -- does not cut the stream mid-race.
 */
@Composable
private fun rememberStarted(): Boolean {
    var started by remember { mutableStateOf(false) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val observer =
            LifecycleEventObserver { _, event ->
                if (event == Lifecycle.Event.ON_START) started = true
                if (event == Lifecycle.Event.ON_STOP) started = false
            }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    return started
}

/** The screen as dark as the phone allows while [dimmed]; the stream goes on. */
@Composable
private fun DimScreen(dimmed: Boolean) {
    val context = LocalContext.current
    LaunchedEffect(dimmed) {
        (context as? Activity)?.window?.let { window ->
            window.attributes =
                window.attributes.apply {
                    screenBrightness =
                        if (dimmed) DIM_BRIGHTNESS else WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
                }
        }
    }
}

/**
 * The camera's picture at [size]. A SurfaceView, as the system turns the camera's
 * frames upright for the screen's rotation on its own; [onSurface] hears of the
 * surface each time its size changes, and of null once it is gone.
 */
@Composable
private fun CameraPreview(
    size: Resolution?,
    onSurface: (PreviewSurface?) -> Unit,
) {
    val ratio = size?.let { it.width.toFloat() / it.height } ?: (16f / 9f)
    AndroidView(
        factory = { viewContext ->
            SurfaceView(viewContext).apply {
                holder.addCallback(
                    object : SurfaceHolder.Callback {
                        override fun surfaceCreated(holder: SurfaceHolder) = Unit

                        override fun surfaceChanged(
                            holder: SurfaceHolder,
                            format: Int,
                            width: Int,
                            height: Int,
                        ) = onSurface(PreviewSurface(holder.surface, Resolution(width, height)))

                        override fun surfaceDestroyed(holder: SurfaceHolder) = onSurface(null)
                    },
                )
            }
        },
        update = { view -> size?.let { view.holder.setFixedSize(it.width, it.height) } },
        modifier = Modifier.aspectRatio(ratio),
    )
}

@Composable
private fun ControlPanel(
    state: ScreenState,
    granted: Boolean,
    format: StreamFormat?,
) {
    Column(
        modifier =
            Modifier
                .width(PANEL_WIDTH.dp)
                .fillMaxHeight()
                .padding(start = 8.dp)
                .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(statusText(state, granted, format), color = Color.White)
        OutlinedTextField(
            value = state.address,
            onValueChange = { state.enterAddress(it) },
            label = { Text(stringResource(R.string.address)) },
            singleLine = true,
            enabled = !state.streaming,
            isError = state.address.isNotEmpty() && state.parsedAddress == null,
            modifier = Modifier.fillMaxWidth(),
        )
        ScanButton(enabled = !state.streaming) { state.enterAddress(it) }
        Text(stringResource(R.string.picture), color = Color.White)
        Choices(state.resolutions, format?.resolution, !state.streaming, { it.toString() }) { state.choose(it) }
        Choices(
            state.rates,
            format?.fps,
            !state.streaming,
            { stringResource(R.string.fps, it) },
        ) { state.chooseFps(it) }
        Button(
            onClick = { state.streaming = !state.streaming },
            enabled = state.streaming || (granted && format != null && state.parsedAddress != null),
        ) { Text(stringResource(if (state.streaming) R.string.stop else R.string.start)) }
        OutlinedButton(onClick = { state.dimmed = true }, enabled = state.streaming) {
            Text(stringResource(R.string.dim))
        }
    }
}

/** Reads PhotoFinish's QR code: the address to stream to. */
@Composable
private fun ScanButton(
    enabled: Boolean,
    onAddress: (String) -> Unit,
) {
    val scan = rememberLauncherForActivityResult(ScanContract()) { result -> result.contents?.let(onAddress) }
    val prompt = stringResource(R.string.scan_prompt)
    Button(
        onClick = {
            scan.launch(
                ScanOptions()
                    .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                    .setPrompt(prompt)
                    .setBeepEnabled(false)
                    .setOrientationLocked(false),
            )
        },
        enabled = enabled,
    ) { Text(stringResource(R.string.scan)) }
}

/** One chip per option, the [selected] one marked. */
@Composable
private fun <T> Choices(
    options: List<T>,
    selected: T?,
    enabled: Boolean,
    label: @Composable (T) -> String,
    onChoose: (T) -> Unit,
) {
    Row(
        modifier = Modifier.horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        options.forEach { option ->
            FilterChip(
                selected = option == selected,
                onClick = { onChoose(option) },
                label = { Text(label(option)) },
                enabled = enabled,
            )
        }
    }
}

@Composable
private fun statusText(
    state: ScreenState,
    granted: Boolean,
    format: StreamFormat?,
): String {
    if (!granted) return stringResource(R.string.need_camera)
    if (format == null) return stringResource(R.string.no_format)
    return when (val status = state.status) {
        is StreamerStatus.Failed -> stringResource(R.string.camera_failed, status.reason)
        is StreamerStatus.NoClock -> stringResource(R.string.no_clock)
        is StreamerStatus.Link -> linkText(status.status)
        StreamerStatus.Previewing, null -> stringResource(R.string.ready, format.resolution.toString(), format.fps)
    }
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

private const val PANEL_WIDTH = 320
private const val DIM_BRIGHTNESS = 0.01f
