package com.dchernykh.photofinish.camera.sync

import java.io.Closeable
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.UnknownHostException
import java.nio.ByteBuffer
import kotlin.math.abs

/** The clock exchange's messages (specs/003, contracts/phone-stream.md). */
object ClockExchange {
    private val tag = "PFTS".toByteArray(Charsets.US_ASCII)
    private const val VERSION: Byte = 1
    const val REQUEST_SIZE = 13
    const val ANSWER_SIZE = 29

    class Answer(
        val t1: Long,
        val t2: Long,
        val t3: Long,
    )

    fun request(t1: Long): ByteArray =
        ByteBuffer
            .allocate(REQUEST_SIZE)
            .put(tag)
            .put(VERSION)
            .putLong(t1)
            .array()

    /** The answer in the first [length] bytes, or null when it is not one. */
    fun answer(
        bytes: ByteArray,
        length: Int,
    ): Answer? {
        if (length != ANSWER_SIZE) return null
        val buffer = ByteBuffer.wrap(bytes, 0, length)
        val read = ByteArray(tag.size).also { buffer.get(it) }
        if (!read.contentEquals(tag) || buffer.get() != VERSION) return null
        return Answer(buffer.getLong(), buffer.getLong(), buffer.getLong())
    }
}

/** One exchange: sent at [t1] and answered at [t4] on the phone, [t2] and [t3] on the recorder. */
data class Sample(
    val t1: Long,
    val t2: Long,
    val t3: Long,
    val t4: Long,
) {
    /** The recorder's clock minus the phone's. */
    val offset: Long get() = ((t2 - t1) + (t3 - t4)) / 2

    /** The round trip, less the recorder's time with the request. */
    val delay: Long get() = (t4 - t1) - (t3 - t2)
}

/**
 * The recent exchanges; the offset trusted is the one of the shortest delay. An offset the
 * delays cannot explain is the recorder's clock changed -- the recorder started again, or its
 * computer's clock was set -- and the exchanges before it go.
 */
class ClockOffset(
    private val capacity: Int = 8, // 16 s of exchanges: a better one soon, an old one soon gone
) {
    private val samples = ArrayDeque<Sample>()

    @Synchronized
    fun add(sample: Sample) {
        if (sample.delay < 0) return // clocks that went back mid-exchange: not believed
        val best = best()
        // Each offset is within half its delay of the truth; beyond that, and the drift, it moved.
        if (best != null && abs(sample.offset - best.offset) > (sample.delay + best.delay) / 2 + DRIFT_US) {
            samples.clear()
        }
        samples.addLast(sample)
        while (samples.size > capacity) samples.removeFirst()
    }

    /** The best exchange so far, or null before the first. */
    @Synchronized
    fun best(): Sample? = samples.minByOrNull { it.delay }

    private companion object {
        /** Two clocks 50 ppm apart, over the window's 16 s, with room to spare. */
        const val DRIFT_US = 10_000L
    }
}

/**
 * Keeps the phone's camera clock in step with the recorder's: five exchanges at
 * once, then one every two seconds, over UDP to the recorder's host and port.
 * [clockUs] is the clock the camera stamps its frames with, in microseconds.
 */
class ClockSync(
    private val host: String,
    private val port: Int,
    private val clockUs: () -> Long,
    private val socket: DatagramSocket = DatagramSocket(),
) : Closeable {
    val offset = ClockOffset()

    @Volatile private var running = false

    fun start() {
        running = true
        socket.soTimeout = ANSWER_TIMEOUT_MS
        Thread({ run() }, "clock-sync").apply { isDaemon = true }.start()
    }

    private fun run() {
        var made = 0
        while (running) {
            exchange()
            made++
            if (running) Thread.sleep(if (made < FIRST_EXCHANGES) FIRST_PAUSE_MS else PAUSE_MS)
        }
    }

    /** One exchange; true when it was answered. */
    fun exchange(): Boolean =
        try {
            // A name looked up each time: one that does not resolve yet is tried again later.
            val target = InetSocketAddress(host, port)
            if (target.isUnresolved) throw UnknownHostException(host)
            val t1 = clockUs()
            val request = ClockExchange.request(t1)
            socket.send(DatagramPacket(request, request.size, target))
            offset.add(awaitAnswer(t1))
            true
        } catch (_: IOException) {
            false // unanswered in time, no route or no such host yet: the next exchange tries again
        }

    /** The answer to the request sent at [t1]; late answers to earlier requests are passed over. */
    private fun awaitAnswer(t1: Long): Sample {
        val buffer = ByteArray(ClockExchange.ANSWER_SIZE + 1)
        while (true) {
            val packet = DatagramPacket(buffer, buffer.size)
            socket.receive(packet)
            val t4 = clockUs()
            val answer = ClockExchange.answer(buffer, packet.length)
            if (answer?.t1 == t1) return Sample(t1, answer.t2, answer.t3, t4)
        }
    }

    override fun close() {
        running = false
        socket.close()
    }

    companion object {
        private const val ANSWER_TIMEOUT_MS = 500
        private const val FIRST_EXCHANGES = 5
        private const val FIRST_PAUSE_MS = 100L
        private const val PAUSE_MS = 2_000L
    }
}
