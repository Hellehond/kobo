package be.hellehond.kobosync.data

import kotlinx.serialization.Serializable

@Serializable
data class Book(
    val id: String,
    val title: String,
    val authors: List<String> = emptyList(),
    val series: String? = null,
    val seriesNumber: String? = null,
    val description: String = "",
    val downloadUrl: String? = null,
    val format: String? = null,
    val size: Long = 0,
    /** Server's LastModified of the book; changes when the file is reprocessed. */
    val modified: String = "",
)

object Status {
    const val UNREAD = "ReadyToRead"
    const val READING = "Reading"
    const val FINISHED = "Finished"
}

/** Where the reader is in a book, in the terms the Kobo API uses. */
@Serializable
data class ReadingPosition(
    val status: String = Status.UNREAD,
    val progressPercent: Double? = null,
    val chapterPercent: Double? = null,
    /** Path of the content document inside the EPUB. */
    val source: String? = null,
    /** KoboSpan id, such as kobo.12.3. */
    val value: String? = null,
    val type: String? = null,
    /** Epoch milliseconds of the last change, by whoever made it. */
    val modified: Long = 0,
    /** Changed on this device and not yet sent to the server. */
    val dirty: Boolean = false,
    val timesStarted: Int = 0,
) {
    val hasKoboSpan: Boolean get() = type == "KoboSpan" && !source.isNullOrBlank() && !value.isNullOrBlank()
}

@Serializable
data class LibraryData(
    val syncToken: String? = null,
    val books: Map<String, Book> = emptyMap(),
    val positions: Map<String, ReadingPosition> = emptyMap(),
    /** Book id -> Book.modified of the file that is on this device. */
    val downloaded: Map<String, String> = emptyMap(),
    val lastSync: Long = 0,
)

/**
 * A position from the server wins unless this device has a newer change that
 * the server has not seen yet.
 */
fun mergePosition(local: ReadingPosition?, remote: ReadingPosition): ReadingPosition =
    if (local != null && local.dirty && local.modified >= remote.modified) local else remote.copy(dirty = false)
