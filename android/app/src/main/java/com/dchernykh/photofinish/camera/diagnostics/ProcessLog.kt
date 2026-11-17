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
     * [pid]'s system log, warnings and errors, into [log] on a thread of its own while the app lives: read
     * again, its new lines alone, after a pause when it ends -- said, so that no warnings are not taken for
     * none read. One that cannot be read at all is said once, never the app's end (FR-006).
     */
    @Suppress("TooGenericExceptionCaught")
    fun follow(
        log: PhoneLog,
        pid: Int,
        command: (Boolean) -> List<String> = { again -> logcat(pid, again) },
        pauseMs: Long = PAUSE_MS,
    ) {
        Thread({
            var again = false
            while (true) {
                try {
                    val process = ProcessBuilder(command(again)).redirectErrorStream(true).start()
                    process.inputStream.bufferedReader().forEachLine { line ->
                        read(line)?.let { (level, text) -> log.system(level, text) }
                    }
                } catch (error: Exception) {
                    log.system(PhoneLog.SYSTEM_WARNING, "the system log cannot be read: ${Crashes.describe(error)}")
                    return@Thread
                }
                // The log's notes about itself go as the system log's lines: never the phone's last word.
                log.system(
                    PhoneLog.SYSTEM_WARNING,
                    "the system log ended: read again, its new lines, in ${pauseMs / MS_PER_S} s",
                )
                again = true
                Thread.sleep(pauseMs)
            }
        }, "process-log").apply { isDaemon = true }.start()
    }

    /** `logcat` of [pid]'s warnings and errors, the app's own tag left out: from its start, or its newest line. */
    private fun logcat(
        pid: Int,
        again: Boolean,
    ): List<String> =
        listOf("logcat", "-v", "epoch", "--pid=$pid") + (if (again) listOf("-T", "1") else emptyList()) +
            listOf("*:W", "$TAG:S")

    private const val PAUSE_MS = 5_000L
    private const val MS_PER_S = 1_000L
}
