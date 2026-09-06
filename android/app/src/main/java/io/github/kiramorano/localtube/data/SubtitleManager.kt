package io.github.kiramorano.localtube.data

import android.app.Application
import android.net.Uri
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/** Дорожка субтитров на диске. */
data class SubtitleTrack(val lang: String, val path: String)

/** Состояние операций с субтитрами для одного видео. */
data class SubtitleState(
    val tracks: List<SubtitleTrack> = emptyList(),
    val availableLangs: List<String> = emptyList(),
    val loading: Boolean = false,
    val message: String? = null,
    val error: String? = null
)

/**
 * Управление субтитрами уже скачанного видео: список, догрузка с YouTube,
 * импорт своего файла и удаление. Аналог audio_language.py на сервере.
 */
class SubtitleManager(
    private val app: Application,
    private val library: Library,
    private val settings: Settings
) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _state = MutableStateFlow(SubtitleState())
    val state: StateFlow<SubtitleState> = _state.asStateFlow()

    /** Читает дорожки с диска. Вызывается при открытии экрана субтитров. */
    fun load(video: VideoItem) {
        scope.launch {
            val tracks = withContext(Dispatchers.IO) { tracksOf(video) }
            _state.value = _state.value.copy(tracks = tracks, error = null, message = null)
        }
    }

    private fun tracksOf(video: VideoItem): List<SubtitleTrack> =
        library.subtitleFiles(video).map {
            SubtitleTrack(lang = library.subtitleLang(it), path = it.absolutePath)
        }

    /** Спрашивает у YouTube, какие языки есть у видео. */
    fun loadAvailable(video: VideoItem) {
        val url = watchUrl(video) ?: run {
            _state.value = _state.value.copy(
                error = "Для своих видео список языков недоступен"
            )
            return
        }
        scope.launch {
            _state.value = _state.value.copy(loading = true, error = null, message = null)
            try {
                val res = Engine.fetchInfo(
                    url = url,
                    processId = "subs_info_${video.id}_${System.currentTimeMillis()}",
                    preferredLangs = emptyList(),
                    cookiesPath = library.cookiesPath(),
                    playerClient = settings.playerClient
                )
                _state.value = _state.value.copy(
                    loading = false,
                    availableLangs = res.availableSubLangs,
                    message = if (res.availableSubLangs.isEmpty()) "У видео нет субтитров" else null
                )
            } catch (e: Exception) {
                _state.value = _state.value.copy(
                    loading = false,
                    error = (e.message ?: "ошибка").take(300)
                )
            }
        }
    }

    /** Догружает выбранные языки к уже скачанному видео. */
    fun download(video: VideoItem, langs: List<String>) {
        if (langs.isEmpty()) return
        val url = watchUrl(video) ?: run {
            _state.value = _state.value.copy(error = "Для своих видео загрузка недоступна")
            return
        }
        val folder = library.folderOf(video) ?: run {
            _state.value = _state.value.copy(error = "Папка видео не найдена")
            return
        }
        scope.launch {
            _state.value = _state.value.copy(loading = true, error = null, message = null)
            try {
                val added = Engine.downloadSubtitles(
                    videoUrl = url,
                    langs = langs.joinToString(","),
                    outDir = folder,
                    processId = "subs_dl_${video.id}_${System.currentTimeMillis()}",
                    cookiesPath = library.cookiesPath(),
                    playerClient = settings.playerClient
                )
                library.invalidate()
                _state.value = _state.value.copy(
                    loading = false,
                    tracks = withContext(Dispatchers.IO) { tracksOf(video) },
                    message = if (added.isEmpty()) {
                        "Новых дорожек не добавилось: выбранных языков у видео нет"
                    } else {
                        "Добавлено дорожек: ${added.size}"
                    }
                )
            } catch (e: Exception) {
                _state.value = _state.value.copy(
                    loading = false,
                    error = (e.message ?: "ошибка").take(300)
                )
            }
        }
    }

    fun import(video: VideoItem, uri: Uri, lang: String) {
        scope.launch {
            val file = withContext(Dispatchers.IO) { library.importSubtitle(video, uri, lang) }
            _state.value = _state.value.copy(
                tracks = withContext(Dispatchers.IO) { tracksOf(video) },
                message = if (file != null) "Файл субтитров добавлен" else null,
                error = if (file == null) "Не удалось прочитать файл" else null
            )
        }
    }

    fun delete(video: VideoItem, track: SubtitleTrack) {
        scope.launch {
            val ok = withContext(Dispatchers.IO) {
                library.deleteSubtitle(video, File(track.path))
            }
            _state.value = _state.value.copy(
                tracks = withContext(Dispatchers.IO) { tracksOf(video) },
                message = if (ok) "Дорожка удалена" else null,
                error = if (!ok) "Не удалось удалить дорожку" else null
            )
        }
    }

    fun clearMessages() {
        _state.value = _state.value.copy(message = null, error = null)
    }

    /**
     * Адрес видео для дозагрузки субтитров.
     *
     * Сборка вынесена в UrlKind: TikTok-id нельзя подставлять в watch?v=,
     * иначе yt-dlp уйдёт на YouTube.
     */
    private fun watchUrl(video: VideoItem): String? =
        UrlKind.watchUrl(video.source, video.id, video.channelUrl)
}
