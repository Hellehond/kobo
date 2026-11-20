package be.hellehond.kobosync.reader

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import be.hellehond.kobosync.App
import be.hellehond.kobosync.data.ReaderPrefs
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.StateFlow

@Composable
fun StateFlow<ReaderPrefs>.collectAsStateCompat(): ReaderPrefs {
    val state: State<ReaderPrefs> = collectAsStateWithLifecycle()
    return state.value
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReaderOverlay(activity: ReaderActivity, prefs: ReaderPrefs) {
    var showToc by remember { mutableStateOf(false) }
    var showSettings by remember { mutableStateOf(false) }

    Box(Modifier.fillMaxSize()) {
        if (activity.loading) {
            CircularProgressIndicator(Modifier.align(Alignment.Center))
        }
        activity.error?.let { text ->
            Column(Modifier.align(Alignment.Center).padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text(text, textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurface)
                Button(onClick = { activity.finish() }) { Text("Terug") }
            }
        }

        AnimatedVisibility(activity.barsVisible, enter = fadeIn(), exit = fadeOut(), modifier = Modifier.align(Alignment.TopCenter)) {
            Surface(tonalElevation = 3.dp, modifier = Modifier.fillMaxWidth()) {
                Row(Modifier.statusBarsPadding().padding(horizontal = 4.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = { activity.finish() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Terug naar de boeken") }
                    Text(activity.title, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    IconButton(onClick = { showToc = true }) { Icon(Icons.AutoMirrored.Filled.List, "Inhoud") }
                    IconButton(onClick = { showSettings = true }) { Icon(Icons.Default.Settings, "Leesinstellingen") }
                }
            }
        }
        AnimatedVisibility(activity.barsVisible, enter = fadeIn(), exit = fadeOut(), modifier = Modifier.align(Alignment.BottomCenter)) {
            Surface(tonalElevation = 3.dp, modifier = Modifier.fillMaxWidth()) {
                Row(Modifier.navigationBarsPadding().padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(activity.chapter, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    activity.percent?.let { Text("$it%", style = MaterialTheme.typography.bodyMedium) }
                }
            }
        }

        activity.notice?.let { text ->
            LaunchedEffect(text) {
                delay(3500)
                activity.notice = null
            }
            Surface(
                color = MaterialTheme.colorScheme.inverseSurface,
                shape = MaterialTheme.shapes.small,
                modifier = Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(24.dp),
            ) {
                Text(text, color = MaterialTheme.colorScheme.inverseOnSurface, modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp))
            }
        }
    }

    if (showToc) {
        ModalBottomSheet(onDismissRequest = { showToc = false }) {
            Text("Inhoud", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp))
            LazyColumn(Modifier.fillMaxWidth()) {
                items(activity.toc) { entry ->
                    Text(
                        entry.title,
                        style = if (entry.depth == 0) MaterialTheme.typography.bodyLarge else MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.fillMaxWidth()
                            .clickable { showToc = false; activity.goTo(entry.link) }
                            .padding(start = (24 + 16 * entry.depth).dp, end = 24.dp, top = 12.dp, bottom = 12.dp),
                    )
                }
            }
        }
    }

    if (showSettings) {
        val settings = (activity.application as App).settings
        ModalBottomSheet(onDismissRequest = { showSettings = false }) {
            Column(Modifier.padding(horizontal = 24.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Leesinstellingen", style = MaterialTheme.typography.titleLarge)

                Text("Lettergrootte", style = MaterialTheme.typography.labelLarge)
                Slider(value = prefs.fontSize, onValueChange = { settings.setReader(prefs.copy(fontSize = it)) }, valueRange = 0.7f..2.5f, steps = 17)

                Text("Achtergrond", style = MaterialTheme.typography.labelLarge)
                Choices(listOf("system" to "Systeem", "light" to "Licht", "sepia" to "Sepia", "dark" to "Donker"), prefs.theme) {
                    settings.setReader(prefs.copy(theme = it))
                }

                Text("Lettertype", style = MaterialTheme.typography.labelLarge)
                Choices(listOf("" to "Van het boek", "serif" to "Schreef", "sans" to "Schreefloos"), prefs.font) {
                    settings.setReader(prefs.copy(font = it))
                }

                Text("Regelafstand", style = MaterialTheme.typography.labelLarge)
                Choices(listOf("0.0" to "Van het boek", "1.3" to "Krap", "1.6" to "Normaal", "1.9" to "Ruim"), prefs.lineHeight.toString()) {
                    settings.setReader(prefs.copy(lineHeight = it.toFloat()))
                }

                Text("Marges", style = MaterialTheme.typography.labelLarge)
                Slider(value = prefs.margins, onValueChange = { settings.setReader(prefs.copy(margins = it)) }, valueRange = 0.5f..2.5f, steps = 7)
            }
        }
    }
}

@Composable
private fun Choices(options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEach { (value, label) ->
            FilterChip(selected = selected == value, onClick = { onSelect(value) }, label = { Text(label, maxLines = 1) })
        }
    }
}
