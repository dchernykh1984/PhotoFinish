package com.dchernykh.photofinish.camera

import android.content.Context
import androidx.core.content.edit
import com.dchernykh.photofinish.camera.capture.Resolution

/** What the app keeps between runs: the address, the size and the frame rate chosen. */
class Settings(
    context: Context,
) {
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var address: String
        get() = prefs.getString(ADDRESS, "").orEmpty()
        set(value) = prefs.edit { putString(ADDRESS, value) }

    var resolution: Resolution?
        get() {
            val width = prefs.getInt(WIDTH, 0)
            val height = prefs.getInt(HEIGHT, 0)
            return if (width > 0 && height > 0) Resolution(width, height) else null
        }
        set(value) =
            prefs.edit {
                putInt(WIDTH, value?.width ?: 0)
                putInt(HEIGHT, value?.height ?: 0)
            }

    var fps: Int?
        get() = prefs.getInt(FPS, 0).takeIf { it > 0 }
        set(value) = prefs.edit { putInt(FPS, value ?: 0) }

    private companion object {
        const val ADDRESS = "address"
        const val WIDTH = "width"
        const val HEIGHT = "height"
        const val FPS = "fps"
    }
}
