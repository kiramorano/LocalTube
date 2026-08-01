package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import io.github.kiramorano.localtube.data.ServerManager
import io.github.kiramorano.localtube.data.VideoItem
import io.github.kiramorano.localtube.ui.components.AsyncThumb
import io.github.kiramorano.localtube.ui.components.ErrorBox
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.vm.PlayerViewModel

@Composable
fun PlayerScreen(
    videoId: String,
    onBack: () -> Unit,
    vm: PlayerViewModel = viewModel()
) {
    LaunchedEffect(videoId) { vm.load(videoId) }
    val detail = vm.detail

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 4.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
            }
            Text(
                "Сейчас смотрим",
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        when {
            vm.loading && detail == null -> LoadingBox()
            vm.error != null && detail == null -> ErrorBox(vm.error!!) { vm.load(videoId) }
            detail == null -> LoadingBox()
            else -> {
                val url = remember(detail.videoUrl) {
                    detail.videoUrl?.let { ServerManager.api().absolute(it) }
                }
                if (url != null) {
                    VideoPlayer(url)
                } else {
                    Text(
                        "Видео недоступно на сервере",
                        modifier = Modifier.padding(16.dp),
                        color = MaterialTheme.colorScheme.error
                    )
                }
                LazyColumn(Modifier.weight(1f)) {
                    item {
                        Column(Modifier.padding(12.dp)) {
                            Text(detail.title, style = MaterialTheme.typography.titleLarge)
                            Spacer(Modifier.height(4.dp))
                            Text(detail.author, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
                            if (detail.sizeMb > 0) {
                                Text(
                                    "${detail.sizeMb} MB",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            if (detail.description.isNotBlank()) {
                                Spacer(Modifier.height(8.dp))
                                Text(detail.description, style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                    }
                    if (detail.recommended.isNotEmpty()) {
                        item {
                            Text(
                                "Рекомендации",
                                style = MaterialTheme.typography.titleMedium,
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
                            )
                        }
                        items(detail.recommended, key = { it.id }) { rec ->
                            RecommendedRow(rec) { vm.load(rec.id) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun VideoPlayer(url: String) {
    val context = LocalContext.current
    val player = remember { ExoPlayer.Builder(context).build() }
    DisposableEffect(player) {
        onDispose { player.release() }
    }
    LaunchedEffect(url) {
        player.setMediaItem(MediaItem.fromUri(url))
        player.prepare()
        player.playWhenReady = true
    }
    AndroidView(
        factory = { ctx ->
            PlayerView(ctx).apply {
                useController = true
                this.player = player
            }
        },
        modifier = Modifier.fillMaxWidth().aspectRatio(16f / 9f)
    )
}

@Composable
private fun RecommendedRow(v: VideoItem, onClick: () -> Unit) {
    Card(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)
    ) {
        Row(Modifier.padding(8.dp)) {
            AsyncThumb(v.thumb, Modifier.size(96.dp, 54.dp).clip(RoundedCornerShape(6.dp)))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(v.title, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(v.author, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
