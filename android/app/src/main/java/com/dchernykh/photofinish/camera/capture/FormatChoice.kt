package com.dchernykh.photofinish.camera.capture

import kotlin.math.roundToInt

data class Resolution(
    val width: Int,
    val height: Int,
) {
    override fun toString(): String = "${width}x$height"
}

/** One of the camera's auto-exposure frame-rate ranges. */
data class FpsRange(
    val lower: Int,
    val upper: Int,
)

/** What the app streams: a size, a frame rate, the camera's range for it, a bitrate. */
data class StreamFormat(
    val resolution: Resolution,
    val fps: Int,
    val range: FpsRange,
    val bitrate: Int,
)

/**
 * The choice of size, frame rate and bitrate from what the camera and the encoder
 * both give: the sizes a finish camera wants, 60 fps first, a bitrate that follows.
 */
object FormatChoice {
    /** The sizes offered, in the order offered: 1080p first, a fair weight for Wi-Fi. */
    val SIZES = listOf(Resolution(1920, 1080), Resolution(2560, 1440), Resolution(1280, 720))

    /** The frame rates offered, the fastest first. */
    val RATES = listOf(60, 50, 30, 25)

    private const val BITS_PER_PIXEL = 0.08
    private const val MAX_BITRATE = 16_000_000
    private const val BITRATE_STEP = 100_000

    /** The offered sizes the camera gives and the encoder takes at some offered rate. */
    fun resolutions(
        cameraSizes: Collection<Resolution>,
        encoderTakes: (Resolution, Int) -> Boolean,
    ): List<Resolution> = SIZES.filter { size -> size in cameraSizes && RATES.any { encoderTakes(size, it) } }

    /** The offered rates some range of the camera reaches, at [resolution], the fastest first. */
    fun rates(
        ranges: Collection<FpsRange>,
        resolution: Resolution,
        encoderTakes: (Resolution, Int) -> Boolean,
    ): List<Int> = RATES.filter { fps -> rangeFor(fps, ranges) != null && encoderTakes(resolution, fps) }

    /** The camera's range for [fps]: a fixed one, else the one with the highest floor. */
    fun rangeFor(
        fps: Int,
        ranges: Collection<FpsRange>,
    ): FpsRange? =
        ranges
            .filter { it.upper == fps }
            .maxByOrNull { it.lower }

    fun bitrate(
        resolution: Resolution,
        fps: Int,
    ): Int {
        val bits = resolution.width * resolution.height * fps * BITS_PER_PIXEL
        return minOf(MAX_BITRATE, (bits / BITRATE_STEP).roundToInt() * BITRATE_STEP)
    }

    /**
     * The format to stream: [wanted] size and [wantedFps] when the phone gives them,
     * else the first offered size and its fastest rate; null when nothing fits.
     */
    fun choose(
        cameraSizes: Collection<Resolution>,
        ranges: Collection<FpsRange>,
        encoderTakes: (Resolution, Int) -> Boolean,
        wanted: Resolution? = null,
        wantedFps: Int? = null,
    ): StreamFormat? {
        val sizes = resolutions(cameraSizes, encoderTakes)
        val size = wanted?.takeIf { it in sizes } ?: sizes.firstOrNull() ?: return null
        val rates = rates(ranges, size, encoderTakes)
        val fps = wantedFps?.takeIf { it in rates } ?: rates.firstOrNull() ?: return null
        return rangeFor(fps, ranges)?.let { StreamFormat(size, fps, it, bitrate(size, fps)) }
    }
}
