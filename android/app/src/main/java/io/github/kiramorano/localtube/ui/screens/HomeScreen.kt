package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.Catalog
import io.github.kiramorano.localtube.data.VideoItem
import io.github.kiramorano.localtube.ui.components.AuthorsGrid
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.ui.components.PlaylistsGrid
import io.github.kiramorano.localtube.ui.components.VideoGrid
import io.github.kiramorano.localtube.ui.components.VideoCard
import io.github.kiramorano.localtube.vm.HomeViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onOpenVideo: (String) -> Unit,
    onOpenShorts: (String) -> Unit,
    onOpenPlaylist: (String) -> Unit,
    vm: HomeViewModel = viewModel()
) {
    LaunchedEffect(Unit) { vm.load() }

    var tab by rememberSaveable { mutableIntStateOf(0) }
    val tabs = listOf("Видео", "Shorts", "Каналы", "Плейлисты", "Мои")

    Column(Modifier.fillMaxSize()) {
        CenterAlignedTopAppBar(title = { Text("LocalTube", style = MaterialTheme.typography.titleLarge) })
        TabRow(selectedTabIndex = tab) {
            tabs.forEachIndexed { i, t ->
                Tab(selected = tab == i, onClick = { tab = i }, text = { Text(t) })
            }
        }
        val catalog = vm.catalog
        when {
            catalog == null -> LoadingBox()
            else -> when (tab) {
                0 -> VideoGrid(catalog.videos, onOpenVideo)
                1 -> ShortsGrid(catalog.shorts, onOpenShorts)
                2 -> AuthorsGrid(catalog.authors)
                3 -> PlaylistsGrid(catalog.playlists, onOpenPlaylist)
                else -> VideoGrid(catalog.userVideos, onOpenVideo)
            }
        }
    }
}

@Composable
private fun ShortsGrid(shorts: List<VideoItem>, onOpen: (String) -> Unit) {
    if (shorts.isEmpty()) {
        Column(Modifier.fillMaxSize().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text("Shorts пока нет", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Скачивайте вертикальные видео через «Загрузки»", style = MaterialTheme.typography.bodySmall)
        }
        return
    }
    LazyVerticalGrid(
        columns = GridCells.Fixed(3),
        contentPadding = PaddingValues(8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        items(shorts, key = { it.id }) { v ->
            Column(
                Modifier
                    .fillMaxWidth()
                    .clickable { onOpen(v.id) }
            ) {
                VideoCard(v, onClick = { onOpen(v.id) }, short = true)
            }
        }
    }
}

@Composable
fun SectionHeader(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleMedium,
        modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
    )
}
