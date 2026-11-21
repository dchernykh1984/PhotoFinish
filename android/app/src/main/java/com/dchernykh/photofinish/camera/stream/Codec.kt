package com.dchernykh.photofinish.camera.stream

/**
 * The codec a stream is encoded with (specs/010-hevc): H.264, or H.265 as an experiment, at [share] of the
 * bitrate H.264 takes for the same size and rate -- H.265 gives its picture at 50 to 70 % of it.
 */
enum class Codec(
    /** As a kept stream's header names it. */
    val code: String,
    /** As PhotoFinish's code names it. */
    val paired: String,
    val mime: String,
    val share: Double,
) {
    AVC("avc", "h264", "video/avc", 1.0),
    HEVC("hevc", "h265", "video/hevc", 0.7),
    ;

    companion object {
        fun named(code: String?): Codec? = entries.firstOrNull { it.code == code }

        fun paired(name: String): Codec? = entries.firstOrNull { it.paired == name.lowercase() }
    }
}
