package com.dchernykh.photofinish.camera.ui

import com.dchernykh.photofinish.camera.stream.FrameStore
import java.util.Locale

/**
 * Below this, what the phone holds while it streams is the stream's own pace -- a frame or two on their way --, not
 * video behind: not said, as the laptop says nothing under it either (specs/009).
 */
const val SAID_MS = 2_000L

/** Whether what is [held] is said: anything once the streams are [stopped], else [SAID_MS] of video or more. */
fun said(
    held: FrameStore.Pending,
    stopped: Boolean,
): Boolean = held.bytes > 0 && (stopped || held.ms >= SAID_MS)

/** [ms] of video as a clock says it: `M:SS`, from an hour `H:MM:SS` (specs/009). */
fun span(ms: Long): String {
    val seconds = maxOf(ms, 0) / MS_PER_S
    val hours = seconds / S_PER_H
    val minutes = seconds % S_PER_H / S_PER_MIN
    val rest = seconds % S_PER_MIN
    return if (hours > 0) {
        String.format(Locale.ROOT, "%d:%02d:%02d", hours, minutes, rest)
    } else {
        String.format(Locale.ROOT, "%d:%02d", minutes, rest)
    }
}

/** [bytes] in MB, rounded up: a little video held is not "0 MB" (specs/009). */
fun megabytes(bytes: Long): Long = (maxOf(bytes, 0) + BYTES_PER_MB - 1) / BYTES_PER_MB

private const val BYTES_PER_MB = 1_000_000L
private const val MS_PER_S = 1_000L
private const val S_PER_MIN = 60L
private const val S_PER_H = 3_600L
