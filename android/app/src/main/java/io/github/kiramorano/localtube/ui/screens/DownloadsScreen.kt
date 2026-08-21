package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.DownloadTask
import io.github.kiramorano.localtube.data.FormatOption
import io.github.kiramorano.localtube.data.TaskPriority
import io.github.kiramorano.localtube.data.TaskStatus
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.vm.DownloadsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DownloadsScreen(
    initialUrl: String? = null,
    vm: DownloadsViewModel = viewModel()
) {
    val tasks by vm.tasks.collectAsStateWithLifecycle()
    val paused by vm.paused.collectAsStateWithLifecycle()
    var url by rememberSaveable { mutableStateOf(initialUrl.orEmpty()) }
    var selected by remember { mutableStateOf<String?>(null) }
    var filter by rememberSaveable { mutableStateOf("all") }

    LaunchedEffect(initialUrl) {
        if (!initialUrl.isNullOrBlank()) url = initialUrl
    }

    Column(Modifier.fillMaxSize()) {
        CenterAlignedTopAppBar(
            title = { Text("Загрузки") },
            actions = {
                IconButton(onClick = { vm.togglePause() }) {
                    Icon(
                        if (paused) Icons.Filled.PlayArrow else Icons.Filled.Pause,
                        contentDescription = if (paused) "Продолжить" else "Пауза"
                    )
                }
            }
        )

        LazyColumn(Modifier.fillMaxSize()) {
            item {
                Column(Modifier.padding(14.dp)) {
                    Text("Скачать по ссылке", style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold)
                    OutlinedTextField(
                        value = url,
                        onValueChange = { url = it },
                        label = { Text("Ссылка на видео или плейлист") },
                        singleLine = true,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 8.dp)
                    )
                    Row(
                        Modifier.padding(top = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Button(onClick = { vm.fetch(url.trim()) }, enabled = !vm.fetching) {
                            Text("Показать качества")
                        }
                        if (vm.fetching) CircularProgressIndicator(Modifier.padding(4.dp))
                    }
                    Text("Приоритет", style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TaskPriority.entries.forEach { p ->
                            FilterChip(
                                selected = vm.priority == p,
                                onClick = { vm.priority = p },
                                label = { Text(p.label) }
                            )
                        }
                    }
                    vm.phase?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.padding(top = 6.dp))
                    }
                    vm.fetchError?.let {
                        Text(it, color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.padding(top = 6.dp))
                    }
                    vm.infoTitle?.let {
                        Text(it, fontWeight = FontWeight.Medium,
                            modifier = Modifier.padding(top = 8.dp))
                    }
                    vm.started?.let {
                        Text("Добавлено в очередь: $it",
                            color = MaterialTheme.colorScheme.primary,
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.padding(top = 6.dp))
                    }
                }
            }

            val formats = vm.formats
            if (formats != null) {
                item {
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Button(
                            onClick = {
                                selected?.let { vm.start(url.trim(), it) }
                            },
                            enabled = selected != null
                        ) { Text("Скачать выбранное") }
                        OutlinedButton(onClick = { vm.start(url.trim(), "best") }) {
                            Text("Лучшее")
                        }
                    }
                }
                items(formats, key = { it.formatId }) { f ->
                    FormatRow(f, selected == f.formatId) { selected = f.formatId }
                }
                item {
                    Text(
                        "Точкой отмечены потоки без звука: они скачиваются отдельно " +
                            "и склеиваются с лучшим аудио.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 4.dp)
                    )
                }
            }

            item {
                HorizontalDivider(Modifier.padding(vertical = 10.dp))
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("Очередь", style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                    if (tasks.any { it.status == TaskStatus.ERROR }) {
                        TextButton(onClick = { vm.retryAllFailed() }) { Text("Повторить ошибки") }
                    }
                    if (tasks.any { it.isFinished }) {
                        TextButton(onClick = { vm.clearFinished() }) { Text("Очистить") }
                    }
                }
                if (paused) {
                    Text(
                        "Очередь на паузе: текущая загрузка продолжается, новые не начинаются.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 4.dp)
                    )
                }
                if (tasks.isNotEmpty()) {
                    Row(
                        Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        listOf(
                            "all" to "Все",
                            "active" to "Активные",
                            "done" to "Готовые",
                            "error" to "Ошибки"
                        ).forEach { (key, label) ->
                            FilterChip(
                                selected = filter == key,
                                onClick = { filter = key },
                                label = { Text(label) }
                            )
                        }
                    }
                }
            }

            val visible = tasks.filter {
                when (filter) {
                    "active" -> it.status == TaskStatus.WAITING || it.status == TaskStatus.DOWNLOADING
                    "done" -> it.status == TaskStatus.COMPLETED
                    "error" -> it.status == TaskStatus.ERROR || it.status == TaskStatus.CANCELED
                    else -> true
                }
            }
            if (visible.isEmpty()) {
                item { Box(Modifier.heightIn(min = 120.dp)) { EmptyBox("Очередь пуста") } }
            } else {
                items(visible, key = { it.id }) { t ->
                    TaskRow(
                        t = t,
                        onCancel = { vm.cancel(t.id) },
                        onRemove = { vm.remove(t.id) },
                        onRetry = { vm.retry(t.id) },
                        onPriority = { p -> vm.setPriority(t.id, p) }
                    )
                }
            }
        }
    }
}

@Composable
private fun FormatRow(f: FormatOption, selected: Boolean, onSelect: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 14.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        RadioButton(selected = selected, onClick = onSelect)
        Column(Modifier.weight(1f)) {
            Text(f.label, style = MaterialTheme.typography.bodyMedium)
            Text(
                buildString {
                    if (f.codec.isNotBlank()) append(f.codec)
                    if (f.ext.isNotBlank()) append(" · ${f.ext}")
                    if (f.sizeMb > 0) append(" · ${String.format("%.1f", f.sizeMb)} МБ")
                },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun TaskRow(
    t: DownloadTask,
    onCancel: () -> Unit,
    onRemove: () -> Unit,
    onRetry: () -> Unit,
    onPriority: (TaskPriority) -> Unit
) {
    var menu by remember { mutableStateOf(false) }
    Column(Modifier.padding(horizontal = 14.dp, vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                t.title,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f)
            )
            if (t.status == TaskStatus.WAITING) {
                Box {
                    AssistChip(onClick = { menu = true }, label = { Text(t.priority.label) })
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        TaskPriority.entries.forEach { p ->
                            DropdownMenuItem(
                                text = { Text(p.label) },
                                onClick = { menu = false; onPriority(p) }
                            )
                        }
                    }
                }
            }
            when {
                t.status == TaskStatus.DOWNLOADING || t.status == TaskStatus.WAITING ->
                    TextButton(onClick = onCancel) { Text("Отмена") }
                t.status == TaskStatus.ERROR || t.status == TaskStatus.CANCELED ->
                    TextButton(onClick = onRetry) { Text("Повторить") }
                else -> TextButton(onClick = onRemove) { Text("Убрать") }
            }
        }
        Text(
            t.statusText + if (t.attempts > 1) " · попытка ${t.attempts}" else "",
            style = MaterialTheme.typography.labelSmall,
            color = if (t.status == TaskStatus.ERROR) MaterialTheme.colorScheme.error
            else MaterialTheme.colorScheme.onSurfaceVariant
        )
        if (t.status == TaskStatus.DOWNLOADING) {
            // Прогресс приходит в процентах, индикатор ожидает долю.
            LinearProgressIndicator(
                progress = { (t.progress / 100f).coerceIn(0f, 1f) },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 4.dp)
            )
        }
    }
}
