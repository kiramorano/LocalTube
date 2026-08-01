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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.kiramorano.localtube.data.ServerManager
import kotlinx.coroutines.launch

@Composable
fun SettingsScreen() {
    val server by ServerManager.serverUrl.collectAsState()
    var edit by rememberSaveable { mutableStateOf(server) }
    var result by remember { mutableStateOf<String?>(null) }
    var savedMsg by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)
    ) {
        Text("Настройки", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(16.dp))
        Text("Сервер LocalTube", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = edit,
            onValueChange = { edit = it; savedMsg = null },
            label = { Text("Адрес сервера") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                val t = edit.trim().trimEnd('/')
                when {
                    !t.matches(Regex("https?://.+")) -> savedMsg = "Некорректный адрес"
                    t.equals(server, ignoreCase = true) -> savedMsg = "Адрес не изменился"
                    else -> {
                        ServerManager.save(t)
                        savedMsg = "Сохранено. Данные обновятся при переходе на главную."
                    }
                }
            }) {
                Text("Сохранить")
            }
            OutlinedButton(onClick = {
                scope.launch {
                    result = null
                    savedMsg = null
                    result = try {
                        val c = ServerManager.api().catalog()
                        "Подключение есть: ${c.videos.size} видео, ${c.shorts.size} shorts"
                    } catch (e: Exception) {
                        "Ошибка: ${e.message}"
                    }
                }
            }) {
                Text("Проверить")
            }
        }
        savedMsg?.let {
            Spacer(Modifier.height(8.dp))
            Text(it, color = MaterialTheme.colorScheme.primary)
        }
        result?.let {
            Spacer(Modifier.height(8.dp))
            Text(it)
        }
        Spacer(Modifier.height(24.dp))
        HorizontalDivider()
        Spacer(Modifier.height(16.dp))
        Text("LocalTube Android v2.0.0", style = MaterialTheme.typography.titleSmall)
        Text(
            "Нативный клиент для сервера LocalTube. Видео хранятся на сервере.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}
