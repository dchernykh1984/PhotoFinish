package com.dchernykh.photofinish.camera.diagnostics

import java.io.File
import java.io.IOException

/**
 * Errors told whole (specs/008-phone-log, FR-001): what was thrown, its message, where -- the app's own
 * frames first -- and what caused it; and one the app does not catch, kept in a file as the app ends and
 * told by its next start.
 */
object Crashes {
    private const val FRAMES = 3
    private const val OWN = "com.dchernykh.photofinish"

    /** [error] on one line: its class and message, the frames it was thrown through, its causes. */
    fun describe(error: Throwable): String {
        val parts = mutableListOf<String>()
        var at: Throwable? = error
        val seen = mutableSetOf<Throwable>()
        while (at != null && seen.add(at)) {
            val what = at.javaClass.simpleName + (at.message?.let { ": $it" } ?: "")
            // Where it was thrown, and where the app's own code was then.
            val own = at.stackTrace.filter { it.className.startsWith(OWN) }.take(FRAMES)
            val frames = (at.stackTrace.take(FRAMES) + own).distinct()
            val where =
                frames.joinToString(
                    " < ",
                ) { "${it.className.substringAfterLast('.')}.${it.methodName}:${it.lineNumber}" }
            parts += if (where.isEmpty()) what else "$what at $where"
            at = at.cause
        }
        return parts.joinToString("; caused by ")
    }

    /** From now on, an error no thread catches is kept in [file] before the app ends as it would have. */
    fun keep(file: File) {
        val before = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            try {
                file.writeText("in thread ${thread.name}: ${describe(error)}")
            } catch (_: IOException) {
                // the error is the app's end all the same
            }
            before?.uncaughtException(thread, error)
        }
    }

    /** The error that ended the app's last run, if one did, told to [log] and forgotten. */
    fun tell(
        file: File,
        log: PhoneLog,
    ) {
        val text =
            try {
                file.readText().also { file.delete() }
            } catch (_: IOException) {
                return
            }
        log.error(null, "the app ended on an error $text")
    }
}
