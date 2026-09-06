package io.github.kiramorano.localtube.ui.screens

import android.view.KeyEvent
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.PlaylistAdd
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.ClosedCaption
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.material.icons.filled.FullscreenExit
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.HighQuality
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PictureInPictureAlt
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.Forward10
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Subtitles
import androidx.compose.material.icons.filled.Theaters
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.filled.WatchLater
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.onKeyEvent
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import io.github.kiramorano.localtube.data.AudioEffects
import io.github.kiramorano.localtube.data.Ffmpeg
import io.github.kiramorano.localtube.data.PlaybackController
import io.github.kiramorano.localtube.data.PlaybackService
import io.github.kiramorano.localtube.ui.PipHelper
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.ui.components.SaveToCollectionDialog
import io.github.kiramorano.localtube.ui.components.VideoCard
import io.github.kiramorano.localtube.ui.components.formatDuration
import io.github.kiramorano.localtube.ui.theme.LocalIsTv
import io.github.kiramorano.localtube.ui.theme.LtRadius
import io.github.kiramorano.localtube.ui.theme.LtTap
import io.github.kiramorano.localtube.vm.PlayerViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File

private val speeds = listOf(0.5f, 0.75f, 1f, 1.25f, 1.5f, 2f)

/**
 * Поднимает сервис фонового воспроизведения.
 *
 * startForegroundService, а не startService: с API 26 обычный запуск сервиса из
 * свёрнутого приложения запрещён. Сам сервис переходит в передний план, показав
 * уведомление плеера, — это делает MediaSessionService.
 *
 * Ошибки глотаем: если система всё же откажет в запуске (жёсткие ограничения
 * фоновой активности у некоторых прошивок), терять экран плеера из-за этого
 * незачем — просто фон не заработает.
 */
private fun startPlaybackService(context: android.content.Context) {
    runCatching {
        val intent = android.content.Intent(context, PlaybackService::class.java)
        androidx.core.content.ContextCompat.startForegroundService(context, intent)
    }
}

/** Гасит сервис: уведомление плеера исчезает, общий плеер продолжает жить. */
private fun stopPlaybackService(context: android.content.Context) {
    runCatching {
        context.stopService(android.content.Intent(context, PlaybackService::class.java))
    }
}

@OptIn(UnstableApi::class)
@Composable
fun PlayerScreen(
    videoId: String,
    onBack: () -> Unit,
    onOpenVideo: (String) -> Unit,
    onOpenChannel: (String) -> Unit,
    /** Плейлист, из которого открыли видео: пусто — обычный просмотр. */
    collectionId: String = "",
    onOpenSubtitles: () -> Unit = {},
    vm: PlayerViewModel = viewModel()
) {
    val context = LocalContext.current
    val isTv = LocalIsTv.current
    val scope = rememberCoroutineScope()
    val lifecycleOwner = LocalLifecycleOwner.current

    var playing by remember { mutableStateOf(false) }
    var positionMs by remember { mutableLongStateOf(0L) }
    var durationMs by remember { mutableLongStateOf(0L) }
    var speedIndex by remember { mutableIntStateOf(2) }
    var muted by remember { mutableStateOf(false) }
    var volume by remember { mutableFloatStateOf(1f) }
    // rememberSaveable: полный экран выживает поворот и смену конфигурации.
    var fullscreen by rememberSaveable { mutableStateOf(false) }
    var controlsVisible by remember { mutableStateOf(true) }
    var subtitlesOn by remember { mutableStateOf(true) }
    var speedMenu by remember { mutableStateOf(false) }
    var seekFeedback by remember { mutableStateOf<String?>(null) }
    /** Пока пользователь тащит ползунок, показываем его позицию, а не плеера. */
    var dragFraction by remember { mutableStateOf<Float?>(null) }

    // Плеер общий с PlaybackService: сервис отдаёт системе тот же экземпляр,
    // поэтому фоновое воспроизведение продолжает начатое, а не запускает
    // вторую копию звука.
    val player = remember {
        PlaybackController.acquire(context).apply {
            playWhenReady = true
            repeatMode = Player.REPEAT_MODE_OFF
        }
    }
    val focusRequester = remember { FocusRequester() }

    var saveDialog by remember { mutableStateOf(false) }
    var qualityMenu by remember { mutableStateOf(false) }
    var eqDialog by remember { mutableStateOf(false) }
    var theater by rememberSaveable { mutableStateOf(false) }
    /** Размер кадра: нужен PiP, чтобы окно не растягивало видео. */
    var videoSize by remember { mutableStateOf(16 to 9) }

    val activity = context as? android.app.Activity
    val pipSupported = remember { PipHelper.isSupported(context) }
    // В режиме PiP окно размером со значок: элементы управления там не нужны,
    // а системные кнопки воспроизведения рисует сама оболочка.
    val inPip = activity?.isInPictureInPictureMode == true

    val eqPreset by vm.settings.equalizerPresetFlow.collectAsStateWithLifecycle()
    val bassBoost by vm.settings.bassBoostFlow.collectAsStateWithLifecycle()
    val backgroundPlayback by vm.settings.backgroundPlaybackFlow.collectAsStateWithLifecycle()
    val mediaTasks by vm.mediaTasks.collectAsStateWithLifecycle()

    /**
     * Эквалайзер привязан к аудиосессии плеера, поэтому создаётся здесь и
     * освобождается вместе с экраном: системный Equalizer — общий ресурс, и
     * незакрытый экземпляр не даёт другому приложению его получить.
     */
    val effects = remember(player.audioSessionId) {
        AudioEffects.Controller(player.audioSessionId)
    }
    DisposableEffect(effects) { onDispose { effects.release() } }
    LaunchedEffect(effects, eqPreset, bassBoost) {
        effects.apply(AudioEffects.Preset.from(eqPreset), bassBoost)
    }

    LaunchedEffect(videoId, collectionId) { vm.load(videoId, collectionId) }

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

    /**
     * Состояние воспроизведения приходит от плеера событием. Читать isPlaying
     * сразу после play() нельзя: плеер ещё буферизует и отвечает false, из-за
     * чего кнопка показывала не тот значок.
     *
     * Здесь же автопереход к следующему видео: настройка «автовоспроизведение»
     * существовала, но её никто не читал.
     */
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                playing = isPlaying
            }

            override fun onVideoSizeChanged(size: androidx.media3.common.VideoSize) {
                // Реальные пропорции: PiP с ними не добавляет чёрных полос.
                if (size.width > 0 && size.height > 0) videoSize = size.width to size.height
            }

            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_ENDED) {
                    // Дошли до конца: позицию не храним, иначе видео сразу
                    // откроется на последних секундах.
                    vm.savePosition(0, 0)
                    if (vm.settings.autoplayNext) {
                        scope.launch { vm.nextVideoId()?.let(onOpenVideo) }
                    }
                }
            }
        }
        player.addListener(listener)
        onDispose { player.removeListener(listener) }
    }

    // Опрос позиции: обновляет полосу прогресса.
    LaunchedEffect(player) {
        while (true) {
            positionMs = player.currentPosition.coerceAtLeast(0)
            durationMs = player.duration.takeIf { it > 0 } ?: 0
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

    // Фокус нужен и на телефоне: без него onKeyEvent не получает события с
    // клавиатуры и медиакнопок, а на ТВ пульт вообще не работал.
    LaunchedEffect(Unit) { runCatching { focusRequester.requestFocus() } }

    /**
     * Уход в фон: звук должен замолчать, а позиция сохраниться немедленно.
     * Раньше это делалось только в onDispose, а MainActivity объявляет
     * configChanges, поэтому при нажатии «Домой» композиция не пересоздавалась
     * и видео продолжало играть в фоне без всякого уведомления.
     */
    DisposableEffect(lifecycleOwner, backgroundPlayback) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_STOP -> {
                    vm.savePosition(player.currentPosition, player.duration.takeIf { it > 0 } ?: 0)
                    // Пауза только если фоновое воспроизведение выключено:
                    // с включённым звук должен продолжаться при сворачивании.
                    if (!backgroundPlayback) {
                        player.pause()
                        stopPlaybackService(context)
                    } else if (player.playWhenReady) {
                        // Сервис поднимаем в момент сворачивания, а не заранее:
                        // пока экран на переднем плане, уведомление плеера
                        // только занимает панель.
                        startPlaybackService(context)
                    }
                }
                // Вернулись на экран: уведомление больше не нужно, им управляет
                // сам экран.
                Lifecycle.Event.ON_START -> stopPlaybackService(context)
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    /**
     * Позиция сохраняется при уходе с экрана, чтобы вернуться на то же место.
     *
     * Плеер здесь не останавливаем вручную: PlaybackController освободит его
     * сам, когда уйдёт последний владелец, и воспроизведение прекратится. Явные
     * pause/clearMediaItems ломали переход между двумя видео — новый экран
     * компонуется раньше, чем разрушается старый, и остановка старого гасила
     * уже начатое новое видео.
     *
     * Если фоновое воспроизведение включено и сервис держит вторую ссылку,
     * плеер продолжит играть без экрана — этого и ждут от фонового режима.
     */
    DisposableEffect(Unit) {
        onDispose {
            vm.savePosition(player.currentPosition, player.duration.takeIf { it > 0 } ?: 0)
            PlaybackController.release()
        }
    }

    // В полном экране «Назад» выходит из него, а не закрывает плеер.
    BackHandler(enabled = fullscreen) { fullscreen = false }

    fun togglePlay() {
        // playWhenReady, а не isPlaying: значение применяется сразу, а фактическое
        // состояние придёт слушателем.
        player.playWhenReady = !player.playWhenReady
        controlsVisible = true
    }

    fun seekBy(deltaMs: Long) {
        val dur = player.duration
        // До готовности плеера длительность равна C.TIME_UNSET, и перемотка
        // прыгала в самое начало.
        if (dur <= 0) return
        val target = (player.currentPosition + deltaMs).coerceIn(0, dur)
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
            // focusable обязателен: без него requestFocus падает, а onKeyEvent
            // не получает ни одного нажатия.
            .focusable()
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
                    KeyEvent.KEYCODE_MEDIA_PLAY -> { player.playWhenReady = true; true }
                    KeyEvent.KEYCODE_MEDIA_PAUSE -> { player.playWhenReady = false; true }
                    KeyEvent.KEYCODE_MEDIA_NEXT -> {
                        scope.launch { vm.nextVideoId()?.let(onOpenVideo) }; true
                    }
                    // Кнопки пульта, а не клавиатурные M и F: на ТВ-пульте таких
                    // клавиш нет, и звук с полным экраном были доступны лишь
                    // касанием.
                    KeyEvent.KEYCODE_MUTE, KeyEvent.KEYCODE_VOLUME_MUTE, KeyEvent.KEYCODE_M -> {
                        setMuted(!muted); true
                    }
                    KeyEvent.KEYCODE_INFO, KeyEvent.KEYCODE_F -> {
                        fullscreen = !fullscreen; true
                    }
                    KeyEvent.KEYCODE_CAPTIONS -> {
                        if (vm.subtitlePaths.isNotEmpty()) { toggleSubtitles(); true } else false
                    }
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
                // Отвязываем view от плеера при уходе с экрана.
                onRelease = { it.player = null },
                modifier = Modifier.fillMaxSize()
            )

            if (vm.loading) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    LoadingBox()
                }
            }

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

            if (controlsVisible && !inPip) {
                // Верхняя строка: назад и название.
                Row(
                    Modifier
                        .align(Alignment.TopStart)
                        .fillMaxWidth()
                        .background(Color(0x66000000))
                        .padding(4.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(onClick = { if (fullscreen) fullscreen = false else onBack() }) {
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
                        value = dragFraction
                            ?: if (durationMs > 0) positionMs.toFloat() / durationMs else 0f,
                        // Во время перетаскивания только запоминаем позицию:
                        // прежний вариант дёргал seekTo на каждый пиксель, и
                        // ползунок прыгал, споря с опросом плеера.
                        onValueChange = { fraction -> dragFraction = fraction },
                        onValueChangeFinished = {
                            val fraction = dragFraction ?: return@Slider
                            dragFraction = null
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
                                if (muted) Icons.AutoMirrored.Filled.VolumeOff
                                else Icons.AutoMirrored.Filled.VolumeUp,
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
                        if (pipSupported) {
                            IconButton(onClick = {
                                PipHelper.enter(activity, videoSize.first, videoSize.second)
                            }) {
                                Icon(
                                    Icons.Filled.PictureInPictureAlt,
                                    contentDescription = "Картинка в картинке",
                                    tint = Color.White
                                )
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

        // В PiP под видео места нет: список рекомендаций там только съедал бы
        // кадр, ради которого режим и включают.
        if (!fullscreen && !inPip) {
            if (!vm.loading && vm.video == null) {
                // Видео пропало из библиотеки: раньше это сообщение рисовалось
                // поверх плеера и появлялось на каждом первом кадре.
                EmptyBox("Видео не найдено")
                return@Column
            }
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
                            // Переход на канал: на палец приходилась высота
                            // одной строки, около 20dp. Рядом стоит IconButton
                            // на 48dp, из-за чего промах по имени попадал в
                            // соседнюю кнопку «Избранное».
                            Text(
                                vm.video?.author.orEmpty(),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier
                                    .weight(1f)
                                    .clip(RoundedCornerShape(LtRadius.sm))
                                    .clickable { vm.video?.author?.let(onOpenChannel) }
                                    .defaultMinSize(minHeight = LtTap.min)
                                    .wrapContentHeight(Alignment.CenterVertically)
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
                            IconButton(onClick = { vm.toggleWatchLater() }) {
                                Icon(
                                    Icons.Filled.WatchLater,
                                    contentDescription = "Смотреть позже",
                                    tint = if (vm.inWatchLater) MaterialTheme.colorScheme.primary
                                    else MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            IconButton(onClick = { saveDialog = true }) {
                                Icon(
                                    Icons.AutoMirrored.Filled.PlaylistAdd,
                                    contentDescription = "Сохранить в плейлист"
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

                        // Плашка плейлиста: пользователь должен понимать, что
                        // «следующее видео» ведёт по списку, а не по библиотеке.
                        if (vm.collectionTitle.isNotBlank()) {
                            Text(
                                "Плейлист: ${vm.collectionTitle}",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.padding(top = 6.dp)
                            )
                        }

                        PlayerActions(
                            qualities = vm.localQualities(),
                            activeQuality = vm.activeQuality,
                            qualityMenuOpen = qualityMenu,
                            onQualityMenu = { qualityMenu = it },
                            onSelectQuality = { q ->
                                // Позиция сохраняется до смены файла: плеер
                                // начинает новую дорожку с нуля.
                                val at = player.currentPosition
                                vm.selectQuality(q)
                                scope.launch {
                                    // Ждём подготовки нового файла, иначе seekTo
                                    // уходит в ещё не загруженную дорожку.
                                    delay(300)
                                    if (at > 0) player.seekTo(at)
                                }
                            },
                            onConvert = { preset -> vm.convert(preset) },
                            onDeleteQuality = { q -> vm.deleteQuality(q) },
                            ffmpegAvailable = vm.ffmpegAvailable(),
                            audioReady = vm.audioPath() != null,
                            onExtractAudio = { vm.extractAudio() },
                            onOpenEqualizer = { eqDialog = true },
                            eqActive = eqPreset != AudioEffects.Preset.OFF.id || bassBoost > 0,
                            theater = theater,
                            onToggleTheater = { theater = !theater },
                            subtitleCount = vm.subtitlePaths.size,
                            onOpenSubtitles = onOpenSubtitles
                        )

                        // Задачи ffmpeg: конвертация идёт минутами, и без
                        // индикатора кнопка выглядела бы «не сработавшей».
                        mediaTasks
                            .filter { it.videoId == (vm.video?.id ?: "") }
                            .forEach { task ->
                                MediaTaskRow(
                                    task = task,
                                    onCancel = { vm.cancelMediaTask(task.id) },
                                    onDismiss = { vm.dismissMediaTask(task.id) }
                                )
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
                // В театральном режиме рекомендации скрыты: в вебе .theater-mode
                // тоже освобождает всё место под видео.
                if (vm.recommended.isNotEmpty() && !theater) {
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

    if (saveDialog) {
        SaveToCollectionDialog(
            videoId = vm.video?.id.orEmpty(),
            onDismiss = { saveDialog = false }
        )
    }

    if (eqDialog) {
        EqualizerDialog(
            preset = eqPreset,
            bassBoost = bassBoost,
            available = effects.available,
            onPreset = { vm.settings.equalizerPreset = it },
            onBassBoost = { vm.settings.bassBoost = it },
            onDismiss = { eqDialog = false }
        )
    }
}

/**
 * Кнопки под видео: локальное качество, MP3, эквалайзер и театральный режим.
 * Вынесено в отдельную функцию — тело PlayerScreen и без того длинное.
 */
@Composable
private fun PlayerActions(
    qualities: List<String>,
    activeQuality: String,
    qualityMenuOpen: Boolean,
    onQualityMenu: (Boolean) -> Unit,
    onSelectQuality: (String) -> Unit,
    onConvert: (Ffmpeg.Preset) -> Unit,
    onDeleteQuality: (String) -> Unit,
    ffmpegAvailable: Boolean,
    audioReady: Boolean,
    onExtractAudio: () -> Unit,
    onOpenEqualizer: () -> Unit,
    eqActive: Boolean,
    theater: Boolean,
    onToggleTheater: () -> Unit,
    subtitleCount: Int,
    onOpenSubtitles: () -> Unit
) {
    Row(
        Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(top = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box {
            AssistChip(
                onClick = { onQualityMenu(true) },
                label = {
                    Text(if (activeQuality.isBlank()) "Качество" else "${activeQuality}p")
                },
                leadingIcon = { Icon(Icons.Filled.HighQuality, contentDescription = null) }
            )
            DropdownMenu(expanded = qualityMenuOpen, onDismissRequest = { onQualityMenu(false) }) {
                DropdownMenuItem(
                    text = { Text("Оригинал" + if (activeQuality.isBlank()) "  ✓" else "") },
                    onClick = { onQualityMenu(false); onSelectQuality("") }
                )
                qualities.forEach { q ->
                    DropdownMenuItem(
                        text = { Text("${q}p" + if (activeQuality == q) "  ✓" else "") },
                        onClick = { onQualityMenu(false); onSelectQuality(q) },
                        trailingIcon = {
                            IconButton(onClick = { onQualityMenu(false); onDeleteQuality(q) }) {
                                Icon(Icons.Filled.Delete, contentDescription = "Удалить вариант")
                            }
                        }
                    )
                }
                if (ffmpegAvailable) {
                    HorizontalDivider()
                    // Пресеты, для которых файла ещё нет: повторно
                    // конвертировать в уже готовое качество незачем.
                    Ffmpeg.Preset.entries
                        .filterNot { qualities.contains(it.id) }
                        .forEach { preset ->
                            DropdownMenuItem(
                                text = { Text("Создать: ${preset.label}") },
                                onClick = { onQualityMenu(false); onConvert(preset) }
                            )
                        }
                }
            }
        }
        Spacer(Modifier.width(8.dp))
        if (ffmpegAvailable) {
            AssistChip(
                onClick = onExtractAudio,
                label = { Text(if (audioReady) "MP3 готов" else "Извлечь MP3") },
                leadingIcon = { Icon(Icons.Filled.MusicNote, contentDescription = null) }
            )
            Spacer(Modifier.width(8.dp))
        }
        AssistChip(
            onClick = onOpenEqualizer,
            label = { Text(if (eqActive) "Эквалайзер вкл." else "Эквалайзер") },
            leadingIcon = { Icon(Icons.Filled.GraphicEq, contentDescription = null) }
        )
        Spacer(Modifier.width(8.dp))
        AssistChip(
            onClick = onToggleTheater,
            label = { Text(if (theater) "Обычный вид" else "Театр") },
            leadingIcon = { Icon(Icons.Filled.Theaters, contentDescription = null) }
        )
        Spacer(Modifier.width(8.dp))
        AssistChip(
            onClick = onOpenSubtitles,
            label = {
                Text(if (subtitleCount > 0) "Субтитры ($subtitleCount)" else "Субтитры")
            },
            leadingIcon = { Icon(Icons.Filled.Subtitles, contentDescription = null) }
        )
    }
}

/** Прогресс задачи ffmpeg с возможностью отмены. */
@Composable
private fun MediaTaskRow(
    task: io.github.kiramorano.localtube.data.MediaTask,
    onCancel: () -> Unit,
    onDismiss: () -> Unit
) {
    val finished = task.done || task.error != null
    Column(Modifier.fillMaxWidth().padding(top = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                task.error ?: task.message.ifBlank { "Обработка..." },
                style = MaterialTheme.typography.labelMedium,
                color = if (task.error != null) MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f)
            )
            TextButton(onClick = if (finished) onDismiss else onCancel) {
                Text(if (finished) "Скрыть" else "Отменить")
            }
        }
        if (!finished) {
            LinearProgressIndicator(
                progress = { task.progress.coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

/**
 * Эквалайзер: пресеты и усиление басов. Значения хранятся в настройках, поэтому
 * применяются и к следующему видео, как в веб-версии.
 */
@Composable
private fun EqualizerDialog(
    preset: String,
    bassBoost: Int,
    available: Boolean,
    onPreset: (String) -> Unit,
    onBassBoost: (Int) -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Эквалайзер") },
        text = {
            Column {
                if (!available) {
                    // Часть устройств не отдаёт системный эквалайзер: честнее
                    // сказать об этом, чем показывать нерабочие переключатели.
                    Text(
                        "Устройство не предоставило эквалайзер. Настройки сохранятся, но звук не изменится.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(bottom = 8.dp)
                    )
                }
                AudioEffects.Preset.entries.forEach { p ->
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable { onPreset(p.id) }
                            .padding(vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        RadioButton(selected = preset == p.id, onClick = { onPreset(p.id) })
                        Text(p.label, modifier = Modifier.padding(start = 4.dp))
                    }
                }
                HorizontalDivider(Modifier.padding(vertical = 6.dp))
                Text("Усиление басов: ${bassBoost / 10}%", style = MaterialTheme.typography.labelMedium)
                Slider(
                    value = bassBoost.toFloat(),
                    onValueChange = { onBassBoost(it.toInt()) },
                    valueRange = 0f..1000f
                )
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Готово") } }
    )
}
