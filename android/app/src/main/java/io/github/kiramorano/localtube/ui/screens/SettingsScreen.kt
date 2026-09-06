package io.github.kiramorano.localtube.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.AppTheme
import io.github.kiramorano.localtube.data.AudioEffects
import io.github.kiramorano.localtube.data.CatalogSort
import io.github.kiramorano.localtube.data.Engine
import io.github.kiramorano.localtube.data.QrCode
import io.github.kiramorano.localtube.data.Settings
import io.github.kiramorano.localtube.ui.components.LtPanel
import io.github.kiramorano.localtube.ui.theme.LtSpace
import io.github.kiramorano.localtube.ui.theme.LtTheme
import io.github.kiramorano.localtube.vm.SettingsViewModel
import kotlin.math.ceil

@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(vm: SettingsViewModel = viewModel()) {
    val colors = LtTheme.colors
    val settings = vm.settings
    val theme by settings.themeFlow.collectAsStateWithLifecycle()
    val subs by settings.downloadSubsFlow.collectAsStateWithLifecycle()
    val subLangs by settings.subLangsFlow.collectAsStateWithLifecycle()
    val audioLangs by settings.audioLangsFlow.collectAsStateWithLifecycle()
    val notifications by settings.notificationsFlow.collectAsStateWithLifecycle()
    val preferHighest by settings.preferHighestFlow.collectAsStateWithLifecycle()
    val autoplay by settings.autoplayNextFlow.collectAsStateWithLifecycle()
    val sort by settings.sortFlow.collectAsStateWithLifecycle()
    val playerClient by settings.playerClientFlow.collectAsStateWithLifecycle()
    val background by settings.backgroundPlaybackFlow.collectAsStateWithLifecycle()
    val eqPreset by settings.equalizerPresetFlow.collectAsStateWithLifecycle()
    val bassBoost by settings.bassBoostFlow.collectAsStateWithLifecycle()
    val externalStorage by settings.externalStorageFlow.collectAsStateWithLifecycle()
    val lanPort by settings.lanPortFlow.collectAsStateWithLifecycle()
    val userName by settings.userNameFlow.collectAsStateWithLifecycle()
    val lan by vm.lan.collectAsStateWithLifecycle()
    val userData by vm.userData.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val appVersion = remember { Engine.appVersion(context) }

    var confirm by remember { mutableStateOf<String?>(null) }
    // Имя применяется кнопкой, как и порт: сохранять на каждую букву значило бы
    // переписывать настройки при наборе.
    var nameText by remember(userName) { mutableStateOf(userName) }
    var showQr by remember { mutableStateOf(false) }
    // Порт правится в поле и применяется кнопкой: сохранять его на каждый
    // введённый символ значило бы перезапускать сервер после каждой цифры.
    var portText by remember(lanPort) { mutableStateOf(lanPort.toString()) }

    // Размер библиотеки и версия yt-dlp считаются только здесь, а не в init
    // модели: иначе за них платили и другие экраны.
    LaunchedEffect(Unit) { vm.refresh() }

    val cookiesPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri -> uri?.let(vm::importCookies) }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = LtSpace.x4, vertical = LtSpace.x3),
        verticalArrangement = Arrangement.spacedBy(LtSpace.x4)
    ) {
        Text(
            "Настройки",
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.SemiBold,
            color = colors.textPrimary
        )

        SettingsCard("Профиль") {
            OutlinedTextField(
                value = nameText,
                onValueChange = { text -> nameText = text.take(Settings.MAX_USER_NAME) },
                label = { Text("Имя") },
                supportingText = { Text("Показывается в шапке") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedButton(
                onClick = { settings.userName = nameText },
                // Пустое поле вернёт «Гость», поэтому его тоже разрешаем
                // применить: иначе имя нельзя было бы сбросить.
                enabled = nameText.trim() != userName
            ) { Text("Сохранить имя") }
        }

        SettingsCard("Оформление") {
            Text("Тема", style = MaterialTheme.typography.bodyMedium, color = colors.textPrimary)
            // Пять тем в ряд на телефоне не влезают: FlowRow переносит лишние
            // на следующую строку, как чипы качества и сортировки ниже.
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                AppTheme.entries.forEach { option ->
                    FilterChip(
                        selected = theme == option,
                        onClick = { settings.theme = option },
                        label = { Text(option.label) }
                    )
                }
            }
        }

        SettingsCard("Каталог") {
            Text(
                "Сортировка по умолчанию",
                style = MaterialTheme.typography.bodyMedium,
                color = colors.textPrimary
            )
            // FlowRow, а не Row: вариантов пять, в одну строку они не влезают.
            // Раньше здесь стоял take(3), и «По размеру» со «Случайно» нельзя
            // было выбрать по умолчанию, хотя в меню каталога они есть.
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                CatalogSort.entries.forEach { option ->
                    FilterChip(
                        selected = sort == option,
                        onClick = { settings.sort = option },
                        label = { Text(option.label) }
                    )
                }
            }
            SwitchRow("Автозапуск следующего видео", autoplay) { settings.autoplayNext = it }
        }

        SettingsCard("Воспроизведение") {
            SwitchRow(
                "Продолжать в фоне",
                background,
                hint = "Звук не прерывается при сворачивании приложения"
            ) { settings.backgroundPlayback = it }
            Text("Эквалайзер", style = MaterialTheme.typography.bodyMedium, color = colors.textPrimary)
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                AudioEffects.Preset.entries.forEach { option ->
                    FilterChip(
                        selected = eqPreset == option.id,
                        onClick = { settings.equalizerPreset = option.id },
                        label = { Text(option.label) }
                    )
                }
            }
            Text(
                "Усиление басов: ${bassBoost / 10}%",
                style = MaterialTheme.typography.bodySmall,
                color = colors.textSecondary
            )
            Slider(
                value = bassBoost.toFloat(),
                onValueChange = { settings.bassBoost = it.toInt() },
                valueRange = 0f..1000f
            )
        }

        SettingsCard("Загрузка") {
            SwitchRow(
                "Скачивать субтитры",
                subs,
                hint = "Без языков ниже субтитры не запрашиваются"
            ) { settings.downloadSubs = it }
            OutlinedTextField(
                value = subLangs,
                onValueChange = { settings.subLangs = it },
                label = { Text("Языки субтитров (через запятую)") },
                // Поле пустое по умолчанию: заранее вписанные «ru,en» ломали
                // загрузку у видео без таких дорожек. Пример показываем
                // подсказкой, а не значением, чтобы он не уезжал в yt-dlp сам.
                placeholder = { Text("например ru,en") },
                supportingText = {
                    Text(
                        if (subLangs.isBlank()) "Пусто — субтитры не скачиваются"
                        else "Скачиваются только языки, которые есть у видео"
                    )
                },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = audioLangs,
                onValueChange = { settings.audioLangs = it },
                label = { Text("Язык озвучки (через запятую)") },
                placeholder = { Text("например ru,en") },
                supportingText = {
                    Text(
                        if (audioLangs.isBlank()) "Пусто — дорожку выбирает YouTube"
                        else "Для видео с несколькими озвучками"
                    )
                },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            SwitchRow(
                "Предлагать 1080p и выше",
                preferHighest,
                hint = "Такие потоки скачиваются отдельно и склеиваются с аудио"
            ) { settings.preferHighest = it }
            SwitchRow("Уведомления о загрузках", notifications) { settings.enableNotifications = it }
        }

        SettingsCard("Хранилище") {
            Text(
                if (externalStorage) "Библиотека на карте памяти" else "Библиотека во внутренней памяти",
                style = MaterialTheme.typography.bodySmall,
                color = colors.textSecondary
            )
            SwitchRow(
                "Хранить видео на карте памяти",
                externalStorage,
                // Перенос уже скачанного не делается: копирование десятков
                // гигабайт из приложения слишком рискованно, а честное
                // предупреждение позволяет решить самому.
                hint = "Применится после перезапуска. Уже скачанные видео останутся " +
                    "на прежнем месте: перенесите их вручную."
            ) { settings.externalStorage = it }
        }

        SettingsCard("Локальная сеть") {
            Text(
                "Раздаёт библиотеку другим устройствам в той же сети: они " +
                    "открывают адрес в браузере и вводят PIN.",
                style = MaterialTheme.typography.bodySmall,
                color = colors.textSecondary
            )
            SwitchRow(
                "Раздавать по Wi-Fi",
                lan.running,
                hint = "Работает, пока приложение открыто"
            ) { vm.toggleLan() }
            if (lan.running) {
                if (lan.addresses.isEmpty()) {
                    Text(
                        "Не удалось определить адрес в сети. Проверьте подключение к Wi-Fi.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error
                    )
                } else {
                    lan.addresses.forEach { host ->
                        Text(
                            "http://$host:${lan.port}",
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Bold,
                            color = colors.textPrimary
                        )
                    }
                }
                Text(
                    "PIN: ${lan.pin}",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold,
                    color = colors.textPrimary
                )
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    OutlinedButton(onClick = { vm.refreshLanAddresses() }) {
                        Text("Обновить адрес")
                    }
                    // Смена PIN отключает все впущенные устройства: отдельного
                    // списка сессий нет, ключ считается от PIN и секрета.
                    OutlinedButton(onClick = { vm.regenerateLanPin() }) {
                        Text("Новый PIN")
                    }
                }
                // QR с адресом: набирать его руками на чужом телефоне неудобно.
                if (lan.url.isNotBlank()) {
                    OutlinedButton(onClick = { showQr = !showQr }) {
                        Text(if (showQr) "Скрыть QR-код" else "Показать QR-код")
                    }
                    if (showQr) {
                        QrImage(lan.url)
                        Text(
                            "Наведите камеру телефона на код: он ведёт на ${lan.url}",
                            style = MaterialTheme.typography.bodySmall,
                            color = colors.textSecondary
                        )
                    }
                }
            }
            if (lan.error.isNotBlank()) {
                Text(
                    lan.error,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error
                )
            }
            OutlinedTextField(
                value = portText,
                onValueChange = { text ->
                    // Только цифры: буквы в номере порта всё равно не примут, а
                    // поле с ними выглядело бы работающим.
                    portText = text.filter(Char::isDigit).take(5)
                },
                label = { Text("Порт") },
                supportingText = { Text("От 1024 до 65535") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedButton(
                onClick = { portText.toIntOrNull()?.let { vm.setLanPort(it) } },
                // Применять неизменённый или невалидный порт незачем: кнопка
                // выключена, пока в поле нет нового допустимого значения.
                enabled = portText.toIntOrNull()?.let { it in 1024..65535 && it != lanPort } == true
            ) { Text("Применить порт") }
        }

        SettingsCard("Доступ к YouTube") {
            Text(
                "Клиент проигрывателя (player_client)",
                style = MaterialTheme.typography.bodyMedium,
                color = colors.textPrimary
            )
            Text(
                "Помогает при ошибках «Sign in to confirm you're not a bot». " +
                    "«Авто» оставляет выбор за yt-dlp.",
                style = MaterialTheme.typography.bodySmall,
                color = colors.textSecondary
            )
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Settings.PLAYER_CLIENTS.forEach { option ->
                    FilterChip(
                        selected = playerClient == option,
                        onClick = { settings.playerClient = option },
                        label = { Text(Settings.playerClientLabel(option)) }
                    )
                }
            }
        }

        SettingsCard("Cookies") {
            Text(
                if (vm.cookiesActive) "cookies.txt установлен" else "cookies.txt не установлен",
                style = MaterialTheme.typography.bodySmall,
                color = colors.textSecondary
            )
            Text(
                "Нужны для видео с ограничениями. Экспортируйте их расширением " +
                    "«Get cookies.txt LOCALLY» и импортируйте здесь.",
                style = MaterialTheme.typography.bodySmall,
                color = colors.textSecondary
            )
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Button(onClick = { cookiesPicker.launch(arrayOf("text/*", "*/*")) }) {
                    Text("Импортировать")
                }
                OutlinedButton(onClick = { vm.clearCookies() }, enabled = vm.cookiesActive) {
                    Text("Удалить")
                }
            }
        }

        SettingsCard("Мои данные") {
            Text(
                "В избранном ${userData.favorites.size}, в истории ${userData.history.size}, " +
                    "скрыто каналов ${userData.hiddenChannels.size}",
                style = MaterialTheme.typography.bodySmall,
                color = colors.textSecondary
            )
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                OutlinedButton(onClick = { confirm = "history" }) { Text("Очистить историю") }
                OutlinedButton(onClick = { confirm = "favorites" }) { Text("Очистить избранное") }
            }
            OutlinedButton(
                onClick = { confirm = "hidden" },
                enabled = userData.hiddenChannels.isNotEmpty()
            ) { Text("Показать все каналы") }
        }

        SettingsCard("Обслуживание") {
            Text(
                "yt-dlp: ${vm.ytDlpVersion ?: "неизвестно"}",
                style = MaterialTheme.typography.bodySmall,
                color = colors.textSecondary
            )
            Text(
                "Занято на устройстве: ${String.format("%.1f", vm.storageMb)} МБ",
                style = MaterialTheme.typography.bodySmall,
                color = colors.textSecondary
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Button(onClick = { vm.updateYtDlp() }, enabled = !vm.updating) {
                    Text("Обновить yt-dlp")
                }
                if (vm.updating) {
                    CircularProgressIndicator(
                        Modifier
                            .padding(start = 12.dp)
                            .size(22.dp),
                        strokeWidth = 2.dp
                    )
                }
            }
            vm.updateStatus?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = colors.textSecondary)
            }
            Text(
                "LocalTube Android $appVersion",
                style = MaterialTheme.typography.labelSmall,
                color = colors.textSecondary,
                modifier = Modifier.padding(top = 4.dp)
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
private fun SettingsCard(
    title: String,
    content: @Composable ColumnScope.() -> Unit
) {
    LtPanel {
        Text(
            title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = LtTheme.colors.textPrimary
        )
        content()
    }
}

/**
 * QR-код адреса раздачи. Рисуется на Canvas, а не через Bitmap: код нужен
 * ровно одного размера, и промежуточная картинка тут ни к чему.
 *
 * Фон всегда белый, точки чёрные, независимо от темы: инверсный код часть
 * сканеров не читает.
 */
@Composable
private fun QrImage(url: String) {
    // Кодирование не бесплатное, а перерисовок у настроек много: держим
    // матрицу до смены адреса.
    val matrix = remember(url) {
        runCatching { QrCode.matrix(url) }.getOrNull()
    }
    if (matrix == null || matrix.isEmpty()) {
        Text(
            "Не удалось нарисовать QR-код. Введите адрес вручную.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error
        )
        return
    }
    Canvas(
        Modifier
            .size(200.dp)
            .background(Color.White)
            .padding(4.dp)
            .semantics { contentDescription = "QR-код с адресом $url" }
    ) {
        val cells = matrix.size
        // Точку округляем вверх: при дробной ширине между модулями оставались
        // белые полосы, и код читался хуже.
        val cell = size.minDimension / cells
        val dot = ceil(cell)
        for (y in 0 until cells) {
            for (x in 0 until cells) {
                if (!matrix[y][x]) continue
                drawRect(
                    color = Color.Black,
                    topLeft = Offset(x * cell, y * cell),
                    size = Size(dot, dot)
                )
            }
        }
    }
}

@Composable
private fun SwitchRow(
    label: String,
    checked: Boolean,
    hint: String? = null,
    onChange: (Boolean) -> Unit
) {
    val colors = LtTheme.colors
    Row(
        Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.bodyMedium, color = colors.textPrimary)
            if (hint != null) {
                Text(
                    hint,
                    style = MaterialTheme.typography.labelSmall,
                    color = colors.textSecondary
                )
            }
        }
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
