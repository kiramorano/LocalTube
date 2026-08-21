package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.ui.components.AsyncThumb
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.ui.components.VideoGrid
import io.github.kiramorano.localtube.vm.ChannelViewModel

/**
 * Страница канала: аватар, число видео, вкладки «Видео» и «Shorts», кнопка
 * скрытия. Аналог /channel/<author> в веб-версии.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChannelScreen(
    author: String,
    onBack: () -> Unit,
    onOpenVideo: (String) -> Unit,
    onOpenShorts: (String) -> Unit,
    vm: ChannelViewModel = viewModel()
) {
    val userData by vm.userData.collectAsStateWithLifecycle()
    var tab by remember { mutableIntStateOf(0) }

    LaunchedEffect(author) { vm.load(author) }

    val hidden = userData.hiddenChannels.contains(author)
    val favorites = userData.favorites.toSet()

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(author, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
                }
            }
        )

        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                Modifier
                    .size(64.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.Center
            ) {
                if (vm.avatar != null) {
                    AsyncThumb(vm.avatar, Modifier.fillMaxSize())
                } else {
                    Text(author.take(1).uppercase(), style = MaterialTheme.typography.titleLarge)
                }
            }
            Column(
                Modifier
                    .weight(1f)
                    .padding(start = 12.dp)
            ) {
                Text(author, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(
                    "${vm.videos.size} видео · ${vm.shorts.size} Shorts",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        Button(
            onClick = { vm.toggleHidden() },
            modifier = Modifier
                .padding(horizontal = 16.dp)
                .fillMaxWidth(),
            colors = if (hidden) ButtonDefaults.buttonColors()
            else ButtonDefaults.outlinedButtonColors(
                contentColor = MaterialTheme.colorScheme.onSurface
            )
        ) {
            Icon(
                if (hidden) Icons.Filled.Visibility else Icons.Filled.VisibilityOff,
                contentDescription = null
            )
            Text(
                if (hidden) "  Показать канал" else "  Скрыть канал",
                modifier = Modifier.padding(start = 4.dp)
            )
        }
        if (hidden) {
            Text(
                "Канал скрыт: его видео не показываются в подборках и поиске.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp)
            )
        }

        if (vm.shorts.isNotEmpty()) {
            TabRow(selectedTabIndex = tab) {
                Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("Видео") })
                Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("Shorts") })
            }
        }

        when {
            vm.loading -> LoadingBox()
            tab == 1 -> VideoGrid(
                items = vm.shorts,
                onOpen = onOpenShorts,
                short = true,
                favorites = favorites,
                emptyText = "Shorts у канала нет"
            )
            else -> VideoGrid(
                items = vm.videos,
                onOpen = onOpenVideo,
                favorites = favorites,
                emptyText = "Видео у канала нет"
            )
        }
    }
}
