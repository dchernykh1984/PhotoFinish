package com.dchernykh.photofinish.camera.diagnostics

/**
 * The app's own part of the system log, warnings and errors (specs/008-phone-log): what the camera and the
 * encoder services answer the app, said in its process, without a call site for each. Android gives an app
 * its own lines alone, with no permission asked; the app's own tag is left out, its lines being in the log
 * already.
 */
object ProcessLog {
    /** The tag the app writes its own lines under, for a phone on a cable. */
    const val TAG = "PhotoFinish"

    private val LINE = Regex("""^\s*\d+\.\d+\s+\d+\s+\d+\s+([VDIWEFA])\s+(.*?)\s*: (.*)$""")

    /** A line of `logcat -v epoch` as the log keeps it: its level and its tag's words; null for no such line. */
    fun read(line: String): Pair<Char, String>? {
        val (level, tag, text) = LINE.find(line)?.destructured ?: return null
        val kept =
            when (level) {
                "W" -> PhoneLog.SYSTEM_WARNING
                "E", "F", "A" -> PhoneLog.SYSTEM_ERROR
                else -> return null
            }
        return kept to "$tag: $text"
    }

    /**
     * [pid]'s system log, warnings and errors, into [log] on a thread of its own while the app lives; whatever
     * it throws ends the reading alone, said, never the app (FR-006).
     */
    @Suppress("TooGenericExceptionCaught")
    fun follow(
        log: PhoneLog,
        pid: Int,
    ) {
        Thread({
            try {
                val process =
                    ProcessBuilder("logcat", "-v", "epoch", "--pid=$pid", "*:W", "$TAG:S")
                        .redirectErrorStream(true)
                        .start()
                process.inputStream.bufferedReader().forEachLine { line ->
                    read(line)?.let { (level, text) -> log.system(level, text) }
                }
            } catch (error: Exception) {
                log.warning(null, "the system log cannot be read: ${Crashes.describe(error)}")
            }
        }, "process-log").apply { isDaemon = true }.start()
    }
}
