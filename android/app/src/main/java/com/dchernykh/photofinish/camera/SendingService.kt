package com.dchernykh.photofinish.camera

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.dchernykh.photofinish.camera.capture.Senders
import com.dchernykh.photofinish.camera.stream.FrameStore
import com.dchernykh.photofinish.camera.ui.megabytes
import com.dchernykh.photofinish.camera.ui.said
import com.dchernykh.photofinish.camera.ui.span

/**
 * Keeps the app's process while it has frames to send (specs/009, FR-006): a lens streams, or the backlog holds a
 * stream -- after Stop, the screen off, the app in the background --, its notification saying how much video is
 * left. It stops itself once nothing is; Android 15's time limit stops it too, and what is kept is sent at the next
 * start of the app.
 */
class SendingService : Service() {
    /** Its own thread: what is held is counted under the stores' locks, never on the main thread. */
    private val thread = HandlerThread("sending").apply { start() }
    private val handler = Handler(thread.looper)

    /**
     * The processor kept awake while it runs: a foreground service alone keeps the process, not the processor, and
     * with the screen off the phone would sleep with video left to send. Taken for a minute at each tick, so a
     * service Android ends without a word lets it go within the minute; let go while no laptop has taken a
     * connection for [UNHEARD_MS] -- gone for the night --, the frames kept for when the phone wakes.
     */
    private val awake by lazy {
        getSystemService(PowerManager::class.java)
            ?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "PhotoFinish:sending")
            ?.apply { setReferenceCounted(false) }
    }

    /** When a laptop last took a connection of the phone's, on the elapsed clock. */
    private var heardMs = 0L

    private val tick =
        object : Runnable {
            override fun run() {
                if (!Senders.active) return stopSelf()
                val now = SystemClock.elapsedRealtime()
                if (Senders.board.anyConnected()) heardMs = now
                if (awake(heardMs, now)) awake?.acquire(AWAKE_MS) else awake?.takeIf { it.isHeld }?.release()
                notify(notification(Senders.backlog.pending()))
                handler.postDelayed(this, TICK_MS)
            }
        }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int,
    ): Int {
        val type =
            if (Build.VERSION.SDK_INT >=
                Build.VERSION_CODES.Q
            ) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            } else {
                0
            }
        try {
            ServiceCompat.startForeground(this, ID, notification(null), type) // counted at its first tick
        } catch (_: IllegalStateException) {
            // Android refusing it -- the day's time for sending in the background spent --: the app goes on unkept,
            // never ended for it, as it was started as a plain service ([start]): no promise of the foreground is
            // broken by stopping. What is kept is sent at its next start. Not asked again for a minute.
            refusedMs = SystemClock.elapsedRealtime()
            stopSelf()
            return START_NOT_STICKY
        }
        running = true
        heardMs = SystemClock.elapsedRealtime() // a while to connect in, the laptop perhaps there
        awake?.acquire(AWAKE_MS)
        handler.removeCallbacks(tick)
        handler.postDelayed(tick, TICK_MS)
        return START_NOT_STICKY
    }

    override fun onTimeout(
        startId: Int,
        fgsType: Int,
    ) = stopSelf() // the day's time for sending in the background spent: the next start of the app goes on

    override fun onDestroy() {
        running = false
        handler.removeCallbacks(tick)
        awake?.takeIf { it.isHeld }?.release()
        thread.quitSafely()
        super.onDestroy()
    }

    /** The notification, saying what is [held] to send; streaming alone said before it is counted. */
    private fun notification(held: FrameStore.Pending?): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        val channel =
            NotificationChannel(CHANNEL, getString(R.string.sending_channel), NotificationManager.IMPORTANCE_LOW)
        manager?.createNotificationChannel(channel)
        val text =
            if (held != null && said(held, stopped = !Senders.backlog.streaming)) {
                getString(R.string.sending_left, span(held.ms), megabytes(held.bytes))
            } else {
                getString(R.string.sending_live)
            }
        val open = packageManager.getLaunchIntentForPackage(packageName)
        val tap =
            open?.let {
                android.app.PendingIntent.getActivity(this, 0, it, android.app.PendingIntent.FLAG_IMMUTABLE)
            }
        return NotificationCompat
            .Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(tap)
            .build()
    }

    private fun notify(notification: Notification) {
        val allowed =
            Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) ==
                PackageManager.PERMISSION_GRANTED
        if (allowed) getSystemService(NotificationManager::class.java)?.notify(ID, notification)
    }

    companion object {
        /** It runs: the screen starts it again whenever it does not and there are frames to send. */
        @Volatile var running = false
            private set

        /** When Android last refused it the foreground, on the elapsed clock: asked again a minute on. */
        @Volatile internal var refusedMs = Long.MIN_VALUE / 2

        /**
         * Whether the screen starts it at [nowMs]: frames to send, the screen shown, it not running already, and
         * not refused within the minute -- never asked again and again of an Android that keeps saying no.
         */
        fun wanted(
            sending: Boolean,
            shown: Boolean,
            nowMs: Long = SystemClock.elapsedRealtime(),
        ): Boolean = sending && shown && !running && nowMs - refusedMs >= REFUSED_WAIT_MS

        private const val REFUSED_WAIT_MS = 60_000L

        private const val ID = 9
        private const val CHANNEL = "sending"
        private const val TICK_MS = 2_000L

        /** How long each tick keeps the processor awake: past the next ticks, gone within a minute of the last. */
        private const val AWAKE_MS = 60_000L

        /** No laptop taking a connection this long, the processor is let sleep: ten minutes of trying. */
        const val UNHEARD_MS = 600_000L

        /** Whether the processor is kept awake at [nowMs], a laptop last taking a connection at [heardMs]. */
        fun awake(
            heardMs: Long,
            nowMs: Long,
        ): Boolean = nowMs - heardMs < UNHEARD_MS

        /**
         * Started from the screen, in the foreground, as there are frames to send; false when Android refuses it --
         * an app in the background may not start one --: the screen starts it again once it is back. A plain start,
         * the service putting itself in the foreground: one Android then refuses that stops, the app going on, where
         * a foreground start would have Android end the app for a service gone before it was in the foreground.
         */
        fun start(context: Context): Boolean =
            try {
                context.startService(Intent(context, SendingService::class.java))
                true
            } catch (_: IllegalStateException) {
                false
            }
    }
}
