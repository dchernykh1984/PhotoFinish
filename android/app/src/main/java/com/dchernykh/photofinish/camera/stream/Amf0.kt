package com.dchernykh.photofinish.camera.stream

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer

/**
 * AMF0, the encoding of RTMP's commands: the values the app sends and the ones
 * FFmpeg's listener answers with. An [EcmaArray] is written as AMF0's ECMA array
 * (onMetaData), any other map as an object.
 */
object Amf0 {
    private const val NUMBER = 0x00
    private const val BOOLEAN = 0x01
    private const val STRING = 0x02
    private const val OBJECT = 0x03
    private const val NULL = 0x05
    private const val UNDEFINED = 0x06
    private const val ECMA_ARRAY = 0x08
    private const val OBJECT_END = 0x09
    private const val STRICT_ARRAY = 0x0A

    /** A map written as an ECMA array, as onMetaData is. */
    class EcmaArray(
        val entries: Map<String, Any?>,
    )

    fun encode(vararg values: Any?): ByteArray {
        val out = ByteArrayOutputStream()
        values.forEach { write(out, it) }
        return out.toByteArray()
    }

    private fun write(
        out: ByteArrayOutputStream,
        value: Any?,
    ) {
        when (value) {
            null -> out.write(NULL)
            is Boolean -> {
                out.write(BOOLEAN)
                out.write(if (value) 1 else 0)
            }
            is Number -> {
                out.write(NUMBER)
                out.write(ByteBuffer.allocate(8).putDouble(value.toDouble()).array())
            }
            is String -> {
                out.write(STRING)
                writeUtf(out, value)
            }
            is EcmaArray -> {
                out.write(ECMA_ARRAY)
                out.write(ByteBuffer.allocate(4).putInt(value.entries.size).array())
                writeProperties(out, value.entries)
            }
            is Map<*, *> -> {
                out.write(OBJECT)
                writeProperties(out, value.entries.associate { (k, v) -> k as String to v })
            }
            else -> throw IllegalArgumentException("not an AMF0 value: $value")
        }
    }

    private fun writeProperties(
        out: ByteArrayOutputStream,
        properties: Map<String, Any?>,
    ) {
        properties.forEach { (key, value) ->
            writeUtf(out, key)
            write(out, value)
        }
        out.write(0)
        out.write(0)
        out.write(OBJECT_END)
    }

    private fun writeUtf(
        out: ByteArrayOutputStream,
        text: String,
    ) {
        val bytes = text.toByteArray(Charsets.UTF_8)
        require(bytes.size <= 0xFFFF) { "AMF0 string too long" }
        out.write(bytes.size shr 8)
        out.write(bytes.size and 0xFF)
        out.write(bytes)
    }

    /** The values in [data], in order; maps for objects and ECMA arrays. */
    fun decode(data: ByteArray): List<Any?> {
        val buffer = ByteBuffer.wrap(data)
        val values = mutableListOf<Any?>()
        while (buffer.hasRemaining()) {
            values += read(buffer)
        }
        return values
    }

    private fun read(buffer: ByteBuffer): Any? =
        when (val type = buffer.get().toInt() and 0xFF) {
            NUMBER -> buffer.getDouble()
            BOOLEAN -> buffer.get().toInt() != 0
            STRING -> readUtf(buffer)
            OBJECT -> readProperties(buffer)
            NULL, UNDEFINED -> null
            ECMA_ARRAY -> {
                buffer.getInt() // the count, which the end marker makes redundant
                readProperties(buffer)
            }
            STRICT_ARRAY -> {
                // Each entry takes a byte at least: a count beyond what is left is not believed.
                val count = buffer.getInt()
                require(
                    count in 0..buffer.remaining(),
                ) { "AMF0 array of $count entries in ${buffer.remaining()} bytes" }
                List(count) { read(buffer) }
            }
            else -> throw IllegalArgumentException("AMF0 type $type is not read")
        }

    private fun readProperties(buffer: ByteBuffer): Map<String, Any?> {
        val properties = linkedMapOf<String, Any?>()
        while (true) {
            val key = readUtf(buffer)
            if (key.isEmpty() && buffer.get(buffer.position()).toInt() == OBJECT_END) {
                buffer.get()
                return properties
            }
            properties[key] = read(buffer)
        }
    }

    private fun readUtf(buffer: ByteBuffer): String {
        val length = buffer.getShort().toInt() and 0xFFFF
        val bytes = ByteArray(length)
        buffer.get(bytes)
        return String(bytes, Charsets.UTF_8)
    }
}
