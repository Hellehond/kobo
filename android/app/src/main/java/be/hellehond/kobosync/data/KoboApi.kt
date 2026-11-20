package be.hellehond.kobosync.data

import java.io.File
import java.io.IOException
import java.time.Instant
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

class ApiException(message: String, val code: Int = 0) : IOException(message)

sealed interface SyncItem {
    data class BookChanged(val book: Book, val removed: Boolean, val position: ReadingPosition?) : SyncItem
    data class PositionChanged(val bookId: String, val position: ReadingPosition) : SyncItem
}

data class SyncPage(val items: List<SyncItem>, val token: String?, val more: Boolean)

/**
 * Talks to kobosync the way a Kobo e-reader does, so the app is one more
 * device sharing the same books and reading positions.
 */
class KoboApi(
    private val client: OkHttpClient,
    baseUrl: String,
    private val deviceId: String,
    private val userAgent: String = "kobosync-android",
) {
    val baseUrl: String = normaliseBaseUrl(baseUrl)

    private fun request(path: String): Request.Builder =
        Request.Builder()
            .url(if (path.startsWith("http")) path else "$baseUrl$path")
            .header("X-Kobo-DeviceId", deviceId)
            // Tells kobosync this is the app: no Kobo store content wanted.
            .header("X-Kobosync-Client", "android")
            .header("User-Agent", userAgent)

    fun sync(token: String?): SyncPage {
        val builder = request("/v1/library/sync")
        if (!token.isNullOrBlank()) builder.header("x-kobo-synctoken", token)
        client.newCall(builder.build()).execute().use { response ->
            if (!response.isSuccessful) throw ApiException(errorText(response.code), response.code)
            val body = response.body.string()
            val array = try {
                json.parseToJsonElement(body).jsonArray
            } catch (e: Exception) {
                throw ApiException("Dit adres geeft geen kobosync-antwoord. Controleer het adres.")
            }
            return SyncPage(
                items = array.mapNotNull(::parseItem),
                token = response.header("x-kobo-synctoken") ?: token,
                more = response.header("x-kobo-sync") == "continue",
            )
        }
    }

    fun getPosition(bookId: String): ReadingPosition? {
        client.newCall(request("/v1/library/$bookId/state").build()).execute().use { response ->
            if (!response.isSuccessful) return null
            val first = (json.parseToJsonElement(response.body.string()) as? JsonArray)?.firstOrNull()
            return (first as? JsonObject)?.let(::parsePosition)
        }
    }

    fun putPosition(bookId: String, position: ReadingPosition) {
        val body = positionPayload(bookId, position).toString().toRequestBody("application/json".toMediaType())
        client.newCall(request("/v1/library/$bookId/state").put(body).build()).execute().use { response ->
            if (!response.isSuccessful) throw ApiException(errorText(response.code), response.code)
        }
    }

    fun download(url: String, dest: File, onProgress: (Long, Long) -> Unit = { _, _ -> }) {
        val tmp = File(dest.parentFile, dest.name + ".part")
        try {
            client.newCall(request(url).build()).execute().use { response ->
                if (!response.isSuccessful) throw ApiException(errorText(response.code), response.code)
                val total = response.body.contentLength()
                response.body.byteStream().use { input ->
                    tmp.outputStream().use { output ->
                        val buffer = ByteArray(64 * 1024)
                        var done = 0L
                        while (true) {
                            val n = input.read(buffer)
                            if (n < 0) break
                            output.write(buffer, 0, n)
                            done += n
                            onProgress(done, total)
                        }
                    }
                }
            }
            if (!tmp.renameTo(dest)) throw ApiException("Kon het boek niet opslaan.")
        } finally {
            tmp.delete()
        }
    }

    fun coverUrl(bookId: String, width: Int = 355, height: Int = 530): String =
        "$baseUrl/$bookId/$width/$height/false/image.jpg"

    companion object {
        val json = Json { ignoreUnknownKeys = true }

        /** Accepts the address as shown by kobosync, with or without a page name behind it. */
        fun normaliseBaseUrl(input: String): String {
            var url = input.trim().removePrefix("api_endpoint=").trim()
            url = url.substringBefore('?').substringBefore('#').trimEnd('/')
            for (page in listOf("/status", "/statistieken", "/upload")) url = url.removeSuffix(page)
            return url.trimEnd('/')
        }

        fun isValidBaseUrl(input: String): Boolean =
            Regex("^https?://[^/\\s]+(/.*)?/kobo/[^/\\s]+$").matches(normaliseBaseUrl(input))

        private fun errorText(code: Int): String = when (code) {
            401 -> "Het token in het adres klopt niet."
            404 -> "Niet gevonden op de server. Controleer het adres."
            in 500..599 -> "De server geeft een fout ($code)."
            else -> "De server antwoordt met code $code."
        }

        private fun JsonObject.obj(key: String): JsonObject? = this[key] as? JsonObject
        private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.takeUnless { it is JsonNull }?.contentOrNull
        private fun JsonObject.num(key: String): Double? = (this[key] as? JsonPrimitive)?.doubleOrNull

        fun parseTime(text: String?): Long =
            try {
                if (text.isNullOrBlank()) 0 else Instant.parse(text).toEpochMilli()
            } catch (e: Exception) {
                0
            }

        fun formatTime(millis: Long): String =
            DateTimeFormatter.ISO_INSTANT.format(Instant.ofEpochMilli(millis).truncatedTo(ChronoUnit.SECONDS))

        fun parseItem(element: JsonElement): SyncItem? {
            val item = element as? JsonObject ?: return null
            val entitlement = item.obj("NewEntitlement") ?: item.obj("ChangedEntitlement")
            if (entitlement != null) {
                val info = entitlement.obj("BookEntitlement") ?: return null
                val id = info.str("Id") ?: return null
                val removed = (info["IsRemoved"] as? JsonPrimitive)?.contentOrNull == "true"
                val meta = entitlement.obj("BookMetadata")
                // Entitlements without our "Imported" origin are Kobo store books, which the app cannot open.
                if (meta == null || info.str("OriginCategory") != "Imported") {
                    return if (removed) SyncItem.BookChanged(Book(id, ""), true, null) else null
                }
                val download = (meta["DownloadUrls"] as? JsonArray)?.firstOrNull() as? JsonObject
                val series = meta.obj("Series")
                val book = Book(
                    id = id,
                    title = meta.str("Title") ?: "Zonder titel",
                    authors = (meta["Contributors"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull } ?: emptyList(),
                    series = series?.str("Name"),
                    seriesNumber = series?.str("Number"),
                    description = meta.str("Description") ?: "",
                    downloadUrl = download?.str("Url"),
                    format = download?.str("Format"),
                    size = (download?.get("Size") as? JsonPrimitive)?.longOrNull ?: 0,
                    modified = info.str("LastModified") ?: "",
                )
                return SyncItem.BookChanged(book, removed, entitlement.obj("ReadingState")?.let(::parsePosition))
            }
            val state = item.obj("ChangedReadingState")?.obj("ReadingState") ?: return null
            val id = state.str("EntitlementId") ?: return null
            return SyncItem.PositionChanged(id, parsePosition(state))
        }

        fun parsePosition(state: JsonObject): ReadingPosition {
            val status = state.obj("StatusInfo")
            val bookmark = state.obj("CurrentBookmark")
            val location = bookmark?.obj("Location")
            return ReadingPosition(
                status = status?.str("Status") ?: Status.UNREAD,
                progressPercent = bookmark?.num("ProgressPercent"),
                chapterPercent = bookmark?.num("ContentSourceProgressPercent"),
                source = location?.str("Source"),
                value = location?.str("Value"),
                type = location?.str("Type"),
                modified = parseTime(state.str("LastModified")),
                timesStarted = (status?.get("TimesStartedReading") as? JsonPrimitive)?.intOrNull ?: 0,
            )
        }

        fun positionPayload(bookId: String, position: ReadingPosition): JsonObject {
            val time = formatTime(position.modified)
            return buildJsonObject {
                put("ReadingStates", buildJsonArray {
                    add(buildJsonObject {
                        put("EntitlementId", bookId)
                        put("LastModified", time)
                        putJsonObject("StatusInfo") {
                            put("LastModified", time)
                            put("Status", position.status)
                            put("TimesStartedReading", maxOf(position.timesStarted, if (position.status == Status.UNREAD) 0 else 1))
                        }
                        putJsonObject("CurrentBookmark") {
                            put("LastModified", time)
                            position.progressPercent?.let { put("ProgressPercent", Math.round(it)) }
                            position.chapterPercent?.let { put("ContentSourceProgressPercent", Math.round(it)) }
                            if (position.hasKoboSpan) {
                                putJsonObject("Location") {
                                    put("Value", position.value)
                                    put("Type", position.type)
                                    put("Source", position.source)
                                }
                            }
                        }
                    })
                })
            }
        }
    }
}
