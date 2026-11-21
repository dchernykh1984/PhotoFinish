package com.dchernykh.photofinish.camera.status

import android.os.BatteryManager
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

    @Test
    fun `the lenses left out go last, by their codes`() {
        val status = PhoneStatus(battery = 80, left = listOf("front", "ultrawide"))
        assertEquals("battery=80;left=front,ultrawide", status.line())
    }

    @Test
    fun `the free storage and the video held for the camera go after the lenses left out`() {
        val status = PhoneStatus(battery = 80, left = listOf("front"), freeMb = 25_400).holding(750_000, 1_849_500_001)
        assertEquals("battery=80;left=front;free=25400;unsent_ms=750000;unsent_mb=1850", status.line())
        assertEquals("unsent_ms=0;unsent_mb=0", PhoneStatus().holding(0, 0).line())
    }

    @Test
    fun `a phone plugged in but draining is not charging`() {
        assertEquals(true, PhoneStatus.charging(BatteryManager.BATTERY_STATUS_CHARGING))
        assertEquals(true, PhoneStatus.charging(BatteryManager.BATTERY_STATUS_FULL))
        assertEquals(false, PhoneStatus.charging(BatteryManager.BATTERY_STATUS_DISCHARGING))
        assertEquals(false, PhoneStatus.charging(BatteryManager.BATTERY_STATUS_NOT_CHARGING)) // a weak supply
    }
}
