package com.dchernykh.photofinish.camera.diagnostics

import android.content.Context
import android.os.Build
import android.os.Process
import android.util.Log
import com.dchernykh.photofinish.camera.BuildConfig
import java.io.File

/**
 * The phone's log for the app's whole process (specs/008-phone-log): made, told how the app was started,
 * fed the app's own system log and sent to the recorders once, whatever becomes of the activity. A phone
 * on a cable finds the lines in the system log too, under [ProcessLog.TAG].
 */
object Diagnostics {
    private const val CRASH_FILE = "crash.txt"

    val log: PhoneLog by lazy {
        PhoneLog(mirror = { Log.println(priority(it.level), ProcessLog.TAG, "${it.lens ?: "-"} ${it.text}") })
    }

    /** Where the log goes: the recorders of the newest activity's pairing code. */
    @Volatile private var destinations: () -> List<Pair<String, Int>> = { emptyList() }

    private var sender: LogSender? = null

    /** Started, once; [to] the recorders the log is sent to from now on, a lens's host and port each. */
    @Synchronized
    fun start(
        context: Context,
        to: () -> List<Pair<String, Int>>,
    ) {
        destinations = to
        if (sender != null) return
        val crash = File(context.filesDir, CRASH_FILE)
        Crashes.tell(crash, log)
        Crashes.keep(crash)
        log.info(
            null,
            "PhotoFinish Camera ${BuildConfig.VERSION_NAME} on ${Build.MANUFACTURER} ${Build.MODEL}, " +
                "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})",
        )
        ProcessLog.follow(log, Process.myPid())
        sender = LogSender(log, { destinations() }).also { it.start() }
    }

    private fun priority(level: Char): Int =
        when (level) {
            PhoneLog.ERROR, PhoneLog.SYSTEM_ERROR -> Log.ERROR
            PhoneLog.WARNING, PhoneLog.SYSTEM_WARNING -> Log.WARN
            else -> Log.INFO
        }
}
