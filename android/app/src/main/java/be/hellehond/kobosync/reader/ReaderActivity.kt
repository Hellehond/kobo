package be.hellehond.kobosync.reader

import android.content.res.Configuration
import android.graphics.Color as AndroidColor
import android.os.Bundle
import android.view.KeyEvent
import android.view.ViewGroup
import android.widget.FrameLayout
import androidx.appcompat.app.AppCompatActivity
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.ComposeView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.updatePadding
import androidx.fragment.app.FragmentContainerView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import be.hellehond.kobosync.App
import be.hellehond.kobosync.R
import be.hellehond.kobosync.data.ReaderPrefs
import be.hellehond.kobosync.data.ReadingPosition
import be.hellehond.kobosync.data.Status
import be.hellehond.kobosync.ui.KobosyncTheme
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import org.readium.r2.navigator.epub.EpubNavigatorFactory
import org.readium.r2.navigator.epub.EpubNavigatorFragment
import org.readium.r2.navigator.epub.EpubPreferences
import org.readium.r2.navigator.input.InputListener
import org.readium.r2.navigator.input.TapEvent
import org.readium.r2.navigator.preferences.FontFamily
import org.readium.r2.navigator.preferences.Theme
import org.readium.r2.navigator.util.DirectionalNavigationAdapter
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.services.locateProgression
import org.readium.r2.shared.util.getOrElse

data class TocEntry(val title: String, val depth: Int, val link: Link)

class ReaderActivity : AppCompatActivity() {
    private val app get() = application as App
    private lateinit var bookId: String
    private var publication: Publication? = null
    private var navigator: EpubNavigatorFragment? = null
    private var pushJob: Job? = null

    /** The position the reader last showed or was sent to; changes from it are the user's. */
    private var baseline: Pair<String, Double?>? = null
    private var appliedRemote = 0L
    private var settleUntil = 0L
    private var firstResume = true

    // State shown by the overlay.
    var barsVisible by mutableStateOf(false)
    var title by mutableStateOf("")
    var chapter by mutableStateOf("")
    var percent by mutableStateOf<Int?>(null)
    var loading by mutableStateOf(true)
    var error by mutableStateOf<String?>(null)
    var notice by mutableStateOf<String?>(null)
    var toc by mutableStateOf<List<TocEntry>>(emptyList())

    override fun onCreate(savedInstanceState: Bundle?) {
        // No saved state on purpose: the navigator fragment cannot be restored
        // before its book is open, so every start opens the book afresh at the
        // stored position.
        super.onCreate(null)
        bookId = intent.getStringExtra(EXTRA_BOOK_ID) ?: return finish()
        WindowCompat.setDecorFitsSystemWindows(window, false)

        val container = FragmentContainerView(this).apply { id = R.id.reader_container }
        val overlay = ComposeView(this).apply {
            setContent {
                val prefs = app.settings.reader.collectAsStateCompat()
                KobosyncTheme(dark = isDark(prefs)) { ReaderOverlay(this@ReaderActivity, prefs) }
            }
        }
        val root = FrameLayout(this).apply {
            setBackgroundColor(backgroundFor(app.settings.reader.value))
            addView(container, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
            addView(overlay, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        setContentView(root)
        // Keep the text clear of the camera cutout; the bars are hidden while reading.
        ViewCompat.setOnApplyWindowInsetsListener(container) { view, insets ->
            val cutout = insets.getInsets(WindowInsetsCompat.Type.displayCutout())
            view.updatePadding(left = cutout.left, top = cutout.top, right = cutout.right, bottom = cutout.bottom)
            insets
        }
        showSystemBars(false)
        lifecycleScope.launch { open() }
    }

    private suspend fun open() {
        val library = app.library
        val book = library.data.value.books[bookId]
        val file = library.bookFile(bookId)
        if (book == null || !file.exists()) {
            error = "Dit boek staat niet meer op deze telefoon."
            loading = false
            return
        }
        title = book.title
        // Ask the server where the Kobo left off, but do not keep the reader waiting.
        val position = withTimeoutOrNull(2500) { library.refreshPosition(bookId) } ?: library.data.value.positions[bookId]
        appliedRemote = position?.modified ?: 0

        val asset = app.assetRetriever.retrieve(file).getOrElse {
            error = "Het boek kan niet geopend worden."; loading = false; return
        }
        val pub = app.publicationOpener.open(asset, allowUserInteraction = false).getOrElse {
            error = "Het boek kan niet geopend worden."; loading = false; return
        }
        publication = pub
        toc = flatten(pub.tableOfContents.ifEmpty { pub.readingOrder }, 0)

        val factory = EpubNavigatorFactory(pub)
        supportFragmentManager.fragmentFactory = factory.createFragmentFactory(
            initialLocator = locatorFor(pub, position),
            initialPreferences = epubPreferences(app.settings.reader.value),
        )
        if (isFinishing || isDestroyed) return
        // AllowingStateLoss: the reader may have left the app while the book loaded.
        supportFragmentManager.beginTransaction()
            .replace(R.id.reader_container, EpubNavigatorFragment::class.java, Bundle(), NAVIGATOR_TAG)
            .commitNowAllowingStateLoss()
        settleUntil = System.currentTimeMillis() + SETTLE_MS
        val nav = supportFragmentManager.findFragmentByTag(NAVIGATOR_TAG) as EpubNavigatorFragment
        navigator = nav
        nav.addInputListener(DirectionalNavigationAdapter(nav))
        nav.addInputListener(object : InputListener {
            override fun onTap(event: TapEvent): Boolean {
                barsVisible = !barsVisible
                showSystemBars(barsVisible)
                return true
            }
        })
        loading = false
        observe(nav)
    }

    @OptIn(FlowPreview::class)
    private fun observe(nav: EpubNavigatorFragment) {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                nav.currentLocator.debounce(350).collect { onLocator(nav, it) }
            }
        }
        lifecycleScope.launch {
            app.settings.reader.collect {
                nav.submitPreferences(epubPreferences(it))
                window.decorView.findViewById<ViewGroup>(android.R.id.content).getChildAt(0)?.setBackgroundColor(backgroundFor(it))
            }
        }
    }

    private suspend fun onLocator(nav: EpubNavigatorFragment, locator: Locator) {
        val total = locator.locations.totalProgression
        percent = total?.let { Math.round(it * 100).toInt() }
        chapter = locator.title ?: ""
        val key = locator.href.toString() to locator.locations.progression
        if (baseline == null || System.currentTimeMillis() < settleUntil) {
            // Where the book opened or was sent to, including the positions it
            // passes while getting there: not a change by the reader.
            baseline = key
            return
        }
        if (baseline == key) return
        baseline = key

        val span = KoboPosition.parseSpanResult(
            try {
                nav.evaluateJavascript(KoboPosition.FIRST_VISIBLE_SPAN_JS)
            } catch (e: Exception) {
                null
            }
        )
        val old = app.library.data.value.positions[bookId]
        val position = ReadingPosition(
            status = KoboPosition.statusFor(total, old?.status ?: Status.UNREAD),
            progressPercent = total?.times(100),
            chapterPercent = locator.locations.progression?.times(100),
            source = if (span != null) locator.href.toString() else null,
            value = span,
            type = if (span != null) "KoboSpan" else null,
            modified = System.currentTimeMillis(),
            dirty = true,
            timesStarted = maxOf(1, old?.timesStarted ?: 0),
        )
        app.library.setPosition(bookId, position)
        // Send it once the reader has settled on a page for a moment.
        pushJob?.cancel()
        pushJob = app.scope.launch {
            delay(5000)
            app.library.pushPosition(bookId)
        }
    }

    override fun onResume() {
        super.onResume()
        if (firstResume) {
            firstResume = false
            return
        }
        // Back from the background: the Kobo may have been read meanwhile.
        val nav = navigator ?: return
        val pub = publication ?: return
        lifecycleScope.launch {
            val position = withTimeoutOrNull(4000) { app.library.refreshPosition(bookId) } ?: return@launch
            if (!position.dirty && position.modified > appliedRemote) {
                appliedRemote = position.modified
                val locator = locatorFor(pub, position) ?: return@launch
                baseline = null  // the jump is not a change by the reader
                settleUntil = System.currentTimeMillis() + SETTLE_MS
                nav.go(locator)
                notice = "Verder gegaan waar je op een ander toestel was."
            }
        }
    }

    override fun onPause() {
        super.onPause()
        pushJob?.cancel()
        app.scope.launch { app.library.pushPosition(bookId) }
    }

    fun goTo(link: Link) {
        navigator?.go(link)
        barsVisible = false
        showSystemBars(false)
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        val nav = navigator
        if (nav != null && !barsVisible) {
            when (keyCode) {
                KeyEvent.KEYCODE_VOLUME_DOWN -> { nav.goForward(); return true }
                KeyEvent.KEYCODE_VOLUME_UP -> { nav.goBackward(); return true }
            }
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        // Swallow the release too, or the volume panel still appears.
        if (navigator != null && !barsVisible &&
            (keyCode == KeyEvent.KEYCODE_VOLUME_DOWN || keyCode == KeyEvent.KEYCODE_VOLUME_UP)
        ) return true
        return super.onKeyUp(keyCode, event)
    }

    private fun showSystemBars(show: Boolean) {
        val controller = WindowInsetsControllerCompat(window, window.decorView)
        controller.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        if (show) controller.show(WindowInsetsCompat.Type.systemBars()) else controller.hide(WindowInsetsCompat.Type.systemBars())
    }

    private fun isDark(prefs: ReaderPrefs): Boolean = when (prefs.theme) {
        "dark" -> true
        "light", "sepia" -> false
        else -> resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
    }

    private fun backgroundFor(prefs: ReaderPrefs): Int = when {
        isDark(prefs) -> AndroidColor.BLACK
        prefs.theme == "sepia" -> AndroidColor.parseColor("#faf4e8")
        else -> AndroidColor.WHITE
    }

    private fun epubPreferences(prefs: ReaderPrefs): EpubPreferences = EpubPreferences(
        fontSize = prefs.fontSize.toDouble(),
        theme = when {
            isDark(prefs) -> Theme.DARK
            prefs.theme == "sepia" -> Theme.SEPIA
            else -> Theme.LIGHT
        },
        fontFamily = when (prefs.font) {
            "serif" -> FontFamily.SERIF
            "sans" -> FontFamily.SANS_SERIF
            else -> null
        },
        lineHeight = prefs.lineHeight.takeIf { it > 0 }?.toDouble(),
        pageMargins = prefs.margins.toDouble(),
        // A custom line height only applies when the book's own styles step aside.
        publisherStyles = if (prefs.lineHeight > 0) false else null,
        scroll = false,
    )

    private fun flatten(links: List<Link>, depth: Int): List<TocEntry> =
        links.flatMap { link ->
            listOf(TocEntry(link.title ?: link.href.toString().substringAfterLast('/'), depth, link)) + flatten(link.children, depth + 1)
        }

    /** Where to open the book: the exact KoboSpan when known, else the percentage. */
    private suspend fun locatorFor(pub: Publication, position: ReadingPosition?): Locator? {
        if (position == null) return null
        if (position.hasKoboSpan) {
            val index = KoboPosition.matchSource(position.source, pub.readingOrder.map { it.href.toString() })
            val locator = index?.let { pub.locatorFromLink(pub.readingOrder[it]) }
            if (locator != null) {
                return locator.copyWithLocations(
                    fragments = listOf(position.value!!),
                    // Used when the span is not in this file, such as after a rebuild.
                    progression = position.chapterPercent?.div(100)?.coerceIn(0.0, 1.0),
                )
            }
        }
        val percent = position.progressPercent ?: return null
        return pub.locateProgression((percent / 100).coerceIn(0.0, 1.0))
    }

    companion object {
        const val EXTRA_BOOK_ID = "book_id"
        private const val NAVIGATOR_TAG = "navigator"
        private const val SETTLE_MS = 1500L
    }
}
