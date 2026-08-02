package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.DownloadTask
import io.github.kiramorano.localtube.data.FormatOption
import io.github.kiramorano.localtube.data.TaskStatus
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.vm.DownloadsViewModel

@Composable
fun DownloadsScreen(vm: DownloadsViewModel = viewModel()) {
    val tasks by vm.tasks.collectAsState()
    var url by rememberSaveable { mutableStateOf("") }
    var selected by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(vm.formats) { if (vm.formats != null && selected.isEmpty()) selected = vm.formats!!.firstOrNull()?.formatId ?: "" }

    Column(Modifier.fillMaxSize()) {
        Column(Modifier.padding(12.dp)) {
            Text("Скачать по ссылке", style = MaterialTheme.typography.titleMedium)
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it },
                    placeholder = { Text("https://...") },
                    singleLine = true,
                    modifier = Modifier.weight(1f)
                )
                SpacerW()
                Button(onClick = { vm.fetch(url) }, enabled = url.isNotBlank() && !vm.fetching) {
                    Text("Форматы")
                }
            }
            if (vm.fetching) {
                Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.padding(end = 8.dp).size(18.dp), strokeWidth = 2.dp)
                    Text("Получение информации...")
                }
            }
            vm.fetchError?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            vm.infoTitle?.let {
                Text("Видео: $it", style = MaterialTheme.typography.bodyMedium)
            }
            val formats = vm.formats
            if (formats != null) {
                LazyColumn(Modifier.fillMaxWidth().height(260.dp)) {
                    item {
                        Row(Modifier.padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                            Button(onClick = { vm.start(url, selected) }, modifier = Modifier.weight(1f)) { Text("Скачать выбранное") }
                            SpacerW()
                            OutlinedButton(onClick = { vm.start(url, "best") }, modifier = Modifier.weight(1f)) { Text("Лучшее") }
                        }
                    }
                    items(formats) { f ->
                        FormatRow(f, selected == f.formatId) { selected = f.formatId }
                    }
                }
            }
            vm.started?.let {
                Text("Добавлено в очередь: $it", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodySmall)
            }
        }

        HorizontalDivider(Modifier.padding(vertical = 4.dp))
        Text("Очередь", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(horizontal = 12.dp))
        if (tasks.isEmpty()) {
            EmptyBox("Очередь пуста")
        } else {
            LazyColumn(Modifier.weight(1f)) {
                items(tasks, key = { it.id }) { t -> TaskRow(t, onCancel = { vm.cancel(t.id) }, onRemove = { vm.remove(t.id) }) }
                item {
                    Row(Modifier.fillMaxWidth().padding(8.dp), horizontalArrangement = Arrangement.End) {
                        TextButton(onClick = { vm.clearFinished() }) { Text("Очистить завершённые") }
                    }
                }
            }
        }
    }
}

@Composable
private fun SpacerW() = androidx.compose.foundation.layout.Spacer(Modifier.padding(start = 8.dp))

@Composable
private fun FormatRow(f: FormatOption, checked: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        RadioButton(selected = checked, onClick = onClick)
        Column(Modifier.weight(1f)) {
            Text(f.label, style = MaterialTheme.typography.bodyMedium)
            val parts = listOf(f.codec, f.ext, if (f.sizeMb > 0) "%.0f MB".format(f.sizeMb) else "")
                .filter { it.isNotBlank() }
            Text(
                parts.joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

@Composable
private fun TaskRow(t: DownloadTask, onCancel: () -> Unit, onRemove: () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(t.title, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            when (t.status) {
                TaskStatus.DOWNLOADING -> TextButton(onClick = onCancel) { Text("Отмена") }
                TaskStatus.WAITING -> TextButton(onClick = onCancel) { Text("Отмена") }
                else -> TextButton(onClick = onRemove) { Text("Удалить") }
            }
        }
        Text(t.statusText, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (t.status == TaskStatus.DOWNLOADING) {
            LinearProgressIndicator(progress = { t.progress }, modifier = Modifier.fillMaxWidth().padding(top = 4.dp))
        }
    }
}
