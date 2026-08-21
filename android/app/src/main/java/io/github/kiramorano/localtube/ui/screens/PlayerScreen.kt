package io.github.kiramorano.localtube.ui.screens

import android.view.KeyEvent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ClosedCaption
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.material.icons.filled.FullscreenExit
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.Forward10
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.filled.VolumeOff
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.onKeyEvent
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.ui.components.VideoCard
import io.github.kiramorano.localtube.ui.components.formatDuration
import io.github.kiramorano.localtube.ui.theme.LocalIsTv
import io.github.kiramorano.localtube.vm.PlayerViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File

private val speeds = listOf(0.5f, 0.75f, 1f, 1.25f, 1.5f, 2f)

@OptIn(UnstableApi::class)
@Composable
fun PlayerScreen(
    videoId: String,
    onBack: () -> Unit,
    onOpenVideo: (String) -> Unit,
    onOpenChannel: (String) -> Unit,
    vm: PlayerViewModel = viewModel()
) {
    val context = LocalContext.current
    val isTv = LocalIsTv.current
    val scope = rememberCoroutineScope()

    var playing by remember { mutableStateOf(true) }
    var positionMs by remember { mutableLongStateOf(0L) }
    var durationMs by remember { mutableLongStateOf(0L) }
    var bufferedMs by remember { mutableLongStateOf(0L) }
    var speedIndex by remember { mutableStateOf(2) }
    var muted by remember { mutableStateOf(false) }
    var volume by remember { mutableFloatStateOf(1f) }
    var fullscreen by remember { mutableStateOf(false) }
    var controlsVisible by remember { mutableStateOf(true) }
    var subtitlesOn by remember { mutableStateOf(true) }
    var speedMenu by remember { mutableStateOf(false) }
    var seekFeedback by remember { mutableStateOf<String?>(null) }

    val player = remember {
        ExoPlayer.Builder(context).build().apply {
            playWhenReady = true
            repeatMode = Player.REPEAT_MODE_OFF
        }
    }
    val focusRequester = remember { FocusRequester() }

    LaunchedEffect(videoId) { vm.load(videoId) }

    // Загружаем дорожку и субтитры, когда путь известен.
    LaunchedEffect(vm.videoPath, vm.subtitlePaths) {
        val path = vm.videoPath ?: return@LaunchedEffect
        val subtitles = vm.subtitlePaths.map { sub ->
            MediaItem.SubtitleConfiguration.Builder(android.net.Uri.fromFile(File(sub)))
                .setMimeType(MimeTypes.TEXT_VTT)
                .setLanguage(File(sub).nameWithoutExtension)
                .setSelectionFlags(C.SELECTION_FLAG_DEFAULT)
                .build()
        }
        val item = MediaItem.Builder()
            .setUri(android.net.Uri.fromFile(File(path)))
            .setSubtitleConfigurations(subtitles)
            .build()
        player.setMediaItem(item)
        player.prepare()
        // Возобновление с сохранённой позиции.
        if (vm.startPositionMs > 0) player.seekTo(vm.startPositionMs)
        player.play()
    }

    // Опрос позиции: обновляет полосу прогресса и сохраняет место просмотра.
    LaunchedEffect(player) {
        while (true) {
            positionMs = player.currentPosition.coerceAtLeast(0)
            durationMs = player.duration.takeIf { it > 0 } ?: 0
            bufferedMs = player.bufferedPosition.coerceAtLeast(0)
            playing = player.isPlaying
            delay(500)
        }
    }

    // Автоскрытие управления во время воспроизведения.
    LaunchedEffect(controlsVisible, playing) {
        if (controlsVisible && playing) {
            delay(3500)
            controlsVisible = false
        }
    }

    LaunchedEffect(seekFeedback) {
        if (seekFeedback != null) {
            delay(700)
            seekFeedback = null
        }
    }

    if (isTv) {
        LaunchedEffect(Unit) { runCatching { focusRequester.requestFocus() } }
    }

    // Позиция сохраняется при уходе с экрана, чтобы вернуться на то же место.
    DisposableEffect(Unit) {
        onDispose {
            vm.savePosition(player.currentPosition, player.duration.takeIf { it > 0 } ?: 0)
            player.release()
        }
    }

    fun togglePlay() {
        if (player.isPlaying) player.pause() else player.play()
        playing = player.isPlaying
        controlsVisible = true
    }

    fun seekBy(deltaMs: Long) {
        val target = (player.currentPosition + deltaMs).coerceIn(0, player.duration.coerceAtLeast(0))
        player.seekTo(target)
        positionMs = target
        seekFeedback = if (deltaMs > 0) "+${deltaMs / 1000} сек" else "${deltaMs / 1000} сек"
        controlsVisible = true
    }

    fun applySpeed(index: Int) {
        speedIndex = index
        player.playbackParameters = PlaybackParameters(speeds[index])
    }

    fun setMuted(value: Boolean) {
        muted = value
        player.volume = if (value) 0f else volume
    }

    fun toggleSubtitles() {
        subtitlesOn = !subtitlesOn
        player.trackSelectionParameters = player.trackSelectionParameters
            .buildUpon()
            .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, !subtitlesOn)
            .build()
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            // Пульт: центральная кнопка — пауза, влево-вправо — перемотка.
            .focusRequester(focusRequester)
            .onKeyEvent { event ->
                if (event.nativeKeyEvent.action != KeyEvent.ACTION_DOWN) return@onKeyEvent false
                when (event.nativeKeyEvent.keyCode) {
                    KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER,
                    KeyEvent.KEYCODE_SPACE, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> {
                        togglePlay(); true
                    }
                    KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_MEDIA_REWIND -> {
                        seekBy(-10_000); true
                    }
                    KeyEvent.KEYCODE_DPAD_RIGHT, KeyEvent.KEYCODE_MEDIA_FAST_FORWARD -> {
                        seekBy(10_000); true
                    }
                    KeyEvent.KEYCODE_MEDIA_PLAY -> { player.play(); true }
                    KeyEvent.KEYCODE_MEDIA_PAUSE -> { player.pause(); true }
                    KeyEvent.KEYCODE_M -> { setMuted(!muted); true }
                    KeyEvent.KEYCODE_F -> { fullscreen = !fullscreen; true }
                    else -> false
                }
            }
    ) {
        Box(
            Modifier
                .fillMaxWidth()
                .then(
                    if (fullscreen) Modifier.fillMaxHeight()
                    else Modifier.aspectRatio(16f / 9f)
                )
                .background(Color.Black)
                .pointerInput(Unit) {
                    detectTapGestures(
                        onTap = { controlsVisible = !controlsVisible },
                        onDoubleTap = { offset ->
                            // Двойное касание слева и справа — перемотка на 10 секунд.
                            if (offset.x < size.width / 3f) seekBy(-10_000)
                            else if (offset.x > size.width * 2f / 3f) seekBy(10_000)
                            else togglePlay()
                        }
                    )
                }
        ) {
            AndroidView(
                factory = { ctx ->
                    PlayerView(ctx).apply {
                        this.player = player
                        useController = false
                        resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
                    }
                },
                modifier = Modifier.fillMaxSize()
            )

            seekFeedback?.let { text ->
                Text(
                    text,
                    color = Color.White,
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier
                        .align(Alignment.Center)
                        .background(Color(0x99000000), RoundedCornerShape(8.dp))
                        .padding(horizontal = 14.dp, vertical = 8.dp)
                )
            }

            if (controlsVisible) {
                // Верхняя строка: назад и название.
                Row(
                    Modifier
                        .align(Alignment.TopStart)
                        .fillMaxWidth()
                        .background(Color(0x66000000))
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
                        vm.video?.title.orEmpty(),
                        color = Color.White,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f)
                    )
                }

                Column(
                    Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .background(Color(0x99000000))
                        .padding(horizontal = 8.dp, vertical = 4.dp)
                ) {
                    Slider(
                        value = if (durationMs > 0) positionMs.toFloat() / durationMs else 0f,
                        onValueChange = { fraction ->
                            if (durationMs > 0) {
                                val target = (fraction * durationMs).toLong()
                                player.seekTo(target)
                                positionMs = target
                            }
                        },
                        modifier = Modifier.fillMaxWidth()
                    )
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconButton(onClick = { togglePlay() }) {
                            Icon(
                                if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                                contentDescription = if (playing) "Пауза" else "Играть",
                                tint = Color.White
                            )
                        }
                        IconButton(onClick = { seekBy(-10_000) }) {
                            Icon(Icons.Filled.Replay10, contentDescription = "Назад 10 секунд", tint = Color.White)
                        }
                        IconButton(onClick = { seekBy(10_000) }) {
                            Icon(Icons.Filled.Forward10, contentDescription = "Вперёд 10 секунд", tint = Color.White)
                        }
                        Text(
                            "${formatDuration(positionMs / 1000)} / ${formatDuration(durationMs / 1000)}",
                            color = Color.White,
                            style = MaterialTheme.typography.labelMedium,
                            modifier = Modifier.padding(horizontal = 6.dp)
                        )
                        Box(Modifier.weight(1f))
                        IconButton(onClick = { setMuted(!muted) }) {
                            Icon(
                                if (muted) Icons.Filled.VolumeOff else Icons.Filled.VolumeUp,
                                contentDescription = "Звук",
                                tint = Color.White
                            )
                        }
                        if (vm.subtitlePaths.isNotEmpty()) {
                            IconButton(onClick = { toggleSubtitles() }) {
                                Icon(
                                    Icons.Filled.ClosedCaption,
                                    contentDescription = "Субтитры",
                                    tint = if (subtitlesOn) MaterialTheme.colorScheme.primary else Color.White
                                )
                            }
                        }
                        Box {
                            IconButton(onClick = { speedMenu = true }) {
                                Icon(Icons.Filled.Speed, contentDescription = "Скорость", tint = Color.White)
                            }
                            DropdownMenu(expanded = speedMenu, onDismissRequest = { speedMenu = false }) {
                                speeds.forEachIndexed { i, s ->
                                    DropdownMenuItem(
                                        text = { Text("${s}x" + if (i == speedIndex) "  ✓" else "") },
                                        onClick = { speedMenu = false; applySpeed(i) }
                                    )
                                }
                            }
                        }
                        IconButton(onClick = { fullscreen = !fullscreen }) {
                            Icon(
                                if (fullscreen) Icons.Filled.FullscreenExit else Icons.Filled.Fullscreen,
                                contentDescription = "Полный экран",
                                tint = Color.White
                            )
                        }
                    }
                }
            }
        }

        if (!fullscreen) {
            LazyColumn(Modifier.fillMaxSize()) {
                item {
                    Column(Modifier.padding(14.dp)) {
                        Text(
                            vm.video?.title.orEmpty(),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold
                        )
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .padding(top = 8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                vm.video?.author.orEmpty(),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier
                                    .weight(1f)
                                    .clickable { vm.video?.author?.let(onOpenChannel) }
                            )
                            IconButton(onClick = { vm.toggleFavorite() }) {
                                Icon(
                                    if (vm.isFavorite) Icons.Filled.Star else Icons.Outlined.StarBorder,
                                    contentDescription = "Избранное",
                                    tint = if (vm.isFavorite) Color(0xFFFFD700)
                                    else MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            IconButton(onClick = { vm.toggleChannelHidden() }) {
                                Icon(
                                    Icons.Filled.VisibilityOff,
                                    contentDescription = "Скрыть канал",
                                    tint = if (vm.channelHidden) MaterialTheme.colorScheme.primary
                                    else MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            IconButton(onClick = {
                                scope.launch {
                                    vm.nextVideoId()?.let(onOpenVideo)
                                }
                            }) {
                                Icon(Icons.Filled.SkipNext, contentDescription = "Следующее видео")
                            }
                        }
                        if (!vm.video?.description.isNullOrBlank()) {
                            Text(
                                vm.video?.description.orEmpty(),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(top = 10.dp),
                                maxLines = 6,
                                overflow = TextOverflow.Ellipsis
                            )
                        }
                    }
                }
                if (vm.recommended.isNotEmpty()) {
                    item {
                        Text(
                            "Рекомендации",
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp)
                        )
                    }
                    items(vm.recommended, key = { it.id }) { rec ->
                        Box(Modifier.padding(horizontal = 12.dp, vertical = 4.dp)) {
                            VideoCard(v = rec, onClick = { onOpenVideo(rec.id) })
                        }
                    }
                }
            }
        }
    }

    if (vm.video == null && vm.videoPath == null) {
        EmptyBox("Видео не найдено")
    }
}
