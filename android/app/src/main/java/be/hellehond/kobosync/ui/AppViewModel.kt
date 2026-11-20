package be.hellehond.kobosync.ui

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import be.hellehond.kobosync.App
import be.hellehond.kobosync.data.Book
import be.hellehond.kobosync.data.KoboApi
import kotlinx.coroutines.launch

class AppViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as App
    val settings = app.settings
    val library = app.library

    var syncing by mutableStateOf(false)
        private set
    var message by mutableStateOf<String?>(null)
    var connecting by mutableStateOf(false)
        private set

    /** Book id -> download progress between 0 and 1. */
    val downloads = mutableStateMapOf<String, Float>()

    private var lastSync = 0L

    fun coverUrl(book: Book): String? = app.api?.coverUrl(book.id)

    fun connect(url: String) {
        if (!KoboApi.isValidBaseUrl(url)) {
            message = "Dit lijkt geen kobosync-adres. Het ziet eruit als https://jouw.adres/kobo/token."
            return
        }
        connecting = true
        viewModelScope.launch {
            settings.setServerUrl(KoboApi.normaliseBaseUrl(url))
            try {
                library.clear()
                library.sync()
            } catch (e: Exception) {
                settings.setServerUrl("")
                message = "Verbinden lukt niet: ${e.message ?: e.javaClass.simpleName}"
            }
            connecting = false
        }
    }

    fun disconnect() {
        viewModelScope.launch {
            library.clear()
            settings.setServerUrl("")
        }
    }

    fun sync(quiet: Boolean = false) {
        if (syncing || settings.serverUrl.value.isBlank()) return
        val now = System.currentTimeMillis()
        if (quiet && now - lastSync < 30_000) return
        lastSync = now
        syncing = true
        viewModelScope.launch {
            try {
                library.sync()
            } catch (e: Exception) {
                if (!quiet) message = "Synchroniseren lukt niet: ${e.message ?: e.javaClass.simpleName}"
            }
            syncing = false
        }
    }

    /** Make sure the book's file is on the device and current, then hand it to [open]. */
    fun openBook(book: Book, open: (Book) -> Unit) {
        if (book.id in downloads) return
        val needsDownload = !library.isDownloaded(book.id)
        if (!needsDownload && !library.isOutdated(book)) {
            open(book)
            return
        }
        downloads[book.id] = 0f
        viewModelScope.launch {
            try {
                library.download(book) { downloads[book.id] = it }
                downloads.remove(book.id)
                open(book)
            } catch (e: Exception) {
                downloads.remove(book.id)
                if (needsDownload) {
                    message = "Downloaden lukt niet: ${e.message ?: e.javaClass.simpleName}"
                } else {
                    open(book)  // an older copy is still on the device
                }
            }
        }
    }

    fun removeDownload(book: Book) {
        viewModelScope.launch { library.removeDownload(book.id) }
    }
}
