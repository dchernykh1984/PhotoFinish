package com.dchernykh.photofinish.camera.pairing

import com.dchernykh.photofinish.camera.stream.Codec

/** A lens of the phone, as PhotoFinish's pairing code names it (specs/004-phone-lenses). */
enum class Lens(
    val code: String,
) {
    MAIN("main"),
    ULTRAWIDE("ultrawide"),
    TELEPHOTO("telephoto"),
    FRONT("front"),
    ;

    companion object {
        fun named(text: String): Lens? = entries.firstOrNull { it.code == text.lowercase() }
    }
}

/** A stream PhotoFinish asks for: [lens], to [address]. */
data class LensTarget(
    val lens: Lens,
    val address: RtmpAddress,
)

/**
 * What PhotoFinish's code, scanned or typed, asks for: an address alone is the main lens; else
 * one line per lens, `<lens> <address>`; `codec h265` asks for H.265 (specs/010-hevc). A line that cannot be
 * read, or a lens named again after the first, is [unread], to be said.
 */
data class Pairing(
    val targets: List<LensTarget>,
    val unread: List<String>,
    val codec: Codec = Codec.AVC,
) {
    companion object {
        private val SPACES = Regex("\\s+")
        private const val CODEC = "codec"

        fun parse(text: String): Pairing {
            val targets = mutableListOf<LensTarget>()
            val unread = mutableListOf<String>()
            var codec = Codec.AVC
            text.lines().map { it.trim() }.filter { it.isNotEmpty() }.forEach { line ->
                val asked = line.split(SPACES).takeIf { it.size == 2 && it[0] == CODEC }?.let { Codec.paired(it[1]) }
                val target = if (asked == null) read(line) else null
                when {
                    asked != null -> codec = asked
                    target == null || targets.any { it.lens == target.lens } -> unread += line
                    else -> targets += target
                }
            }
            return Pairing(targets, unread, codec)
        }

        private fun read(line: String): LensTarget? {
            val parts = line.split(SPACES, limit = 2)
            val lens = if (parts.size == 2) Lens.named(parts[0]) else Lens.MAIN
            val address = RtmpAddress.parse(parts.last())
            return if (lens == null || address == null) null else LensTarget(lens, address)
        }
    }
}
