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
    private val failed: (String) -> Unit,
) {
    @Volatile private var running = false
    private var thread: Thread? = null

    /** Started, unless it runs; said when the microphone or its encoder cannot be opened. */
    @Synchronized
    fun start() {
        if (running) return
        val opened = open() ?: return
        running = true
        thread = Thread({ run(opened.first, opened.second) }, "microphone").apply { start() }
    }

    /** Stopped, its thread waited for a moment: a piece on its way is let go. */
    @Synchronized
    fun stop() {
        running = false
        thread?.join(JOIN_MS)
        thread = null
    }

    @SuppressLint("MissingPermission") // the caller asks; one refused fails to open, and is said
    @Suppress("TooGenericExceptionCaught") // a microphone the phone will not open costs the sound, never the app
    private fun open(): Pair<AudioRecord, MediaCodec>? {
        var record: AudioRecord? = null
        return try {
            val least = AudioRecord.getMinBufferSize(RATE, CHANNEL, PCM)
            record = AudioRecord(MediaRecorder.AudioSource.CAMCORDER, RATE, CHANNEL, PCM, maxOf(least, BUFFER_BYTES))
            check(record.state == AudioRecord.STATE_INITIALIZED) { "the microphone did not open" }
            val format =
                MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, RATE, 1).apply {
                    setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
                    setInteger(MediaFormat.KEY_BIT_RATE, BITRATE)
                    setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, READ_BYTES)
                }
            val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            codec.start()
            record.startRecording()
            record to codec
        } catch (error: Exception) {
            record?.release()
            failed("no sound: ${error.message ?: error.javaClass.simpleName}")
            null
        }
    }

    @Suppress("TooGenericExceptionCaught") // an encoder that fails costs the sound from then on, never the app
    private fun run(
        record: AudioRecord,
        codec: MediaCodec,
    ) {
        val stamp = AudioTimestamp()
        val info = MediaCodec.BufferInfo()
        var heard = 0L // samples read so far
        try {
            while (running) {
                val index = codec.dequeueInputBuffer(WAIT_US)
                if (index >= 0) {
                    val buffer = codec.getInputBuffer(index) ?: continue
                    buffer.clear()
                    val bytes = record.read(buffer, minOf(buffer.remaining(), READ_BYTES))
                    val read = maxOf(bytes, 0)
                    codec.queueInputBuffer(index, 0, read, heardUs(record, stamp, heard, read), 0)
                    heard += read / 2
                }
                drain(codec, info)
            }
        } catch (error: RuntimeException) {
            failed("no sound from now on: ${error.message ?: error.javaClass.simpleName}")
        } finally {
            record.stop()
            record.release()
            codec.stop()
            codec.release()
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
        private const val NANOS = 1_000_000_000L
    }
}
