package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
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
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.ServerManager
import io.github.kiramorano.localtube.ui.components.AuthorsGrid
import io.github.kiramorano.localtube.ui.components.ErrorBox
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.ui.components.PlaylistsList
import io.github.kiramorano.localtube.ui.components.VideoGrid
import io.github.kiramorano.localtube.vm.HomeViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onOpenVideo: (String) -> Unit,
    vm: HomeViewModel = viewModel()
) {
    val server by ServerManager.serverUrl.collectAsState()
    LaunchedEffect(server) { vm.load() }

    var tab by rememberSaveable { mutableIntStateOf(0) }
    val tabs = listOf("Видео", "Shorts", "Каналы", "Плейлисты", "Мои")

    Column(Modifier.fillMaxSize()) {
        CenterAlignedTopAppBar(
            title = {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("LocalTube", style = MaterialTheme.typography.titleLarge)
                    Text(
                        server.removePrefix("http://").removePrefix("https://"),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }
        )
        TabRow(selectedTabIndex = tab) {
            tabs.forEachIndexed { i, t ->
                Tab(selected = tab == i, onClick = { tab = i }, text = { Text(t) })
            }
        }
        val catalog = vm.catalog
        when {
            vm.error != null && catalog == null -> ErrorBox(vm.error!!) { vm.load() }
            catalog == null -> LoadingBox()
            else -> when (tab) {
                0 -> VideoGrid(catalog.videos, onOpenVideo)
                1 -> VideoGrid(catalog.shorts, onOpenVideo, short = true)
                2 -> AuthorsGrid(catalog.authors)
                3 -> PlaylistsList(catalog.playlists)
                else -> VideoGrid(catalog.userVideos, onOpenVideo)
            }
        }
    }
}
