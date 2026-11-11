package com.dchernykh.photofinish.camera.status

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
) {
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
        ).joinToString(";")

    private fun flag(on: Boolean) = if (on) "1" else "0"
}
