package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.PlaylistEntry
import io.github.kiramorano.localtube.ui.components.AsyncThumb
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.vm.PlaylistViewModel

@Composable
fun PlaylistScreen(
    playlistId: String,
    onBack: () -> Unit,
    onOpenVideo: (String) -> Unit,
    vm: PlaylistViewModel = viewModel()
) {
    LaunchedEffect(playlistId) { vm.load(playlistId) }
    val p = vm.playlist
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 4.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
            }
            Text("Плейлист", style = MaterialTheme.typography.titleMedium)
        }
        if (p == null) {
            EmptyBox("Плейлист не найден")
        } else {
            Column(Modifier.fillMaxWidth().padding(12.dp)) {
                Text(p.title, style = MaterialTheme.typography.titleLarge)
                Text(p.uploader, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("${p.videoCount} видео", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
            }
            if (p.entries.isEmpty()) {
                EmptyBox("В плейлисте нет видео")
            } else {
                LazyColumn(Modifier.weight(1f)) {
                    items(p.entries, key = { it.id }) { e ->
                        PlaylistEntryRow(e, onClick = { onOpenVideo(e.id) })
                    }
                }
            }
        }
    }
}

@Composable
private fun PlaylistEntryRow(e: PlaylistEntry, onClick: () -> Unit) {
    androidx.compose.material3.Card(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)
    ) {
        Row(Modifier.padding(8.dp)) {
            AsyncThumb(e.thumb, Modifier.size(96.dp, 54.dp))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(e.title, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                if (e.videoPath == null) {
                    Text("не скачано", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}
