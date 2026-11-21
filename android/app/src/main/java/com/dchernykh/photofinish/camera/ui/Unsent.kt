package com.dchernykh.photofinish.camera.ui

import java.util.Locale

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

private const val MS_PER_S = 1_000L
private const val S_PER_MIN = 60L
private const val S_PER_H = 3_600L
