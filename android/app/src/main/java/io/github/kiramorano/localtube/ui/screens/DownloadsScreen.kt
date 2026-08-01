package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.FormatItem
import io.github.kiramorano.localtube.data.ServerManager
import io.github.kiramorano.localtube.vm.QueueViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun DownloadsScreen(vm: QueueViewModel = viewModel()) {
    var url by rememberSaveable { mutableStateOf("") }
    var formats by remember { mutableStateOf<List<FormatItem>?>(null) }
    var selectedFormat by remember { mutableStateOf<FormatItem?>(null) }
    var fetching by remember { mutableStateOf(false) }
    var actionMsg by remember { mutableStateOf<String?>(null) }
    var queueError by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        while (true) {
            vm.refresh()
            delay(3000)
        }
    }

    Column(Modifier.fillMaxSize()) {
        Text(
            "Скачивание с YouTube",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(12.dp)
        )
        OutlinedTextField(
            value = url,
            onValueChange = {
                url = it
                formats = null
                selectedFormat = null
                actionMsg = null
            },
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp),
            label = { Text("Ссылка на видео (YouTube)") },
            singleLine = true
        )
        Row(
            Modifier.padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            OutlinedButton(
                enabled = url.isNotBlank() && !fetching,
                onClick = {
                    scope.launch {
                        fetching = true
                        actionMsg = null
                        queueError = null
                        try {
                            formats = ServerManager.api().directFormats(url.trim())
                            selectedFormat = formats?.firstOrNull()
                            if (formats.isNullOrEmpty()) actionMsg = "Форматы не найдены"
                        } catch (e: Exception) {
                            queueError = "Ошибка: ${e.message}"
                        } finally {
                            fetching = false
                        }
                    }
                }
            ) {
                if (fetching) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                } else {
                    Text("Форматы")
                }
            }
            Button(
                enabled = url.isNotBlank(),
                onClick = {
                    scope.launch {
                        try {
                            ServerManager.api().queueAdd(listOf(url.trim()), selectedFormat?.formatId, "YouTube")
                            actionMsg = "Добавлено в очередь"
                            formats = null
                            selectedFormat = null
                            vm.refresh()
                        } catch (e: Exception) {
                            queueError = "Ошибка: ${e.message}"
                        }
                    }
                }
            ) {
                Text("В очередь")
            }
        }
        formats?.let { list ->
            Text("Качество:", style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(horizontal = 12.dp))
            LazyRow(
                contentPadding = PaddingValues(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(list, key = { it.formatId ?: it.resolution }) { f ->
                    FilterChip(
                        selected = selectedFormat?.formatId == f.formatId,
                        onClick = { selectedFormat = f },
                        label = { Text(f.resolution + if (f.sizeMb > 0) " · ${f.sizeMb} MB" else "") }
                    )
                }
            }
            Spacer(Modifier.height(8.dp))
        }
        actionMsg?.let {
            Text(it, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(horizontal = 12.dp))
        }
        queueError?.let {
            Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(horizontal = 12.dp))
        }
        HorizontalDivider(Modifier.padding(vertical = 8.dp))
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("Очередь", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            TextButton(onClick = { scope.launch { vm.refresh() } }) { Text("Обновить") }
            TextButton(onClick = { if (vm.paused) vm.resume() else vm.pause() }) {
                Text(if (vm.paused) "Старт" else "Пауза")
            }
            TextButton(onClick = { vm.clear() }) { Text("Очистить") }
        }
        LazyColumn(Modifier.weight(1f)) {
            items(vm.tasks, key = { it.id }) { t ->
                Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(t.title, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                            Text(statusText(t.status), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        IconButton(onClick = { vm.remove(t.id) }) {
                            Icon(Icons.Filled.Delete, contentDescription = "Удалить")
                        }
                    }
                    if (t.status == "downloading" || t.status == "waiting") {
                        LinearProgressIndicator(
                            progress = { t.progress / 100f },
                            modifier = Modifier.fillMaxWidth().height(4.dp)
                        )
                    }
                }
            }
        }
    }
}

private fun statusText(status: String): String = when (status) {
    "waiting" -> "В очереди"
    "downloading" -> "Скачивание..."
    "completed" -> "Готово"
    "error" -> "Ошибка"
    else -> status
}
