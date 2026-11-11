package com.dchernykh.photofinish.camera.status

import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.Locale

class PhoneStatusTest {
    @Test
    fun `every reading is a key and a value, a decimal point whatever the phone's language`() {
        val default = Locale.getDefault()
        Locale.setDefault(Locale.GERMANY) // a decimal comma there
        try {
            val status = PhoneStatus(57, true, 34.25, 1, false, -61, 3)
            assertEquals("battery=57;charging=1;temp=34.3;thermal=1;saver=0;wifi=-61;dropped=3", status.line())
        } finally {
            Locale.setDefault(default)
        }
    }

    @Test
    fun `a reading the phone cannot tell is left out`() {
        assertEquals("battery=9;charging=0", PhoneStatus(battery = 9, charging = false).line())
        assertEquals("", PhoneStatus().line())
    }
}
