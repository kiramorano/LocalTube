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
import io.github.kiramorano.localtube.data.DownloadTask
import io.github.kiramorano.localtube.data.Engine
import io.github.kiramorano.localtube.data.FormatOption
import io.github.kiramorano.localtube.data.Playlist
import io.github.kiramorano.localtube.data.VideoItem
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.io.File

private fun repo(app: Application) = LocalTubeApp.from(app).repository

class HomeViewModel(app: Application) : AndroidViewModel(app) {
    var catalog by mutableStateOf<Catalog?>(null)
        private set
    var loading by mutableStateOf(false)
        private set

    fun load() {
        if (loading) return
        viewModelScope.launch {
            loading = true
            catalog = repo(getApplication()).library.scan()
            loading = false
        }
    }
}

class SearchViewModel(app: Application) : AndroidViewModel(app) {
    var query by mutableStateOf("")
        private set
    var results by mutableStateOf<List<VideoItem>?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    private var job: Job? = null

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
            results = repo(getApplication()).library.search(q)
            loading = false
        }
    }

    fun reload() {
        val q = query
        if (q.isNotBlank()) {
            results = repo(getApplication()).library.search(q)
        }
    }
}

class DownloadsViewModel(app: Application) : AndroidViewModel(app) {
    val tasks: StateFlow<List<DownloadTask>> = repo(app).downloads.tasks

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

    fun fetch(url: String) {
        if (fetching || url.isBlank()) return
        viewModelScope.launch {
            fetching = true
            fetchError = null
            formats = null
            infoTitle = null
            phase = "Проверка yt-dlp..."
            try {
                val app = getApplication<Application>()
                if (!Engine.ensureYtDlpFresh(app, Engine.appVersion(app))) {
                    phase = "yt-dlp не удалось обновить, пробую встроенную версию..."
                } else {
                    phase = "Получение информации о видео..."
                }
                val (title, fmts) = Engine.fetchInfo(
                    url, "fetch_${System.currentTimeMillis()}"
                )
                infoTitle = title
                formats = fmts
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
        repo(getApplication()).downloads.add(url, formatId, t)
        started = t
    }

    fun cancel(id: String) = repo(getApplication()).downloads.cancel(id)
    fun remove(id: String) = repo(getApplication()).downloads.remove(id)
    fun clearFinished() = repo(getApplication()).downloads.clearFinished()
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

    fun load(id: String) {
        val lib = repo(getApplication()).library
        val v = lib.findVideo(id)
        video = v
        if (v != null) {
            videoPath = lib.videoFile(v)?.absolutePath
            subtitlePaths = lib.subtitleFiles(v).map { it.absolutePath }
        }
        recommended = lib.recommended(id)
    }
}

class PlaylistViewModel(app: Application) : AndroidViewModel(app) {
    var playlist by mutableStateOf<Playlist?>(null)
        private set

    fun load(id: String) {
        playlist = repo(getApplication()).library.scanPlaylists().firstOrNull { it.id == id }
    }
}

class ShortsViewModel(app: Application) : AndroidViewModel(app) {
    var shorts by mutableStateOf<List<VideoItem>>(emptyList())
        private set

    fun load() {
        shorts = repo(getApplication()).library.scan().shorts
    }
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
        videos = repo(getApplication()).library.scan().userVideos
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
        } catch (_: Exception) {
            null
        }
    }

    fun upload() {
        if (uploading || videoUri == null) return
        viewModelScope.launch {
            uploading = true
            status = "Добавление..."
            try {
                val vf = copyToCache(videoUri!!, "user_video")
                if (vf == null) {
                    status = "Ошибка чтения файла"
                    return@launch
                }
                repo(getApplication()).library.addUserVideo(vf, title, description, author)
                status = "Видео добавлено!"
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
        repo(getApplication()).library.deleteUserVideo(id)
        load()
    }

    fun edit(id: String, newTitle: String, newDesc: String) {
        repo(getApplication()).library.editUserVideo(id, newTitle, newDesc, author)
        load()
    }
}

class SettingsViewModel(app: Application) : AndroidViewModel(app) {
    val settings = repo(app).settings

    var ytDlpVersion by mutableStateOf<String?>(null)
        private set
    var storageMb by mutableStateOf(0.0)
        private set
    var updating by mutableStateOf(false)
        private set
    var updateStatus by mutableStateOf<String?>(null)
        private set

    init {
        viewModelScope.launch {
            val app = getApplication<Application>()
            ytDlpVersion = try {
                com.yausername.youtubedl_android.YoutubeDL.getInstance().version(app)
            } catch (_: Exception) {
                null
            }
            storageMb = folderSize(repo(app).library.root) +
                folderSize(repo(app).library.userRoot) +
                folderSize(repo(app).library.playlistsRoot) +
                folderSize(repo(app).library.avatarsRoot)
        }
    }

    fun updateYtDlp() {
        if (updating) return
        viewModelScope.launch {
            updating = true
            updateStatus = null
            try {
                val app = getApplication<Application>()
                com.yausername.youtubedl_android.YoutubeDL.getInstance()
                    .updateYoutubeDL(app, com.yausername.youtubedl_android.YoutubeDL.UpdateChannel.STABLE)
                ytDlpVersion = com.yausername.youtubedl_android.YoutubeDL.getInstance().version(app)
                updateStatus = "yt-dlp обновлён: $ytDlpVersion"
            } catch (e: Exception) {
                updateStatus = "Ошибка обновления: ${e.message}"
            } finally {
                updating = false
            }
        }
    }

    private fun folderSize(f: File): Double {
        return f.walkTopDown().filter { it.isFile }.sumOf { it.length() } / 1024.0 / 1024.0
    }
}
