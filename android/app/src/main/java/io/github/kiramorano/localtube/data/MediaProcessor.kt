package io.github.kiramorano.localtube.data

import android.app.Application
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File

/** Состояние одной задачи ffmpeg. */
data class MediaTask(
    val id: String,
    val videoId: String,
    val title: String,
    /** Идентификатор пресета конвертации либо "audio" для извлечения звука. */
    val kind: String,
    val progress: Float = 0f,
    val done: Boolean = false,
    val error: String? = null,
    val message: String = ""
)

/**
 * Конвертация качества и извлечение звука.
 *
 * Задачи живут в менеджере, а не в модели экрана: переход на другой экран или
 * поворот телефона не должны обрывать перекодирование, которое идёт минутами.
 * Одновременно выполняется одна операция — ffmpeg и без того забирает все ядра.
 */
class MediaProcessor(
    private val app: Application,
    private val library: Library
) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val runMutex = Mutex()

    private val _tasks = MutableStateFlow<List<MediaTask>>(emptyList())
    val tasks: StateFlow<List<MediaTask>> = _tasks.asStateFlow()

    /** Сообщает UI, что на диске появился новый файл качества или mp3. */
    private val _version = MutableStateFlow(0L)
    val version: StateFlow<Long> = _version.asStateFlow()

    private val jobs = java.util.concurrent.ConcurrentHashMap<String, Job>()

    fun isAvailable(): Boolean = Ffmpeg.isAvailable(app)

    fun activeFor(videoId: String): MediaTask? =
        _tasks.value.firstOrNull { it.videoId == videoId && !it.done && it.error == null }

    /**
     * Ставит конвертацию в выбранное качество. Повторный запрос для той же
     * пары «видео + качество» игнорируется: иначе два ffmpeg писали бы в один
     * временный файл.
     */
    fun convert(video: VideoItem, preset: Ffmpeg.Preset): String? {
        val source = library.videoFile(video) ?: return null
        val key = "${video.id}:${preset.id}"
        if (_tasks.value.any { it.id == key && !it.done && it.error == null }) return key
        enqueue(
            MediaTask(
                id = key,
                videoId = video.id,
                title = video.title,
                kind = preset.id,
                message = "В очереди"
            )
        ) { task ->
            Ffmpeg.convert(
                ctx = app,
                source = source,
                preset = preset,
                durationMs = video.durationSec * 1000
            ) { p -> progress(task.id, p) }
        }
        return key
    }

    /** Извлекает MP3. Возвращает ключ задачи либо null, если файла нет. */
    fun extractAudio(video: VideoItem): String? {
        val source = library.videoFile(video) ?: return null
        val key = "${video.id}:audio"
        if (_tasks.value.any { it.id == key && !it.done && it.error == null }) return key
        enqueue(
            MediaTask(
                id = key,
                videoId = video.id,
                title = video.title,
                kind = "audio",
                message = "В очереди"
            )
        ) { task ->
            val (_, result) = Ffmpeg.extractAudio(
                ctx = app,
                source = source,
                durationMs = video.durationSec * 1000
            ) { p -> progress(task.id, p) }
            result
        }
        return key
    }

    private fun enqueue(task: MediaTask, block: suspend (MediaTask) -> Ffmpeg.Result) {
        _tasks.update { list -> list.filterNot { it.id == task.id } + task }
        jobs[task.id] = scope.launch {
            try {
                // Замок держит очередь из одной операции: параллельные ffmpeg
                // на телефоне только мешают друг другу и греют устройство.
                runMutex.withLock {
                    setMessage(task.id, "Обработка...")
                    val result = block(task)
                    if (result.success) {
                        library.invalidate()
                        _version.value = System.currentTimeMillis()
                        finish(task.id, null, result.message)
                    } else {
                        finish(task.id, result.message, result.message)
                    }
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                // Отмена — не ошибка: задачу просто убираем из списка.
                _tasks.update { list -> list.filterNot { it.id == task.id } }
                throw e
            } catch (e: Exception) {
                finish(task.id, (e.message ?: "ошибка").take(200), "Ошибка")
            } finally {
                jobs.remove(task.id)
            }
        }
    }

    fun cancel(id: String) {
        jobs.remove(id)?.cancel()
        _tasks.update { list -> list.filterNot { it.id == id } }
    }

    fun dismiss(id: String) {
        _tasks.update { list -> list.filterNot { it.id == id } }
    }

    fun clearFinished() {
        _tasks.update { list -> list.filterNot { it.done || it.error != null } }
    }

    private fun progress(id: String, value: Float) {
        _tasks.update { list ->
            list.map { if (it.id == id) it.copy(progress = value) else it }
        }
    }

    private fun setMessage(id: String, text: String) {
        _tasks.update { list ->
            list.map { if (it.id == id) it.copy(message = text) else it }
        }
    }

    private fun finish(id: String, error: String?, message: String) {
        _tasks.update { list ->
            list.map {
                if (it.id != id) it
                else it.copy(
                    done = error == null,
                    error = error,
                    message = message,
                    progress = if (error == null) 1f else it.progress
                )
            }
        }
    }

    /**
     * Удаляет локально сконвертированный вариант качества.
     * Исходник (video.*) не трогаем: его удаление — это удаление видео.
     */
    fun deleteQuality(video: VideoItem, quality: String): Boolean {
        val source = library.videoFile(video) ?: return false
        val folder = source.parentFile ?: return false
        val file = File(folder, "video_$quality.mp4")
        if (!file.isFile) return false
        val ok = file.delete()
        if (ok) {
            library.invalidate()
            _version.value = System.currentTimeMillis()
        }
        return ok
    }
}
