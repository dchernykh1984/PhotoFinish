package com.dchernykh.photofinish.camera.status

import android.os.BatteryManager
import java.util.Locale

/**
 * What may stop the phone's stream, as the phone reads it (specs/005-phone-status): its battery,
 * charging or not, the battery's temperature, Android's thermal status, the power saver, the Wi-Fi
 * signal, and the frames its uplink dropped for the network. Null: the phone cannot tell.
 */
data class PhoneStatus(
    val battery: Int? = null,
    val charging: Boolean? = null,
    val temperatureC: Double? = null,
    val thermal: Int? = null,
    val saver: Boolean? = null,
    val wifiDbm: Int? = null,
    val dropped: Long? = null,
    /** The lenses asked for and not streamed, by their codes (specs/004-phone-lenses). */
    val left: List<String> = emptyList(),
    /** The phone's free storage, MB (specs/009). */
    val freeMb: Long? = null,
    /** The video the phone holds for the lens's camera, not sent yet: its span, ms, and its size, MB (specs/009). */
    val unsentMs: Long? = null,
    val unsentMb: Long? = null,
) {
    /** With what the phone holds for the camera: [ms] of video, [bytes] of it. */
    fun holding(
        ms: Long,
        bytes: Long,
    ): PhoneStatus = copy(unsentMs = ms, unsentMb = (bytes + BYTES_PER_MB / 2) / BYTES_PER_MB)

    /** The line the keyframes carry: `key=value` pairs, `;` between, a reading not known left out. */
    fun line(): String =
        listOfNotNull(
            battery?.let { "battery=$it" },
            charging?.let { "charging=${flag(it)}" },
            temperatureC?.let { "temp=${String.format(Locale.ROOT, "%.1f", it)}" },
            thermal?.let { "thermal=$it" },
            saver?.let { "saver=${flag(it)}" },
            wifiDbm?.let { "wifi=$it" },
            dropped?.let { "dropped=$it" },
            left.takeIf { it.isNotEmpty() }?.let { "left=${it.joinToString(",")}" },
            freeMb?.let { "free=$it" },
            unsentMs?.let { "unsent_ms=$it" },
            unsentMb?.let { "unsent_mb=$it" },
        ).joinToString(";")

    private fun flag(on: Boolean) = if (on) "1" else "0"

    companion object {
        const val BYTES_PER_MB = 1_000_000L

        /**
         * Charging as the battery says it: filling, or full on its supply -- a phone plugged into
         * a supply weaker than its use drains, and is not.
         */
        fun charging(batteryStatus: Int): Boolean =
            batteryStatus == BatteryManager.BATTERY_STATUS_CHARGING ||
                batteryStatus == BatteryManager.BATTERY_STATUS_FULL
    }
}
