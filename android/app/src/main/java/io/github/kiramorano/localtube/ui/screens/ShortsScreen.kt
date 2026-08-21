package io.github.kiramorano.localtube.ui.screens

import android.view.KeyEvent
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.VolumeOff
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.foundation.focusable
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.onKeyEvent
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.vm.ShortsViewModel
import kotlinx.coroutines.launch
import java.io.File

/**
 * Вертикальная лента Shorts: прокрутка с прилипанием, автозапуск видео в
 * фокусе, общая громкость. Один плеер переиспользуется между страницами,
 * иначе несколько ExoPlayer быстро упираются в лимит декодеров.
 */
@OptIn(UnstableApi::class)
@Composable
fun ShortsScreen(
    startId: String,
    onBack: () -> Unit,
    vm: ShortsViewModel = viewModel()
) {
    val context = LocalContext.current
    var muted by remember { mutableStateOf(false) }
    var playing by remember { mutableStateOf(true) }
    val focusRequester = remember { FocusRequester() }
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    LaunchedEffect(startId) { vm.load(startId.ifBlank { null }) }

    val player = remember {
        ExoPlayer.Builder(context).build().apply {
            repeatMode = Player.REPEAT_MODE_ONE
            playWhenReady = true
        }
    }

    DisposableEffect(Unit) {
        onDispose { player.release() }
    }

    val shorts = vm.shorts
    if (shorts.isEmpty()) {
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            EmptyBox("Shorts пока нет")
            IconButton(onClick = onBack, modifier = Modifier.align(Alignment.TopStart)) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад", tint = Color.White)
            }
        }
        return
    }

    val pagerState = rememberPagerState(pageCount = { shorts.size })

    // Смена страницы: перезаряжаем плеер и отмечаем просмотр.
    LaunchedEffect(pagerState, shorts) {
        snapshotFlow { pagerState.currentPage }.collect { page ->
            val item = shorts.getOrNull(page) ?: return@collect
            val path = item.videoPath ?: return@collect
            player.setMediaItem(MediaItem.fromUri(android.net.Uri.fromFile(File(path))))
            player.prepare()
            player.volume = if (muted) 0f else 1f
            player.play()
            playing = true
            vm.markWatched(item.id)
        }
    }

    LaunchedEffect(Unit) { runCatching { focusRequester.requestFocus() } }

    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black)
            .focusRequester(focusRequester)
            .focusable()
            .onKeyEvent { event ->
                if (event.nativeKeyEvent.action != KeyEvent.ACTION_DOWN) return@onKeyEvent false
                when (event.nativeKeyEvent.keyCode) {
                    // Пультом лента прокручивается вверх-вниз.
                    KeyEvent.KEYCODE_DPAD_DOWN -> {
                        scope.launch {
                            if (pagerState.currentPage < shorts.lastIndex) {
                                pagerState.animateScrollToPage(pagerState.currentPage + 1)
                            }
                        }
                        true
                    }
                    KeyEvent.KEYCODE_DPAD_UP -> {
                        scope.launch {
                            if (pagerState.currentPage > 0) {
                                pagerState.animateScrollToPage(pagerState.currentPage - 1)
                            }
                        }
                        true
                    }
                    KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER,
                    KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> {
                        if (player.isPlaying) player.pause() else player.play()
                        playing = player.isPlaying
                        true
                    }
                    KeyEvent.KEYCODE_M -> {
                        muted = !muted
                        player.volume = if (muted) 0f else 1f
                        true
                    }
                    else -> false
                }
            }
    ) {
        VerticalPager(
            state = pagerState,
            modifier = Modifier.fillMaxSize()
        ) { page ->
            val item = shorts[page]
            Box(
                Modifier
                    .fillMaxSize()
                    .pointerInput(page) {
                        detectTapGestures(onTap = {
                            if (player.isPlaying) player.pause() else player.play()
                            playing = player.isPlaying
                        })
                    }
            ) {
                if (page == pagerState.currentPage) {
                    AndroidView(
                        factory = { ctx ->
                            PlayerView(ctx).apply {
                                this.player = player
                                useController = false
                                resizeMode = AspectRatioFrameLayout.RESIZE_MODE_ZOOM
                                setBackgroundColor(android.graphics.Color.BLACK)
                            }
                        },
                        update = { view -> view.player = player },
                        modifier = Modifier.fillMaxSize()
                    )
                }

                if (!playing && page == pagerState.currentPage) {
                    Icon(
                        Icons.Filled.PlayArrow,
                        contentDescription = null,
                        tint = Color.White.copy(alpha = 0.85f),
                        modifier = Modifier
                            .align(Alignment.Center)
                            .padding(8.dp)
                    )
                }

                // Подпись и действия поверх видео.
                Column(
                    Modifier
                        .align(Alignment.BottomStart)
                        .fillMaxWidth()
                        .background(Color(0x88000000))
                        .padding(12.dp)
                ) {
                    Text(
                        item.title,
                        color = Color.White,
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis
                    )
                    Text(
                        item.author,
                        color = Color.White.copy(alpha = 0.8f),
                        style = MaterialTheme.typography.bodySmall
                    )
                }

                Column(
                    Modifier
                        .align(Alignment.CenterEnd)
                        .padding(end = 8.dp)
                ) {
                    var favorite by remember(item.id) { mutableStateOf(vm.isFavorite(item.id)) }
                    IconButton(onClick = { favorite = vm.toggleFavorite(item.id) }) {
                        Icon(
                            if (favorite) Icons.Filled.Star else Icons.Outlined.StarBorder,
                            contentDescription = "Избранное",
                            tint = if (favorite) Color(0xFFFFD700) else Color.White
                        )
                    }
                    IconButton(onClick = {
                        muted = !muted
                        player.volume = if (muted) 0f else 1f
                    }) {
                        Icon(
                            if (muted) Icons.Filled.VolumeOff else Icons.Filled.VolumeUp,
                            contentDescription = "Звук",
                            tint = Color.White
                        )
                    }
                    IconButton(onClick = {
                        if (player.isPlaying) player.pause() else player.play()
                        playing = player.isPlaying
                    }) {
                        Icon(
                            if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                            contentDescription = "Пауза",
                            tint = Color.White
                        )
                    }
                }
            }
        }

        Row(
            Modifier
                .align(Alignment.TopStart)
                .fillMaxWidth()
                .padding(4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = onBack) {
                Icon(
                    Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "Назад",
                    tint = Color.White
                )
            }
            Text(
                "Shorts ${pagerState.currentPage + 1}/${shorts.size}",
                color = Color.White,
                style = MaterialTheme.typography.labelMedium
            )
        }
    }
}
