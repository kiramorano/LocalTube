package io.github.kiramorano.localtube.data

import android.content.Context
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

data class FetchResult(
    val title: String,
    val formats: List<FormatOption>,
    val subLangs: List<String>,
    /** Языки субтитров, доступные у видео: нужны экрану выбора. */
    val availableSubLangs: List<String> = emptyList(),
    val thumbnail: String = "",
    val durationSec: Long = 0,
    val uploader: String = ""
)

/** Запись из удалённого списка видео канала или плейлиста. */
data class RemoteEntry(
    val id: String,
    val title: String,
    val url: String,
    val durationSec: Long = 0,
    val uploader: String = ""
)

/** Итог обхода канала: что есть на канале и чего нет в библиотеке. */
data class RemoteListing(
    val title: String,
    val entries: List<RemoteEntry>,
    /** Разделы, которые не удалось прочитать: канал без Shorts — норма. */
    val skipped: List<String> = emptyList()
)

/** Оформление канала: аналог channel_assets.py на сервере. */
data class ChannelAssets(
    val title: String = "",
    val avatarUrl: String = "",
    val bannerUrl: String = "",
    val description: String = "",
    val subscribers: Long = 0,
    val channelUrl: String = ""
)

object Engine {

    private const val UPDATED_PREF = "ytdlp_updated_v"
    private const val FETCH_TIMEOUT_MS = 120_000L
    private const val UPDATE_TIMEOUT_MS = 300_000L
    private val updateMutex = Mutex()

    /**
     * Пауза между повторами: экспоненциальная от 1 до 10 секунд.
     * yt-dlp принимает только `exp=` / `linear=` / одно число, а список через
     * запятую считает синтаксической ошибкой и завершается, ничего не скачав.
     */
    const val RETRY_SLEEP = "exp=1:10"

    /** Контейнер по умолчанию, как merge_format в app.py. */
    const val DEFAULT_MERGE_FORMAT = "mp4"

    /** Контейнеры для склейки: тот же список, что в диалоге канала на сервере. */
    val MERGE_FORMATS = listOf("mp4", "mkv", "webm")

    /**
     * Незнакомый контейнер заменяем на mp4: значение уходит в командную строку
     * yt-dlp, и произвольная строка оттуда либо всё сломает, либо даст файл,
     * который не откроет плеер.
     */
    fun normalizeMergeFormat(value: String?): String {
        val clean = value?.trim()?.lowercase().orEmpty()
        return if (clean in MERGE_FORMATS) clean else DEFAULT_MERGE_FORMAT
    }

    /**
     * Готовность yt-dlp. init() распаковывает интерпретатор и бинарники, и до
     * его завершения любой execute() падает. Флаг ждут все точки входа.
     */
    private val initialized = kotlinx.coroutines.CompletableDeferred<Boolean>()

    /** Вызывается один раз из Application в фоновом потоке. */
    suspend fun prepare(init: () -> Unit): Boolean {
        if (initialized.isCompleted) return initialized.await()
        val ok = withContext(Dispatchers.IO) {
            try {
                init()
                true
            } catch (e: Exception) {
                false
            }
        }
        initialized.complete(ok)
        return ok
    }

    /**
     * Ждёт распаковки yt-dlp. Без этого нажатие «Показать качества» в первые
     * секунды после установки падало с невнятной ошибкой инициализации.
     */
    private suspend fun awaitReady() {
        if (initialized.isCompleted) {
            if (!initialized.await()) throw RuntimeException(
                "yt-dlp не удалось подготовить. Перезапустите приложение."
            )
            return
        }
        val ok = withTimeoutOrNull(INIT_TIMEOUT_MS) { initialized.await() }
        if (ok != true) throw RuntimeException(
            "yt-dlp ещё готовится к работе. Попробуйте через несколько секунд."
        )
    }

    private const val INIT_TIMEOUT_MS = 60_000L

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
        if (!initialized.isCompleted || !initialized.await()) return false
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
        cookiesPath: String?,
        /** false — показывать только готовые потоки со звуком (до 720p). */
        allowSplitStreams: Boolean = true,
        /** Клиент YouTube (player_client) — как youtube_auth в настройках ПК. */
        playerClient: String = ""
    ): FetchResult {
        val req = YoutubeDLRequest(url).apply {
            addOption("-J")
            addOption("--no-playlist")
            addOption("--no-warnings")
            addOption("--no-call-home")
            addOption("--socket-timeout", 20)
            cookiesPath?.let { addOption("--cookies", it) }
            applyPlayerClient(this, playerClient, url)
        }
        awaitReady()
        return withContext(Dispatchers.IO) {
            val out = try {
                runWithTimeout(processId, FETCH_TIMEOUT_MS) {
                    YoutubeDL.getInstance().execute(req, processId).out
                }
            } catch (e: CancellationException) {
                // Закрытие экрана — не ошибка: гасим процесс и пробрасываем
                // отмену дальше, не подменяя её выдуманной ошибкой yt-dlp.
                runCatching { YoutubeDL.getInstance().destroyProcessById(processId) }
                throw e
            } catch (e: Exception) {
                runCatching { YoutubeDL.getInstance().destroyProcessById(processId) }
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
            val parsed = parseFormatsJson(j.optJSONArray("formats"))
            FetchResult(
                title = j.optString("title", "Видео"),
                // Настройка «предлагать раздельные потоки» действительно влияет
                // на список: раньше переключатель в настройках ничего не делал.
                formats = listOf(bestOption()) +
                    if (allowSplitStreams) parsed else parsed.filterNot { it.needsAudio },
                subLangs = collectSubLangs(j, preferredLangs),
                availableSubLangs = availableSubLangs(j),
                thumbnail = j.optString("thumbnail", ""),
                durationSec = j.optLong("duration", 0),
                uploader = j.optString("uploader", "")
            )
        }
    }

    /**
     * Добавляет extractor-args с выбранным player_client.
     *
     * Пустое значение означает «как решит yt-dlp»: подставлять клиент по
     * умолчанию нельзя, иначе настройка перестаёт быть необязательной.
     *
     * Ссылки не с YouTube пропускаются: `youtube:player_client` понимает только
     * YouTube-экстрактор, и для TikTok такой аргумент — мусор в командной
     * строке. Веб-версия гасит его там же (download_lib.py, po_args).
     */
    private fun applyPlayerClient(req: YoutubeDLRequest, playerClient: String, url: String) {
        extractorArgsFor(url, playerClient)?.let { req.addOption("--extractor-args", it) }
    }

    /**
     * Значение `--extractor-args` или null, если аргумент не нужен.
     *
     * Вынесено отдельно, чтобы тесты проверяли правило без запуска yt-dlp.
     */
    internal fun extractorArgsFor(url: String, playerClient: String): String? {
        if (UrlKind.isTikTok(url)) return null
        val client = playerClient.trim()
        if (client.isEmpty()) return null
        return "youtube:player_client=$client"
    }

    /**
     * Адрес ролика, когда yt-dlp отдал только id.
     *
     * Для YouTube это watch?v=. Для TikTok из id YouTube-ссылку собирать нельзя:
     * 19 цифр — не 11-символьный код, и загрузка ушла бы на чужой сайт.
     */
    internal fun fallbackWatchUrl(id: String, listingUrl: String): String {
        val profile = listingUrl.trim().trimEnd('/').substringBefore('?')
        if (UrlKind.isProfile(profile)) return "$profile/video/$id"
        if (UrlKind.isTikTok(profile)) return profile
        return "https://www.youtube.com/watch?v=$id"
    }

    /**
     * Разделы канала: у корневого адреса yt-dlp отдаёт вкладки, а не видео.
     *
     * У TikTok вкладок нет — профиль сам и есть лента роликов, а адрес
     * `/@author/videos` отдал бы 404.
     */
    internal fun channelTabUrls(channelUrl: String): List<String> {
        val base = channelUrl.trim().trimEnd('/')
        if (base.isEmpty()) return emptyList()
        if (UrlKind.isTikTok(base)) return listOf(base)
        // Ссылка уже указывает на конкретную вкладку: второй суффикс сломал бы её.
        val tabs = listOf("videos", "shorts", "streams")
        if (tabs.any { base.endsWith("/$it") }) return listOf(base)
        return tabs.map { "$base/$it" }
    }

    /**
     * Перечисляет видео канала или плейлиста без скачивания.
     *
     * extract_flat: полные метаданные каждого видео потребовали бы отдельного
     * запроса на ролик, а списку нужны только id и название. Разделы обходятся
     * по одному, и мёртвая вкладка не отменяет весь обход: у канала без Shorts
     * ошибка на /shorts — норма, а не сбой.
     */
    suspend fun listChannel(
        channelUrl: String,
        processId: String,
        cookiesPath: String?,
        playerClient: String = "",
        limitPerTab: Int = 0
    ): RemoteListing {
        awaitReady()
        val urls = channelTabUrls(channelUrl)
        if (urls.isEmpty()) throw RuntimeException("Не указан адрес канала")
        val collected = LinkedHashMap<String, RemoteEntry>()
        val skipped = mutableListOf<String>()
        var title = ""
        var lastError: String? = null

        urls.forEachIndexed { index, url ->
            val req = YoutubeDLRequest(url).apply {
                addOption("-J")
                addOption("--flat-playlist")
                addOption("--no-warnings")
                addOption("--socket-timeout", 30)
                if (limitPerTab > 0) addOption("--playlist-end", limitPerTab)
                cookiesPath?.let { addOption("--cookies", it) }
                applyPlayerClient(this, playerClient, url)
            }
            val tabId = "$processId:$index"
            val out = try {
                withContext(Dispatchers.IO) {
                    runWithTimeout(tabId, LIST_TIMEOUT_MS) {
                        YoutubeDL.getInstance().execute(req, tabId).out
                    }
                }
            } catch (e: CancellationException) {
                runCatching { YoutubeDL.getInstance().destroyProcessById(tabId) }
                throw e
            } catch (e: Exception) {
                lastError = (e.message ?: "ошибка").take(300)
                skipped += url.substringAfterLast('/')
                return@forEachIndexed
            }
            val start = out.indexOf('{')
            if (start < 0) {
                skipped += url.substringAfterLast('/')
                return@forEachIndexed
            }
            val json = runCatching { JSONObject(out.substring(start)) }.getOrNull()
            if (json == null) {
                skipped += url.substringAfterLast('/')
                return@forEachIndexed
            }
            if (title.isEmpty()) {
                title = json.optString("channel").ifEmpty {
                    json.optString("uploader").ifEmpty { json.optString("title", "") }
                }
            }
            collectEntries(json, collected, url)
        }

        // Ошибка объявляется только если не нашлось ничего: одна недоступная
        // вкладка не должна выглядеть как недоступный канал.
        if (collected.isEmpty()) {
            throw RuntimeException(lastError ?: "Не удалось получить список видео")
        }
        return RemoteListing(title = title, entries = collected.values.toList(), skipped = skipped)
    }

    /** Рекурсивно собирает записи: у канала entries вложены по вкладкам. */
    private fun collectEntries(node: JSONObject, out: MutableMap<String, RemoteEntry>, listingUrl: String) {
        val entries = node.optJSONArray("entries") ?: return
        for (i in 0 until entries.length()) {
            val e = entries.optJSONObject(i) ?: continue
            if (e.optJSONArray("entries") != null) {
                collectEntries(e, out, listingUrl)
                continue
            }
            val id = e.optString("id").trim()
            if (id.isEmpty()) continue
            // webpage_url надёжнее: у TikTok в url часто лежит только id,
            // а fallback на youtube.com/watch?v= с 19-значным TikTok-id
            // уводил бы загрузку на чужой сайт.
            val url = e.optString("webpage_url")
                .ifBlank { e.optString("url") }
                .ifBlank { fallbackWatchUrl(id, listingUrl) }
            out.putIfAbsent(
                id,
                RemoteEntry(
                    id = id,
                    title = e.optString("title").ifBlank { "Без названия" },
                    url = url,
                    durationSec = e.optLong("duration", 0),
                    uploader = e.optString("uploader").ifBlank { node.optString("channel", "") }
                )
            )
        }
    }

    /** Полный список языков субтитров у видео, без фильтра по настройкам. */
    private fun availableSubLangs(j: JSONObject): List<String> {
        val avail = LinkedHashSet<String>()
        j.optJSONObject("subtitles")?.keys()?.forEach { avail.add(it) }
        j.optJSONObject("automatic_captions")?.keys()?.forEach { avail.add(it) }
        return avail.toList()
    }

    private const val LIST_TIMEOUT_MS = 180_000L

    /**
     * Запускает блокирующий вызов yt-dlp с ограничением по времени.
     *
     * Обычный withTimeout здесь бесполезен: execute() ждёт нативный процесс и
     * не реагирует на отмену корутины, поэтому withTimeout отменял дочернюю
     * задачу и сам вставал в ожидание навсегда. Единственный способ разблокировать
     * вызов — убить процесс, что и делается по истечении таймаута.
     */
    private suspend fun <T> runWithTimeout(
        processId: String,
        timeoutMs: Long,
        block: () -> T
    ): T {
        // Намеренно вне structured concurrency: coroutineScope дожидался бы
        // зависшего потомка, а он как раз и не отвечает на отмену.
        val job = detachedScope.async { block() }
        val done = withTimeoutOrNull(timeoutMs) {
            runCatching { job.await() }
        }
        if (done != null) return done.getOrThrow()
        // Процесс убиваем: только это разблокирует нативный вызов. Дальше
        // корутину можно бросить, она завершится сама с ошибкой.
        runCatching { YoutubeDL.getInstance().destroyProcessById(processId) }
        job.cancel()
        throw RuntimeException(
            "Превышено время ожидания. Проверьте интернет или обновите yt-dlp в настройках."
        )
    }

    /** Область для блокирующих вызовов, которые допустимо оставить позади. */
    private val detachedScope =
        kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + Dispatchers.IO)

    /**
     * Языки субтитров для скачивания. Сравнение регистронезависимое: yt-dlp
     * отдаёт ключи вида zh-Hans и pt-BR, и приведённая к нижнему регистру
     * настройка с ними никогда не совпадала.
     */
    internal fun chooseSubLangs(available: Collection<String>, preferred: List<String>): List<String> {
        if (available.isEmpty()) return emptyList()
        val byLower = LinkedHashMap<String, String>()
        available.forEach { byLower.putIfAbsent(it.lowercase(), it) }
        val chosen = LinkedHashSet<String>()
        preferred.map { it.trim().lowercase() }.filter { it.isNotBlank() }.forEach { want ->
            byLower[want]?.let { chosen.add(it) }
                // ru подходит и для ru-RU: точного совпадения часто нет.
                ?: byLower.entries.firstOrNull {
                    it.key.substringBefore('-') == want.substringBefore('-')
                }?.let { chosen.add(it.value) }
        }
        // Без совпадений ничего не качаем: раньше подставлялись два случайных
        // языка, которых пользователь не просил.
        return chosen.toList()
    }

    private fun collectSubLangs(j: JSONObject, preferred: List<String>): List<String> {
        val avail = LinkedHashSet<String>()
        j.optJSONObject("subtitles")?.keys()?.forEach { avail.add(it) }
        j.optJSONObject("automatic_captions")?.keys()?.forEach { avail.add(it) }
        return chooseSubLangs(avail, preferred)
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
            // acodec != "none" обязателен: у раскадровок (storyboard, ext=mhtml)
            // оба кодека равны "none", и они попадали в список как «Аудио mhtml».
            if (vcodec == "none" && acodec != "none" && acodec.isNotBlank()) {
                val formatId = o.optString("format_id")
                if (formatId.isBlank()) continue
                val key = o.optString("ext", "") + o.optLong("abr", 0)
                if (!seenAudio.add(key)) continue
                out += FormatOption(
                    formatId = formatId,
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
     *
     * У TikTok отдельных потоков нет, а числовые id форматов YouTube там не
     * существуют: любой YouTube-селектор кончается отказом «Requested format is
     * not available». Поэтому для TikTok выбор сводится к одному потоку, и
     * сохраняется только пожелание «звук отдельно» (download_lib.py делает так же).
     */
    internal fun formatSelector(formatId: String, url: String = ""): String {
        if (UrlKind.isTikTok(url)) {
            return if (formatId.startsWith("audio:") || formatId.startsWith("bestaudio")) {
                "bestaudio/best"
            } else {
                "best"
            }
        }
        return when {
            formatId == "best" -> "bestvideo*+bestaudio/best"
            formatId.startsWith("video:") ->
                "${formatId.removePrefix("video:")}+bestaudio/${formatId.removePrefix("video:")}"
            formatId.startsWith("audio:") -> formatId.removePrefix("audio:")
            else -> formatId
        }
    }

    /** Селекторы одного потока: аудио отдельным форматом там не существует. */
    private val SINGLE_STREAM = setOf("best", "worst")

    /**
     * Дописывает к селектору приоритет языка аудиодорожки — как
     * download_prefs.audio_format_selector в веб-версии.
     *
     * У видео с несколькими озвучками yt-dlp брал дорожку по умолчанию, то есть
     * язык оригинала, а не тот, что нужен. Фильтр вешается только на аудиочасть:
     * у видеопотока поля language нет.
     *
     * Оператор `^=` (начинается с), а не `=`: YouTube отдаёт дорожки как `ru-RU`
     * и `en-US`, точного совпадения с `ru` обычно нет.
     *
     * Исходный селектор остаётся последним запасом — у большинства видео дорожка
     * одна и вообще без языка, иначе не скачалось бы ничего.
     */
    internal fun audioFormatSelector(selector: String, langs: List<String>): String {
        val wanted = langs.map { it.trim() }.filter { it.isNotEmpty() }
        if (selector.isBlank() || wanted.isEmpty()) return selector
        val head = selector.split('/').first()
        if (head.trim() in SINGLE_STREAM) return selector

        val audio = Regex("""\b(bestaudio|worstaudio)\b""")
        if (!audio.containsMatchIn(head)) return selector

        val variants = LinkedHashSet<String>()
        wanted.forEach { lang ->
            variants += audio.replace(head) { m -> "${m.groupValues[1]}[language^=$lang]" }
        }
        variants += selector
        return variants.joinToString("/")
    }

    fun buildRequest(
        url: String,
        formatId: String,
        outDir: File,
        downloadSubs: Boolean,
        subLangs: String,
        cookiesPath: String?,
        playerClient: String = "",
        mergeFormat: String = DEFAULT_MERGE_FORMAT,
        audioLangs: List<String> = emptyList()
    ): YoutubeDLRequest {
        val req = YoutubeDLRequest(url)
        val f = audioFormatSelector(formatSelector(formatId, url), audioLangs)
        req.addOption("-f", f)
        req.addOption("-o", File(outDir, "%(id)s.%(ext)s").absolutePath)
        req.addOption("--merge-output-format", normalizeMergeFormat(mergeFormat))
        req.addOption("--write-info-json")
        req.addOption("--write-thumbnail")
        req.addOption("--no-warnings")
        req.addOption("--socket-timeout", 30)
        req.addOption("-c")
        req.addOption("--no-mtime")
        req.addOption("--retries", 10)
        req.addOption("--fragment-retries", 10)
        // Пауза между попытками растёт от 1 до 10 секунд. Синтаксис строгий:
        // список через запятую yt-dlp не принимает и сразу завершается с ошибкой.
        req.addOption("--retry-sleep", RETRY_SLEEP)
        cookiesPath?.let { req.addOption("--cookies", it) }
        applyPlayerClient(req, playerClient, url)
        if (downloadSubs && subLangs.isNotBlank()) {
            req.addOption("--write-subs")
            req.addOption("--write-auto-subs")
            req.addOption("--sub-langs", subLangs)
        }
        return req
    }

    /**
     * Догружает субтитры к уже скачанному видео, не качая само видео заново.
     * Аналог /api/subtitles/download/<id> на сервере.
     */
    suspend fun downloadSubtitles(
        videoUrl: String,
        langs: String,
        outDir: File,
        processId: String,
        cookiesPath: String?,
        playerClient: String = ""
    ): List<File> {
        if (langs.isBlank()) return emptyList()
        awaitReady()
        val before = subtitleSnapshot(outDir)
        val req = YoutubeDLRequest(videoUrl).apply {
            // --skip-download: видео уже на диске, нужны только дорожки.
            addOption("--skip-download")
            addOption("--write-subs")
            addOption("--write-auto-subs")
            addOption("--sub-langs", langs)
            addOption("--sub-format", "vtt/srt/best")
            addOption("--convert-subs", "vtt")
            addOption("-o", File(outDir, "%(id)s.%(ext)s").absolutePath)
            addOption("--no-warnings")
            addOption("--socket-timeout", 30)
            cookiesPath?.let { addOption("--cookies", it) }
            applyPlayerClient(this, playerClient, videoUrl)
        }
        withContext(Dispatchers.IO) {
            try {
                runWithTimeout(processId, FETCH_TIMEOUT_MS) {
                    YoutubeDL.getInstance().execute(req, processId).out
                }
            } catch (e: CancellationException) {
                runCatching { YoutubeDL.getInstance().destroyProcessById(processId) }
                throw e
            } catch (e: Exception) {
                runCatching { YoutubeDL.getInstance().destroyProcessById(processId) }
                throw RuntimeException("yt-dlp: ${(e.message ?: "ошибка").take(300)}")
            }
        }
        // Возвращаем только новые файлы: экран показывает, что реально добавилось.
        return subtitleSnapshot(outDir).filterNot { before.contains(it) }
    }

    private fun subtitleSnapshot(dir: File): Set<File> =
        dir.listFiles()
            ?.filter { it.isFile && it.extension.lowercase() in setOf("vtt", "srt") }
            ?.toSet()
            ?: emptySet()

    /**
     * Адрес аватара и баннера канала. Заменяет download_avatars.py: сами файлы
     * скачивает вызывающий, здесь только адреса из метаданных.
     */
    suspend fun fetchChannelAssets(
        channelUrl: String,
        processId: String,
        cookiesPath: String?,
        playerClient: String = ""
    ): ChannelAssets {
        awaitReady()
        val req = YoutubeDLRequest(channelUrl).apply {
            addOption("-J")
            addOption("--flat-playlist")
            // Одна запись: метаданные канала лежат в корне ответа, а полный
            // обход ради аватара занял бы минуты.
            addOption("--playlist-end", 1)
            addOption("--no-warnings")
            addOption("--socket-timeout", 30)
            cookiesPath?.let { addOption("--cookies", it) }
            applyPlayerClient(this, playerClient, channelUrl)
        }
        val out = withContext(Dispatchers.IO) {
            try {
                runWithTimeout(processId, FETCH_TIMEOUT_MS) {
                    YoutubeDL.getInstance().execute(req, processId).out
                }
            } catch (e: CancellationException) {
                runCatching { YoutubeDL.getInstance().destroyProcessById(processId) }
                throw e
            } catch (e: Exception) {
                runCatching { YoutubeDL.getInstance().destroyProcessById(processId) }
                throw RuntimeException("yt-dlp: ${(e.message ?: "ошибка").take(300)}")
            }
        }
        val start = out.indexOf('{')
        if (start < 0) throw RuntimeException("yt-dlp не вернул данные о канале")
        val j = runCatching { JSONObject(out.substring(start)) }.getOrNull()
            ?: throw RuntimeException("Не удалось разобрать данные о канале")
        return parseChannelAssets(j)
    }

    /**
     * Разбирает метаданные канала. Вынесено отдельно: у thumbnails нет
     * гарантированного порядка, и выбор «самой большой картинки» надо проверять
     * тестом без запуска yt-dlp.
     */
    internal fun parseChannelAssets(j: JSONObject): ChannelAssets {
        var avatar = ""
        var avatarArea = -1
        var banner = ""
        var bannerRatio = 0.0
        val thumbs = j.optJSONArray("thumbnails")
        if (thumbs != null) {
            for (i in 0 until thumbs.length()) {
                val t = thumbs.optJSONObject(i) ?: continue
                val url = t.optString("url")
                if (url.isBlank()) continue
                val w = t.optInt("width", 0)
                val h = t.optInt("height", 0)
                val id = t.optString("id")
                // Баннер широкий (примерно 6:1), аватар квадратный. Поле id у
                // YouTube называется avatar_uncropped/banner_uncropped, но оно
                // есть не всегда, поэтому решаем и по пропорциям.
                val ratio = if (h > 0) w.toDouble() / h else 0.0
                if (id.contains("banner") || ratio >= 3.0) {
                    // Условие «или банner ещё не найден» обязательно: у записи,
                    // опознанной по id, размеров может не быть вовсе, и по одному
                    // сравнению пропорций она всегда проигрывала бы нулю.
                    if (banner.isEmpty() || ratio > bannerRatio) {
                        bannerRatio = ratio
                        banner = url
                    }
                } else {
                    val area = w * h
                    if (area > avatarArea) {
                        avatarArea = area
                        avatar = url
                    }
                }
            }
        }
        return ChannelAssets(
            title = j.optString("channel").ifEmpty { j.optString("uploader", "") },
            avatarUrl = avatar,
            bannerUrl = banner,
            description = j.optString("description", ""),
            subscribers = j.optLong("channel_follower_count", 0),
            channelUrl = j.optString("channel_url").ifEmpty { j.optString("uploader_url", "") }
        )
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
        awaitReady()
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
