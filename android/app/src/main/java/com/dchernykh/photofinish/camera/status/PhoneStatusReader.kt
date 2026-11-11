package com.dchernykh.photofinish.camera.status

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import androidx.core.content.ContextCompat

/**
 * The phone's status read from Android (specs/005-phone-status): the battery from its sticky
 * broadcast, the thermal status (Android 10) and the power saver from the power manager, the Wi-Fi
 * signal from the active network (Android 10) or the Wi-Fi manager. Read on the uplinks' threads,
 * once a second; a reading Android will not give is left out.
 */
class PhoneStatusReader(
    context: Context,
) {
    private val context = context.applicationContext
    private val power = context.getSystemService(PowerManager::class.java)
    private val connectivity = context.getSystemService(ConnectivityManager::class.java)
    private val wifi = context.applicationContext.getSystemService(WifiManager::class.java)

    fun read(): PhoneStatus {
        val battery =
            ContextCompat.registerReceiver(
                context,
                null,
                IntentFilter(Intent.ACTION_BATTERY_CHANGED),
                ContextCompat.RECEIVER_NOT_EXPORTED,
            )
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val temperature = battery?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, NONE) ?: NONE
        return PhoneStatus(
            battery = if (level >= 0 && scale > 0) level * PERCENT / scale else null,
            charging = battery?.let { it.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0 },
            temperatureC = if (temperature == NONE) null else temperature / TENTHS,
            thermal = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) power?.currentThermalStatus else null,
            saver = power?.isPowerSaveMode,
            wifiDbm = wifiDbm(),
        )
    }

    /** The Wi-Fi signal, dBm; null off Wi-Fi -- the phone being the hotspot -- or when unknown. */
    private fun wifiDbm(): Int? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            connectivity
                ?.let { it.getNetworkCapabilities(it.activeNetwork) }
                ?.takeIf { it.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) }
                ?.signalStrength
                ?.takeIf { it != NetworkCapabilities.SIGNAL_STRENGTH_UNSPECIFIED }
        } else {
            @Suppress("DEPRECATION") // the only way before Android 10
            wifi?.connectionInfo?.rssi?.takeIf { it in WEAKEST..0 }
        }

    private companion object {
        const val NONE = Int.MIN_VALUE
        const val PERCENT = 100
        const val TENTHS = 10.0
        const val WEAKEST = -126
    }
}
