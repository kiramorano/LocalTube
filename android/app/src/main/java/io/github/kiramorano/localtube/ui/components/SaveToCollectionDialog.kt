package io.github.kiramorano.localtube.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.automirrored.filled.PlaylistAddCheck
import androidx.compose.material.icons.filled.WatchLater
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.VideoCollection
import io.github.kiramorano.localtube.ui.theme.LtTap
import io.github.kiramorano.localtube.ui.theme.LtTheme
import io.github.kiramorano.localtube.vm.SaveToCollectionViewModel

/**
 * Диалог «Сохранить в...»: галочки у плейлистов и поле для создания нового.
 *
 * Повторяет модальное окно веб-версии. Отметки применяются сразу, без кнопки
 * «Сохранить»: на сервере запрос уходит по каждому клику, и одинаковое
 * поведение важнее лишнего подтверждения.
 */
@Composable
fun SaveToCollectionDialog(
    videoId: String,
    onDismiss: () -> Unit,
    vm: SaveToCollectionViewModel = viewModel()
) {
    val colors = LtTheme.colors
    val userData by vm.userData.collectAsStateWithLifecycle()
    var creating by remember { mutableStateOf(false) }
    var newTitle by remember { mutableStateOf("") }

    val collections = vm.collections(userData)
    val watchLaterExists = collections.any { it.id == VideoCollection.WATCH_LATER_ID }

    AlertDialog(
        onDismissRequest = {
            vm.clearError()
            onDismiss()
        },
        title = { Text("Сохранить в...") },
        text = {
            Column {
                vm.error?.let {
                    Text(it, color = colors.brandRed, fontSize = 12.sp, modifier = Modifier.padding(bottom = 6.dp))
                }

                // «Смотреть позже» материализуется только при первом
                // использовании, поэтому в списке его может ещё не быть.
                if (!watchLaterExists) {
                    CollectionCheckRow(
                        title = VideoCollection.WATCH_LATER_TITLE,
                        checked = false,
                        onToggle = { vm.toggleWatchLater(videoId) }
                    )
                }

                LazyColumn(
                    Modifier.heightIn(max = 260.dp),
                    verticalArrangement = Arrangement.spacedBy(2.dp)
                ) {
                    items(collections, key = { it.id }) { c ->
                        CollectionCheckRow(
                            title = c.title,
                            checked = vm.contains(userData, c.id, videoId),
                            onToggle = { vm.toggle(c.id, videoId) }
                        )
                    }
                }

                if (creating) {
                    Row(
                        Modifier.fillMaxWidth().padding(top = 8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        OutlinedTextField(
                            value = newTitle,
                            onValueChange = {
                                if (it.length <= VideoCollection.TITLE_LIMIT) newTitle = it
                            },
                            label = { Text("Название") },
                            singleLine = true,
                            modifier = Modifier.weight(1f)
                        )
                        TextButton(
                            onClick = {
                                vm.createAndAdd(newTitle, videoId)
                                // Поле очищаем только при успехе: иначе набранное
                                // название пропадало вместе с текстом ошибки.
                                if (vm.error == null) {
                                    newTitle = ""
                                    creating = false
                                }
                            },
                            enabled = newTitle.isNotBlank()
                        ) { Text("ОК") }
                    }
                } else {
                    Row(
                        Modifier
                            .fillMaxWidth()
                            // Было 44dp: иконка 24dp плюс по 10dp.
                            .heightIn(min = LtTap.min)
                            .clickable { creating = true },
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(Icons.Filled.Add, contentDescription = null, tint = colors.textPrimary)
                        Text(
                            "Создать плейлист",
                            color = colors.textPrimary,
                            modifier = Modifier.padding(start = 8.dp)
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                vm.clearError()
                onDismiss()
            }) { Text("Готово") }
        }
    )
}

@Composable
private fun CollectionCheckRow(title: String, checked: Boolean, onToggle: () -> Unit) {
    val colors = LtTheme.colors
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onToggle),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Checkbox(checked = checked, onCheckedChange = { onToggle() })
        Icon(
            if (title == VideoCollection.WATCH_LATER_TITLE) Icons.Filled.WatchLater
            else Icons.AutoMirrored.Filled.PlaylistAddCheck,
            contentDescription = null,
            tint = colors.textSecondary
        )
        Text(
            title,
            color = colors.textPrimary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(start = 8.dp)
        )
    }
}
