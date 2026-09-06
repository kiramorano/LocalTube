package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AssistChip
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.DownloadTask
import io.github.kiramorano.localtube.data.FormatOption
import io.github.kiramorano.localtube.data.TaskPriority
import io.github.kiramorano.localtube.data.TaskStatus
import io.github.kiramorano.localtube.ui.components.LtPanel
import io.github.kiramorano.localtube.ui.components.tvFocusBorder
import io.github.kiramorano.localtube.ui.theme.LtRadius
import io.github.kiramorano.localtube.ui.theme.LtSpace
import io.github.kiramorano.localtube.ui.theme.LtTheme
import io.github.kiramorano.localtube.vm.DownloadsViewModel

@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
fun DownloadsScreen(
    initialUrl: String? = null,
    onInitialUrlConsumed: () -> Unit = {},
    vm: DownloadsViewModel = viewModel()
) {
    val colors = LtTheme.colors
    val tasks by vm.tasks.collectAsStateWithLifecycle()
    val paused by vm.paused.collectAsStateWithLifecycle()
    var url by rememberSaveable { mutableStateOf(initialUrl.orEmpty()) }
    var selected by remember { mutableStateOf<String?>(null) }
    var filter by rememberSaveable { mutableStateOf("all") }

    // Ссылку из «Поделиться» сбрасываем только после того, как она попала в
    // поле: иначе она терялась по пути от MainActivity к этому экрану.
    LaunchedEffect(initialUrl) {
        if (!initialUrl.isNullOrBlank()) {
            url = initialUrl
            onInitialUrlConsumed()
        }
    }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(
            horizontal = LtSpace.x4,
            vertical = LtSpace.x3
        ),
        verticalArrangement = Arrangement.spacedBy(LtSpace.x3)
    ) {
        item {
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        "Очередь",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold,
                        color = colors.textPrimary
                    )
                    Text(
                        if (paused) "На паузе" else queueSubtitle(tasks),
                        style = MaterialTheme.typography.bodySmall,
                        color = colors.textSecondary,
                        modifier = Modifier.padding(top = 2.dp)
                    )
                }
                IconButton(
                    onClick = { vm.togglePause() },
                    modifier = Modifier
                        .clip(CircleShape)
                        .background(colors.buttonBg)
                ) {
                    Icon(
                        if (paused) Icons.Filled.PlayArrow else Icons.Filled.Pause,
                        contentDescription = if (paused) "Продолжить" else "Пауза",
                        tint = colors.iconInactive
                    )
                }
            }
        }

        item {
            LtPanel {
                Text(
                    "Скачать по ссылке",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = colors.textPrimary
                )
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it },
                    label = { Text("Ссылка на видео или плейлист") },
                    // Платформы названы прямо: иначе неочевидно, что кроме
                    // YouTube принимается и TikTok.
                    placeholder = { Text("Вставьте ссылку YouTube или TikTok") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                Row(
                    horizontalArrangement = Arrangement.spacedBy(LtSpace.x2),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Button(
                        onClick = { vm.fetch(url.trim()) },
                        enabled = !vm.fetching
                    ) {
                        Text("Показать качества")
                    }
                    if (vm.fetching) {
                        CircularProgressIndicator(
                            Modifier.size(22.dp),
                            strokeWidth = 2.dp
                        )
                    }
                }
                Text(
                    "Приоритет",
                    style = MaterialTheme.typography.labelMedium,
                    color = colors.textSecondary
                )
                FlowRow(horizontalArrangement = Arrangement.spacedBy(LtSpace.x2)) {
                    TaskPriority.entries.forEach { p ->
                        FilterChip(
                            selected = vm.priority == p,
                            onClick = { vm.priority = p },
                            label = { Text(p.label) }
                        )
                    }
                }
                vm.phase?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall, color = colors.textSecondary)
                }
                vm.fetchError?.let {
                    Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }
                vm.infoTitle?.let {
                    Text(it, fontWeight = FontWeight.Medium, color = colors.textPrimary)
                }
                vm.started?.let {
                    Text(
                        "Добавлено в очередь: $it",
                        color = colors.brandRed,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        }

        // Профиль TikTok: качеств у ленты нет, выбирать нечего — только
        // подтвердить загрузку всех роликов.
        vm.profileEntries?.let { entries ->
            item {
                LtPanel {
                    Text(
                        "Профиль TikTok: ${entries.size} роликов",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                        color = colors.textPrimary
                    )
                    Text(
                        "Каждый ролик встанет в очередь отдельной задачей.",
                        style = MaterialTheme.typography.bodySmall,
                        color = colors.textSecondary
                    )
                    Button(onClick = { vm.start(url.trim(), "best") }) {
                        Text("Скачать все")
                    }
                }
            }
        }

        val formats = vm.formats
        if (formats != null) {
            item {
                LtPanel {
                    Text(
                        "Качество",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = colors.textPrimary
                    )
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(LtSpace.x2)
                    ) {
                        // Ссылку берёт модель — ту, для которой получены форматы.
                        Button(
                            onClick = { selected?.let { vm.start(url.trim(), it) } },
                            enabled = selected != null
                        ) { Text("Скачать выбранное") }
                        OutlinedButton(onClick = { vm.start(url.trim(), "best") }) {
                            Text("Лучшее")
                        }
                    }
                    if (vm.fetchedUrl != null && vm.fetchedUrl != url.trim()) {
                        Text(
                            "Ссылка изменилась: будет скачано ранее проверенное видео",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.error
                        )
                    }
                    Text(
                        "Точкой отмечены потоки без звука: они скачиваются отдельно " +
                            "и склеиваются с лучшим аудио.",
                        style = MaterialTheme.typography.labelSmall,
                        color = colors.textSecondary
                    )
                }
            }
            items(formats, key = { it.formatId }) { f ->
                FormatRow(f, selected == f.formatId) { selected = f.formatId }
            }
        }

        item {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(top = LtSpace.x2),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    "Задачи",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = colors.textPrimary,
                    modifier = Modifier.weight(1f)
                )
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
                    color = colors.brandRed,
                    modifier = Modifier.padding(top = 4.dp)
                )
            }
            if (tasks.isNotEmpty()) {
                FlowRow(
                    Modifier.padding(top = LtSpace.x2),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
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
            item {
                // Своя заглушка вместо EmptyBox: тот растягивается на весь
                // экран (fillMaxSize), а здесь он вложен в элемент списка, и
                // высоту приходилось задавать снаружи. Заодно текст различает
                // пустую очередь и пустой результат фильтра — раньше на «Ошибки»
                // без ошибок писалось «Очередь пуста», хотя задачи есть.
                Box(
                    Modifier
                        .fillMaxWidth()
                        .heightIn(min = 120.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        if (tasks.isEmpty()) "Очередь пуста"
                        else "В этом фильтре задач нет",
                        style = MaterialTheme.typography.bodyMedium,
                        color = colors.textSecondary
                    )
                }
            }
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

private fun queueSubtitle(tasks: List<DownloadTask>): String {
    if (tasks.isEmpty()) return "Нет задач"
    val active = tasks.count {
        it.status == TaskStatus.WAITING || it.status == TaskStatus.DOWNLOADING
    }
    val done = tasks.count { it.status == TaskStatus.COMPLETED }
    val errors = tasks.count { it.status == TaskStatus.ERROR }
    return buildString {
        append("Задач: ${tasks.size}")
        if (active > 0) append(" · активных $active")
        if (done > 0) append(" · готовых $done")
        if (errors > 0) append(" · ошибок $errors")
    }
}

@Composable
private fun FormatRow(f: FormatOption, selected: Boolean, onSelect: () -> Unit) {
    val colors = LtTheme.colors
    val interactionSource = remember { MutableInteractionSource() }
    val focused by interactionSource.collectIsFocusedAsState()
    val shape = RoundedCornerShape(LtTheme.sizes.cornerRadius)
    val bg = if (selected) colors.buttonHover else if (colors.cardBg.alpha > 0f) colors.cardBg else colors.modalBg
    Row(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(bg)
            .border(1.dp, if (selected) colors.brandRed else colors.border, shape)
            .tvFocusBorder(focused, colors.brandRed)
            // Вся строка нажимается: пультом попасть в маленький RadioButton
            // практически невозможно.
            .clickable(
                interactionSource = interactionSource,
                indication = LocalIndication.current,
                onClick = onSelect
            )
            .padding(horizontal = LtSpace.x3, vertical = LtSpace.x2),
        verticalAlignment = Alignment.CenterVertically
    ) {
        RadioButton(selected = selected, onClick = onSelect)
        Column(Modifier.weight(1f)) {
            Text(f.label, style = MaterialTheme.typography.bodyMedium, color = colors.textPrimary)
            Text(
                buildString {
                    if (f.codec.isNotBlank()) append(f.codec)
                    if (f.ext.isNotBlank()) append(" · ${f.ext}")
                    if (f.sizeMb > 0) append(" · ${String.format("%.1f", f.sizeMb)} МБ")
                },
                style = MaterialTheme.typography.labelSmall,
                color = colors.textSecondary
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
    val colors = LtTheme.colors
    var menu by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(LtTheme.sizes.cornerRadius)
    val bg = if (colors.cardBg.alpha > 0f) colors.cardBg else colors.modalBg
    Column(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(bg)
            .border(1.dp, colors.border, shape)
            .padding(LtSpace.x4)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                t.title,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium,
                color = colors.textPrimary,
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
            else colors.textSecondary,
            modifier = Modifier.padding(top = 4.dp)
        )
        if (t.status == TaskStatus.DOWNLOADING) {
            // Прогресс приходит в процентах, индикатор ожидает долю.
            LinearProgressIndicator(
                progress = { (t.progress / 100f).coerceIn(0f, 1f) },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 8.dp)
                    .height(6.dp)
                    .clip(RoundedCornerShape(LtRadius.pill)),
                color = colors.brandRed,
                trackColor = colors.buttonBg
            )
        }
    }
}
