package io.github.kiramorano.localtube.data

import android.app.Application
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID
import java.util.concurrent.ConcurrentLinkedQueue

class DownloadManager(
    private val app: Application,
    private val library: Library,
    private val settings: Settings
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _tasks = MutableStateFlow<List<DownloadTask>>(emptyList())
    val tasks: StateFlow<List<DownloadTask>> = _tasks.asStateFlow()

    private val queue = ConcurrentLinkedQueue<String>()
    private val canceled = ConcurrentLinkedQueue<String>()
    private var activeId: String? = null
    private var workerRunning = false

    private val notifications by lazy {
        app.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    }

    init {
        val channel = NotificationChannel(
            "downloads", "Загрузки", NotificationManager.IMPORTANCE_LOW
        ).apply { description = "Прогресс загрузки видео" }
        notifications.createNotificationChannel(channel)
    }

    fun add(url: String, formatId: String, title: String, subLangs: String? = null): String {
        val id = UUID.randomUUID().toString().substring(0, 8)
        _tasks.update { list ->
            list + DownloadTask(
                id = id, title = title.ifBlank { "Видео" }, url = url,
                formatId = formatId, status = TaskStatus.WAITING, progress = 0f,
                addedAt = System.currentTimeMillis(), error = null, subLangs = subLangs
            )
        }
        queue.add(id)
        ensureWorker()
        return id
    }

    fun cancel(id: String) {
        canceled.add(id)
        Engine.cancel(id)
    }

    fun remove(id: String) {
        _tasks.update { list -> list.filterNot { it.id == id } }
    }

    fun clearFinished() {
        _tasks.update { list ->
            list.filterNot { it.status == TaskStatus.COMPLETED || it.status == TaskStatus.ERROR || it.status == TaskStatus.CANCELED }
        }
    }

    private fun ensureWorker() {
        if (workerRunning) return
        workerRunning = true
        scope.launch {
            while (true) {
                val id = queue.poll() ?: break
                val task = _tasks.value.firstOrNull { it.id == id } ?: continue
                activeId = id
                runTask(task)
                activeId = null
            }
            workerRunning = false
        }
    }

    private suspend fun runTask(task: DownloadTask) {
        canceled.remove(task.id)
        update(task, TaskStatus.DOWNLOADING, 0f)
        val outDir = File(library.tmpRoot, task.id).apply { mkdirs() }
        try {
            val langs = task.subLangs?.takeIf { it.isNotBlank() } ?: settings.subLangs
            val request = Engine.buildRequest(
                task.url, task.formatId, outDir,
                settings.downloadSubs, langs,
                library.cookiesPath()
            )
            Engine.download(request, task.id) { p ->
                if (p.isFinite() && p in 0f..100f) {
                    _tasks.update { list ->
                        list.map { if (it.id == task.id) it.copy(progress = p) else it }
                    }
                    notifyProgress(task, p)
                }
            }
            if (canceled.contains(task.id)) {
                update(task, TaskStatus.CANCELED, 0f, "Отменено")
                notifyDone(task, "Отменено")
                return
            }
            postProcess(outDir, task.id)
            update(task, TaskStatus.COMPLETED, 100f)
            notifyDone(task, "Готово")
        } catch (e: Exception) {
            if (canceled.contains(task.id)) {
                update(task, TaskStatus.CANCELED, 0f, "Отменено")
                notifyDone(task, "Отменено")
            } else {
                update(task, TaskStatus.ERROR, task.progress, e.message ?: "Ошибка")
                notifyDone(task, "Ошибка: ${e.message ?: ""}")
            }
        } finally {
            outDir.deleteRecursively()
        }
    }

    private fun update(task: DownloadTask, status: TaskStatus, progress: Float, error: String? = null) {
        _tasks.update { list ->
            list.map {
                if (it.id == task.id) {
                    it.copy(status = status, progress = if (status == TaskStatus.COMPLETED) 100f else progress, error = error)
                } else it
            }
        }
    }

    private fun postProcess(outDir: File, taskId: String) {
        val infoFiles = outDir.listFiles()?.filter { it.isFile && it.name.endsWith(".info.json") } ?: return
        var playlistJson: JSONObject? = null
        for (infoFile in infoFiles) {
            val id = infoFile.name.removeSuffix(".info.json")
            val meta = try {
                JSONObject(infoFile.readText(Charsets.UTF_8))
            } catch (_: Exception) {
                continue
            }
            val author = library.safeName(meta.optString("uploader").ifEmpty { "Unknown" })
            val destDir = File(File(library.root, author), id).apply { mkdirs() }
            val videoSrc = outDir.listFiles()
                ?.firstOrNull {
                    it.isFile && it.name.startsWith("$id.") &&
                        it.extension.lowercase() in setOf("mp4", "mkv", "webm", "avi", "mov")
                }
            videoSrc?.let { src ->
                val dest = File(destDir, "video.${src.extension}")
                if (src.absolutePath != dest.absolutePath) src.copyTo(dest, overwrite = true)
            }
            infoFile.copyTo(File(destDir, "info.json"), overwrite = true)
            outDir.listFiles()?.forEach { f ->
                if (!f.isFile) return@forEach
                val name = f.name
                val thumbExt = imageExt(f)
                when {
                    name == "$id.$thumbExt" && thumbExt != null ->
                        f.copyTo(File(destDir, "thumbnail.$thumbExt"), overwrite = true)
                    name.startsWith("$id.") && name.endsWith(".vtt") ->
                        f.copyTo(File(destDir, name.removePrefix("$id.")), overwrite = true)
                }
            }
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
                    put("author", meta.optString("uploader", "Unknown"))
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
            File(folder, "playlist.json").writeText(pl.toString(2), Charsets.UTF_8)
        }
    }

    private fun imageExt(f: File): String? {
        val e = f.extension.lowercase()
        return if (e in setOf("jpg", "jpeg", "png", "webp")) e else null
    }

    private fun notifyProgress(task: DownloadTask, progress: Float) {
        if (!settings.enableNotifications) return
        val n = baseNotification(task.title)
            .setContentText("${progress.toInt()}%")
            .setProgress(100, progress.toInt(), false)
            .build()
        try {
            notifications.notify(task.id.hashCode(), n)
        } catch (_: Exception) {
        }
    }

    private fun notifyDone(task: DownloadTask, text: String) {
        if (!settings.enableNotifications) return
        val n = baseNotification(task.title)
            .setContentText(text)
            .setContentIntent(openApp())
            .setAutoCancel(true)
            .build()
        try {
            notifications.notify(task.id.hashCode(), n)
        } catch (_: Exception) {
        }
    }

    private fun baseNotification(title: String): Notification.Builder {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(app, "downloads")
                .setSmallIcon(android.R.drawable.stat_sys_download)
                .setContentTitle(title)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(app)
                .setSmallIcon(android.R.drawable.stat_sys_download)
                .setContentTitle(title)
        }
    }

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
}
