package be.hellehond.kobosync.reader

import java.net.URLDecoder

/**
 * Translation between Kobo's reading position (a content document plus the id
 * of a KoboSpan in it) and what the reader view needs.
 */
object KoboPosition {

    /**
     * JavaScript that returns the id of the first KoboSpan visible on the
     * current page, or an empty string. Works for paginated (columns) and
     * scrolled layouts: a span counts when one of its boxes starts inside
     * the viewport.
     */
    const val FIRST_VISIBLE_SPAN_JS = """(function(){
  var spans=document.querySelectorAll('span.koboSpan');
  var w=window.innerWidth,h=window.innerHeight;
  for(var i=0;i<spans.length;i++){
    var rects=spans[i].getClientRects();
    for(var j=0;j<rects.length;j++){
      var r=rects[j];
      if(r.width>0&&r.height>0&&r.left>=0&&r.left<w&&r.bottom>0&&r.top<h){return spans[i].id;}
    }
  }
  return '';
})();"""

    private val SPAN_ID = Regex("^kobo\\.\\d+\\.\\d+$")

    /** The WebView returns JavaScript results JSON-encoded: "kobo.1.2", "" or null. */
    fun parseSpanResult(raw: String?): String? {
        val text = raw?.trim()?.removeSurrounding("\"") ?: return null
        return text.takeIf { SPAN_ID.matches(it) }
    }

    private fun clean(href: String): String {
        val path = href.substringBefore('#').substringBefore('?').trimStart('/')
        return try {
            URLDecoder.decode(path.replace("+", "%2B"), "UTF-8")
        } catch (e: Exception) {
            path
        }
    }

    /**
     * Find the reading-order document a Kobo "Source" refers to. Kobo devices
     * and kobosync name it by its path in the EPUB, but be forgiving about
     * prefixes, encoding and fragments.
     *
     * @return index into [hrefs], or null when nothing matches.
     */
    fun matchSource(source: String?, hrefs: List<String>): Int? {
        if (source.isNullOrBlank()) return null
        val wanted = clean(source.substringAfterLast('!'))
        val cleaned = hrefs.map(::clean)
        cleaned.indexOf(wanted).takeIf { it >= 0 }?.let { return it }
        val suffix = cleaned.withIndex().filter { (_, h) -> wanted.endsWith("/$h") || h.endsWith("/$wanted") }
        if (suffix.size == 1) return suffix[0].index
        val name = wanted.substringAfterLast('/')
        val sameName = cleaned.withIndex().filter { (_, h) -> h.substringAfterLast('/') == name }
        return sameName.singleOrNull()?.index
    }

    /** A book counts as finished when the reader is on its very last pages. */
    fun statusFor(totalProgression: Double?, current: String): String = when {
        totalProgression != null && totalProgression >= 0.995 -> be.hellehond.kobosync.data.Status.FINISHED
        current == be.hellehond.kobosync.data.Status.FINISHED -> current
        else -> be.hellehond.kobosync.data.Status.READING
    }
}
