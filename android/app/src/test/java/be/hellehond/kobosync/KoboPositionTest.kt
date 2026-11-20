package be.hellehond.kobosync

import be.hellehond.kobosync.data.Status
import be.hellehond.kobosync.reader.KoboPosition
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class KoboPositionTest {
    private val spine = listOf("OEBPS/cover.xhtml", "OEBPS/Text/ch 1.xhtml", "OEBPS/Text/ch2.xhtml", "OEBPS/Other/ch2.xhtml")

    @Test fun exactPath() = assertEquals(0, KoboPosition.matchSource("OEBPS/cover.xhtml", spine))
    @Test fun encodedAndFragment() = assertEquals(1, KoboPosition.matchSource("OEBPS/Text/ch%201.xhtml#kobo.1.1", spine))
    @Test fun containerPrefix() = assertEquals(2, KoboPosition.matchSource("file:///mnt/onboard/boek.kepub.epub!OEBPS/Text/ch2.xhtml", spine))
    @Test fun shorterPath() = assertEquals(2, KoboPosition.matchSource("Text/ch2.xhtml", spine))
    @Test fun uniqueFileName() = assertEquals(0, KoboPosition.matchSource("cover.xhtml", spine))
    @Test fun ambiguousFileName() = assertNull(KoboPosition.matchSource("ch2.xhtml", spine))
    @Test fun unknown() = assertNull(KoboPosition.matchSource("nope.xhtml", spine))
    @Test fun blank() = assertNull(KoboPosition.matchSource(null, spine))

    @Test fun spanResults() {
        assertEquals("kobo.12.3", KoboPosition.parseSpanResult("\"kobo.12.3\""))
        assertEquals("kobo.1.1", KoboPosition.parseSpanResult("kobo.1.1"))
        assertNull(KoboPosition.parseSpanResult("\"\""))
        assertNull(KoboPosition.parseSpanResult("null"))
        assertNull(KoboPosition.parseSpanResult(null))
        assertNull(KoboPosition.parseSpanResult("\"x');alert(1)\""))
    }

    @Test fun status() {
        assertEquals(Status.READING, KoboPosition.statusFor(0.2, Status.UNREAD))
        assertEquals(Status.FINISHED, KoboPosition.statusFor(0.999, Status.READING))
        assertEquals(Status.FINISHED, KoboPosition.statusFor(0.1, Status.FINISHED))
        assertEquals(Status.READING, KoboPosition.statusFor(null, Status.UNREAD))
    }
}
