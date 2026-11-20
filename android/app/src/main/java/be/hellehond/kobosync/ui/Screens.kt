package be.hellehond.kobosync.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import be.hellehond.kobosync.data.Book
import be.hellehond.kobosync.data.ReadingPosition
import be.hellehond.kobosync.data.Status
import coil3.compose.AsyncImage

@Composable
fun AppRoot(vm: AppViewModel, openReader: (Book) -> Unit) {
    val serverUrl by vm.settings.serverUrl.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(vm.message) {
        vm.message?.let {
            snackbar.showSnackbar(it)
            vm.message = null
        }
    }
    if (serverUrl.isBlank() || vm.connecting) {
        SetupScreen(vm, snackbar)
    } else {
        LibraryScreen(vm, snackbar, openReader)
    }
}

@Composable
fun SetupScreen(vm: AppViewModel, snackbar: SnackbarHostState) {
    var url by rememberSaveable { mutableStateOf("") }
    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { padding ->
        Column(
            Modifier.padding(padding).fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        ) {
            Text("kobosync", style = MaterialTheme.typography.headlineLarge)
            Text(
                "Lees je eigen boeken op je telefoon en ga verder waar je op je Kobo gebleven was.",
                style = MaterialTheme.typography.bodyLarge,
            )
            OutlinedTextField(
                value = url,
                onValueChange = { url = it },
                label = { Text("Adres van je kobosync-server") },
                placeholder = { Text("https://kobo.jouwdomein.nl/kobo/token") },
                singleLine = true,
                enabled = !vm.connecting,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go),
                keyboardActions = KeyboardActions(onGo = { vm.connect(url) }),
                modifier = Modifier.fillMaxWidth(),
            )
            Text(
                "Dit is hetzelfde adres als de regel api_endpoint op je Kobo's. Het staat ook bovenaan de logs van kobosync.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Button(onClick = { vm.connect(url) }, enabled = !vm.connecting && url.isNotBlank(), modifier = Modifier.fillMaxWidth()) {
                if (vm.connecting) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                } else {
                    Text("Verbinden")
                }
            }
        }
    }
}

private enum class Filter(val label: String) { ALL("Alle"), READING("Bezig"), UNREAD("Ongelezen"), FINISHED("Uitgelezen") }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryScreen(vm: AppViewModel, snackbar: SnackbarHostState, openReader: (Book) -> Unit) {
    val data by vm.library.data.collectAsStateWithLifecycle()
    var filter by rememberSaveable { mutableStateOf(Filter.ALL) }
    var menu by remember { mutableStateOf(false) }
    var confirmDisconnect by remember { mutableStateOf(false) }

    val books = remember(data, filter) {
        data.books.values
            .filter { book ->
                val status = data.positions[book.id]?.status ?: Status.UNREAD
                when (filter) {
                    Filter.ALL -> true
                    Filter.READING -> status == Status.READING
                    Filter.UNREAD -> status == Status.UNREAD
                    Filter.FINISHED -> status == Status.FINISHED
                }
            }
            // Books in progress first, most recently read on top; then by title.
            .sortedWith(
                compareByDescending<Book> { data.positions[it.id]?.status == Status.READING }
                    .thenByDescending { if (data.positions[it.id]?.status == Status.READING) data.positions[it.id]?.modified ?: 0 else 0 }
                    .thenBy { it.title.lowercase() }
            )
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("Boeken") },
                actions = {
                    if (vm.syncing) {
                        CircularProgressIndicator(Modifier.padding(12.dp).size(24.dp), strokeWidth = 2.dp)
                    } else {
                        IconButton(onClick = { vm.sync() }) { Icon(Icons.Default.Refresh, "Synchroniseren") }
                    }
                    IconButton(onClick = { menu = true }) { Icon(Icons.Default.MoreVert, "Meer") }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text("Andere server") }, onClick = { menu = false; confirmDisconnect = true })
                    }
                },
            )
        },
    ) { padding ->
        PullToRefreshBox(isRefreshing = vm.syncing, onRefresh = { vm.sync() }, modifier = Modifier.padding(padding).fillMaxSize()) {
            Column(Modifier.fillMaxSize()) {
                Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Filter.entries.forEach { f ->
                        FilterChip(selected = filter == f, onClick = { filter = f }, label = { Text(f.label) })
                    }
                }
                if (books.isEmpty()) {
                    Box(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(32.dp), contentAlignment = Alignment.Center) {
                        Text(
                            if (data.books.isEmpty()) "Nog geen boeken. Zet boeken in de bibliotheekmap van kobosync en synchroniseer."
                            else "Geen boeken in deze lijst.",
                            textAlign = TextAlign.Center,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                } else {
                    LazyVerticalGrid(
                        columns = GridCells.Adaptive(108.dp),
                        contentPadding = PaddingValues(12.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp),
                        modifier = Modifier.fillMaxSize(),
                    ) {
                        items(books, key = { it.id }) { book ->
                            BookCard(
                                book = book,
                                position = data.positions[book.id],
                                coverUrl = vm.coverUrl(book),
                                downloaded = book.id in data.downloaded,
                                progress = vm.downloads[book.id],
                                onOpen = { vm.openBook(book, openReader) },
                                onRemoveDownload = { vm.removeDownload(book) },
                            )
                        }
                    }
                }
            }
        }
    }

    if (confirmDisconnect) {
        AlertDialog(
            onDismissRequest = { confirmDisconnect = false },
            title = { Text("Andere server instellen?") },
            text = { Text("De gedownloade boeken worden van deze telefoon gehaald. Je leesposities blijven op de server staan.") },
            confirmButton = { TextButton(onClick = { confirmDisconnect = false; vm.disconnect() }) { Text("Doorgaan") } },
            dismissButton = { TextButton(onClick = { confirmDisconnect = false }) { Text("Annuleren") } },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun BookCard(
    book: Book,
    position: ReadingPosition?,
    coverUrl: String?,
    downloaded: Boolean,
    progress: Float?,
    onOpen: () -> Unit,
    onRemoveDownload: () -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    Column(Modifier.combinedClickable(onClick = onOpen, onLongClick = { if (downloaded) menu = true })) {
        Box(
            Modifier.fillMaxWidth().aspectRatio(2f / 3f).clip(RoundedCornerShape(6.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                book.title,
                style = MaterialTheme.typography.labelMedium,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(8.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (coverUrl != null) {
                AsyncImage(model = coverUrl, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            }
            if (progress != null) {
                Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.5f)), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(progress = { progress })
                }
            } else if (!downloaded) {
                Surface(
                    color = MaterialTheme.colorScheme.surface.copy(alpha = 0.85f),
                    shape = RoundedCornerShape(bottomStart = 6.dp),
                    modifier = Modifier.align(Alignment.TopEnd),
                ) {
                    Text("↓", Modifier.padding(horizontal = 7.dp, vertical = 2.dp), style = MaterialTheme.typography.labelLarge)
                }
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(text = { Text("Download verwijderen") }, onClick = { menu = false; onRemoveDownload() })
            }
        }
        val percent = position?.progressPercent
        if (position?.status == Status.READING && percent != null) {
            LinearProgressIndicator(
                progress = { (percent / 100).toFloat().coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth().padding(top = 6.dp).height(3.dp),
            )
        } else {
            Spacer(Modifier.height(9.dp))
        }
        Text(book.title, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 4.dp))
        Text(
            if (position?.status == Status.FINISHED) "Uitgelezen" else book.authors.joinToString(", "),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
