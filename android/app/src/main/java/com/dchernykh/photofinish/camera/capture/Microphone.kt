package com.dchernykh.photofinish.camera.capture

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTimestamp
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaRecorder
import com.dchernykh.photofinish.camera.stream.EncodedFrame
import com.dchernykh.photofinish.camera.stream.SoundTime
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The phone's microphone into AAC, mono, 48 kHz, 128 kbit/s (specs/013-sound), on a thread of its own while it
 * runs: each piece stamped with when its first sample was heard, on the clock the lens's frames are stamped on --
 * [framesClock], unknown before the lens's first frame, when a piece is not kept: there is no run to keep it in.
 * Allowed the microphone or not is the caller's to know: one refused fails to open, and is said.
 */
internal class Microphone(
    private val onConfig: (ByteArray) -> Unit,
    private val onPiece: (EncodedFrame) -> Unit,
    private val framesClock: () -> (() -> Long)?,
    /** The microphone allowed, asked at each start: allowed after the stream began, it starts at the next. */
    private val allowed: () -> Boolean,
    /** Told whether it runs: as it starts, before its thread can fail, and as it fails. */
    private val sounded: (Boolean) -> Unit,
    private val failed: (String) -> Unit,
) {
    /** Started and not stopped since: a start put off for a thread still reading is made then. */
    @Volatile private var wanted = false

    /** Its refusal said already: once, not at each camera opened again. */
    private var refusalSaid = false

    /** The thread reading the microphone now, and its own word to go on: one stopped never runs again. */
    private var running: AtomicBoolean? = null
    private var thread: Thread? = null

    /**
     * Started, unless it runs: whether it runs; said when the microphone or its encoder cannot be opened. Not while
     * the thread of a stop before still reads -- the audio server stalled --: two would send each piece twice.
     */
    @Synchronized
    fun start(): Boolean {
        wanted = true
        if (running?.get() == true) return true
        val opened =
            when {
                !allowed() -> refused()
                stillReading() -> later()
                else -> open()
            }
        if (opened == null) return false.also { sounded(false) }
        val going = AtomicBoolean(true)
        running = going
        sounded(true) // before its thread runs: a failure of its told after
        thread = Thread({ run(opened.first, opened.second, going) }, "microphone").apply { start() }
        return true
    }

    /** Started once the thread of a stop before has stopped reading, if still wanted then. */
    private fun later(): Pair<AudioRecord, MediaCodec>? {
        val before = thread
        Thread(
            {
                before?.join(LATER_MS)
                if (wanted) start()
            },
            "microphone-later",
        ).apply {
            isDaemon = true
            start()
        }
        return null
    }

    /** Not allowed the microphone: said the first time, the stream going without sound; nothing opened. */
    private fun refused(): Pair<AudioRecord, MediaCodec>? {
        if (!refusalSaid) failed("no sound: the microphone is not allowed")
        refusalSaid = true
        return null
    }

    /** The thread of a stop before still reads after a moment more: the audio server stalled. */
    private fun stillReading(): Boolean {
        val before = thread ?: return false
        before.join(JOIN_MS)
        return before.isAlive
    }

    /** Stopped, its thread waited for a moment: a piece on its way is let go. */
    @Synchronized
    fun stop() {
        wanted = false
        running?.set(false)
        running = null
        thread?.join(JOIN_MS)
    }

    @SuppressLint("MissingPermission") // the caller asks; one refused fails to open, and is said
    @Suppress("TooGenericExceptionCaught") // a microphone the phone will not open costs the sound, never the app
    private fun open(): Pair<AudioRecord, MediaCodec>? {
        refusalSaid = false // allowed again: a refusal after it said again
        var record: AudioRecord? = null
        var codec: MediaCodec? = null
        return try {
            record = recorder()
            val format =
                MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, RATE, 1).apply {
                    setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
                    setInteger(MediaFormat.KEY_BIT_RATE, BITRATE)
                    setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, READ_BYTES)
                }
            codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            codec.start()
            record.startRecording()
            record to codec
        } catch (error: Exception) {
            record?.release()
            codec?.release() // made, perhaps started: an encoder leaked is one the video may not get
            failed("no sound: ${error.message ?: error.javaClass.simpleName}")
            null
        }
    }

    /**
     * The microphone as a camcorder records it -- tuned for video, the one beside the lens where a phone has
     * several --, else the plain one a phone may offer alone.
     */
    @SuppressLint("MissingPermission") // asked by the caller, as for open
    private fun recorder(): AudioRecord {
        val least = AudioRecord.getMinBufferSize(RATE, CHANNEL, PCM)
        for (source in listOf(MediaRecorder.AudioSource.CAMCORDER, MediaRecorder.AudioSource.MIC)) {
            val record = AudioRecord(source, RATE, CHANNEL, PCM, maxOf(least, BUFFER_BYTES))
            if (record.state == AudioRecord.STATE_INITIALIZED) return record
            record.release()
        }
        error("the microphone did not open")
    }

    @Suppress("TooGenericExceptionCaught") // an encoder that fails costs the sound from then on, never the app
    private fun run(
        record: AudioRecord,
        codec: MediaCodec,
        going: AtomicBoolean,
    ) {
        val stamp = AudioTimestamp()
        val info = MediaCodec.BufferInfo()
        var heard = 0L // samples read so far
        try {
            while (going.get()) {
                val index = codec.dequeueInputBuffer(WAIT_US)
                if (index >= 0) {
                    val buffer = codec.getInputBuffer(index) ?: continue
                    buffer.clear()
                    val bytes = record.read(buffer, minOf(buffer.remaining(), READ_BYTES))
                    // An error -- the audio server gone, the microphone taken -- comes at once at every read: stopped,
                    // said, never read again and again for nothing.
                    check(bytes >= 0) { "the microphone stopped (error $bytes)" }
                    val read = bytes
                    codec.queueInputBuffer(index, 0, read, heardUs(record, stamp, heard, read), 0)
                    heard += read / 2
                }
                drain(codec, info)
            }
        } catch (error: RuntimeException) {
            failed("no sound from now on: ${error.message ?: error.javaClass.simpleName}")
        } finally {
            // Each let go on its own: an encoder in its error state throws at stop, and an exception out of this
            // thread would end the app -- both lenses' streams with it. Released whatever came before.
            going.set(false) // the next start opens the microphone again
            runCatching { record.stop() }
            runCatching { record.release() }
            runCatching { codec.stop() }
            runCatching { codec.release() }
        }
    }

    /**
     * When the first of the [read] bytes just read, sample [heard], was heard, us on the monotonic clock: by the
     * microphone's own timestamp, else as the read ended less its length.
     */
    private fun heardUs(
        record: AudioRecord,
        stamp: AudioTimestamp,
        heard: Long,
        read: Int,
    ): Long {
        val nanos =
            if (record.getTimestamp(stamp, AudioTimestamp.TIMEBASE_MONOTONIC) == AudioRecord.SUCCESS) {
                SoundTime.heardNanos(heard, stamp.framePosition, stamp.nanoTime, RATE)
            } else {
                System.nanoTime() - (read / 2) * NANOS / RATE
            }
        return nanos / 1000
    }

    /** What the encoder has given: its config once, each piece on the frames' clock. */
    private fun drain(
        codec: MediaCodec,
        info: MediaCodec.BufferInfo,
    ) {
        while (true) {
            val index = codec.dequeueOutputBuffer(info, 0)
            if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                codec.outputFormat.getByteBuffer("csd-0")?.let { onConfig(ByteArray(it.remaining()).also(it::get)) }
                continue
            }
            if (index < 0) return
            val bytes = ByteArray(info.size)
            codec.getOutputBuffer(index)?.apply {
                position(info.offset)
                get(bytes)
            }
            codec.releaseOutputBuffer(index, false)
            when {
                info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0 -> onConfig(bytes)
                bytes.isNotEmpty() ->
                    framesClock()?.let { clock ->
                        val at = SoundTime.onFramesClock(info.presentationTimeUs, clock(), System.nanoTime() / 1000)
                        onPiece(EncodedFrame(bytes, at, keyframe = false, sound = true))
                    }
            }
        }
    }

    companion object {
        const val RATE = 48_000
        private const val CHANNEL = AudioFormat.CHANNEL_IN_MONO
        private const val PCM = AudioFormat.ENCODING_PCM_16BIT
        private const val BITRATE = 128_000
        private const val READ_BYTES = 2048 * 2 // two AAC frames' samples at a time
        private const val BUFFER_BYTES = RATE / 5 * 2 // a fifth of a second: a slow thread loses nothing
        private const val WAIT_US = 10_000L
        private const val JOIN_MS = 500L
        private const val LATER_MS = 5_000L
        private const val NANOS = 1_000_000_000L
    }
}
