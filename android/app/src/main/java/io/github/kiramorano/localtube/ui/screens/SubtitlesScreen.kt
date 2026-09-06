package io.github.kiramorano.localtube.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Subtitles
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.vm.SubtitlesViewModel

/**
 * Управление субтитрами скачанного видео: список дорожек, догрузка нужных
 * языков с YouTube, импорт своего .vtt и удаление. Аналог раздела субтитров на
 * странице видео в веб-версии.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun SubtitlesScreen(
    videoId: String,
    onBack: () -> Unit,
    vm: SubtitlesViewModel = viewModel()
) {
    val state by vm.state.collectAsStateWithLifecycle()
    var chosen by remember { mutableStateOf(setOf<String>()) }
    var importLang by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(videoId) { vm.load(videoId) }

    // Импорт своего файла: язык спрашиваем до выбора файла, иначе после
    // возврата из системного диалога состояние экрана могло быть уже сброшено.
    val picker = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri ->
        val lang = importLang
        importLang = null
        if (uri != null && lang != null) vm.import(uri, lang)
    }

    Column(Modifier.fillMaxSize()) {
        CenterAlignedTopAppBar(
            title = { Text("Субтитры") },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
                }
            }
        )

        if (vm.video == null) {
            EmptyBox("Видео не найдено")
            return@Column
        }

        state.error?.let { Notice(it, isError = true) { vm.clearMessages() } }
        state.message?.let { Notice(it, isError = false) { vm.clearMessages() } }

        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(14.dp)
        ) {
            Text(
                vm.video?.title.orEmpty(),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )

            Text(
                "Дорожки на диске",
                style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.padding(top = 14.dp, bottom = 4.dp)
            )
            if (state.tracks.isEmpty()) {
                Text(
                    "Субтитров нет.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            } else {
                state.tracks.forEach { track ->
                    Row(
                        Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            Icons.Filled.Subtitles,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Text(
                            track.lang,
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier
                                .weight(1f)
                                .padding(start = 8.dp)
                        )
                        IconButton(onClick = { vm.delete(track) }) {
                            Icon(Icons.Filled.Delete, contentDescription = "Удалить дорожку")
                        }
                    }
                }
            }

            HorizontalDivider(Modifier.padding(vertical = 12.dp))

            if (vm.isUserVideo()) {
                // У своих видео нет адреса на YouTube, значит и языков спросить
                // не у кого: остаётся только импорт файла.
                Text(
                    "Для своих видео доступен только импорт файла субтитров.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            } else {
                Text("Скачать с YouTube", style = MaterialTheme.typography.labelLarge)
                if (state.loading) {
                    LinearProgressIndicator(Modifier.fillMaxWidth().padding(vertical = 8.dp))
                }
                if (state.availableLangs.isEmpty()) {
                    OutlinedButton(
                        onClick = { vm.loadAvailable() },
                        enabled = !state.loading,
                        modifier = Modifier.padding(top = 6.dp)
                    ) { Text("Узнать доступные языки") }
                } else {
                    FlowRow(
                        Modifier.padding(top = 6.dp),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        state.availableLangs.forEach { lang ->
                            FilterChip(
                                selected = chosen.contains(lang),
                                onClick = {
                                    chosen = if (chosen.contains(lang)) chosen - lang else chosen + lang
                                },
                                label = { Text(lang) }
                            )
                        }
                    }
                    Row(Modifier.padding(top = 8.dp)) {
                        OutlinedButton(
                            onClick = {
                                vm.download(chosen.toList())
                                chosen = emptySet()
                            },
                            enabled = chosen.isNotEmpty() && !state.loading
                        ) { Text("Скачать (${chosen.size})") }
                        TextButton(
                            onClick = { vm.loadAvailable() },
                            enabled = !state.loading
                        ) { Text("Обновить список") }
                    }
                }
            }

            HorizontalDivider(Modifier.padding(vertical = 12.dp))

            Text("Свой файл", style = MaterialTheme.typography.labelLarge)
            OutlinedButton(
                onClick = { importLang = "" },
                modifier = Modifier.padding(top = 6.dp)
            ) { Text("Импортировать .vtt или .srt") }
        }
    }

    // Диалог языка перед выбором файла: имя дорожки становится именем файла,
    // и без него все импортированные субтитры назывались бы одинаково.
    importLang?.let { current ->
        if (current.isEmpty()) {
            TitleDialog(
                title = "Язык дорожки",
                initial = "ru",
                confirmLabel = "Выбрать файл",
                onDismiss = { importLang = null },
                onConfirm = { lang ->
                    importLang = lang
                    // Тип оставляем широким: часть файловых менеджеров не
                    // сообщает MIME для .vtt, и фильтр по нему прятал файл.
                    picker.launch("*/*")
                }
            )
        }
    }
}
