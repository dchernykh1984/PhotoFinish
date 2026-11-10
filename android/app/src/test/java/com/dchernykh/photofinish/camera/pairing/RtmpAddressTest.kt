package com.dchernykh.photofinish.camera.pairing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RtmpAddressTest {
    @Test
    fun `the address PhotoFinish shows reads into its parts`() {
        val address = RtmpAddress.parse(" rtmp://10.89.30.50:1936/live/cam2 ")!!
        assertEquals(RtmpAddress("10.89.30.50", 1936, "live", "cam2"), address)
        assertEquals("rtmp://10.89.30.50:1936/live", address.tcUrl)
        assertEquals("rtmp://10.89.30.50:1936/live/cam2", address.toString())
    }

    @Test
    fun `the port defaults to 1935 and a deeper path stays the stream`() {
        assertEquals(RtmpAddress("photo.local", 1935, "live", "a/b"), RtmpAddress.parse("RTMP://photo.local/live/a/b/"))
    }

    @Test
    fun `an IPv6 host is bracketed`() {
        val address = RtmpAddress.parse("rtmp://[fe80::1]:1940/live/x")!!
        assertEquals("fe80::1", address.host)
        assertEquals(1940, address.port)
        assertEquals("rtmp://[fe80::1]:1940/live/x", address.toString())
        assertEquals(1935, RtmpAddress.parse("rtmp://[fe80::1]/live/x")!!.port)
    }

    @Test
    fun `a path of one part, which PhotoFinish takes too, is the application alone`() {
        val address = RtmpAddress.parse("rtmp://10.0.0.5:1935/cam1/")!!
        assertEquals(RtmpAddress("10.0.0.5", 1935, "cam1", ""), address)
        assertEquals("rtmp://10.0.0.5:1935/cam1", address.toString())
        assertEquals("rtmp://10.0.0.5:1935/cam1", address.tcUrl)
    }

    @Test
    fun `anything else is not an address`() {
        listOf(
            "http://10.0.0.2/live/x",
            "rtmp://10.0.0.2",
            "rtmp://10.0.0.2/",
            "rtmp:///live/x",
            "rtmp://10.0.0.2:0/live/x",
            "rtmp://10.0.0.2:70000/live/x",
            "rtmp://10.0.0.2:port/live/x",
            "rtmp://[fe80::1/live/x",
            "",
        ).forEach { assertNull(it, RtmpAddress.parse(it)) }
    }
}
