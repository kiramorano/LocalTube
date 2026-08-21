package io.github.kiramorano.localtube.data

import android.content.Context
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

data class FetchResult(
    val title: String,
    val formats: List<FormatOption>,
    val subLangs: List<String>
)

object Engine {

    private const val UPDATED_PREF = "ytdlp_updated_v"
    private const val FETCH_TIMEOUT_MS = 120_000L
    private const val UPDATE_TIMEOUT_MS = 300_000L
    private val updateMutex = Mutex()

    fun appVersion(app: Context): String = try {
        app.packageManager.getPackageInfo(app.packageName, 0).versionName ?: "1"
    } catch (_: Exception) {
        "1"
    }

    /**
     * Обновляет встроенный yt-dlp до последней стабильной версии, но не чаще одного раза за версию приложения.
     * Возвращает true, если yt-dlp актуален (или только что обновлён).
     */
    suspend fun ensureYtDlpFresh(app: Context, appVersion: String): Boolean {
        val sp = app.getSharedPreferences("localtube", Context.MODE_PRIVATE)
        if (sp.getString(UPDATED_PREF, "") == appVersion) return true
        return withContext(Dispatchers.IO) {
            updateMutex.withLock {
                if (sp.getString(UPDATED_PREF, "") == appVersion) {
                    true
                } else {
                    val ok = try {
                        withTimeout(UPDATE_TIMEOUT_MS) {
                            YoutubeDL.getInstance().updateYoutubeDL(app, YoutubeDL.UpdateChannel.STABLE)
                        }
                        true
                    } catch (_: Exception) {
                        false
                    }
                    if (ok) sp.edit().putString(UPDATED_PREF, appVersion).apply()
                    ok
                }
            }
        }
    }

    /**
     * Получает название, форматы и доступные языки субтитров. Использует `-J`, чтобы иметь возможность
     * прервать зависший процесс по таймауту.
     */
    suspend fun fetchInfo(
        url: String,
        processId: String,
        preferredLangs: List<String>,
        cookiesPath: String?
    ): FetchResult {
        val req = YoutubeDLRequest(url).apply {
            addOption("-J")
            addOption("--no-playlist")
            addOption("--no-warnings")
            addOption("--no-call-home")
            addOption("--socket-timeout", 20)
            cookiesPath?.let { addOption("--cookies", it) }
        }
        return withContext(Dispatchers.IO) {
            val out = try {
                withTimeout(FETCH_TIMEOUT_MS) {
                    withContext(Dispatchers.IO) {
                        YoutubeDL.getInstance().execute(req, processId).out
                    }
                }
            } catch (e: TimeoutCancellationException) {
                YoutubeDL.getInstance().destroyProcessById(processId)
                throw RuntimeException("Превышено время ожидания. Проверьте интернет или обновите yt-dlp в настройках.")
            } catch (e: Exception) {
                YoutubeDL.getInstance().destroyProcessById(processId)
                throw RuntimeException("yt-dlp: ${(e.message ?: "ошибка").take(500)}")
            }
            val start = out.indexOf('{')
            if (start < 0) {
                throw RuntimeException("yt-dlp не вернул данные. Попробуйте обновить yt-dlp в настройках.")
            }
            val j = try {
                JSONObject(out.substring(start))
            } catch (e: Exception) {
                throw RuntimeException("Не удалось разобрать ответ yt-dlp.")
            }
            FetchResult(
                title = j.optString("title", "Видео"),
                formats = listOf(bestOption()) + parseFormatsJson(j.optJSONArray("formats")),
                subLangs = collectSubLangs(j, preferredLangs)
            )
        }
    }

    private fun collectSubLangs(j: JSONObject, preferred: List<String>): List<String> {
        val avail = LinkedHashSet<String>()
        j.optJSONObject("subtitles")?.keys()?.forEach { avail.add(it) }
        j.optJSONObject("automatic_captions")?.keys()?.forEach { avail.add(it) }
        if (avail.isEmpty()) return emptyList()
        val pref = preferred.map { it.trim().lowercase() }.filter { it.isNotBlank() }
        val chosen = pref.filter { it in avail }
        return if (chosen.isNotEmpty()) chosen else avail.take(2)
    }

    private fun bestOption() = FormatOption(
        formatId = "best",
        label = "Лучшее доступное",
        isVideo = true,
        resolution = "auto",
        ext = "mp4",
        sizeMb = 0.0,
        fps = 0,
        codec = ""
    )

    /**
     * Разбирает список форматов.
     *
     * YouTube отдаёт 1080p и выше только раздельными потоками: видео без звука
     * плюс отдельное аудио. Раньше фильтр требовал наличия звуковой дорожки, из
     * за чего список качеств обрывался на 720p. Теперь такие потоки тоже
     * попадают в список и помечаются префиксом video:, чтобы при загрузке
     * склеиваться с лучшим аудио.
     */
    internal fun parseFormatsJson(arr: JSONArray?): List<FormatOption> {
        val out = mutableListOf<FormatOption>()
        if (arr == null) return out
        // Для каждой высоты храним лучший вариант: со звуком предпочтительнее
        // только если раздельного потока той же высоты нет.
        val byHeight = LinkedHashMap<Int, FormatOption>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val h = o.optInt("height", 0)
            if (h <= 0) continue
            val vcodec = o.optString("vcodec", "none")
            if (vcodec == "none") continue
            val acodec = o.optString("acodec", "none")
            val hasAudio = acodec != "none" && acodec.isNotBlank()
            val fps = o.optInt("fps", 0)
            val rawId = o.optString("format_id")
            if (rawId.isBlank()) continue

            val option = FormatOption(
                // Раздельный поток помечаем, чтобы buildRequest добавил bestaudio.
                formatId = if (hasAudio) rawId else "video:$rawId",
                label = buildString {
                    append("${h}p")
                    if (fps > 30) append(" $fps")
                    if (!hasAudio) append(" ·")
                },
                isVideo = true,
                resolution = "${h}p",
                ext = o.optString("ext", ""),
                sizeMb = fileSize(o) / 1024.0 / 1024.0,
                fps = fps,
                codec = vcodec.substringBefore("."),
                needsAudio = !hasAudio
            )
            val existing = byHeight[h]
            if (existing == null) {
                byHeight[h] = option
            } else if (existing.fps < fps) {
                // При равной высоте выбираем более плавный вариант.
                byHeight[h] = option
            }
        }
        // Сначала высокое качество.
        byHeight.entries.sortedByDescending { it.key }.forEach { out += it.value }
        val seenAudio = HashSet<String>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val vcodec = o.optString("vcodec", "none")
            val acodec = o.optString("acodec", "")
            if (vcodec == "none" && acodec.isNotBlank()) {
                val key = o.optString("ext", "") + o.optLong("abr", 0)
                if (!seenAudio.add(key)) continue
                out += FormatOption(
                    formatId = o.optString("format_id"),
                    label = "Аудио ${o.optString("format_note").ifBlank { o.optString("ext", "m4a") }}",
                    isVideo = false,
                    resolution = "audio",
                    ext = o.optString("ext", "m4a"),
                    sizeMb = fileSize(o) / 1024.0 / 1024.0,
                    fps = 0,
                    codec = acodec.substringBefore(".")
                )
            }
        }
        return out
    }

    private fun fileSize(o: JSONObject): Long {
        val f = o.optLong("filesize", 0)
        return if (f > 0) f else o.optLong("filesize_approx", 0)
    }

    /**
     * Строит селектор формата для yt-dlp.
     *
     * "best" раньше давал best[ext=mp4]/best — прогрессивный поток, то есть не
     * выше 720p. Теперь запрашивается лучшее видео плюс лучшее аудио.
     */
    internal fun formatSelector(formatId: String): String = when {
        formatId == "best" -> "bestvideo*+bestaudio/best"
        formatId.startsWith("video:") ->
            "${formatId.removePrefix("video:")}+bestaudio/${formatId.removePrefix("video:")}"
        formatId.startsWith("audio:") -> formatId.removePrefix("audio:")
        else -> formatId
    }

    fun buildRequest(
        url: String,
        formatId: String,
        outDir: File,
        downloadSubs: Boolean,
        subLangs: String,
        cookiesPath: String?
    ): YoutubeDLRequest {
        val req = YoutubeDLRequest(url)
        val f = formatSelector(formatId)
        req.addOption("-f", f)
        req.addOption("-o", File(outDir, "%(id)s.%(ext)s").absolutePath)
        req.addOption("--merge-output-format", "mp4")
        req.addOption("--write-info-json")
        req.addOption("--write-thumbnail")
        req.addOption("--no-warnings")
        req.addOption("--socket-timeout", 30)
        req.addOption("-c")
        req.addOption("--no-mtime")
        req.addOption("--retries", 10)
        req.addOption("--fragment-retries", 10)
        req.addOption("--retry-sleep", "1,10")
        cookiesPath?.let { req.addOption("--cookies", it) }
        if (downloadSubs && subLangs.isNotBlank()) {
            req.addOption("--write-subs")
            req.addOption("--write-auto-subs")
            req.addOption("--sub-langs", subLangs)
        }
        return req
    }

    /**
     * Запускает загрузку.
     *
     * Коллбэк получает не только процент, но и оставшееся время со скоростью:
     * раньше эти данные приходили от yt-dlp и отбрасывались, поэтому в очереди
     * не было ни скорости, ни ETA.
     */
    suspend fun download(
        request: YoutubeDLRequest,
        processId: String,
        onProgress: (progress: Float, etaSeconds: Long, line: String) -> Unit
    ) {
        withContext(Dispatchers.IO) {
            YoutubeDL.getInstance().execute(request, processId) { progress, etaSeconds, line ->
                onProgress(progress, etaSeconds, line ?: "")
            }
        }
    }

    /** Вытаскивает скорость из строки прогресса yt-dlp: "... at 1.25MiB/s ...". */
    internal fun parseSpeed(line: String): String {
        val match = Regex("""at\s+([0-9.]+\s*[KMG]?i?B/s)""", RegexOption.IGNORE_CASE).find(line)
        return match?.groupValues?.getOrNull(1)?.trim().orEmpty()
    }

    fun cancel(processId: String) {
        YoutubeDL.getInstance().destroyProcessById(processId)
    }
}
