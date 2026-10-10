package io.github.kiramorano.localtube.vm

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.kiramorano.localtube.LocalTubeApp
import io.github.kiramorano.localtube.data.Catalog
import io.github.kiramorano.localtube.data.CatalogSort
import io.github.kiramorano.localtube.data.ChannelAssets
import io.github.kiramorano.localtube.data.CollectionResult
import io.github.kiramorano.localtube.data.DownloadTask
import io.github.kiramorano.localtube.data.Engine
import io.github.kiramorano.localtube.data.Ffmpeg
import io.github.kiramorano.localtube.data.FormatOption
import io.github.kiramorano.localtube.data.LanSharing
import io.github.kiramorano.localtube.data.MediaTask
import io.github.kiramorano.localtube.data.Playlist
import io.github.kiramorano.localtube.data.RemoteEntry
import io.github.kiramorano.localtube.data.SubtitleState
import io.github.kiramorano.localtube.data.SubtitleTrack
import io.github.kiramorano.localtube.data.SyncState
import io.github.kiramorano.localtube.data.TaskPriority
import io.github.kiramorano.localtube.data.UrlKind
import io.github.kiramorano.localtube.data.UserData
import io.github.kiramorano.localtube.data.VideoCollection
import io.github.kiramorano.localtube.data.VideoItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

private fun repo(app: Application) = LocalTubeApp.from(app).repository

/** Применяет выбранную сортировку к списку видео. */
internal fun List<VideoItem>.sortedBy(sort: CatalogSort): List<VideoItem> = when (sort) {
    CatalogSort.NEWEST -> sortedByDescending { it.sortKey }
    CatalogSort.OLDEST -> sortedBy { it.sortKey }
    CatalogSort.TITLE -> sortedBy { it.title.lowercase() }
    CatalogSort.SIZE -> sortedByDescending { it.sizeMb }
    CatalogSort.RANDOM -> shuffled()
}

class HomeViewModel(app: Application) : AndroidViewModel(app) {
    var catalog by mutableStateOf<Catalog?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    private var loadJob: Job? = null

    val userData: StateFlow<UserData> = repo(app).userData.data
    val libraryVersion: StateFlow<Long> = repo(app).downloads.libraryVersion
    val settings = repo(app).settings

    /** Сканирование идёт в IO: раньше оно выполнялось на главном потоке. */
    fun load(force: Boolean = false) {
        // Повторные вызовы не плодят параллельные сканирования: экран и сайдбар
        // просят каталог одновременно.
        if (loadJob?.isActive == true && !force) return
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            loading = true
            try {
                val lib = repo(getApplication()).library
                val scanned = withContext(Dispatchers.IO) {
                    if (force) lib.scan() else lib.catalog()
                }
                catalog = scanned
            } finally {
                loading = false
            }
        }
    }

    /** Каталог без скрытых каналов и с применённой сортировкой. */
    fun visible(catalog: Catalog, hidden: List<String>, sort: CatalogSort): Catalog {
        val hiddenSet = hidden.toSet()
        return catalog.copy(
            videos = catalog.videos.filterNot { hiddenSet.contains(it.author) }.sortedBy(sort),
            shorts = catalog.shorts.filterNot { hiddenSet.contains(it.author) }.sortedBy(sort),
            authors = catalog.authors.filterNot { hiddenSet.contains(it.name) }
        )
    }

    fun favorites(catalog: Catalog, ids: List<String>): List<VideoItem> {
        val all = catalog.videos + catalog.shorts + catalog.userVideos
        // Порядок как в избранном, а не как в каталоге.
        return ids.mapNotNull { id -> all.firstOrNull { it.id == id } }
    }

    fun history(catalog: Catalog, ids: List<String>): List<VideoItem> {
        val all = catalog.videos + catalog.shorts + catalog.userVideos
        return ids.mapNotNull { id -> all.firstOrNull { it.id == id } }
    }

    fun toggleFavorite(id: String) = repo(getApplication()).userData.toggleFavorite(id)

    fun setChannelHidden(author: String, hidden: Boolean) =
        repo(getApplication()).userData.setChannelHidden(author, hidden)

    /** Очистка списков: раньше экраны ради этого создавали SettingsViewModel,
     *  а его init обходил всю библиотеку ради размера на диске. */
    fun clearFavorites() = repo(getApplication()).userData.clearFavorites()

    fun clearHistory() = repo(getApplication()).userData.clearHistory()

    fun setSort(sort: CatalogSort) {
        settings.sort = sort
    }

    fun delete(v: VideoItem) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                if (v.source == "user") repo(getApplication()).library.deleteUserVideo(v.id)
                else repo(getApplication()).library.deleteVideo(v)
            }
            load(force = true)
        }
    }
}

class ChannelViewModel(app: Application) : AndroidViewModel(app) {
    var author by mutableStateOf("")
        private set
    private var assetsJob: Job? = null
    var videos by mutableStateOf<List<VideoItem>>(emptyList())
        private set
    var shorts by mutableStateOf<List<VideoItem>>(emptyList())
        private set
    var avatar by mutableStateOf<String?>(null)
        private set
    var banner by mutableStateOf<String?>(null)
        private set
    /** Метаданные канала: описание и число подписчиков, как на ПК. */
    var meta by mutableStateOf<ChannelAssets?>(null)
        private set
    var loading by mutableStateOf(false)
        private set

    val userData: StateFlow<UserData> = repo(app).userData.data
    val syncStates: StateFlow<Map<String, SyncState>> = repo(app).channels.states

    fun load(name: String) {
        author = name
        // Отписываемся от старого канала: событие того — не должно перезаписать
        // показанное сейчас.
        assetsJob?.cancel()
        viewModelScope.launch {
            loading = true
            try {
                val lib = repo(getApplication()).library
                val all = withContext(Dispatchers.IO) { lib.videosOf(name) }
                videos = all.filterNot { it.isShort }
                shorts = all.filter { it.isShort }
                avatar = withContext(Dispatchers.IO) { lib.avatarFor(name) }
                banner = withContext(Dispatchers.IO) { lib.bannerFor(name) }
                meta = withContext(Dispatchers.IO) { lib.channelMeta(name) }
            } finally {
                loading = false
            }
        }
        // Подписка на обновление оформления: без неё экран держит старую
        // аватарку и описание до перезахода, хотя они уже скачаны на диск.
        assetsJob = viewModelScope.launch {
            repo(getApplication()).channels.assetsUpdated
                .filter { it == name }
                .collectLatest {
                    val lib = repo(getApplication()).library
                    meta = withContext(Dispatchers.IO) { lib.channelMeta(name) }
                }
        }
    }

    fun isHidden(): Boolean = repo(getApplication()).userData.isChannelHidden(author)

    fun toggleHidden(): Boolean = repo(getApplication()).userData.toggleChannelHidden(author)

    /** Звёздочка на карточке канала: без этого на странице канала её не было. */
    fun toggleFavorite(id: String) = repo(getApplication()).userData.toggleFavorite(id)

    // ---------- синхронизация ----------

    fun syncState(): SyncState = repo(getApplication()).channels.state(author)

    /** Ищет на канале видео, которых нет на диске. */
    fun scan() = repo(getApplication()).channels.scan(author)

    fun toggleMissing(videoId: String) = repo(getApplication()).channels.toggle(author, videoId)

    fun setAllMissing(selected: Boolean) =
        repo(getApplication()).channels.setAllSelected(author, selected)

    /** Ставит отмеченные видео в очередь загрузок. */
    fun queueSelected(
        formatId: String = "best",
        mergeFormat: String = Engine.DEFAULT_MERGE_FORMAT
    ): Int = repo(getApplication()).channels.queueSelected(
        author, formatId, TaskPriority.NORMAL, mergeFormat
    )

    fun clearSync() = repo(getApplication()).channels.clear(author)

    /** Обновляет аватар, баннер и описание канала. */
    fun refreshAssets() {
        repo(getApplication()).channels.fetchAssets(author)
        // Перечитываем через паузу: скачивание идёт в своей области, и сразу
        // после вызова файлов на диске ещё нет.
        viewModelScope.launch {
            delay(3000)
            load(author)
        }
    }

    /** Адрес канала: без него синхронизация невозможна, и кнопку надо гасить. */
    fun channelUrl(): String? = repo(getApplication()).library.channelUrlOf(author)
}

class SearchViewModel(app: Application) : AndroidViewModel(app) {
    var query by mutableStateOf("")
        private set
    var results by mutableStateOf<List<VideoItem>?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    private var job: Job? = null

    val userData: StateFlow<UserData> = repo(app).userData.data

    fun onQuery(q: String) {
        query = q
        job?.cancel()
        if (q.isBlank()) {
            results = null
            return
        }
        job = viewModelScope.launch {
            delay(300)
            loading = true
            val hidden = repo(getApplication()).userData.current.hiddenChannels.toSet()
            results = withContext(Dispatchers.IO) {
                repo(getApplication()).library.search(q).filterNot { hidden.contains(it.author) }
            }
            loading = false
        }
    }

    fun reload() {
        if (query.isNotBlank()) onQuery(query)
    }

    fun toggleFavorite(id: String) = repo(getApplication()).userData.toggleFavorite(id)
}

class DownloadsViewModel(app: Application) : AndroidViewModel(app) {
    val tasks: StateFlow<List<DownloadTask>> = repo(app).downloads.tasks
    val paused: StateFlow<Boolean> = repo(app).downloads.paused

    var formats by mutableStateOf<List<FormatOption>?>(null)
        private set
    var infoTitle by mutableStateOf<String?>(null)
        private set
    var fetching by mutableStateOf(false)
        private set
    var fetchError by mutableStateOf<String?>(null)
        private set
    var started by mutableStateOf<String?>(null)
        private set
    var phase by mutableStateOf<String?>(null)
        private set
    var priority by mutableStateOf(TaskPriority.NORMAL)
    private var lastSubLangs: List<String> = emptyList()

    /** Ссылка, к которой относятся полученные форматы. */
    var fetchedUrl by mutableStateOf<String?>(null)
        private set

    /**
     * Ролики профиля TikTok, развёрнутые в список.
     *
     * Профиль нельзя качать одной задачей: `--no-playlist` отдал бы только
     * обложку ленты. Как на сервере (app.py expand_download_urls), сначала
     * получаем плоский список, потом ставим каждый ролик в очередь.
     */
    var profileEntries by mutableStateOf<List<RemoteEntry>?>(null)
        private set

    fun fetch(url: String) {
        if (fetching || url.isBlank()) return
        val target = url.trim()
        // Проверка до запуска движка: иначе ожидание сети кончается невнятным
        // отказом yt-dlp, хотя причина видна по самой ссылке.
        if (!UrlKind.isSupported(target)) {
            fetchError = UrlKind.UNSUPPORTED_MESSAGE
            formats = null
            infoTitle = null
            profileEntries = null
            return
        }
        viewModelScope.launch {
            fetching = true
            fetchError = null
            formats = null
            infoTitle = null
            started = null
            fetchedUrl = null
            profileEntries = null
            phase = "Проверка yt-dlp..."
            try {
                val app = getApplication<Application>()
                if (!Engine.ensureYtDlpFresh(app, Engine.appVersion(app))) {
                    phase = "yt-dlp не удалось обновить, пробую встроенную версию..."
                }
                val settings = repo(app).settings
                if (UrlKind.isProfile(target)) {
                    phase = "Читаю профиль TikTok..."
                    val listing = Engine.listChannel(
                        channelUrl = target,
                        processId = "fetch_tt_${System.currentTimeMillis()}",
                        cookiesPath = repo(app).library.cookiesPath(),
                        playerClient = settings.playerClient
                    )
                    if (listing.entries.isEmpty()) {
                        throw RuntimeException("TikTok не вернул ролики профиля")
                    }
                    profileEntries = listing.entries
                    infoTitle = listing.title.ifBlank { target }
                    fetchedUrl = target
                    phase = null
                    return@launch
                }
                phase = "Получение информации о видео..."
                val preferred = settings.subLangs.split(",").map { it.trim() }
                val res = Engine.fetchInfo(
                    url = target,
                    processId = "fetch_${System.currentTimeMillis()}",
                    preferredLangs = preferred,
                    cookiesPath = repo(app).library.cookiesPath(),
                    allowSplitStreams = settings.preferHighest,
                    playerClient = settings.playerClient
                )
                lastSubLangs = res.subLangs
                infoTitle = res.title
                formats = res.formats
                fetchedUrl = target
                phase = null
            } catch (e: Exception) {
                fetchError = e.message ?: "Не удалось получить информацию о видео"
                phase = null
            } finally {
                fetching = false
            }
        }
    }

    /**
     * Ставит в очередь именно ту ссылку, для которой запрашивались форматы:
     * раньше бралось текущее содержимое поля, и правка адреса после «Показать
     * качества» скачивала другое видео с чужим format_id.
     */
    fun start(url: String, formatId: String) {
        val target = (fetchedUrl ?: url).trim()
        if (target.isBlank()) return
        // Второй барьер: ссылку можно поменять после проверки форматов, и в
        // очередь попала бы задача, которая молча падает в фоне.
        if (!UrlKind.isSupported(target)) {
            fetchError = UrlKind.UNSUPPORTED_MESSAGE
            return
        }
        val profile = profileEntries
        if (profile != null && fetchedUrl == target) {
            enqueueProfile(profile, formatId)
            return
        }
        val t = infoTitle ?: target
        repo(getApplication()).downloads.add(
            target, formatId, t, lastSubLangs.joinToString(","), priority
        )
        started = t
    }

    /**
     * Ставит каждый ролик профиля отдельной задачей.
     *
     * Одна задача на весь профиль снова упёрлась бы в `--no-playlist` и
     * скачала бы только первое видео, если вообще что-то скачала.
     */
    private fun enqueueProfile(entries: List<RemoteEntry>, formatId: String) {
        val downloads = repo(getApplication()).downloads
        var added = 0
        for (entry in entries) {
            if (!UrlKind.isSupported(entry.url)) continue
            downloads.add(entry.url, formatId, entry.title, lastSubLangs.joinToString(","), priority)
            added++
        }
        started = if (added == 0) null else "профиль: $added роликов"
        if (added == 0) fetchError = "TikTok не вернул ролики профиля"
    }

    fun cancel(id: String) = repo(getApplication()).downloads.cancel(id)
    fun remove(id: String) = repo(getApplication()).downloads.remove(id)
    fun retry(id: String) = repo(getApplication()).downloads.retry(id)
    fun retryAllFailed() = repo(getApplication()).downloads.retryAllFailed()
    fun clearFinished() = repo(getApplication()).downloads.clearFinished()
    fun setPriority(id: String, p: TaskPriority) = repo(getApplication()).downloads.setPriority(id, p)
    fun togglePause() {
        val downloads = repo(getApplication()).downloads
        downloads.setPaused(!downloads.paused.value)
    }
}

class PlayerViewModel(app: Application) : AndroidViewModel(app) {
    var video by mutableStateOf<VideoItem?>(null)
        private set
    var recommended by mutableStateOf<List<VideoItem>>(emptyList())
        private set
    var videoPath by mutableStateOf<String?>(null)
        private set
    var subtitlePaths by mutableStateOf<List<String>>(emptyList())
        private set
    var startPositionMs by mutableStateOf(0L)
        private set
    var isFavorite by mutableStateOf(false)
        private set
    var channelHidden by mutableStateOf(false)
        private set

    /** Пока идёт поиск видео, экран показывает индикатор, а не «не найдено». */
    var loading by mutableStateOf(true)
        private set

    /** Плейлист, по которому идёт просмотр: определяет «следующее видео». */
    var collectionId by mutableStateOf("")
        private set
    var collectionTitle by mutableStateOf("")
        private set
    var inWatchLater by mutableStateOf(false)
        private set

    /** Выбранный локальный вариант качества: пусто — исходный файл. */
    var activeQuality by mutableStateOf("")
        private set

    val settings = repo(app).settings
    val mediaTasks: StateFlow<List<MediaTask>> = repo(app).media.tasks
    val userData: StateFlow<UserData> = repo(app).userData.data

    fun load(id: String, collection: String = "") {
        viewModelScope.launch {
            loading = true
            try {
                val store = repo(getApplication()).userData
                val lib = repo(getApplication()).library
                val hidden = store.current.hiddenChannels.toSet()
                val v = withContext(Dispatchers.IO) { lib.findVideo(id) }
                video = v
                collectionId = collection
                collectionTitle = store.collection(collection)?.title.orEmpty()
                // Качество сбрасываем на исходное: у нового видео вариантов
                // прежнего набора может не быть вовсе.
                activeQuality = ""
                if (v != null) {
                    videoPath = withContext(Dispatchers.IO) { lib.videoFile(v)?.absolutePath }
                    subtitlePaths = withContext(Dispatchers.IO) {
                        lib.subtitleFiles(v).map { it.absolutePath }
                    }
                    isFavorite = store.isFavorite(v.id)
                    channelHidden = store.isChannelHidden(v.author)
                    inWatchLater = store.isInWatchLater(v.id)
                    // Возобновление с места, где остановились.
                    startPositionMs = store.position(v.id)
                    store.markWatched(v.id)
                } else {
                    videoPath = null
                    subtitlePaths = emptyList()
                    startPositionMs = 0L
                    inWatchLater = false
                }
                recommended = withContext(Dispatchers.IO) { lib.recommended(id, hidden = hidden) }
            } finally {
                loading = false
            }
        }
    }

    /**
     * Переключает дорожку на локально сконвертированное качество.
     * Позиция сохраняется вызывающим: файл меняется, а место просмотра нет.
     */
    fun selectQuality(quality: String) {
        val v = video ?: return
        val lib = repo(getApplication()).library
        activeQuality = quality
        videoPath = if (quality.isBlank()) {
            lib.videoFile(v)?.absolutePath
        } else {
            lib.qualityFile(v, quality)?.absolutePath ?: lib.videoFile(v)?.absolutePath
        }
    }

    /** Запускает конвертацию в выбранное качество. */
    fun convert(preset: Ffmpeg.Preset) {
        val v = video ?: return
        repo(getApplication()).media.convert(v, preset)
    }

    fun deleteQuality(quality: String) {
        val v = video ?: return
        viewModelScope.launch {
            withContext(Dispatchers.IO) { repo(getApplication()).media.deleteQuality(v, quality) }
            // Если играло удалённое качество, возвращаемся к исходнику.
            if (activeQuality == quality) selectQuality("")
            load(v.id, collectionId)
        }
    }

    fun extractAudio() {
        val v = video ?: return
        repo(getApplication()).media.extractAudio(v)
    }

    /** Путь к готовому MP3 либо null: кнопка меняет подпись на «Открыть». */
    fun audioPath(): String? =
        video?.let { repo(getApplication()).library.audioFile(it)?.absolutePath }

    fun ffmpegAvailable(): Boolean = repo(getApplication()).media.isAvailable()

    fun cancelMediaTask(id: String) = repo(getApplication()).media.cancel(id)

    fun dismissMediaTask(id: String) = repo(getApplication()).media.dismiss(id)

    fun toggleWatchLater() {
        val id = video?.id ?: return
        inWatchLater = repo(getApplication()).userData.toggleWatchLater(id)
    }

    fun savePosition(positionMs: Long, durationMs: Long) {
        val id = video?.id ?: return
        // У самого конца позицию не храним: при следующем открытии начнём заново.
        val nearEnd = durationMs > 0 && positionMs > durationMs - 10_000
        repo(getApplication()).userData.savePosition(id, if (nearEnd) 0 else positionMs)
    }

    fun toggleFavorite() {
        val id = video?.id ?: return
        isFavorite = repo(getApplication()).userData.toggleFavorite(id)
    }

    fun toggleChannelHidden() {
        val author = video?.author ?: return
        channelHidden = repo(getApplication()).userData.toggleChannelHidden(author)
    }

    /**
     * Следующее видео. Внутри плейлиста порядок задаёт сам плейлист, а не
     * библиотека: иначе просмотр списка уводил бы в случайное видео канала.
     */
    fun nextVideoId(): String? {
        val id = video?.id ?: return null
        val store = repo(getApplication()).userData
        if (collectionId.isNotBlank()) {
            val ids = store.collection(collectionId)?.videos.orEmpty()
            val index = ids.indexOf(id)
            if (index >= 0) {
                val lib = repo(getApplication()).library
                // Пропускаем удалённые с диска: остановиться на первом же
                // отсутствующем файле значило бы прервать плейлист.
                for (next in ids.drop(index + 1)) {
                    if (lib.findVideo(next) != null) return next
                }
                return null
            }
        }
        val hidden = store.current.hiddenChannels.toSet()
        return repo(getApplication()).library.nextAfter(id, hidden)?.id
    }

    fun localQualities(): List<String> = video?.qualities ?: emptyList()
}

class PlaylistViewModel(app: Application) : AndroidViewModel(app) {
    var playlist by mutableStateOf<Playlist?>(null)
        private set
    var loading by mutableStateOf(true)
        private set

    fun load(id: String) {
        viewModelScope.launch {
            loading = true
            try {
                playlist = withContext(Dispatchers.IO) {
                    repo(getApplication()).library.scanPlaylists().firstOrNull { it.id == id }
                }
            } finally {
                loading = false
            }
        }
    }
}

class ShortsViewModel(app: Application) : AndroidViewModel(app) {
    var shorts by mutableStateOf<List<VideoItem>>(emptyList())
        private set
    var loading by mutableStateOf(true)
        private set

    /** Избранное наблюдаем, а не снимаем снимок: иначе звёздочка устаревала. */
    val userData: StateFlow<UserData> = repo(app).userData.data

    fun load(startId: String?) {
        viewModelScope.launch {
            loading = true
            try {
                val store = repo(getApplication()).userData
                val hidden = store.current.hiddenChannels.toSet()
                val watched = store.current.history.toSet()
                val all = withContext(Dispatchers.IO) {
                    repo(getApplication()).library.catalog().shorts
                }
                // Текущее видео оставляем даже если его канал скрыт: пользователь
                // открыл его намеренно.
                val visible = all.filter { !hidden.contains(it.author) || it.id == startId }
                shorts = if (startId.isNullOrBlank()) {
                    // Как в вебе: начинаем с непросмотренных, остальные следом.
                    val fresh = visible.filterNot { watched.contains(it.id) }
                    (fresh.shuffled() + visible.filter { watched.contains(it.id) })
                } else {
                    visible.sortedByDescending { it.id == startId }
                }
            } finally {
                loading = false
            }
        }
    }

    fun markWatched(id: String) = repo(getApplication()).userData.markWatched(id)

    fun toggleFavorite(id: String) = repo(getApplication()).userData.toggleFavorite(id)

    fun isFavorite(id: String) = repo(getApplication()).userData.isFavorite(id)
}

class MyVideosViewModel(app: Application) : AndroidViewModel(app) {
    var videos by mutableStateOf<List<VideoItem>>(emptyList())
        private set
    var loading by mutableStateOf(true)
        private set

    var title by mutableStateOf("")
    var author by mutableStateOf("Гость")
    var description by mutableStateOf("")
    var videoUri by mutableStateOf<Uri?>(null)
    var videoName by mutableStateOf<String?>(null)
    var status by mutableStateOf<String?>(null)
    var uploading by mutableStateOf(false)

    fun load() {
        viewModelScope.launch {
            loading = true
            try {
                videos = withContext(Dispatchers.IO) {
                    repo(getApplication()).library.catalog().userVideos
                }
            } finally {
                loading = false
            }
        }
    }

    private fun queryName(uri: Uri): String? {
        return getApplication<Application>().contentResolver.query(uri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (idx >= 0 && c.moveToFirst()) c.getString(idx) else null
        }
    }

    fun setVideo(uri: Uri) {
        videoUri = uri
        videoName = queryName(uri)
        status = null
    }

    fun cancelUpload() {
        videoUri = null
        videoName = null
        status = null
    }

    private fun copyToCache(uri: Uri, prefix: String): File? {
        val ctx = getApplication<Application>()
        val name = queryName(uri) ?: prefix
        val ext = name.substringAfterLast('.', "").takeIf { it.isNotBlank() } ?: "bin"
        val f = File(ctx.cacheDir, "$prefix.$ext")
        return try {
            ctx.contentResolver.openInputStream(uri)?.use { ins ->
                f.outputStream().use { outs -> ins.copyTo(outs) }
            }
            f
        } catch (e: Exception) {
            null
        }
    }

    fun upload() {
        // Значение забираем сразу: «Отмена» могла обнулить videoUri до того,
        // как тело корутины начнёт выполняться, и !! падал с NPE.
        val uri = videoUri ?: return
        if (uploading) return
        viewModelScope.launch {
            uploading = true
            status = "Добавление..."
            try {
                val vf = withContext(Dispatchers.IO) { copyToCache(uri, "user_video") }
                if (vf == null) {
                    status = "Ошибка чтения файла"
                    return@launch
                }
                val id = withContext(Dispatchers.IO) {
                    repo(getApplication()).library.addUserVideo(vf, title, description, author)
                }
                // Превью вытаскиваем кадром из самого видео: своё видео приходит
                // без обложки, и в списке оставался серый прямоугольник. Аналог
                // download_thumbnails.py на сервере.
                status = "Создание превью..."
                withContext(Dispatchers.IO) { makeThumbnail(id, vf) }
                // Копия из cache больше не нужна: иначе файл лежит дважды.
                withContext(Dispatchers.IO) { runCatching { vf.delete() } }
                status = "Видео добавлено"
                videoUri = null
                videoName = null
                title = ""
                description = ""
                load()
            } catch (e: Exception) {
                status = "Ошибка: ${e.message}"
            } finally {
                uploading = false
            }
        }
    }

    /**
     * Кадр из видео как обложка. Провал не считается ошибкой добавления: видео
     * уже в библиотеке, а без превью оно просто покажет заглушку.
     */
    private suspend fun makeThumbnail(id: String, source: File) {
        val library = repo(getApplication()).library
        val folder = library.userVideoFolder(id) ?: return
        runCatching {
            val dest = File(folder, "thumb.jpg")
            if (Ffmpeg.extractThumbnail(getApplication(), source, dest)) {
                library.setUserThumbnail(id, "jpg")
            }
        }
    }

    fun delete(id: String) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { repo(getApplication()).library.deleteUserVideo(id) }
            load()
        }
    }

    /**
     * Автор передаётся явно. Раньше сюда шло поле формы загрузки (по умолчанию
     * «Гость»), и правка названия любого видео перезаписывала его автора.
     */
    fun edit(id: String, newTitle: String, newDesc: String, videoAuthor: String) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                repo(getApplication()).library.editUserVideo(id, newTitle, newDesc, videoAuthor)
            }
            load()
        }
    }
}

/**
 * Свои плейлисты. Список коллекций берётся из общего потока личных данных,
 * а видео разрешаются по библиотеке: коллекция хранит только id, как на сервере.
 */
class CollectionsViewModel(app: Application) : AndroidViewModel(app) {
    val userData: StateFlow<UserData> = repo(app).userData.data

    var catalog by mutableStateOf<Catalog?>(null)
        private set
    var loading by mutableStateOf(true)
        private set

    /** Сообщение о результате действия: показывается и при отказе, и при успехе. */
    var message by mutableStateOf<String?>(null)
    var error by mutableStateOf<String?>(null)

    fun load() {
        viewModelScope.launch {
            loading = true
            try {
                catalog = withContext(Dispatchers.IO) { repo(getApplication()).library.catalog() }
            } finally {
                loading = false
            }
        }
    }

    /** Коллекции с «Смотреть позже» первым, как в сайдбаре веб-версии. */
    fun collections(data: UserData): List<VideoCollection> =
        data.collections.sortedByDescending { it.id == VideoCollection.WATCH_LATER_ID }

    /**
     * Видео коллекции в том порядке, в котором их добавляли. Отсутствующие
     * пропускаем: видео могли удалить с диска, и пустая карточка была бы хуже.
     */
    fun videosOf(collection: VideoCollection): List<VideoItem> {
        val c = catalog ?: return emptyList()
        val all = c.videos + c.shorts + c.userVideos
        return collection.videos.mapNotNull { id -> all.firstOrNull { it.id == id } }
    }

    /** Число потерянных видео: подсказка «часть видео удалена с диска». */
    fun missingCount(collection: VideoCollection): Int =
        collection.videos.size - videosOf(collection).size

    fun create(title: String) = apply(repo(getApplication()).userData.createCollection(title), "Плейлист создан")

    fun rename(id: String, title: String) =
        apply(repo(getApplication()).userData.renameCollection(id, title), "Плейлист переименован")

    fun delete(id: String) =
        apply(repo(getApplication()).userData.deleteCollection(id), "Плейлист удалён")

    fun removeVideo(collectionId: String, videoId: String) {
        repo(getApplication()).userData.removeFromCollection(collectionId, videoId)
    }

    private fun apply(result: CollectionResult, okText: String) {
        when (result) {
            is CollectionResult.Ok -> {
                message = okText
                error = null
            }
            is CollectionResult.Error -> {
                error = result.message
                message = null
            }
        }
    }

    fun clearMessages() {
        message = null
        error = null
    }

    fun toggleFavorite(id: String) = repo(getApplication()).userData.toggleFavorite(id)
}

/**
 * Выбор плейлистов для одного видео: используется диалогом «Сохранить в...».
 * Отдельная модель, чтобы диалог работал с любого экрана без его переделки.
 */
class SaveToCollectionViewModel(app: Application) : AndroidViewModel(app) {
    val userData: StateFlow<UserData> = repo(app).userData.data

    var error by mutableStateOf<String?>(null)

    fun collections(data: UserData): List<VideoCollection> =
        data.collections.sortedByDescending { it.id == VideoCollection.WATCH_LATER_ID }

    fun contains(data: UserData, collectionId: String, videoId: String): Boolean =
        data.collections.firstOrNull { it.id == collectionId }?.videos?.contains(videoId) == true

    /** Переключает видео в плейлисте: одно нажатие и добавляет, и убирает. */
    fun toggle(collectionId: String, videoId: String) {
        val store = repo(getApplication()).userData
        if (contains(store.current, collectionId, videoId)) {
            store.removeFromCollection(collectionId, videoId)
        } else if (!store.addToCollection(collectionId, videoId)) {
            error = "В плейлисте уже ${VideoCollection.VIDEOS_LIMIT} видео"
        }
    }

    /** Создаёт плейлист и сразу кладёт в него видео. */
    fun createAndAdd(title: String, videoId: String) {
        val store = repo(getApplication()).userData
        when (val result = store.createCollection(title)) {
            is CollectionResult.Ok -> {
                store.addToCollection(result.id, videoId)
                error = null
            }
            is CollectionResult.Error -> error = result.message
        }
    }

    fun toggleWatchLater(videoId: String): Boolean =
        repo(getApplication()).userData.toggleWatchLater(videoId)

    fun clearError() {
        error = null
    }
}

/**
 * Субтитры одного видео. Сама работа идёт в SubtitleManager: он живёт в
 * Repository, поэтому догрузка не обрывается при повороте экрана.
 */
class SubtitlesViewModel(app: Application) : AndroidViewModel(app) {
    val state: StateFlow<SubtitleState> = repo(app).subtitles.state

    var video by mutableStateOf<VideoItem?>(null)
        private set

    fun load(videoId: String) {
        viewModelScope.launch {
            val v = withContext(Dispatchers.IO) { repo(getApplication()).library.findVideo(videoId) }
            video = v
            if (v != null) repo(getApplication()).subtitles.load(v)
        }
    }

    /** Свои видео: сетевые операции для них недоступны. */
    fun isUserVideo(): Boolean = video?.source == "user"

    fun loadAvailable() {
        val v = video ?: return
        repo(getApplication()).subtitles.loadAvailable(v)
    }

    fun download(langs: List<String>) {
        val v = video ?: return
        repo(getApplication()).subtitles.download(v, langs)
    }

    fun import(uri: Uri, lang: String) {
        val v = video ?: return
        repo(getApplication()).subtitles.import(v, uri, lang)
    }

    fun delete(track: SubtitleTrack) {
        val v = video ?: return
        repo(getApplication()).subtitles.delete(v, track)
    }

    fun clearMessages() = repo(getApplication()).subtitles.clearMessages()
}

class SettingsViewModel(app: Application) : AndroidViewModel(app) {
    val settings = repo(app).settings
    val userData: StateFlow<UserData> = repo(app).userData.data

    /** Состояние раздачи по локальной сети: адреса, порт, PIN. */
    val lan: StateFlow<LanSharing.State> = repo(app).lan.state

    var ytDlpVersion by mutableStateOf<String?>(null)
        private set
    var storageMb by mutableStateOf(0.0)
        private set
    var updating by mutableStateOf(false)
        private set
    var updateStatus by mutableStateOf<String?>(null)
        private set
    var cookiesActive by mutableStateOf(false)
        private set

    private var refreshed = false

    /**
     * Тяжёлые данные (обход библиотеки ради размера и запуск yt-dlp ради версии)
     * собираются только по запросу экрана настроек. Раньше это висело в init, и
     * любой экран, которому нужен был лишь clearHistory(), запускал полный обход
     * диска.
     */
    fun refresh() {
        if (refreshed) return
        refreshed = true
        viewModelScope.launch {
            val app = getApplication<Application>()
            cookiesActive = repo(app).library.cookiesPath() != null
            ytDlpVersion = withContext(Dispatchers.IO) {
                runCatching {
                    com.yausername.youtubedl_android.YoutubeDL.getInstance().version(app)
                }.getOrNull()
            }
            storageMb = withContext(Dispatchers.IO) {
                repo(app).library.storageUsedBytes() / 1024.0 / 1024.0
            }
        }
    }

    fun importCookies(uri: android.net.Uri) {
        val lib = repo(getApplication()).library
        if (lib.saveCookies(uri)) {
            cookiesActive = true
            updateStatus = "cookies.txt импортирован"
        } else {
            updateStatus = "Не удалось прочитать файл cookies"
        }
    }

    fun clearCookies() {
        repo(getApplication()).library.clearCookies()
        cookiesActive = false
        updateStatus = "cookies удалены"
    }

    fun clearFavorites() = repo(getApplication()).userData.clearFavorites()
    fun clearHistory() = repo(getApplication()).userData.clearHistory()
    fun clearHidden() = repo(getApplication()).userData.clearHiddenChannels()

    // ---------- локальная сеть ----------

    fun toggleLan() = repo(getApplication()).lan.toggle()

    fun refreshLanAddresses() = repo(getApplication()).lan.refreshAddresses()

    fun regenerateLanPin() = repo(getApplication()).lan.regeneratePin()

    /**
     * Меняет порт раздачи. Сервер перезапускается: слушающий сокет порт на ходу
     * не меняет, а молча оставить старый значило бы показывать неверный адрес.
     */
    fun setLanPort(port: Int) {
        settings.lanPort = port
        repo(getApplication()).lan.restartIfRunning()
    }

    fun updateYtDlp() {
        if (updating) return
        viewModelScope.launch {
            updating = true
            updateStatus = null
            try {
                val app = getApplication<Application>()
                withContext(Dispatchers.IO) {
                    com.yausername.youtubedl_android.YoutubeDL.getInstance()
                        .updateYoutubeDL(app, com.yausername.youtubedl_android.YoutubeDL.UpdateChannel.STABLE)
                }
                ytDlpVersion = withContext(Dispatchers.IO) {
                    com.yausername.youtubedl_android.YoutubeDL.getInstance().version(app)
                }
                updateStatus = "yt-dlp обновлён: $ytDlpVersion"
            } catch (e: Exception) {
                updateStatus = "Ошибка обновления: ${e.message}"
            } finally {
                updating = false
            }
        }
    }
}
