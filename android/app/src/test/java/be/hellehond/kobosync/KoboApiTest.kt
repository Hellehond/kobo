package be.hellehond.kobosync

import be.hellehond.kobosync.data.ApiException
import be.hellehond.kobosync.data.KoboApi
import be.hellehond.kobosync.data.LibraryData
import be.hellehond.kobosync.data.ReadingPosition
import be.hellehond.kobosync.data.Status
import be.hellehond.kobosync.data.SyncItem
import be.hellehond.kobosync.data.applySync
import be.hellehond.kobosync.data.mergePosition
import java.io.File
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class KoboApiTest {
    private lateinit var server: MockWebServer
    private lateinit var api: KoboApi

    // A sync response as kobosync produces it (abridged).
    private val syncBody = """[
      {"NewEntitlement": {
        "BookEntitlement": {"Id": "b1", "IsRemoved": false, "LastModified": "2026-11-03T10:00:00Z", "OriginCategory": "Imported"},
        "BookMetadata": {"Title": "Tetris", "Contributors": ["Thomas Heerma van Voss", "Maartje Wortel"],
          "Description": "Novelle", "Series": {"Name": "Reeks", "Number": 2},
          "DownloadUrls": [{"Format": "KEPUB", "Size": 1234, "Url": "http://x/kobo/t/download/1/KEPUB"}]},
        "ReadingState": {"LastModified": "2026-11-03T10:00:00Z",
          "StatusInfo": {"Status": "ReadyToRead", "TimesStartedReading": 0},
          "CurrentBookmark": {"Location": {"Value": "kobo.1.1", "Type": "KoboSpan", "Source": "OEBPS/ch1.xhtml"}}}}},
      {"NewEntitlement": {"BookEntitlement": {"Id": "store1", "IsRemoved": false, "OriginCategory": "Purchased"},
        "BookMetadata": {"Title": "Kobo-aankoop"}}},
      {"ChangedReadingState": {"ReadingState": {"EntitlementId": "b1", "LastModified": "2026-11-03T12:00:00Z",
        "StatusInfo": {"Status": "Reading", "TimesStartedReading": 1},
        "CurrentBookmark": {"ProgressPercent": 37, "ContentSourceProgressPercent": 10,
          "Location": {"Value": "kobo.12.3", "Type": "KoboSpan", "Source": "OEBPS/ch4.xhtml"}}}}},
      {"NewTag": {"Tag": {"Id": "t1", "Name": "Romans", "Items": []}}}
    ]"""

    @Before fun setUp() {
        server = MockWebServer()
        server.start()
        api = KoboApi(OkHttpClient(), server.url("/kobo/tok/").toString(), "dev-1", "test")
    }

    @After fun tearDown() = server.close()

    @Test fun baseUrlIsNormalised() {
        assertEquals("https://k.example/kobo/abc", KoboApi.normaliseBaseUrl(" api_endpoint=https://k.example/kobo/abc/status "))
        assertEquals("https://k.example/kobo/abc", KoboApi.normaliseBaseUrl("https://k.example/kobo/abc/"))
        assertTrue(KoboApi.isValidBaseUrl("http://192.168.1.20:8085/kobo/3f9c0e"))
        assertFalse(KoboApi.isValidBaseUrl("https://k.example/"))
        assertFalse(KoboApi.isValidBaseUrl("k.example/kobo/abc"))
    }

    @Test fun syncParsesBooksAndPositions() {
        server.enqueue(MockResponse.Builder().body(syncBody).addHeader("x-kobo-synctoken", "T2").addHeader("x-kobo-sync", "continue").build())
        val page = api.sync("T1")
        val request = server.takeRequest()
        assertEquals("/kobo/tok/v1/library/sync", request.url.encodedPath)
        assertEquals("T1", request.headers["x-kobo-synctoken"])
        assertEquals("dev-1", request.headers["X-Kobo-DeviceId"])
        assertEquals("android", request.headers["X-Kobosync-Client"])
        assertEquals("T2", page.token)
        assertTrue(page.more)
        assertEquals(2, page.items.size)  // store book and tag are skipped

        val book = page.items[0] as SyncItem.BookChanged
        assertEquals("Tetris", book.book.title)
        assertEquals(listOf("Thomas Heerma van Voss", "Maartje Wortel"), book.book.authors)
        assertEquals("KEPUB", book.book.format)
        assertEquals("2", book.book.seriesNumber)
        assertEquals("kobo.1.1", book.position?.value)

        val data = applySync(LibraryData(), page.items)
        val position = data.positions.getValue("b1")
        assertEquals(Status.READING, position.status)
        assertEquals(37.0, position.progressPercent!!, 0.0)
        assertEquals("OEBPS/ch4.xhtml", position.source)
        assertTrue(position.hasKoboSpan)
        assertFalse(position.dirty)
    }

    @Test fun removedBooksDisappear() {
        val items = listOf(KoboApi.parseItem(KoboApi.json.parseToJsonElement(
            """{"ChangedEntitlement": {"BookEntitlement": {"Id": "b1", "IsRemoved": true, "OriginCategory": "Imported"},
               "BookMetadata": {"Title": "Tetris"}}}"""))!!)
        val before = applySync(LibraryData(), api.run {
            server.enqueue(MockResponse.Builder().body(syncBody).build()); sync(null).items
        })
        assertTrue("b1" in before.books)
        val after = applySync(before.copy(downloaded = mapOf("b1" to "x")), items)
        assertTrue(after.books.isEmpty() && after.positions.isEmpty() && after.downloaded.isEmpty())
    }

    @Test fun localUnsentChangeBeatsOlderServerState() {
        val local = ReadingPosition(progressPercent = 50.0, modified = 2000, dirty = true)
        val older = ReadingPosition(progressPercent = 10.0, modified = 1000)
        val newer = ReadingPosition(progressPercent = 80.0, modified = 3000)
        assertEquals(local, mergePosition(local, older))
        assertEquals(newer, mergePosition(local, newer))
        assertEquals(older, mergePosition(local.copy(dirty = false), older))
        assertEquals(older, mergePosition(null, older))
    }

    @Test fun putPositionSendsKoboPayload() {
        server.enqueue(MockResponse.Builder().body("""{"RequestResult":"Success"}""").build())
        api.putPosition("b1", ReadingPosition(Status.READING, 37.4, 9.6, "OEBPS/ch4.xhtml", "kobo.12.3", "KoboSpan",
            modified = 1793707200000, dirty = true))
        val request = server.takeRequest()
        assertEquals("PUT", request.method)
        assertEquals("/kobo/tok/v1/library/b1/state", request.url.encodedPath)
        val state = KoboApi.json.parseToJsonElement(request.body!!.utf8()).jsonObject["ReadingStates"]!!.jsonArray[0].jsonObject
        val bookmark = state["CurrentBookmark"]!!.jsonObject
        assertEquals("37", bookmark["ProgressPercent"]!!.jsonPrimitive.content)
        assertEquals("10", bookmark["ContentSourceProgressPercent"]!!.jsonPrimitive.content)
        assertEquals("kobo.12.3", bookmark["Location"]!!.jsonObject["Value"]!!.jsonPrimitive.content)
        assertEquals("Reading", state["StatusInfo"]!!.jsonObject["Status"]!!.jsonPrimitive.content)
        assertEquals("1", state["StatusInfo"]!!.jsonObject["TimesStartedReading"]!!.jsonPrimitive.content)
        assertTrue(state["LastModified"]!!.jsonPrimitive.content.endsWith("Z"))
    }

    @Test fun positionWithoutSpanSendsNoLocation() {
        val payload = KoboApi.positionPayload("b1", ReadingPosition(Status.READING, 20.0, modified = 1000))
        val bookmark = payload["ReadingStates"]!!.jsonArray[0].jsonObject["CurrentBookmark"]!!.jsonObject
        assertNull(bookmark["Location"])
    }

    @Test fun errorsAreExplained() {
        server.enqueue(MockResponse.Builder().code(401).build())
        try {
            api.sync(null); throw AssertionError("expected failure")
        } catch (e: ApiException) {
            assertEquals(401, e.code); assertTrue(e.message!!.contains("token"))
        }
        server.enqueue(MockResponse.Builder().body("<html>nginx</html>").build())
        try {
            api.sync(null); throw AssertionError("expected failure")
        } catch (e: ApiException) {
            assertTrue(e.message!!.contains("kobosync"))
        }
    }

    @Test fun downloadWritesFileAtomically() {
        server.enqueue(MockResponse.Builder().body("PK-epub-bytes").build())
        val dest = File.createTempFile("book", ".epub").apply { delete() }
        var last = 0L
        api.download(server.url("/kobo/tok/download/1/KEPUB").toString(), dest) { done, _ -> last = done }
        assertEquals("PK-epub-bytes", dest.readText())
        assertEquals(13L, last)
        assertFalse(File(dest.parentFile, dest.name + ".part").exists())
        dest.delete()
    }

    @Test fun coverUrl() = assertTrue(api.coverUrl("b1").endsWith("/kobo/tok/b1/355/530/false/image.jpg"))
}
