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
 * What the app meets, for the laptop (specs/008-phone-log): numbered lines, each on one line and cut to
 * [MAX_BYTES]; the last [capacity] kept for recorders that have not answered yet. The app's own lines are
 * kept whole; the phone's system log's ([system]), which a driver may fill a line a frame, [perSecond] a
 * second at most -- how many were left out said -- and the first to go when the log is full. Any thread
 * adds; the sender reads.
 */
class PhoneLog(
    private val capacity: Int = CAPACITY,
    private val perSecond: Int = PER_SECOND,
    private val clockMs: () -> Long = System::currentTimeMillis,
    /**
     * Each of the app's own lines kept, written on as well: to the system log, for a phone on a cable -- not
     * the system log's own, read from it.
     */
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
    ) = once(INFO, lens, text)

    fun warning(
        lens: String?,
        text: String,
    ) = once(WARNING, lens, text)

    fun error(
        lens: String?,
        text: String,
    ) = once(ERROR, lens, text)

    /**
     * The app's own line of [level] -- [INFO], [WARNING] or [ERROR] -- of [lens], or of the phone as a whole, kept
     * as it comes: its caller counts what it says again itself ([StatusLog], whose line of where a lens came to
     * rest may say what it said a moment before).
     */
    @Synchronized
    fun add(
        level: Char,
        lens: String?,
        text: String,
    ) {
        val now = clockMs()
        tell(now)
        keep(now, level, lens, text)
    }

    /**
     * [add], but the same line again within [AGAIN_MS] -- a camera failing and opened again every 2 s -- counted,
     * and told with its next time: the log keeps what happened, not a thousand times the same.
     */
    @Synchronized
    private fun once(
        level: Char,
        lens: String?,
        text: String,
    ) {
        val now = clockMs()
        tell(now)
        val key = Triple(level, lens, text)
        val before = said[key]
        if (before != null && now - before.atMs < AGAIN_MS) {
            before.again++
            return
        }
        val more =
            before
                ?.again
                ?.takeIf { it > 0 }
                ?.let { " ($it times more in the minute before)" }
                .orEmpty()
        said.remove(key)
        said[key] = Said(now)
        if (said.size > SAID_KEPT) said.remove(said.keys.first())
        keep(now, level, lens, text + more)
    }

    private class Said(
        val atMs: Long,
    ) {
        var again = 0
    }

    /** The app's own lines lately kept, the newest last: one said again within [AGAIN_MS] is counted. */
    private val said = LinkedHashMap<Triple<Char, String?, String>, Said>()

    /** A line of the phone's system log, of [level] -- [SYSTEM_WARNING] or [SYSTEM_ERROR]: [perSecond] a second. */
    @Synchronized
    fun system(
        level: Char,
        text: String,
    ) {
        val now = clockMs()
        tell(now)
        if (inSecond >= perSecond) {
            leftOut++
            return
        }
        inSecond++
        keep(now, level, null, text)
    }

    /** The lines after the one numbered [seq] that are still kept, oldest first. */
    @Synchronized
    fun after(seq: Long): List<LogLine> {
        tell(clockMs())
        return lines.filter { it.seq > seq }
    }

    /**
     * A second gone by: how many of the system log's lines it left out said, whatever line comes next -- or
     * none: the sender's next look tells it, a burst that ends the system log's lines told all the same.
     */
    private fun tell(now: Long) {
        if (Math.floorDiv(now, SECOND_MS) == second) return
        second = Math.floorDiv(now, SECOND_MS)
        inSecond = 0
        if (leftOut > 0) {
            keep(now, SYSTEM_WARNING, null, "$leftOut lines of the system log left out: more than $perSecond a second")
            leftOut = 0
            inSecond++
        }
    }

    private fun keep(
        now: Long,
        level: Char,
        lens: String?,
        text: String,
    ) {
        val line = LogLine(next++, now, level, lens, cut(text))
        lines.addLast(line)
        if (lines.size > capacity) {
            // The system log's oldest line goes first -- the app's own say why a phone gives no video --, but not
            // the line just come: the log holds the lines answered as well, and one full of the app's lines would
            // never keep a system line again. A line gone from between leaves a gap the recorder passes over.
            val oldest = lines.indexOfFirst { it.level == SYSTEM_WARNING || it.level == SYSTEM_ERROR }
            lines.removeAt(if (oldest in 0 until lines.lastIndex) oldest else 0)
        }
        if (level != SYSTEM_WARNING && level != SYSTEM_ERROR) mirror(line)
    }

    companion object {
        const val INFO = 'I'
        const val WARNING = 'W'
        const val ERROR = 'E'

        /** The phone's system log's warnings and errors, as the app reads them (contract). */
        const val SYSTEM_WARNING = 'w'
        const val SYSTEM_ERROR = 'e'

        /** A line's text at most, in UTF-8: a message holds a few, and the network takes it whole. */
        const val MAX_BYTES = 400

        private const val CAPACITY = 1_000
        private const val AGAIN_MS = 60_000L
        private const val SAID_KEPT = 64
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
