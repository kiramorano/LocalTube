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
import io.github.kiramorano.localtube.data.DownloadTask
import io.github.kiramorano.localtube.data.Engine
import io.github.kiramorano.localtube.data.FormatOption
import io.github.kiramorano.localtube.data.Playlist
import io.github.kiramorano.localtube.data.TaskPriority
import io.github.kiramorano.localtube.data.UserData
import io.github.kiramorano.localtube.data.VideoItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.StateFlow
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

    val userData: StateFlow<UserData> = repo(app).userData.data
    val libraryVersion: StateFlow<Long> = repo(app).downloads.libraryVersion
    val settings = repo(app).settings

    /** Сканирование идёт в IO: раньше оно выполнялось на главном потоке. */
    fun load(force: Boolean = false) {
        viewModelScope.launch {
            loading = true
            val lib = repo(getApplication()).library
            val scanned = withContext(Dispatchers.IO) {
                if (force) lib.scan() else lib.catalog()
            }
            catalog = scanned
            loading = false
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
    var videos by mutableStateOf<List<VideoItem>>(emptyList())
        private set
    var shorts by mutableStateOf<List<VideoItem>>(emptyList())
        private set
    var avatar by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set

    val userData: StateFlow<UserData> = repo(app).userData.data

    fun load(name: String) {
        author = name
        viewModelScope.launch {
            loading = true
            val lib = repo(getApplication()).library
            val all = withContext(Dispatchers.IO) { lib.videosOf(name) }
            videos = all.filterNot { it.isShort }
            shorts = all.filter { it.isShort }
            avatar = withContext(Dispatchers.IO) { lib.avatarFor(name) }
            loading = false
        }
    }

    fun isHidden(): Boolean = repo(getApplication()).userData.isChannelHidden(author)

    fun toggleHidden(): Boolean = repo(getApplication()).userData.toggleChannelHidden(author)
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

    fun fetch(url: String) {
        if (fetching || url.isBlank()) return
        viewModelScope.launch {
            fetching = true
            fetchError = null
            formats = null
            infoTitle = null
            started = null
            phase = "Проверка yt-dlp..."
            try {
                val app = getApplication<Application>()
                if (!Engine.ensureYtDlpFresh(app, Engine.appVersion(app))) {
                    phase = "yt-dlp не удалось обновить, пробую встроенную версию..."
                } else {
                    phase = "Получение информации о видео..."
                }
                val preferred = repo(app).settings.subLangs.split(",").map { it.trim() }
                val res = Engine.fetchInfo(
                    url,
                    "fetch_${System.currentTimeMillis()}",
                    preferred,
                    repo(app).library.cookiesPath()
                )
                lastSubLangs = res.subLangs
                infoTitle = res.title
                formats = res.formats
                phase = null
            } catch (e: Exception) {
                fetchError = e.message ?: "Не удалось получить информацию о видео"
                phase = null
            } finally {
                fetching = false
            }
        }
    }

    fun start(url: String, formatId: String) {
        val t = infoTitle ?: url
        repo(getApplication()).downloads.add(
            url, formatId, t, lastSubLangs.joinToString(","), priority
        )
        started = t
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

    val settings = repo(app).settings

    fun load(id: String) {
        viewModelScope.launch {
            val store = repo(getApplication()).userData
            val lib = repo(getApplication()).library
            val hidden = store.current.hiddenChannels.toSet()
            val v = withContext(Dispatchers.IO) { lib.findVideo(id) }
            video = v
            if (v != null) {
                videoPath = withContext(Dispatchers.IO) { lib.videoFile(v)?.absolutePath }
                subtitlePaths = withContext(Dispatchers.IO) {
                    lib.subtitleFiles(v).map { it.absolutePath }
                }
                isFavorite = store.isFavorite(v.id)
                channelHidden = store.isChannelHidden(v.author)
                // Возобновление с места, где остановились.
                startPositionMs = store.position(v.id)
                store.markWatched(v.id)
            }
            recommended = withContext(Dispatchers.IO) { lib.recommended(id, hidden = hidden) }
        }
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

    fun nextVideoId(): String? {
        val id = video?.id ?: return null
        val hidden = repo(getApplication()).userData.current.hiddenChannels.toSet()
        return repo(getApplication()).library.nextAfter(id, hidden)?.id
    }

    fun localQualities(): List<String> = video?.qualities ?: emptyList()
}

class PlaylistViewModel(app: Application) : AndroidViewModel(app) {
    var playlist by mutableStateOf<Playlist?>(null)
        private set

    fun load(id: String) {
        viewModelScope.launch {
            playlist = withContext(Dispatchers.IO) {
                repo(getApplication()).library.scanPlaylists().firstOrNull { it.id == id }
            }
        }
    }
}

class ShortsViewModel(app: Application) : AndroidViewModel(app) {
    var shorts by mutableStateOf<List<VideoItem>>(emptyList())
        private set

    fun load(startId: String?) {
        viewModelScope.launch {
            val store = repo(getApplication()).userData
            val hidden = store.current.hiddenChannels.toSet()
            val all = withContext(Dispatchers.IO) {
                repo(getApplication()).library.catalog().shorts
            }
            // Текущее видео оставляем даже если его канал скрыт: пользователь
            // открыл его намеренно.
            val visible = all.filter { !hidden.contains(it.author) || it.id == startId }
            shorts = if (startId == null) visible
            else visible.sortedByDescending { it.id == startId }
        }
    }

    fun markWatched(id: String) = repo(getApplication()).userData.markWatched(id)

    fun toggleFavorite(id: String) = repo(getApplication()).userData.toggleFavorite(id)

    fun isFavorite(id: String) = repo(getApplication()).userData.isFavorite(id)
}

class MyVideosViewModel(app: Application) : AndroidViewModel(app) {
    var videos by mutableStateOf<List<VideoItem>>(emptyList())
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
            videos = withContext(Dispatchers.IO) {
                repo(getApplication()).library.catalog().userVideos
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
        if (uploading || videoUri == null) return
        viewModelScope.launch {
            uploading = true
            status = "Добавление..."
            try {
                val vf = withContext(Dispatchers.IO) { copyToCache(videoUri!!, "user_video") }
                if (vf == null) {
                    status = "Ошибка чтения файла"
                    return@launch
                }
                withContext(Dispatchers.IO) {
                    repo(getApplication()).library.addUserVideo(vf, title, description, author)
                }
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

    fun delete(id: String) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { repo(getApplication()).library.deleteUserVideo(id) }
            load()
        }
    }

    fun edit(id: String, newTitle: String, newDesc: String) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                repo(getApplication()).library.editUserVideo(id, newTitle, newDesc, author)
            }
            load()
        }
    }
}

class SettingsViewModel(app: Application) : AndroidViewModel(app) {
    val settings = repo(app).settings
    val userData: StateFlow<UserData> = repo(app).userData.data

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

    init {
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
