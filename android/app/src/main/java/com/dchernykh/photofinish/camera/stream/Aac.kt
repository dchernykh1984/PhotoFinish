package com.dchernykh.photofinish.camera.stream

/**
 * The phone's sound as RTMP carries it (specs/013-sound): FLV's audio tags of AAC -- its AudioSpecificConfig once,
 * then each piece as the encoder gives it.
 */
object Aac {
    /** AAC, and the rate, size and channels FLV's AAC tags always say: the real ones are in the config. */
    private const val TAG = 0xAF.toByte()
    private const val CONFIG: Byte = 0
    private const val PIECE: Byte = 1

    /** The tag of the stream's AudioSpecificConfig, as the encoder gives it in its csd-0. */
    fun sequenceHeaderTag(config: ByteArray): ByteArray = byteArrayOf(TAG, CONFIG) + config

    /** The tag of one piece of sound. */
    fun pieceTag(piece: ByteArray): ByteArray = byteArrayOf(TAG, PIECE) + piece
}
