package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DeleteSweep
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.CatalogSort
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.ui.components.VideoGrid
import io.github.kiramorano.localtube.vm.HomeViewModel
import io.github.kiramorano.localtube.vm.SettingsViewModel

/** Общий экран для избранного и истории: списки различаются только источником. */
object HistoryScreen {
    enum class Mode { FAVORITES, HISTORY }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryScreen(
    mode: HistoryScreen.Mode,
    onOpenVideo: (String) -> Unit,
    vm: HomeViewModel = viewModel(),
    settingsVm: SettingsViewModel = viewModel()
) {
    val userData by vm.userData.collectAsStateWithLifecycle()
    var confirmClear by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.load() }

    val isFavorites = mode == HistoryScreen.Mode.FAVORITES
    val title = if (isFavorites) "Избранное" else "История просмотров"

    Column(Modifier.fillMaxSize()) {
        CenterAlignedTopAppBar(
            title = { Text(title) },
            actions = {
                IconButton(onClick = { confirmClear = true }) {
                    Icon(Icons.Filled.DeleteSweep, contentDescription = "Очистить")
                }
            }
        )

        val catalog = vm.catalog
        if (catalog == null) {
            LoadingBox()
        } else {
            val hidden = userData.hiddenChannels.toSet()
            val ids = if (isFavorites) userData.favorites else userData.history
            val items = (if (isFavorites) vm.favorites(catalog, ids) else vm.history(catalog, ids))
                .filterNot { hidden.contains(it.author) }
            VideoGrid(
                items = items,
                onOpen = onOpenVideo,
                favorites = userData.favorites.toSet(),
                onToggleFavorite = vm::toggleFavorite,
                emptyText = if (isFavorites) "В избранном пока ничего нет"
                else "История пуста"
            )
        }
    }

    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            title = { Text(if (isFavorites) "Очистить избранное?" else "Очистить историю?") },
            text = { Text("Действие необратимо.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmClear = false
                    if (isFavorites) settingsVm.clearFavorites() else settingsVm.clearHistory()
                }) { Text("Очистить") }
            },
            dismissButton = {
                TextButton(onClick = { confirmClear = false }) { Text("Отмена") }
            }
        )
    }
}
