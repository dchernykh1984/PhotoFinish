package com.dchernykh.photofinish.camera.stream

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer

/** The reverse of [Sei.escape], as a decoder (and PhotoFinish) reads a unit. */
internal fun unescape(data: ByteArray): ByteArray {
    val out = ByteArrayOutputStream()
    var zeros = 0
    for (byte in data) {
        val value = byte.toInt() and 0xFF
        if (zeros >= 2 && value == 3) {
            zeros = 0
            continue
        }
        out.write(value)
        zeros = if (value == 0) zeros + 1 else 0
    }
    return out.toByteArray()
}

/** The moment an SEI unit from [Sei.frameMoment] carries. */
internal fun momentOf(sei: ByteArray): Long = ByteBuffer.wrap(unescape(sei.copyOfRange(1, sei.size)), 22, 8).getLong()
