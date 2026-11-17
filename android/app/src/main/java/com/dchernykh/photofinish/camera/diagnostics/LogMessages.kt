package com.dchernykh.photofinish.camera.diagnostics

/**
 * The log's messages to a recorder and its answers, on the port of the clock exchange (specs/008-phone-log,
 * contract): text, `PFLG 1 <run> <from>` -- the line the phone's round of messages began with, the oldest it
 * still had that the recorder had not answered -- and a line a line, `<seq> <ms> <level> <lens> <text>`, `-`
 * for the phone as a whole; the answer `PFLG 1 <run> <seq>`, the newest line the recorder kept.
 */
object LogMessages {
    /** A message at most: one the network takes whole, unsplit. */
    const val MAX_BYTES = 1_200

    private const val TAG = "PFLG"
    private const val VERSION = "1"
    private const val ANSWER_PARTS = 4

    /**
     * A message of [run]'s [lines] from the first, as many as [MAX_BYTES] holds -- one at least -- and how many;
     * [from] the line the round began with.
     */
    fun message(
        run: String,
        from: Long,
        lines: List<LogLine>,
    ): Pair<ByteArray, Int> {
        val text = StringBuilder("$TAG $VERSION $run $from\n")
        var size = text.length
        var count = 0
        for (line in lines) {
            val written = "${line.seq} ${line.atMs} ${line.level} ${line.lens ?: "-"} ${line.text}\n"
            val bytes = written.toByteArray(Charsets.UTF_8).size
            if (count > 0 && size + bytes > MAX_BYTES) break
            text.append(written)
            size += bytes
            count++
        }
        return text.toString().toByteArray(Charsets.UTF_8) to count
    }

    /** The newest line a recorder kept of [run], as its answer of [length] bytes says; null for no answer of [run]. */
    fun answered(
        answer: ByteArray,
        length: Int,
        run: String,
    ): Long? {
        val parts = String(answer, 0, length, Charsets.UTF_8).trim().split(' ')
        if (parts.size != ANSWER_PARTS || parts.take(ANSWER_PARTS - 1) != listOf(TAG, VERSION, run)) return null
        return parts.last().toLongOrNull()?.takeIf { it >= 0 }
    }
}
