package be.hellehond.kobosync

import be.hellehond.kobosync.data.KoboApi
import be.hellehond.kobosync.data.LibraryData
import be.hellehond.kobosync.data.Status
import be.hellehond.kobosync.data.applySync
import be.hellehond.kobosync.reader.KoboPosition
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Responses captured from the real kobosync server (see the README of the
 * android folder for how to refresh them), so the app and server stay in step.
 */
class ServerSampleTest {
    private val sample = KoboApi.json.parseToJsonElement(
        javaClass.classLoader!!.getResource("server-sample.json")!!.readText()
    ).jsonObject
    private val arrId = sample["arrId"]!!.jsonPrimitive.content

    private fun items(key: String) = sample[key]!!.jsonArray.mapNotNull(KoboApi::parseItem)

    @Test fun firstSyncGivesBothBooksWithTheirStartingPoint() {
        val data = applySync(LibraryData(), items("first"))
        assertEquals(setOf("Arr", "Tetris"), data.books.values.map { it.title }.toSet())
        val arr = data.books.getValue(arrId)
        assertEquals(listOf("Jørn Lier Horst", "Thomas Enger"), arr.authors)
        assertEquals("KEPUB", arr.format)
        assertTrue(arr.downloadUrl!!.startsWith("https://kobo.example.org/kobo/tok/download/"))
        // An unopened book opens at the story, not at the cover.
        val start = data.positions.getValue(arrId)
        assertEquals(Status.UNREAD, start.status)
        assertTrue(start.hasKoboSpan)
        assertEquals("OEBPS/E19957-Bonnier-ARR-1.xhtml", start.source)
    }

    @Test fun readingOnAKoboArrivesInTheApp() {
        val first = applySync(LibraryData(), items("first"))
        val second = applySync(first, items("second"))
        val position = second.positions.getValue(arrId)
        assertEquals(Status.READING, position.status)
        assertEquals("kobo.7.1", position.value)
        assertEquals(9.0, position.progressPercent!!, 0.0)
        assertTrue(position.modified > 0)
        val spine = listOf("OEBPS/cover.xhtml", "OEBPS/E19957-Bonnier-ARR-1.xhtml", "OEBPS/E19957-Bonnier-ARR-2.xhtml")
        assertEquals(2, KoboPosition.matchSource(position.source, spine))
    }

    @Test fun stateEndpointMatchesSync() {
        val state = KoboApi.parsePosition(sample["state"]!!.jsonArray[0].jsonObject)
        assertEquals("kobo.7.1", state.value)
        assertEquals(40.0, state.chapterPercent!!, 0.0)
    }
}
