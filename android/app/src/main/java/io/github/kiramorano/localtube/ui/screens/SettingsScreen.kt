package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.vm.SettingsViewModel

@Composable
fun SettingsScreen(vm: SettingsViewModel = viewModel()) {
    val s = vm.settings
    var subLangs by remember { mutableStateOf(s.subLangs) }
    var defaultFormat by remember { mutableStateOf(s.defaultFormat) }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)
    ) {
        Text("Настройки", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(16.dp))

        Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Тёмная тема", style = MaterialTheme.typography.titleSmall)
                Text("Интерфейс в тёмных тонах", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Switch(checked = s.darkTheme, onCheckedChange = { s.darkTheme = it })
        }
        Spacer(Modifier.height(8.dp))

        Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Скачивать субтитры", style = MaterialTheme.typography.titleSmall)
                Text("Автоматически при загрузке", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Switch(checked = s.downloadSubs, onCheckedChange = { s.downloadSubs = it })
        }
        Spacer(Modifier.height(8.dp))

        Text("Языки субтитров (через запятую)", style = MaterialTheme.typography.titleSmall)
        OutlinedTextField(
            value = subLangs,
            onValueChange = { subLangs = it; s.subLangs = it },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(12.dp))

        Text("Формат по умолчанию", style = MaterialTheme.typography.titleSmall)
        OutlinedTextField(
            value = defaultFormat,
            onValueChange = { defaultFormat = it; s.defaultFormat = it },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Text("best / bestvideo+bestaudio / 1080p и т.п.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(8.dp))

        Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Уведомления", style = MaterialTheme.typography.titleSmall)
                Text("О завершении загрузок", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Switch(checked = s.enableNotifications, onCheckedChange = { s.enableNotifications = it })
        }

        Spacer(Modifier.height(16.dp))
        HorizontalDivider()
        Spacer(Modifier.height(16.dp))

        Text("yt-dlp", style = MaterialTheme.typography.titleMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { vm.updateYtDlp() }, enabled = !vm.updating) {
                Text(if (vm.updating) "Обновление..." else "Обновить yt-dlp")
            }
        }
        Text(
            "Версия: ${vm.ytDlpVersion ?: "недоступно"}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        vm.updateStatus?.let {
            Spacer(Modifier.height(4.dp))
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
        }

        Spacer(Modifier.height(16.dp))
        Text("Занято на диске: %.1f MB".format(vm.storageMb), style = MaterialTheme.typography.bodySmall)
        Text(
            "Видео хранятся локально на устройстве.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(16.dp))
        HorizontalDivider()
        Spacer(Modifier.height(16.dp))
        Text("LocalTube Android v3.0.0", style = MaterialTheme.typography.titleSmall)
    }
}
