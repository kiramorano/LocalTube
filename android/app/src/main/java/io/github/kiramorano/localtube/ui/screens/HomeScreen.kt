package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Sort
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.CatalogSort
import io.github.kiramorano.localtube.ui.components.AuthorsGrid
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.ui.components.PlaylistsGrid
import io.github.kiramorano.localtube.ui.components.VideoGrid
import io.github.kiramorano.localtube.vm.HomeViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onOpenVideo: (String) -> Unit,
    onOpenShorts: (String) -> Unit,
    onOpenPlaylist: (String) -> Unit,
    onOpenChannel: (String) -> Unit,
    vm: HomeViewModel = viewModel()
) {
    val userData by vm.userData.collectAsStateWithLifecycle()
    val sort by vm.settings.sortFlow.collectAsStateWithLifecycle()
    val libraryVersion by vm.libraryVersion.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var sortMenu by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.load() }
    // Каталог перечитывается после завершения загрузки: раньше новое видео
    // появлялось только если уйти с экрана и вернуться.
    LaunchedEffect(libraryVersion) { if (libraryVersion > 0) vm.load(force = true) }

    val titles = listOf("Видео", "Shorts", "Каналы", "Плейлисты", "Мои")

    Column(Modifier.fillMaxSize()) {
        CenterAlignedTopAppBar(
            title = { Text("LocalTube") },
            actions = {
                IconButton(onClick = { sortMenu = true }) {
                    Icon(Icons.Filled.Sort, contentDescription = "Сортировка")
                }
                DropdownMenu(expanded = sortMenu, onDismissRequest = { sortMenu = false }) {
                    CatalogSort.entries.forEach { option ->
                        DropdownMenuItem(
                            text = { Text(option.label + if (option == sort) "  ✓" else "") },
                            onClick = {
                                sortMenu = false
                                vm.setSort(option)
                            }
                        )
                    }
                }
                IconButton(onClick = { vm.load(force = true) }) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Обновить")
                }
            }
        )
        ScrollableTabRow(selectedTabIndex = tab, edgePadding = 8.dp) {
            titles.forEachIndexed { i, t ->
                Tab(selected = tab == i, onClick = { tab = i }, text = { Text(t) })
            }
        }

        val catalog = vm.catalog
        when {
            catalog == null -> LoadingBox()
            else -> {
                val visible = vm.visible(catalog, userData.hiddenChannels, sort)
                val favorites = userData.favorites.toSet()
                when (tab) {
                    0 -> VideoGrid(
                        items = visible.videos,
                        onOpen = onOpenVideo,
                        favorites = favorites,
                        onToggleFavorite = vm::toggleFavorite,
                        onOpenChannel = onOpenChannel,
                        onHideChannel = { author -> vm.setChannelHidden(author, true) },
                        onDelete = vm::delete,
                        emptyText = "Видео пока нет. Скачайте что-нибудь на вкладке «Загрузки»."
                    )
                    1 -> VideoGrid(
                        items = visible.shorts,
                        onOpen = onOpenShorts,
                        short = true,
                        favorites = favorites,
                        onToggleFavorite = vm::toggleFavorite,
                        onOpenChannel = onOpenChannel,
                        onHideChannel = { author -> vm.setChannelHidden(author, true) },
                        onDelete = vm::delete,
                        emptyText = "Shorts пока нет"
                    )
                    2 -> AuthorsGrid(authors = visible.authors, onOpen = onOpenChannel)
                    3 -> PlaylistsGrid(playlists = visible.playlists, onOpen = onOpenPlaylist)
                    else -> VideoGrid(
                        items = visible.userVideos,
                        onOpen = onOpenVideo,
                        favorites = favorites,
                        onToggleFavorite = vm::toggleFavorite,
                        onDelete = vm::delete,
                        emptyText = "Свои видео можно добавить на вкладке «Моё»"
                    )
                }
            }
        }
    }
}
