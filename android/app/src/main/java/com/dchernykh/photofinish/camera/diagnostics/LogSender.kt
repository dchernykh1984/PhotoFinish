package com.dchernykh.photofinish.camera.diagnostics

import com.dchernykh.photofinish.camera.pairing.Pairing
import java.io.Closeable
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketTimeoutException

/**
 * Sends [log] to each recorder [destinations] names -- a lens's host, and the port its clock exchange is
 * answered on (specs/008-phone-log) -- from the line after the newest it answered, a few messages a round,
 * twice a second: a message lost on the way is sent again. A recorder that has answered nothing for
 * [QUIET_MS] -- an older PhotoFinish answers none -- is sent to every [SLOW_MS]. One socket for all: an
 * answer is told by who sent it.
 */
class LogSender(
    private val log: PhoneLog,
    private val destinations: () -> List<Pair<String, Int>>,
    private val socket: DatagramSocket = DatagramSocket(),
    private val nowMs: () -> Long = { System.nanoTime() / NANOS_PER_MS },
) : Closeable {
    private class Recorder(
        val since: Long,
    ) {
        var answered = 0L
        var heardMs: Long? = null
        var sentMs: Long? = null

        /** Where its host was found; a name looked up again only when it was not found. */
        var address: InetSocketAddress? = null
    }

    /** The recorders by the host and port the code names; the sender's thread alone keeps them. */
    private val recorders = HashMap<Pair<String, Int>, Recorder>()

    @Volatile private var running = false

    init {
        socket.soTimeout = LISTEN_MS
    }

    fun start() {
        running = true
        Thread({ run() }, "phone-log").apply { isDaemon = true }.start()
    }

    // Whatever a round throws costs that round: the log must never end the app it tells of (FR-006).
    @Suppress("TooGenericExceptionCaught")
    private fun run() {
        while (running) {
            try {
                round()
                val until = nowMs() + ROUND_MS
                while (running && nowMs() < until) hear()
            } catch (error: Exception) {
                log.warning(null, "the log could not be sent: ${Crashes.describe(error)}")
                Thread.sleep(ROUND_MS)
            }
        }
    }

    /** One round: each recorder due sent the lines it has not answered, [WINDOW] messages at most. */
    fun round() {
        val now = nowMs()
        val wanted = destinations().toSet()
        recorders.keys.retainAll(wanted)
        for (named in wanted) {
            val recorder = recorders.getOrPut(named) { Recorder(now) }
            // A name that does not resolve now keeps what its recorder answered: tried again next round.
            val address = recorder.address ?: address(named.first, named.second)?.also { recorder.address = it }
            if (address != null && log.newest > recorder.answered && due(recorder, now)) {
                recorder.sentMs = now
                // A recorder that never answered may be an older PhotoFinish's, to which a message is a
                // datagram too long (Windows pauses its clock exchange for each): one a round.
                send(log.after(recorder.answered), address, if (recorder.heardMs == null) 1 else WINDOW)
            }
        }
    }

    /** [lines] to [address], [most] messages at most, each saying the round began with the first. */
    private fun send(
        lines: List<LogLine>,
        address: InetSocketAddress,
        most: Int,
    ) {
        val from = lines.firstOrNull()?.seq ?: return
        var prev = from - 1 // the round's first message: the recorder knows it by this
        var left = lines
        repeat(most) {
            if (left.isNotEmpty()) {
                val (bytes, count) = LogMessages.message(log.run, from, prev, left)
                send(bytes, address)
                prev = left[count - 1].seq
                left = left.drop(count)
            }
        }
    }

    /** An answer, waited for [LISTEN_MS] at most: the newest line its recorder kept. */
    fun hear() {
        val buffer = ByteArray(ANSWER_BYTES)
        val packet = DatagramPacket(buffer, buffer.size)
        if (!receive(packet)) return // a packet that came from nowhere has no sender to ask about
        val seq = LogMessages.answered(buffer, packet.length, log.run)
        val recorder = recorders.values.firstOrNull { it.address == packet.socketAddress }
        if (seq == null || recorder == null) return
        recorder.answered = maxOf(recorder.answered, seq)
        recorder.heardMs = nowMs()
    }

    /** [packet] received; false when none came in [LISTEN_MS], or the network failed. */
    private fun receive(packet: DatagramPacket): Boolean =
        try {
            socket.receive(packet)
            true
        } catch (_: SocketTimeoutException) {
            false
        } catch (_: IOException) {
            if (running) Thread.sleep(LISTEN_MS.toLong()) // a network gone: no busy loop
            false
        }

    /** The newest line [host]'s recorder on [port] answered: a test's look. */
    internal fun answered(
        host: String,
        port: Int,
    ): Long? = recorders[host to port]?.answered

    override fun close() {
        running = false
        socket.close()
    }

    private fun due(
        recorder: Recorder,
        now: Long,
    ): Boolean {
        val sent = recorder.sentMs ?: return true
        val quiet = now - (recorder.heardMs ?: recorder.since) > QUIET_MS
        return !quiet || now - sent >= SLOW_MS
    }

    private fun send(
        bytes: ByteArray,
        address: InetSocketAddress,
    ) {
        try {
            socket.send(DatagramPacket(bytes, bytes.size, address))
        } catch (_: IOException) {
            // no route now: sent again in a round
        }
    }

    companion object {
        /** The recorders a pairing [code] names, a lens's host and port each: where the log goes. */
        fun recordersOf(code: String): List<Pair<String, Int>> =
            Pairing
                .parse(code)
                .targets
                .map { it.address.host to it.address.port }
                .distinct()

        private const val NANOS_PER_MS = 1_000_000L
        private const val ROUND_MS = 500L
        private const val LISTEN_MS = 100
        private const val WINDOW = 8
        private const val QUIET_MS = 10_000L
        private const val SLOW_MS = 5_000L
        private const val ANSWER_BYTES = 128

        /** [host] and [port] as an address to send to; null when the name does not resolve yet. */
        private fun address(
            host: String,
            port: Int,
        ): InetSocketAddress? = InetSocketAddress(host, port).takeUnless { it.isUnresolved }
    }
}
