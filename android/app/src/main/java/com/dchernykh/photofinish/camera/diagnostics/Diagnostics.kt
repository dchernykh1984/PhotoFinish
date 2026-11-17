package com.dchernykh.photofinish.camera.diagnostics

import android.content.Context
import android.os.Build
import android.os.Process
import android.util.Log
import com.dchernykh.photofinish.camera.BuildConfig
import com.dchernykh.photofinish.camera.Settings
import java.io.File

/**
 * The phone's log for the app's whole process (specs/008-phone-log): made, told how the app was started,
 * fed the app's own system log and sent to the recorders once, whatever becomes of the activity. A phone
 * on a cable finds the lines in the system log too, under [ProcessLog.TAG].
 */
object Diagnostics {
    private const val CRASH_FILE = "crash.txt"
    private const val SETTLE_EVERY_MS = 1_000L

    val log: PhoneLog by lazy {
        PhoneLog(mirror = { Log.println(priority(it.level), ProcessLog.TAG, "${it.lens ?: "-"} ${it.text}") })
    }

    /** What the screen shows, into the log: the lens a status came to rest in told every second. */
    val statuses: StatusLog by lazy {
        StatusLog(log).also { statuses ->
            Thread({
                while (true) {
                    Thread.sleep(SETTLE_EVERY_MS)
                    statuses.settle()
                }
            }, "status-log").apply { isDaemon = true }.start()
        }
    }

    private var sender: LogSender? = null

    /**
     * Started, once, told the phone's [lenses]: the log sent to the recorders of the pairing code the app keeps,
     * read each round from the settings of [context]'s application -- no activity is held, whatever becomes of it.
     */
    @Synchronized
    fun start(
        context: Context,
        lenses: String,
    ) {
        if (sender != null) return // an activity made again: told once, its lenses' line too
        val settings = Settings(context.applicationContext)
        val crash = File(context.filesDir, CRASH_FILE)
        Crashes.tell(crash, log)
        Crashes.keep(crash)
        log.info(
            null,
            "PhotoFinish Camera ${BuildConfig.VERSION_NAME} on ${Build.MANUFACTURER} ${Build.MODEL}, " +
                "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})",
        )
        log.info(null, lenses) // once: a line of the phone's after an error would end its last word
        ProcessLog.follow(log, Process.myPid())
        sender = LogSender(log, { LogSender.recordersOf(settings.address) }).also { it.start() }
    }

    private fun priority(level: Char): Int =
        when (level) {
            PhoneLog.ERROR, PhoneLog.SYSTEM_ERROR -> Log.ERROR
            PhoneLog.WARNING, PhoneLog.SYSTEM_WARNING -> Log.WARN
            else -> Log.INFO
        }
}
