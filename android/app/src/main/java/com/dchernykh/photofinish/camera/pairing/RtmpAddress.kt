package com.dchernykh.photofinish.camera.pairing

/**
 * Where to stream: `rtmp://host:port/app/stream`, as PhotoFinish shows it in text
 * and in its QR code. The clock exchange goes to the same host and port over UDP.
 */
data class RtmpAddress(
    val host: String,
    val port: Int,
    val app: String,
    val stream: String,
) {
    /** The connect command's tcUrl: the address without the stream. */
    val tcUrl: String get() = "rtmp://${hostForUrl()}:$port/$app"

    override fun toString(): String = if (stream.isEmpty()) tcUrl else "$tcUrl/$stream"

    private fun hostForUrl(): String = if (':' in host) "[$host]" else host

    companion object {
        const val DEFAULT_PORT = 1935
        private const val SCHEME = "rtmp://"
        private const val MAX_PORT = 65535

        /**
         * The address in [text], or null when it is not an `rtmp://` address with a path. A path
         * of one part, which PhotoFinish takes too, is the application with no stream name.
         */
        fun parse(text: String): RtmpAddress? {
            val trimmed = text.trim()
            val rest = if (trimmed.startsWith(SCHEME, ignoreCase = true)) trimmed.substring(SCHEME.length) else ""
            val (host, port) = hostAndPort(rest.substringBefore('/', "")) ?: return null
            val path = rest.substringAfter('/', "").trim('/')
            val app = path.substringBefore('/')
            val stream = path.substringAfter('/', "")
            return if (app.isEmpty()) null else RtmpAddress(host, port, app, stream)
        }

        /** `host`, `host:port` or `[v6 host]:port`; the port defaults to RTMP's. */
        private fun hostAndPort(authority: String): Pair<String, Int>? {
            val bracketed = authority.startsWith("[")
            val host =
                if (bracketed) authority.substring(1).substringBefore(']', "") else authority.substringBefore(':')
            val portText =
                if (bracketed) {
                    authority
                        .substringAfter(
                            ']',
                            "",
                        ).removePrefix(":")
                } else {
                    authority.substringAfter(':', "")
                }
            val port = if (portText.isEmpty()) DEFAULT_PORT else portText.toIntOrNull()
            return if (host.isEmpty() || port == null || port !in 1..MAX_PORT) null else host to port
        }
    }
}
