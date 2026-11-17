package com.dchernykh.photofinish.camera.diagnostics

import java.security.SecureRandom

/** A line of the phone's log: its number in this run of the app, when, how grave, of which lens. */
class LogLine(
    val seq: Long,
    val atMs: Long,
    val level: Char,
    /** A lens's code; null for the phone as a whole. */
    val lens: String?,
    val text: String,
)

/**
 * What the app meets, for the laptop (specs/008-phone-log): numbered lines, the last [capacity] kept for
 * recorders that have not answered yet, [perSecond] a second at most -- how many were left out said -- each
 * on one line and cut to [MAX_BYTES]. Any thread adds; the sender reads.
 */
class PhoneLog(
    private val capacity: Int = CAPACITY,
    private val perSecond: Int = PER_SECOND,
    private val clockMs: () -> Long = System::currentTimeMillis,
    /** Each line kept, written on as well: to the system log, for a phone on a cable. */
    private val mirror: (LogLine) -> Unit = {},
) {
    /** This run of the app, in every message: a recorder knows the app was started again. */
    val run: String = ByteArray(RUN_BYTES).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }

    private val lines = ArrayDeque<LogLine>()
    private var next = 1L
    private var second = Long.MIN_VALUE
    private var inSecond = 0
    private var leftOut = 0

    /** The newest line's number; 0 before the first. */
    val newest: Long
        @Synchronized get() = next - 1

    fun info(
        lens: String?,
        text: String,
    ) = add(INFO, lens, text)

    fun warning(
        lens: String?,
        text: String,
    ) = add(WARNING, lens, text)

    fun error(
        lens: String?,
        text: String,
    ) = add(ERROR, lens, text)

    /** A line of [level] -- [INFO], [WARNING] or [ERROR] -- of [lens], or of the phone as a whole. */
    @Synchronized
    fun add(
        level: Char,
        lens: String?,
        text: String,
    ) {
        val now = clockMs()
        if (Math.floorDiv(now, SECOND_MS) != second) {
            second = Math.floorDiv(now, SECOND_MS)
            inSecond = 0
            if (leftOut > 0) {
                keep(now, WARNING, null, "$leftOut lines left out: more than $perSecond a second")
                leftOut = 0
                inSecond++
            }
        }
        if (inSecond >= perSecond) {
            leftOut++
            return
        }
        inSecond++
        keep(now, level, lens, text)
    }

    /** The lines after the one numbered [seq] that are still kept, oldest first. */
    @Synchronized
    fun after(seq: Long): List<LogLine> = lines.filter { it.seq > seq }

    private fun keep(
        now: Long,
        level: Char,
        lens: String?,
        text: String,
    ) {
        val line = LogLine(next++, now, level, lens, cut(text))
        lines.addLast(line)
        while (lines.size > capacity) lines.removeFirst()
        mirror(line)
    }

    companion object {
        const val INFO = 'I'
        const val WARNING = 'W'
        const val ERROR = 'E'

        /** A line's text at most, in UTF-8: a message holds a few, and the network takes it whole. */
        const val MAX_BYTES = 400

        private const val CAPACITY = 1_000
        private const val PER_SECOND = 20
        private const val SECOND_MS = 1_000L
        private const val RUN_BYTES = 8
        private const val CUT_MARK = " [cut]"
        private val BREAKS = Regex("\\s*[\\r\\n]+\\s*")

        /** [text] on one line, and cut, whole characters, where it would be over [MAX_BYTES]. */
        fun cut(text: String): String {
            val flat = text.trim().replace(BREAKS, " | ")
            if (flat.toByteArray(Charsets.UTF_8).size <= MAX_BYTES) return flat
            val room = MAX_BYTES - CUT_MARK.length
            var bytes = 0
            var end = 0
            while (end < flat.length) {
                val point = flat.codePointAt(end)
                val size = utf8Size(point)
                if (bytes + size > room) break
                bytes += size
                end += Character.charCount(point)
            }
            return flat.substring(0, end) + CUT_MARK
        }

        private fun utf8Size(point: Int): Int =
            when {
                point < 0x80 -> 1
                point < 0x800 -> 2
                point < 0x10000 -> 3
                else -> 4
            }
    }
}
