package com.dchernykh.photofinish.camera.status

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import androidx.core.content.ContextCompat

/**
 * The phone's status read from Android (specs/005-phone-status): the battery from its sticky
 * broadcast, the thermal status (Android 10) and the power saver from the power manager, the Wi-Fi
 * signal from the Wi-Fi manager. Asked on the uplinks' threads,
 * read once a second for all of them; a reading Android will not give is left out.
 */
class PhoneStatusReader(
    context: Context,
) {
    private val context = context.applicationContext
    private val power = context.getSystemService(PowerManager::class.java)
    private val wifi = context.applicationContext.getSystemService(WifiManager::class.java)

    private val recent = Recent(ONE_SECOND_NS) { readNow() }

    /** The status, read at most once a second whatever the number of lenses asking. */
    fun read(): PhoneStatus = recent.get()

    private fun readNow(): PhoneStatus {
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
            charging =
                battery?.let {
                    PhoneStatus.charging(
                        it.getIntExtra(BatteryManager.EXTRA_STATUS, BatteryManager.BATTERY_STATUS_UNKNOWN),
                    )
                },
            temperatureC = if (temperature == NONE) null else temperature / TENTHS,
            thermal = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) power?.currentThermalStatus else null,
            saver = power?.isPowerSaveMode,
            wifiDbm = wifiDbm(),
        )
    }

    /**
     * The Wi-Fi signal, dBm, from the Wi-Fi the phone joined -- not the active network, which Android
     * keeps on mobile data while a race's Wi-Fi has no internet; null off Wi-Fi, the phone being the
     * hotspot.
     */
    @Suppress("DEPRECATION") // the signal of the Wi-Fi joined, whatever network is the default
    private fun wifiDbm(): Int? = wifi?.connectionInfo?.rssi?.takeIf { it in WEAKEST..0 }

    private companion object {
        const val NONE = Int.MIN_VALUE
        const val PERCENT = 100
        const val TENTHS = 10.0
        const val WEAKEST = -126
        const val ONE_SECOND_NS = 1_000_000_000L
    }
}
