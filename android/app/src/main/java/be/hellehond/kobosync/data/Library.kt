package be.hellehond.kobosync.data

import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString

/** Applies one page of sync results to the stored library. Pure, for testing. */
fun applySync(data: LibraryData, items: List<SyncItem>): LibraryData {
    val books = data.books.toMutableMap()
    val positions = data.positions.toMutableMap()
    val downloaded = data.downloaded.toMutableMap()
    for (item in items) {
        when (item) {
            is SyncItem.BookChanged -> {
                val id = item.book.id
                if (item.removed) {
                    books.remove(id)
                    positions.remove(id)
                    downloaded.remove(id)
                } else {
                    books[id] = item.book
                    item.position?.let { positions[id] = mergePosition(positions[id], it) }
                }
            }
            is SyncItem.PositionChanged ->
                if (item.bookId in books) positions[item.bookId] = mergePosition(positions[item.bookId], item.position)
        }
    }
    return data.copy(books = books, positions = positions, downloaded = downloaded)
}

/**
 * The books and reading positions on this device, kept in one JSON file, and
 * their exchange with the server.
 */
class Library(private val dir: File, private val apiProvider: () -> KoboApi?) {
    private val file = File(dir, "library.json")
    private val booksDir = File(dir, "books").apply { mkdirs() }
    private val mutex = Mutex()
    private val _data = MutableStateFlow(load())
    val data: StateFlow<LibraryData> = _data.asStateFlow()

    private fun load(): LibraryData =
        try {
            if (file.exists()) KoboApi.json.decodeFromString<LibraryData>(file.readText()) else LibraryData()
        } catch (e: Exception) {
            LibraryData()
        }

    private fun save(data: LibraryData) {
        _data.value = data
        val tmp = File(dir, "library.json.tmp")
        tmp.writeText(KoboApi.json.encodeToString(data))
        tmp.renameTo(file)
    }

    fun bookFile(bookId: String): File = File(booksDir, "$bookId.epub")

    fun isDownloaded(bookId: String): Boolean = bookFile(bookId).exists()

    /** The file on this device is older than the version the server now offers. */
    fun isOutdated(book: Book): Boolean =
        isDownloaded(book.id) && _data.value.downloaded[book.id].let { it != null && it != book.modified }

    /** Pull changes, then push positions changed here that the server has not overruled. */
    suspend fun sync() = withContext(Dispatchers.IO) {
        val api = apiProvider() ?: throw ApiException("Nog geen server ingesteld.")
        mutex.withLock {
            var data = _data.value
            var token = data.syncToken
            var pages = 0
            do {
                val page = api.sync(token)
                data = applySync(data, page.items).copy(syncToken = page.token)
                token = page.token
            } while (page.more && ++pages < 200)
            for ((id, position) in data.positions.filterValues { it.dirty }) {
                if (id !in data.books) continue
                try {
                    api.putPosition(id, position)
                    data = data.copy(positions = data.positions + (id to position.copy(dirty = false)))
                } catch (e: Exception) {
                    // Stays dirty; the next sync tries again.
                }
            }
            for (stale in booksDir.listFiles().orEmpty()) {
                if (stale.name.removeSuffix(".epub") !in data.books) stale.delete()
            }
            save(data.copy(lastSync = System.currentTimeMillis()))
        }
    }

    suspend fun download(book: Book, onProgress: (Float) -> Unit = {}) = withContext(Dispatchers.IO) {
        val api = apiProvider() ?: throw ApiException("Nog geen server ingesteld.")
        val url = book.downloadUrl ?: throw ApiException("Dit boek heeft geen download.")
        api.download(url, bookFile(book.id)) { done, total ->
            if (total > 0) onProgress(done.toFloat() / total)
        }
        mutex.withLock { save(_data.value.let { it.copy(downloaded = it.downloaded + (book.id to book.modified)) }) }
    }

    suspend fun removeDownload(bookId: String) = withContext(Dispatchers.IO) {
        bookFile(bookId).delete()
        mutex.withLock { save(_data.value.let { it.copy(downloaded = it.downloaded - bookId) }) }
    }

    /** The freshest position for a book: asks the server, falls back to what is stored. */
    suspend fun refreshPosition(bookId: String): ReadingPosition? = withContext(Dispatchers.IO) {
        val remote = try {
            apiProvider()?.getPosition(bookId)
        } catch (e: Exception) {
            null
        }
        mutex.withLock {
            val local = _data.value.positions[bookId]
            if (remote == null) return@withLock local
            val merged = mergePosition(local, remote)
            if (merged != local) save(_data.value.let { it.copy(positions = it.positions + (bookId to merged)) })
            merged
        }
    }

    /** Record a position read on this device. */
    suspend fun setPosition(bookId: String, position: ReadingPosition) = withContext(Dispatchers.IO) {
        mutex.withLock { save(_data.value.let { it.copy(positions = it.positions + (bookId to position)) }) }
    }

    /** Send a book's position to the server if it has unsent changes. */
    suspend fun pushPosition(bookId: String): Boolean = withContext(Dispatchers.IO) {
        val api = apiProvider() ?: return@withContext false
        val position = _data.value.positions[bookId]?.takeIf { it.dirty } ?: return@withContext true
        try {
            api.putPosition(bookId, position)
            mutex.withLock {
                // Only clear the flag if nothing newer was recorded meanwhile.
                val current = _data.value.positions[bookId]
                if (current == position) save(_data.value.let { it.copy(positions = it.positions + (bookId to position.copy(dirty = false))) })
            }
            true
        } catch (e: Exception) {
            false
        }
    }

    suspend fun clear() = withContext(Dispatchers.IO) {
        mutex.withLock {
            booksDir.listFiles().orEmpty().forEach { it.delete() }
            save(LibraryData())
        }
    }
}
