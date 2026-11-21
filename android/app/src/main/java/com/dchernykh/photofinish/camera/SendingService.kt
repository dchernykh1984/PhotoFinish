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
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.dchernykh.photofinish.camera.capture.Senders
import com.dchernykh.photofinish.camera.ui.megabytes
import com.dchernykh.photofinish.camera.ui.span

/**
 * Keeps the app's process while it has frames to send (specs/009, FR-006): a lens streams, or the backlog holds a
 * stream -- after Stop, the screen off, the app in the background --, its notification saying how much video is
 * left. It stops itself once nothing is; Android 15's time limit stops it too, and what is kept is sent at the next
 * start of the app.
 */
class SendingService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private val tick =
        object : Runnable {
            override fun run() {
                if (!Senders.active) return stopSelf()
                notify(notification())
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
        ServiceCompat.startForeground(this, ID, notification(), type)
        handler.removeCallbacks(tick)
        handler.postDelayed(tick, TICK_MS)
        return START_NOT_STICKY
    }

    override fun onTimeout(
        startId: Int,
        fgsType: Int,
    ) = stopSelf() // the day's time for sending in the background spent: the next start of the app goes on

    override fun onDestroy() {
        handler.removeCallbacks(tick)
        super.onDestroy()
    }

    private fun notification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        val channel =
            NotificationChannel(CHANNEL, getString(R.string.sending_channel), NotificationManager.IMPORTANCE_LOW)
        manager?.createNotificationChannel(channel)
        val held = Senders.backlog.pending()
        val text =
            if (held.bytes > 0) {
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
        private const val ID = 9
        private const val CHANNEL = "sending"
        private const val TICK_MS = 2_000L

        /** Started from the screen, in the foreground, as there are frames to send. */
        fun start(context: Context) {
            ContextCompat.startForegroundService(context, Intent(context, SendingService::class.java))
        }
    }
}
