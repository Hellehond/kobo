package be.hellehond.kobosync

import android.app.Application
import be.hellehond.kobosync.data.KoboApi
import be.hellehond.kobosync.data.Library
import be.hellehond.kobosync.data.Settings
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import okhttp3.OkHttpClient
import org.readium.r2.shared.util.asset.AssetRetriever
import org.readium.r2.shared.util.http.DefaultHttpClient
import org.readium.r2.streamer.PublicationOpener
import org.readium.r2.streamer.parser.DefaultPublicationParser

class App : Application() {
    lateinit var settings: Settings
        private set
    lateinit var library: Library
        private set

    /** Outlives screens, so a position is still sent after the reader closes. */
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build()
    }

    private var cachedApi: KoboApi? = null

    val api: KoboApi?
        get() {
            val url = settings.serverUrl.value
            if (url.isBlank()) return null
            cachedApi?.takeIf { it.baseUrl == KoboApi.normaliseBaseUrl(url) }?.let { return it }
            return KoboApi(http, url, settings.deviceId, "kobosync-android/${BuildConfig.VERSION_NAME}").also { cachedApi = it }
        }

    private val readiumHttp by lazy { DefaultHttpClient() }
    val assetRetriever by lazy { AssetRetriever(contentResolver, readiumHttp) }
    val publicationOpener by lazy {
        PublicationOpener(DefaultPublicationParser(this, readiumHttp, assetRetriever, pdfFactory = null))
    }

    override fun onCreate() {
        super.onCreate()
        settings = Settings(this)
        library = Library(filesDir) { api }
    }
}
