package io.github.kiramorano.localtube.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.AppTheme
import io.github.kiramorano.localtube.data.CatalogSort
import io.github.kiramorano.localtube.vm.SettingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(vm: SettingsViewModel = viewModel()) {
    val settings = vm.settings
    val theme by settings.themeFlow.collectAsStateWithLifecycle()
    val subs by settings.downloadSubsFlow.collectAsStateWithLifecycle()
    val subLangs by settings.subLangsFlow.collectAsStateWithLifecycle()
    val notifications by settings.notificationsFlow.collectAsStateWithLifecycle()
    val preferHighest by settings.preferHighestFlow.collectAsStateWithLifecycle()
    val autoplay by settings.autoplayNextFlow.collectAsStateWithLifecycle()
    val sort by settings.sortFlow.collectAsStateWithLifecycle()
    val userData by vm.userData.collectAsStateWithLifecycle()

    var confirm by remember { mutableStateOf<String?>(null) }

    val cookiesPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri -> uri?.let(vm::importCookies) }

    Column(Modifier.fillMaxSize()) {
        CenterAlignedTopAppBar(title = { Text("Настройки") })
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            SectionTitle("Оформление")
            Text("Тема", style = MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AppTheme.entries.forEach { option ->
                    FilterChip(
                        selected = theme == option,
                        onClick = { settings.theme = option },
                        label = { Text(option.label) }
                    )
                }
            }

            HorizontalDivider()
            SectionTitle("Каталог")
            Text("Сортировка по умолчанию", style = MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CatalogSort.entries.take(3).forEach { option ->
                    FilterChip(
                        selected = sort == option,
                        onClick = { settings.sort = option },
                        label = { Text(option.label) }
                    )
                }
            }
            SwitchRow("Автозапуск следующего видео", autoplay) { settings.autoplayNext = it }

            HorizontalDivider()
            SectionTitle("Загрузка")
            SwitchRow("Скачивать субтитры", subs) { settings.downloadSubs = it }
            OutlinedTextField(
                value = subLangs,
                onValueChange = { settings.subLangs = it },
                label = { Text("Языки субтитров (через запятую)") },
                modifier = Modifier.fillMaxWidth()
            )
            SwitchRow(
                "Предлагать 1080p и выше",
                preferHighest,
                hint = "Такие потоки скачиваются отдельно и склеиваются с аудио"
            ) { settings.preferHighest = it }
            SwitchRow("Уведомления о загрузках", notifications) { settings.enableNotifications = it }

            HorizontalDivider()
            SectionTitle("Cookies")
            Text(
                if (vm.cookiesActive) "cookies.txt установлен" else "cookies.txt не установлен",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                "Нужны для видео с ограничениями. Экспортируйте их расширением " +
                    "«Get cookies.txt LOCALLY» и импортируйте здесь.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { cookiesPicker.launch(arrayOf("text/*", "*/*")) }) {
                    Text("Импортировать")
                }
                OutlinedButton(onClick = { vm.clearCookies() }, enabled = vm.cookiesActive) {
                    Text("Удалить")
                }
            }

            HorizontalDivider()
            SectionTitle("Мои данные")
            Text(
                "В избранном ${userData.favorites.size}, в истории ${userData.history.size}, " +
                    "скрыто каналов ${userData.hiddenChannels.size}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { confirm = "history" }) { Text("Очистить историю") }
                OutlinedButton(onClick = { confirm = "favorites" }) { Text("Очистить избранное") }
            }
            OutlinedButton(
                onClick = { confirm = "hidden" },
                enabled = userData.hiddenChannels.isNotEmpty()
            ) { Text("Показать все каналы") }

            HorizontalDivider()
            SectionTitle("Обслуживание")
            Text(
                "yt-dlp: ${vm.ytDlpVersion ?: "неизвестно"}",
                style = MaterialTheme.typography.bodySmall
            )
            Text(
                "Занято на устройстве: ${String.format("%.1f", vm.storageMb)} МБ",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Button(onClick = { vm.updateYtDlp() }, enabled = !vm.updating) {
                    Text("Обновить yt-dlp")
                }
                if (vm.updating) {
                    CircularProgressIndicator(Modifier.padding(start = 12.dp))
                }
            }
            vm.updateStatus?.let {
                Text(it, style = MaterialTheme.typography.bodySmall)
            }
            Text(
                "LocalTube Android 3.1.0",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 12.dp)
            )
        }
    }

    confirm?.let { what ->
        val title = when (what) {
            "history" -> "Очистить историю просмотров?"
            "favorites" -> "Очистить избранное?"
            else -> "Показать все скрытые каналы?"
        }
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text(title) },
            text = { Text("Действие необратимо.") },
            confirmButton = {
                TextButton(onClick = {
                    when (what) {
                        "history" -> vm.clearHistory()
                        "favorites" -> vm.clearFavorites()
                        else -> vm.clearHidden()
                    }
                    confirm = null
                }) { Text("Да") }
            },
            dismissButton = {
                TextButton(onClick = { confirm = null }) { Text("Отмена") }
            }
        )
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.Bold,
        modifier = Modifier.padding(top = 6.dp)
    )
}

@Composable
private fun SwitchRow(
    label: String,
    checked: Boolean,
    hint: String? = null,
    onChange: (Boolean) -> Unit
) {
    Row(
        Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.bodyMedium)
            if (hint != null) {
                Text(
                    hint,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
