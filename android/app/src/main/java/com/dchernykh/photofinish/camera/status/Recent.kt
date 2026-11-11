package com.dchernykh.photofinish.camera.status

/**
 * [read]'s value, read again only once [maxAgeNs] has passed since the last read: the phone's status
 * asked by every lens's uplink at each keyframe is read once a second for them all (specs/005).
 */
class Recent<T : Any>(
    private val maxAgeNs: Long,
    private val nanos: () -> Long = System::nanoTime,
    private val read: () -> T,
) {
    private var value: T? = null
    private var at = 0L

    @Synchronized
    fun get(): T {
        val now = nanos()
        val known = value
        if (known != null && now - at < maxAgeNs) return known
        return read().also {
            value = it
            at = now
        }
    }
}
