package be.hellehond.kobosync.data

import android.content.Context
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

data class ReaderPrefs(
    val fontSize: Float = 1.0f,
    /** system, light, sepia or dark */
    val theme: String = "system",
    /** empty for the book's own font, serif or sans */
    val font: String = "",
    /** 0 keeps the book's own line height */
    val lineHeight: Float = 0f,
    val margins: Float = 1.0f,
)

class Settings(context: Context) {
    private val prefs = context.getSharedPreferences("kobosync", Context.MODE_PRIVATE)

    private val _serverUrl = MutableStateFlow(prefs.getString("server_url", "") ?: "")
    val serverUrl: StateFlow<String> = _serverUrl

    fun setServerUrl(url: String) {
        prefs.edit().putString("server_url", url).apply()
        _serverUrl.value = url
    }

    /** Identifies this phone to kobosync, like a Kobo's device id. */
    val deviceId: String = prefs.getString("device_id", null) ?: UUID.randomUUID().toString().also {
        prefs.edit().putString("device_id", it).apply()
    }

    private val _reader = MutableStateFlow(
        ReaderPrefs(
            fontSize = prefs.getFloat("font_size", 1.0f),
            theme = prefs.getString("theme", "system") ?: "system",
            font = prefs.getString("font", "") ?: "",
            lineHeight = prefs.getFloat("line_height", 0f),
            margins = prefs.getFloat("margins", 1.0f),
        )
    )
    val reader: StateFlow<ReaderPrefs> = _reader

    fun setReader(value: ReaderPrefs) {
        prefs.edit()
            .putFloat("font_size", value.fontSize)
            .putString("theme", value.theme)
            .putString("font", value.font)
            .putFloat("line_height", value.lineHeight)
            .putFloat("margins", value.margins)
            .apply()
        _reader.value = value
    }
}
