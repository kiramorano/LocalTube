package io.github.kiramorano.localtube.data

import android.app.Application
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/**
 * Очередь загрузок с приоритетами, паузой, повтором и сохранением на диск.
 *
 * Прежняя версия держала очередь только в памяти (при перезапуске всё
 * терялось), не умела приоритеты и паузу, а отмена ожидающей задачи не
 * работала: флаг снимался в самом начале обработки, и загрузка всё равно
 * начиналась.
 */
class DownloadManager(
    private val app: Application,
    private val library: Library,
    private val settings: Settings
) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val stateFile = File(app.filesDir, "queue.json")

    private val _tasks = MutableStateFlow<List<DownloadTask>>(emptyList())
    val tasks: StateFlow<List<DownloadTask>> = _tasks.asStateFlow()

    private val _paused = MutableStateFlow(false)
    val paused: StateFlow<Boolean> = _paused.asStateFlow()

    /** Сообщает UI, что библиотека изменилась и её надо перечитать. */
    private val _libraryVersion = MutableStateFlow(0L)
    val libraryVersion: StateFlow<Long> = _libraryVersion.asStateFlow()

    private val cancelRequests = java.util.Collections.newSetFromMap(
        java.util.concurrent.ConcurrentHashMap<String, Boolean>()
    )

    /** Мьютекс вместо флага: прежний Boolean без синхронизации терял задачи. */
    private val workerMutex = Mutex()

    @Volatile
    private var activeId: String? = null

    /** Признак запущенного foreground-сервиса, чтобы не дёргать его на каждую задачу. */
    @Volatile
    private var serviceRunning = false

    private val notifications by lazy {
        app.getSystemService(NotificationManager::class.java)
    }

    init {
        // minSdk 26, поэтому канал создаётся безусловно и без проверки версии.
        runCatching {
            notifications?.createNotificationChannel(
                NotificationChannel("downloads", "Загрузки", NotificationManager.IMPORTANCE_LOW)
            )
        }
        restore()
    }

    // ---------- публичный API ----------

    fun add(
        url: String,
        formatId: String,
        title: String,
        subLangs: String? = null,
        priority: TaskPriority = TaskPriority.NORMAL,
        mergeFormat: String = Engine.DEFAULT_MERGE_FORMAT
    ): String {
        val id = UUID.randomUUID().toString().substring(0, 8)
        val task = DownloadTask(
            id = id,
            title = title.ifBlank { url },
            url = url,
            formatId = formatId,
            status = TaskStatus.WAITING,
            progress = 0f,
            addedAt = System.currentTimeMillis(),
            error = null,
            subLangs = subLangs,
            priority = priority,
            mergeFormat = Engine.normalizeMergeFormat(mergeFormat)
        )
        _tasks.update { it + task }
        persist()
        ensureWorker()
        return id
    }

    fun cancel(id: String) {
        val task = _tasks.value.firstOrNull { it.id == id } ?: return
        if (task.isFinished) return
        cancelRequests.add(id)
        if (task.status == TaskStatus.DOWNLOADING || id == activeId) {
            // Процесс могли ещё не зарегистрировать: пробуем всё равно, а
            // cancelRequests подстрахует, если убить оказалось нечего.
            runCatching { Engine.cancel(id) }
        } else {
            // Ожидающую задачу помечаем сразу: она даже не начнётся.
            cancelRequests.remove(id)
            update(id, TaskStatus.CANCELED, 0f)
        }
        persist()
    }

    fun remove(id: String) {
        // Удаление активной задачи равносильно её отмене.
        if (_tasks.value.firstOrNull { it.id == id }?.status == TaskStatus.DOWNLOADING) {
            cancelRequests.add(id)
            runCatching { Engine.cancel(id) }
        } else {
            cancelRequests.remove(id)
        }
        _tasks.update { list -> list.filterNot { it.id == id } }
        runCatching { notifications?.cancel(id.hashCode()) }
        persist()
    }

    /** Повтор начинается с чистого счётчика попыток, иначе он растёт вечно. */
    fun retry(id: String) {
        cancelRequests.remove(id)
        _tasks.update { list ->
            list.map {
                if (it.id == id && it.isFinished) {
                    it.copy(
                        status = TaskStatus.WAITING,
                        progress = 0f,
                        error = null,
                        speed = "",
                        etaSeconds = 0,
                        attempts = 0
                    )
                } else it
            }
        }
        persist()
        ensureWorker()
    }

    fun retryAllFailed() {
        _tasks.update { list ->
            list.map {
                if (it.status == TaskStatus.ERROR) {
                    cancelRequests.remove(it.id)
                    it.copy(status = TaskStatus.WAITING, progress = 0f, error = null, attempts = 0)
                } else it
            }
        }
        persist()
        ensureWorker()
    }

    fun setPriority(id: String, priority: TaskPriority) {
        _tasks.update { list ->
            list.map {
                // Менять приоритет уже качающейся задачи бессмысленно.
                if (it.id == id && it.status == TaskStatus.WAITING) it.copy(priority = priority) else it
            }
        }
        persist()
    }

    /** Пауза не обрывает текущую загрузку, только не даёт начаться следующим. */
    fun setPaused(value: Boolean) {
        _paused.value = value
        persist()
        if (!value) ensureWorker()
    }

    fun clearFinished() {
        val finished = _tasks.value.filter { it.isFinished }
        finished.forEach {
            cancelRequests.remove(it.id)
            runCatching { notifications?.cancel(it.id.hashCode()) }
        }
        _tasks.update { list -> list.filterNot { it.isFinished } }
        persist()
    }

    // ---------- воркер ----------

    private fun ensureWorker() {
        scope.launch {
            // Мьютекс гарантирует единственного воркера без гонки на флаге.
            // Проверять приходится в цикле: уходящий воркер держит замок до
            // самого конца, и без повторной попытки задача, добавленная в этот
            // момент, оставалась бы в очереди навсегда.
            while (true) {
                if (!workerMutex.tryLock()) return@launch
                try {
                    drain()
                } finally {
                    workerMutex.unlock()
                }
                if (_paused.value) return@launch
                if (_tasks.value.none { it.status == TaskStatus.WAITING }) return@launch
            }
        }
    }

    private suspend fun drain() {
        try {
            while (true) {
                if (_paused.value) {
                    // Ждём снятия паузы событием, а не опросом раз в секунду:
                    // прежний цикл жил всё время работы процесса.
                    if (_tasks.value.none { it.status == TaskStatus.WAITING }) return
                    _paused.first { !it }
                    continue
                }
                val next = nextWaiting() ?: return
                activeId = next.id
                startService(next.title)
                try {
                    runTask(next)
                } finally {
                    activeId = null
                }
            }
        } finally {
            stopService()
        }
    }

    /**
     * Пока идёт загрузка, живёт foreground-сервис: без него система вправе
     * убить процесс, и длинная загрузка не доживала до конца, стоило свернуть
     * приложение.
     */
    private fun startService(title: String) {
        if (serviceRunning) return
        val intent = Intent(app, DownloadService::class.java)
            .putExtra(DownloadService.EXTRA_TEXT, title.take(80))
        val ok = runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                app.startForegroundService(intent)
            } else {
                app.startService(intent)
            }
        }.isSuccess
        // На Android 12+ запуск из фона запрещён: тогда просто качаем без
        // сервиса, вместо того чтобы уронить процесс необработанным исключением.
        serviceRunning = ok
    }

    private fun stopService() {
        if (!serviceRunning) return
        serviceRunning = false
        runCatching { app.stopService(Intent(app, DownloadService::class.java)) }
    }

    /**
     * Выбирает задачу с наивысшим приоритетом. При равном приоритете сохраняется
     * порядок добавления.
     */
    private fun nextWaiting(): DownloadTask? = _tasks.value
        .filter { it.status == TaskStatus.WAITING }
        .minWithOrNull(compareBy({ it.priority.order }, { it.addedAt }))

    private suspend fun runTask(task: DownloadTask) {
        if (cancelRequests.remove(task.id)) {
            update(task.id, TaskStatus.CANCELED, 0f)
            return
        }
        update(task.id, TaskStatus.DOWNLOADING, 0f, attempts = task.attempts + 1)
        val outDir = File(library.tmpRoot, task.id).apply { mkdirs() }
        // Частичную загрузку сохраняем: yt-dlp запускается с -c и при повторе
        // продолжает с того же места вместо скачивания заново.
        var keepPartial = false
        try {
            // Чистим языки от висячих запятых и пробелов: поле в настройках
            // пишется на каждый символ, поэтому «ru,» — обычное состояние, а
            // задачи из синхронизации канала идут сюда без фильтра chooseSubLangs.
            val langs = Settings.normalizeLangs(
                task.subLangs?.takeIf { it.isNotBlank() } ?: settings.subLangs
            )
            val request = Engine.buildRequest(
                url = task.url,
                formatId = task.formatId,
                outDir = outDir,
                downloadSubs = settings.downloadSubs,
                subLangs = langs,
                cookiesPath = library.cookiesPath(),
                playerClient = settings.playerClient,
                mergeFormat = task.mergeFormat,
                audioLangs = Settings.normalizeLangs(settings.audioLangs)
                    .split(',')
                    .filter { it.isNotEmpty() }
            )
            var lastNotify = 0L
            Engine.download(request, task.id) { progress, eta, line ->
                if (!progress.isFinite() || progress < 0f || progress > 100f) return@download
                val speed = Engine.parseSpeed(line)
                updateProgress(task.id, progress, eta, speed)
                // Уведомление обновляем не чаще раза в секунду: раньше это
                // происходило на каждый тик и нагружало систему.
                val now = System.currentTimeMillis()
                if (now - lastNotify > 1000) {
                    lastNotify = now
                    notifyProgress(task, progress)
                }
            }
            if (cancelRequests.remove(task.id)) {
                update(task.id, TaskStatus.CANCELED, 0f)
                notifyDone(task, "Загрузка отменена")
                return
            }
            val placed = postProcess(outDir, task.id)
            if (placed == 0) {
                keepPartial = true
                update(task.id, TaskStatus.ERROR, 0f, error = "yt-dlp не вернул файлы")
                notifyDone(task, "Ошибка загрузки")
                return
            }
            library.invalidate()
            _libraryVersion.value = System.currentTimeMillis()
            update(task.id, TaskStatus.COMPLETED, 100f)
            notifyDone(task, "Загрузка завершена")
        } catch (e: Exception) {
            if (cancelRequests.remove(task.id)) {
                update(task.id, TaskStatus.CANCELED, 0f)
                notifyDone(task, "Загрузка отменена")
            } else {
                keepPartial = true
                update(task.id, TaskStatus.ERROR, 0f, error = (e.message ?: "ошибка").take(300))
                notifyDone(task, "Ошибка загрузки")
            }
        } finally {
            if (!keepPartial) outDir.deleteRecursively()
            persist()
        }
    }

    // ---------- состояние ----------

    private fun update(
        id: String,
        status: TaskStatus,
        progress: Float,
        error: String? = null,
        attempts: Int? = null
    ) {
        // update() вместо value = value.map{}: прогресс приходит из потока
        // yt-dlp, а отмена и удаление — с главного, и одно перетирало другое.
        _tasks.update { list ->
            list.map {
                if (it.id != id) it else it.copy(
                    status = status,
                    progress = if (status == TaskStatus.COMPLETED) 100f else progress,
                    error = error,
                    attempts = attempts ?: it.attempts,
                    speed = if (status == TaskStatus.DOWNLOADING) it.speed else "",
                    etaSeconds = if (status == TaskStatus.DOWNLOADING) it.etaSeconds else 0
                )
            }
        }
        persist()
    }

    private fun updateProgress(id: String, progress: Float, eta: Long, speed: String) {
        _tasks.update { list ->
            list.map {
                if (it.id != id) it
                else it.copy(progress = progress, etaSeconds = eta.coerceAtLeast(0), speed = speed)
            }
        }
    }

    /**
     * Запись очереди на диск. Идёт в отдельной корутине: вызовы приходят из
     * обработчиков нажатий, а JsonStore.write копирует бэкап и переписывает
     * файл целиком — на главном потоке это заметный фриз.
     */
    private fun persist() {
        val snapshot = _tasks.value
        val paused = _paused.value
        scope.launch {
            runCatching {
                val arr = JSONArray()
                snapshot.forEach { t ->
                    arr.put(JSONObject().apply {
                        put("id", t.id)
                        put("title", t.title)
                        put("url", t.url)
                        put("format_id", t.formatId)
                        put("status", t.status.name)
                        put("progress", t.progress.toDouble())
                        put("added_at", t.addedAt)
                        put("error", t.error ?: "")
                        put("sub_langs", t.subLangs ?: "")
                        put("priority", t.priority.name)
                        put("attempts", t.attempts)
                        put("merge_format", t.mergeFormat)
                    })
                }
                JsonStore.write(stateFile, JSONObject().apply {
                    put("paused", paused)
                    put("tasks", arr)
                })
            }
        }
    }

    private fun restore() {
        val json = JsonStore.read(stateFile)
        if (json == null) {
            cleanupTmp(emptySet())
            return
        }
        _paused.value = json.optBoolean("paused", false)
        val arr = json.optJSONArray("tasks")
        if (arr == null) {
            cleanupTmp(emptySet())
            return
        }
        val restored = mutableListOf<DownloadTask>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val status = runCatching { TaskStatus.valueOf(o.optString("status")) }
                .getOrDefault(TaskStatus.WAITING)
            restored += DownloadTask(
                id = o.optString("id").ifBlank { UUID.randomUUID().toString().substring(0, 8) },
                title = o.optString("title"),
                url = o.optString("url"),
                formatId = o.optString("format_id", "best"),
                // Прерванная перезапуском загрузка возвращается в ожидание.
                status = if (status == TaskStatus.DOWNLOADING) TaskStatus.WAITING else status,
                progress = if (status == TaskStatus.DOWNLOADING) 0f else o.optDouble("progress", 0.0).toFloat(),
                addedAt = o.optLong("added_at", System.currentTimeMillis()),
                error = o.optString("error").ifBlank { null },
                subLangs = o.optString("sub_langs").ifBlank { null },
                priority = runCatching { TaskPriority.valueOf(o.optString("priority")) }
                    .getOrDefault(TaskPriority.NORMAL),
                attempts = o.optInt("attempts", 0),
                // Очередь с прошлой версии контейнера не знает: normalize вернёт mp4.
                mergeFormat = Engine.normalizeMergeFormat(o.optString("merge_format"))
            )
        }
        _tasks.value = restored
        cleanupTmp(restored.map { it.id }.toSet())
        if (restored.any { it.status == TaskStatus.WAITING }) ensureWorker()
    }

    /**
     * Убирает мусор из tmp: процесс могли убить во время загрузки, и тогда
     * фрагменты оставались навсегда, занимая место, которое пользователь не мог
     * освободить из приложения.
     */
    private fun cleanupTmp(knownIds: Set<String>) {
        scope.launch {
            runCatching {
                library.tmpRoot.listFiles()?.forEach { f ->
                    if (f.name !in knownIds) f.deleteRecursively()
                }
            }
        }
    }

    // ---------- раскладка результата ----------

    /** Возвращает число разложенных видео: ноль означает неудачу. */
    private fun postProcess(outDir: File, taskId: String): Int {
        val infoFiles = outDir.listFiles()?.filter { it.isFile && it.name.endsWith(".info.json") }
            ?: return 0
        var placed = 0
        var playlistJson: JSONObject? = null
        for (infoFile in infoFiles) {
            val id = infoFile.name.removeSuffix(".info.json")
            val meta = try {
                JSONObject(infoFile.readText(Charsets.UTF_8))
            } catch (e: Exception) {
                continue
            }
            val author = library.safeName(meta.optString("uploader").ifEmpty { "Unknown" })
            // Вертикальные видео помечаем в имени папки, как на сервере.
            val destDir = File(File(library.root, author), id).apply { mkdirs() }
            val candidates = outDir.listFiles()
                ?.filter { it.isFile && it.name.startsWith("$id.") }
                .orEmpty()
            val videoSrc = candidates.firstOrNull { it.extension.lowercase() in VIDEO_EXTS }
            // Аудиодорожка тоже результат: раньше загрузка «только звука»
            // всегда падала с «yt-dlp не вернул файлы», а файл удалялся.
            val audioSrc = candidates.firstOrNull { it.extension.lowercase() in AUDIO_EXTS }
            val src = videoSrc ?: audioSrc ?: continue
            val baseName = if (videoSrc != null) "video" else "audio"
            val dest = File(destDir, "$baseName.${src.extension}")
            if (src.absolutePath != dest.absolutePath) {
                // renameTo вместо copyTo: копирование удваивало расход диска.
                if (!src.renameTo(dest)) src.copyTo(dest, overwrite = true)
            }
            infoFile.copyTo(File(destDir, "info.json"), overwrite = true)
            outDir.listFiles()?.forEach { f ->
                if (!f.isFile) return@forEach
                val name = f.name
                val thumbExt = imageExt(f)
                when {
                    name == "$id.$thumbExt" && thumbExt != null ->
                        f.copyTo(File(destDir, "thumbnail.$thumbExt"), overwrite = true)
                    // Кроме vtt берём и srt: --sub-format может отдать любой из них.
                    name.startsWith("$id.") && (name.endsWith(".vtt") || name.endsWith(".srt")) ->
                        f.copyTo(File(destDir, name.removePrefix("$id.")), overwrite = true)
                }
            }
            placed++
            if (meta.has("playlist_title") && !meta.isNull("playlist_title")) {
                val pt = meta.optString("playlist_title")
                val pl = (playlistJson ?: JSONObject().also {
                    it.put("id", meta.optString("playlist_id").ifEmpty { taskId })
                    it.put("title", pt)
                    it.put("uploader", meta.optString("playlist_uploader", meta.optString("uploader")))
                    it.put("videos", JSONArray())
                })
                val arr = pl.getJSONArray("videos")
                arr.put(JSONObject().apply {
                    put("id", id)
                    put("title", meta.optString("title", "Без названия"))
                    // Имя автора пишем уже нормализованным: плейлист ищет папку
                    // по этому полю, а на диске она названа через safeName.
                    put("author", author)
                })
                playlistJson = pl
            }
        }
        playlistJson?.let { pl ->
            val folder = File(library.playlistsRoot, library.safeName(pl.optString("title"))).apply { mkdirs() }
            pl.put("video_count", pl.getJSONArray("videos").length())
            val thumb = outDir.listFiles()?.firstOrNull { f -> imageExt(f) != null }
            if (thumb != null) {
                thumb.copyTo(File(folder, "thumbnail.${imageExt(thumb)}"), overwrite = true)
            }
            JsonStore.write(File(folder, "playlist.json"), pl)
        }
        return placed
    }

    private fun imageExt(f: File): String? {
        val e = f.extension.lowercase()
        return if (e in setOf("jpg", "jpeg", "png", "webp")) e else null
    }

    // ---------- уведомления ----------

    private fun notifyProgress(task: DownloadTask, progress: Float) {
        if (!settings.enableNotifications) return
        val n = baseNotification(task.title)
            .setContentText("${progress.toInt()}%")
            .setProgress(100, progress.toInt(), false)
            .setOngoing(true)
            .build()
        runCatching { notifications?.notify(task.id.hashCode(), n) }
    }

    private fun notifyDone(task: DownloadTask, text: String) {
        if (!settings.enableNotifications) return
        val n = baseNotification(task.title)
            .setContentText(text)
            .setContentIntent(openApp())
            .setAutoCancel(true)
            .build()
        runCatching { notifications?.notify(task.id.hashCode(), n) }
    }

    private fun baseNotification(title: String): Notification.Builder =
        Notification.Builder(app, "downloads")
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(title)

    private fun openApp(): PendingIntent {
        val intent = app.packageManager.getLaunchIntentForPackage(app.packageName)
        if (intent != null) {
            intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            return PendingIntent.getActivity(
                app, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        }
        return PendingIntent.getActivity(app, 0, Intent(), PendingIntent.FLAG_IMMUTABLE)
    }

    companion object {
        internal val VIDEO_EXTS = setOf("mp4", "mkv", "webm", "avi", "mov")
        internal val AUDIO_EXTS = setOf("m4a", "mp3", "opus", "aac", "ogg", "flac", "wav")
    }
}
