package io.github.kiramorano.localtube.vm

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import io.github.kiramorano.localtube.data.Catalog
import io.github.kiramorano.localtube.data.QueueItem
import io.github.kiramorano.localtube.data.ServerManager
import io.github.kiramorano.localtube.data.VideoDetail
import io.github.kiramorano.localtube.data.VideoItem
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File

class HomeViewModel : ViewModel() {
    var catalog by mutableStateOf<Catalog?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    fun load() {
        viewModelScope.launch {
            loading = true
            error = null
            try {
                catalog = ServerManager.api().catalog()
            } catch (e: Exception) {
                error = e.message ?: "Ошибка подключения к серверу"
            } finally {
                loading = false
            }
        }
    }
}

class PlayerViewModel : ViewModel() {
    var detail by mutableStateOf<VideoDetail?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    fun load(id: String) {
        viewModelScope.launch {
            loading = true
            error = null
            try {
                detail = ServerManager.api().video(id)
            } catch (e: Exception) {
                error = e.message ?: "Ошибка загрузки видео"
            } finally {
                loading = false
            }
        }
    }
}

class SearchViewModel : ViewModel() {
    var query by mutableStateOf("")
        private set
    var results by mutableStateOf<List<VideoItem>?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    private var job: Job? = null

    fun onQuery(q: String) {
        query = q
        job?.cancel()
        if (q.isBlank()) {
            results = null
            error = null
            return
        }
        job = viewModelScope.launch {
            delay(400)
            loading = true
            error = null
            try {
                results = ServerManager.api().search(q)
            } catch (e: Exception) {
                error = e.message ?: "Ошибка поиска"
            } finally {
                loading = false
            }
        }
    }
}

class QueueViewModel : ViewModel() {
    var tasks by mutableStateOf<List<QueueItem>>(emptyList())
        private set
    var paused by mutableStateOf(false)
        private set

    suspend fun refresh() {
        try {
            val snap = ServerManager.api().queueList()
            tasks = snap.tasks
            paused = snap.paused
        } catch (_: Exception) {
        }
    }

    fun pause() = viewModelScope.launch {
        ServerManager.api().queuePause()
        refresh()
    }

    fun resume() = viewModelScope.launch {
        ServerManager.api().queueResume()
        refresh()
    }

    fun clear() = viewModelScope.launch {
        ServerManager.api().queueClear()
        refresh()
    }

    fun remove(id: String) = viewModelScope.launch {
        ServerManager.api().queueRemove(id)
        refresh()
    }
}

class UploadViewModel(app: Application) : AndroidViewModel(app) {
    var title by mutableStateOf("")
    var username by mutableStateOf("Гость")
    var description by mutableStateOf("")
    var videoUri by mutableStateOf<Uri?>(null)
    var thumbUri by mutableStateOf<Uri?>(null)
    var videoName by mutableStateOf<String?>(null)
    var thumbName by mutableStateOf<String?>(null)
    var status by mutableStateOf<String?>(null)
    var uploading by mutableStateOf(false)

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

    fun setThumb(uri: Uri) {
        thumbUri = uri
        thumbName = queryName(uri)
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
            status = "Загрузка на сервер..."
            try {
                val vf = copyToCache(videoUri!!, "upload_video")
                val tf = thumbUri?.let { copyToCache(it, "upload_thumb") }
                if (vf == null) {
                    status = "Ошибка чтения файла"
                    return@launch
                }
                val res = ServerManager.api().upload(
                    title.ifBlank { "Без названия" },
                    description,
                    username.ifBlank { "Гость" },
                    vf,
                    tf
                )
                status = if (res == "ok") "Видео загружено!" else "Ошибка загрузки на сервер"
            } catch (e: Exception) {
                status = "Ошибка: ${e.message}"
            } finally {
                uploading = false
            }
        }
    }
}
