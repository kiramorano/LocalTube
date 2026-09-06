package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CloudDownload
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.Engine
import io.github.kiramorano.localtube.data.SyncState
import io.github.kiramorano.localtube.ui.components.AsyncThumb
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.ui.components.VideoGrid
import io.github.kiramorano.localtube.ui.theme.LtRadius
import io.github.kiramorano.localtube.ui.theme.LtTap
import io.github.kiramorano.localtube.vm.ChannelViewModel

/**
 * Страница канала: аватар, число видео, вкладки «Видео» и «Shorts», кнопка
 * скрытия. Аналог /channel/<author> в веб-версии.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChannelScreen(
    author: String,
    onBack: () -> Unit,
    onOpenVideo: (String) -> Unit,
    onOpenShorts: (String) -> Unit,
    vm: ChannelViewModel = viewModel()
) {
    val userData by vm.userData.collectAsStateWithLifecycle()
    val syncStates by vm.syncStates.collectAsStateWithLifecycle()
    var tab by remember { mutableIntStateOf(0) }
    var aboutOpen by remember { mutableStateOf(false) }
    var syncOpen by remember { mutableStateOf(false) }
    var mergeFormat by remember { mutableStateOf(Engine.DEFAULT_MERGE_FORMAT) }

    LaunchedEffect(author) { vm.load(author) }

    val hidden = userData.hiddenChannels.contains(author)
    val favorites = userData.favorites.toSet()
    val sync = syncStates[author] ?: SyncState(author)
    val channelUrl = remember(author, vm.meta) { vm.channelUrl() }

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(author, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
                }
            },
            actions = {
                IconButton(onClick = { vm.refreshAssets() }, enabled = channelUrl != null) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Обновить оформление")
                }
            }
        )

        // Баннер канала: в вебе это .channel-banner высотой 6:1.
        vm.banner?.let { path ->
            AsyncThumb(
                path = path,
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(6f / 1f)
            )
        }

        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                Modifier
                    .size(64.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.Center
            ) {
                if (vm.avatar != null) {
                    AsyncThumb(vm.avatar, Modifier.fillMaxSize())
                } else {
                    Text(author.take(1).uppercase(), style = MaterialTheme.typography.titleLarge)
                }
            }
            Column(
                Modifier
                    .weight(1f)
                    .padding(start = 12.dp)
            ) {
                Text(author, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(
                    buildString {
                        val subs = vm.meta?.subscribers ?: 0
                        if (subs > 0) append("${formatSubscribers(subs)} · ")
                        append("${vm.videos.size} видео · ${vm.shorts.size} Shorts")
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                if (!vm.meta?.description.isNullOrBlank()) {
                    // На палец приходилось около 20dp: у кликабельного текста
                    // не было ни своей высоты, ни отступов по вертикали.
                    Text(
                        "О канале",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier
                            .clip(RoundedCornerShape(LtRadius.sm))
                            .clickable { aboutOpen = true }
                            .defaultMinSize(minHeight = LtTap.min)
                            .wrapContentHeight(Alignment.CenterVertically)
                    )
                }
            }
        }

        // Синхронизация: аналог кнопки «Скачать остальные видео» на ПК.
        OutlinedButton(
            onClick = {
                syncOpen = true
                if (sync.missing.isEmpty() && !sync.running) vm.scan()
            },
            enabled = channelUrl != null && !sync.running,
            modifier = Modifier
                .padding(horizontal = 16.dp)
                .fillMaxWidth()
        ) {
            Icon(Icons.Filled.CloudDownload, contentDescription = null)
            Text(
                if (sync.running) "  Поиск новых видео..." else "  Скачать остальные видео",
                modifier = Modifier.padding(start = 4.dp)
            )
        }
        if (channelUrl == null) {
            Text(
                "Адрес канала неизвестен: в info.json скачанных видео нет channel_url.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
            )
        }

        // Раньше здесь был Button с outlinedButtonColors: заливка получалась
        // прозрачной, а рамки у Button нет, и кнопка «Скрыть канал» была почти
        // не видна. Теперь для каждого состояния свой тип кнопки.
        val buttonModifier = Modifier
            .padding(horizontal = 16.dp)
            .fillMaxWidth()
        if (hidden) {
            Button(onClick = { vm.toggleHidden() }, modifier = buttonModifier) {
                Icon(Icons.Filled.Visibility, contentDescription = null)
                Text("  Показать канал", modifier = Modifier.padding(start = 4.dp))
            }
        } else {
            OutlinedButton(onClick = { vm.toggleHidden() }, modifier = buttonModifier) {
                Icon(Icons.Filled.VisibilityOff, contentDescription = null)
                Text("  Скрыть канал", modifier = Modifier.padding(start = 4.dp))
            }
        }
        if (hidden) {
            Text(
                "Канал скрыт: его видео не показываются в подборках и поиске.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp)
            )
        }

        if (vm.shorts.isNotEmpty()) {
            TabRow(selectedTabIndex = tab) {
                Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("Видео") })
                Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("Shorts") })
            }
        }

        when {
            vm.loading -> LoadingBox()
            // onToggleFavorite обязателен: без него VideoCard вообще не рисует
            // звёздочку, и на странице канала избранное было недоступно.
            tab == 1 -> VideoGrid(
                items = vm.shorts,
                onOpen = onOpenShorts,
                short = true,
                favorites = favorites,
                onToggleFavorite = vm::toggleFavorite,
                emptyText = "Shorts у канала нет"
            )
            else -> VideoGrid(
                items = vm.videos,
                onOpen = onOpenVideo,
                favorites = favorites,
                onToggleFavorite = vm::toggleFavorite,
                emptyText = "Видео у канала нет"
            )
        }
    }

    if (aboutOpen) {
        AlertDialog(
            onDismissRequest = { aboutOpen = false },
            title = { Text("О канале") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    val subs = vm.meta?.subscribers ?: 0
                    if (subs > 0) {
                        Text(
                            formatSubscribers(subs),
                            style = MaterialTheme.typography.labelLarge,
                            modifier = Modifier.padding(bottom = 8.dp)
                        )
                    }
                    Text(vm.meta?.description.orEmpty(), style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = { TextButton(onClick = { aboutOpen = false }) { Text("Закрыть") } }
        )
    }

    if (syncOpen) {
        SyncDialog(
            state = sync,
            mergeFormat = mergeFormat,
            onMergeFormat = { mergeFormat = it },
            onDismiss = { syncOpen = false },
            onRescan = { vm.scan() },
            onToggle = vm::toggleMissing,
            onSelectAll = vm::setAllMissing,
            onQueue = {
                vm.queueSelected(mergeFormat = mergeFormat)
                syncOpen = false
            }
        )
    }
}

/**
 * Диалог синхронизации: список отсутствующих видео с галочками.
 * Повторяет модальное окно веб-версии, где можно выбрать, что именно качать.
 */
@Composable
private fun SyncDialog(
    state: SyncState,
    mergeFormat: String,
    onMergeFormat: (String) -> Unit,
    onDismiss: () -> Unit,
    onRescan: () -> Unit,
    onToggle: (String) -> Unit,
    onSelectAll: (Boolean) -> Unit,
    onQueue: () -> Unit
) {
    val selected = state.missing.count { it.selected }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Новые видео канала") },
        text = {
            Column {
                state.error?.let {
                    Text(
                        it,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(bottom = 6.dp)
                    )
                }
                if (state.message.isNotBlank()) {
                    Text(
                        state.message,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                if (state.skipped.isNotEmpty()) {
                    // Канал без Shorts или трансляций — обычное дело, поэтому
                    // это подсказка, а не ошибка.
                    Text(
                        "Не удалось прочитать разделы: ${state.skipped.joinToString(", ")}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp)
                    )
                }
                if (state.running) {
                    LinearProgressIndicator(Modifier.fillMaxWidth().padding(vertical = 8.dp))
                }
                if (state.missing.isNotEmpty()) {
                    Row(
                        Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        TextButton(onClick = { onSelectAll(true) }) { Text("Все") }
                        TextButton(onClick = { onSelectAll(false) }) { Text("Снять") }
                        Text(
                            "Выбрано: $selected",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    // Контейнер, как в диалоге «Скачать остальные видео» в вебе.
                    Text(
                        "Формат файла",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Engine.MERGE_FORMATS.forEach { option ->
                            FilterChip(
                                selected = mergeFormat == option,
                                onClick = { onMergeFormat(option) },
                                label = { Text(option.uppercase()) }
                            )
                        }
                    }
                    LazyColumn(Modifier.heightIn(max = 300.dp)) {
                        items(state.missing, key = { it.entry.id }) { item ->
                            Row(
                                Modifier
                                    .fillMaxWidth()
                                    .clickable { onToggle(item.entry.id) },
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Checkbox(
                                    checked = item.selected,
                                    onCheckedChange = { onToggle(item.entry.id) }
                                )
                                Text(
                                    item.entry.title,
                                    style = MaterialTheme.typography.bodySmall,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onQueue, enabled = selected > 0) {
                Text("В очередь ($selected)")
            }
        },
        dismissButton = {
            Row {
                TextButton(onClick = onRescan, enabled = !state.running) { Text("Обновить") }
                TextButton(onClick = onDismiss) { Text("Закрыть") }
            }
        }
    )
}

/**
 * Подписчики в коротком виде: 1,2 млн вместо 1234567.
 * Формат тот же, что format_subscribers на сервере.
 */
internal fun formatSubscribers(count: Long): String = when {
    count >= 1_000_000 -> {
        val millions = count / 1_000_000.0
        // Один знак после запятой у значений меньше десяти миллионов: «1,2 млн»
        // читается, а «1 млн» теряет заметную разницу.
        if (millions < 10) "${String.format("%.1f", millions).replace('.', ',')} млн подписчиков"
        else "${millions.toInt()} млн подписчиков"
    }
    count >= 1_000 -> {
        val thousands = count / 1_000.0
        if (thousands < 10) "${String.format("%.1f", thousands).replace('.', ',')} тыс. подписчиков"
        else "${thousands.toInt()} тыс. подписчиков"
    }
    else -> "$count подписчиков"
}
