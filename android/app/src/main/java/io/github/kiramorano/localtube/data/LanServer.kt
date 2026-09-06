package io.github.kiramorano.localtube.data

import java.io.BufferedOutputStream
import java.io.File
import java.io.InputStream
import java.io.OutputStream
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import java.util.concurrent.Executors
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit

/**
 * Минимальный HTTP-сервер для раздачи библиотеки в локальную сеть.
 *
 * Написан на ServerSocket, без сторонних библиотек: нужен небольшой набор
 * возможностей (GET, POST, Range для видео, cookie), а NanoHTTPD и подобные
 * тянут за собой заброшенные зависимости.
 *
 * Обрабатывается ровно то подмножество HTTP/1.1, которое нужно браузеру:
 * запросная строка, заголовки, тело для POST, ответы с Content-Length и
 * поддержка Range. Соединение всегда закрывается после ответа
 * (Connection: close) — keep-alive сэкономил бы рукопожатия, но требует
 * аккуратного разбора границ тела, а цена ошибки здесь — зависший поток.
 *
 * Права: гость без верного PIN не получает ничего, кроме страницы входа,
 * проверки доступности и самой проверки PIN. Разрешения перечислены явно
 * (белый список), как в GUEST_ENDPOINTS на сервере: обратный порядок означал бы,
 * что каждый новый маршрут открыт всей сети, пока про него не вспомнят.
 */
class LanServer(
    private val library: Source,
    private val access: Guard
) {

    /**
     * То, что сервер берёт из библиотеки.
     *
     * Узкий интерфейс вместо самих Library и UserDataStore: те требуют Context и
     * читают диск, а сервер пользуется лишь горсткой методов. Заодно это делает
     * его проверяемым обычными юнит-тестами, без эмулятора.
     */
    interface Source {
        val videosRoot: File
        val userVideosRoot: File
        val avatarsDir: File
        val bannersDir: File

        fun catalog(): Catalog
        fun findVideo(id: String): VideoItem?
        fun videosOf(author: String): List<VideoItem>
        fun search(query: String): List<VideoItem>

        /** Файлы субтитров рядом с видео: пара «язык, имя файла». */
        fun subtitlesOf(v: VideoItem): List<Pair<String, String>>

        fun isChannelHidden(author: String): Boolean
        fun hiddenChannels(): Set<String>
    }

    /** Проверка прав гостя. Отделена, чтобы тесты не заводили реальный PIN. */
    interface Guard {
        fun isValidToken(token: String?): Boolean
        fun checkPin(input: String?, address: String): LanAccess.PinResult
    }

    @Volatile
    private var socket: ServerSocket? = null

    @Volatile
    private var pool: ThreadPoolExecutor? = null

    @Volatile
    private var acceptor: Thread? = null

    /** Порт, на котором сервер реально слушает, либо 0. */
    @Volatile
    var activePort: Int = 0
        private set

    /** Последняя ошибка запуска: показывается в настройках. */
    @Volatile
    var lastError: String = ""
        private set

    val isRunning: Boolean
        get() = socket?.isClosed == false

    /**
     * Поднимает сервер. Возвращает true, если слушает.
     *
     * Порт может быть занят другим приложением, и тогда занятость надо показать
     * пользователю, а не падать: с телефона выбрать свободный порт вручную —
     * нормальный сценарий.
     */
    fun start(port: Int): Boolean {
        stop()
        return try {
            val server = ServerSocket(port)
            // Небольшой таймаут на accept: без него поток висит в accept
            // навсегда и не замечает закрытия сервера.
            server.soTimeout = ACCEPT_TIMEOUT_MS
            socket = server
            activePort = server.localPort
            lastError = ""
            val executor = Executors.newFixedThreadPool(MAX_THREADS) as ThreadPoolExecutor
            pool = executor
            val thread = Thread({ acceptLoop(server, executor) }, "lan-acceptor")
            thread.isDaemon = true
            acceptor = thread
            thread.start()
            true
        } catch (e: Exception) {
            lastError = e.message ?: "не удалось занять порт"
            activePort = 0
            socket = null
            false
        }
    }

    fun stop() {
        runCatching { socket?.close() }
        socket = null
        activePort = 0
        pool?.let { executor ->
            executor.shutdownNow()
            // Ждём недолго: висящая отдача большого видео всё равно оборвётся
            // по закрытию сокета, а блокировать UI надолго нельзя.
            runCatching { executor.awaitTermination(1, TimeUnit.SECONDS) }
        }
        pool = null
        acceptor = null
    }

    private fun acceptLoop(server: ServerSocket, executor: ThreadPoolExecutor) {
        while (!server.isClosed) {
            val client = try {
                server.accept()
            } catch (e: java.net.SocketTimeoutException) {
                continue
            } catch (e: Exception) {
                break
            }
            val accepted = runCatching {
                executor.execute {
                    runCatching { handle(client) }
                    runCatching { client.close() }
                }
            }.isSuccess
            // Пул переполнен или уже погашен: соединение надо закрыть, иначе
            // клиент будет ждать ответа до таймаута.
            if (!accepted) runCatching { client.close() }
        }
    }

    // ---------- разбор запроса ----------

    private class Request(
        val method: String,
        val path: String,
        val query: Map<String, String>,
        val headers: Map<String, String>,
        val body: String,
        val remote: String
    ) {
        fun cookie(name: String): String? {
            val raw = headers["cookie"] ?: return null
            return raw.split(';')
                .map { it.trim() }
                .firstOrNull { it.startsWith("$name=") }
                ?.substringAfter('=')
        }
    }

    private fun handle(client: Socket) {
        client.soTimeout = READ_TIMEOUT_MS
        val input = client.getInputStream().buffered()
        val output = BufferedOutputStream(client.getOutputStream())
        val request = readRequest(input, client) ?: return
        route(request, output)
        runCatching { output.flush() }
    }

    private fun readRequest(input: InputStream, client: Socket): Request? {
        val line = readLine(input) ?: return null
        val parts = line.split(' ')
        if (parts.size < 2) return null
        val method = parts[0].uppercase()
        val target = parts[1]

        val headers = HashMap<String, String>()
        while (true) {
            val header = readLine(input) ?: break
            if (header.isEmpty()) break
            val idx = header.indexOf(':')
            if (idx <= 0) continue
            // Имена заголовков регистронезависимы, поэтому ключи приводим к
            // нижнему регистру: браузеры пишут и Range, и range.
            headers[header.substring(0, idx).trim().lowercase()] =
                header.substring(idx + 1).trim()
        }

        val length = headers["content-length"]?.toIntOrNull() ?: 0
        val body = if (length in 1..MAX_BODY) {
            val buf = ByteArray(length)
            var read = 0
            while (read < length) {
                val n = input.read(buf, read, length - read)
                if (n <= 0) break
                read += n
            }
            String(buf, 0, read, Charsets.UTF_8)
        } else ""

        val path = decode(target.substringBefore('?'))
        val query = target.substringAfter('?', "")
            .split('&')
            .filter { it.isNotBlank() }
            .associate { pair ->
                decode(pair.substringBefore('=')) to decode(pair.substringAfter('=', ""))
            }

        return Request(
            method = method,
            path = path,
            query = query,
            headers = headers,
            body = body,
            remote = client.inetAddress?.hostAddress ?: ""
        )
    }

    /** Чтение строки до CRLF без буферизации сверх нужного. */
    private fun readLine(input: InputStream): String? {
        val out = StringBuilder()
        while (true) {
            val b = input.read()
            if (b < 0) return if (out.isEmpty()) null else out.toString()
            if (b == '\n'.code) return out.toString().removeSuffix("\r")
            out.append(b.toChar())
            if (out.length > MAX_LINE) return null
        }
    }

    private fun decode(value: String): String =
        runCatching { URLDecoder.decode(value, "UTF-8") }.getOrDefault(value)

    // ---------- маршрутизация ----------

    private fun route(req: Request, out: OutputStream) {
        val authorized = access.isValidToken(req.cookie(LanAccess.TOKEN_COOKIE))

        // Доступно без PIN: проверка доступности сервера, вход и страница входа.
        when {
            req.path == "/api/network/ping" -> return sendJson(out, 200, pingJson())
            req.path == "/api/network/unlock" && req.method == "POST" -> return unlock(req, out)
            req.path == "/unlock" -> return sendHtml(out, 200, LanPages.unlockPage())
        }

        if (!authorized) {
            // Страницы отправляем на форму ввода PIN, запросы данных — с 401:
            // редирект в ответ на fetch показал бы гостю HTML вместо JSON.
            return if (req.path.startsWith("/api/")) {
                sendJson(out, 401, """{"error":"Нужен PIN","guest":true}""")
            } else {
                sendRedirect(out, "/unlock")
            }
        }

        val segments = req.path.trim('/').split('/').filter { it.isNotBlank() }
        when {
            req.path == "/" -> sendHtml(out, 200, LanPages.indexPage(visibleCatalog()))
            // Форма поиска в шапке отправляет сюда обычным GET: страница должна
            // работать и без JavaScript.
            req.path == "/search" -> {
                val q = req.query["q"].orEmpty()
                sendHtml(out, 200, LanPages.searchPage(q, searchVisible(q)))
            }
            segments.size == 2 && segments[0] == "watch" ->
                watchPage(segments[1], out)
            segments.size == 2 && segments[0] == "channel" ->
                channelPage(segments[1], out)
            segments.firstOrNull() == "media" ->
                sendLibraryFile(req, out, library.videosRoot, segments.drop(1))
            segments.firstOrNull() == "usermedia" ->
                sendLibraryFile(req, out, library.userVideosRoot, segments.drop(1))
            segments.firstOrNull() == "avatars" ->
                sendLibraryFile(req, out, library.avatarsDir, segments.drop(1))
            segments.firstOrNull() == "banners" ->
                sendLibraryFile(req, out, library.bannersDir, segments.drop(1))
            req.path == "/api/catalog" -> sendJson(out, 200, LanPages.catalogJson(visibleCatalog()))
            req.path == "/api/search" ->
                sendJson(out, 200, LanPages.searchJson(searchVisible(req.query["q"].orEmpty())))
            segments.size == 3 && segments[0] == "api" && segments[1] == "video" ->
                videoJson(segments[2], out)
            segments.size == 3 && segments[0] == "api" && segments[1] == "thumbnail" ->
                thumbnail(segments[2], out)
            else -> sendText(out, 404, "Не найдено")
        }
    }

    private fun unlock(req: Request, out: OutputStream) {
        // PIN приходит и из формы (application/x-www-form-urlencoded), и из
        // JSON: страница входа работает без JavaScript, а API удобнее с JSON.
        val pin = if (req.body.trimStart().startsWith("{")) {
            Regex("\"pin\"\\s*:\\s*\"([^\"]*)\"").find(req.body)?.groupValues?.get(1)
        } else {
            req.body.split('&')
                .firstOrNull { it.startsWith("pin=") }
                ?.substringAfter('=')
                ?.replace('+', ' ')
                ?.let { decode(it) }
        }
        val wantsHtml = !req.body.trimStart().startsWith("{")
        when (val result = access.checkPin(pin, req.remote)) {
            is LanAccess.PinResult.Ok -> {
                val cookie = "${LanAccess.TOKEN_COOKIE}=${result.token}; Max-Age=" +
                    "${LanAccess.COOKIE_MAX_AGE_SEC}; Path=/; HttpOnly; SameSite=Lax"
                if (wantsHtml) {
                    sendResponse(
                        out, 303, "text/html; charset=utf-8", ByteArray(0),
                        extraHeaders = listOf("Set-Cookie: $cookie", "Location: /")
                    )
                } else {
                    sendJson(out, 200, """{"ok":true}""", listOf("Set-Cookie: $cookie"))
                }
            }
            is LanAccess.PinResult.Wrong -> {
                if (wantsHtml) {
                    sendHtml(out, 403, LanPages.unlockPage("Неверный PIN. Осталось попыток: ${result.attemptsLeft}"))
                } else {
                    sendJson(
                        out, 403,
                        """{"error":"Неверный PIN","attempts_left":${result.attemptsLeft}}"""
                    )
                }
            }
            is LanAccess.PinResult.TooMany -> {
                val msg = "Слишком много попыток. Повторите через ${result.retryAfterSec} с."
                if (wantsHtml) sendHtml(out, 429, LanPages.unlockPage(msg))
                else sendJson(
                    out, 429,
                    """{"error":"${LanPages.escapeJson(msg)}","retry_after":${result.retryAfterSec}}"""
                )
            }
        }
    }

    private fun pingJson(): String {
        val catalog = visibleCatalog()
        val count = catalog.videos.size + catalog.shorts.size + catalog.userVideos.size
        return """{"app":"LocalTube","title":"LocalTube на Android","videos":$count,"guest_allowed":true}"""
    }

    private fun watchPage(id: String, out: OutputStream) {
        val video = findVisible(id) ?: return sendText(out, 404, "Видео не найдено")
        val subs = library.subtitlesOf(video)
        sendHtml(out, 200, LanPages.watchPage(video, mediaUrl(video), subs, subtitleBase(video)))
    }

    private fun channelPage(author: String, out: OutputStream) {
        if (library.isChannelHidden(author)) return sendText(out, 404, "Канал не найден")
        val videos = library.videosOf(author)
        if (videos.isEmpty()) return sendText(out, 404, "Канал не найден")
        sendHtml(out, 200, LanPages.channelPage(author, videos) { mediaUrl(it) })
    }

    private fun videoJson(id: String, out: OutputStream) {
        val video = findVisible(id) ?: return sendJson(out, 404, """{"error":"Видео не найдено"}""")
        sendJson(out, 200, LanPages.videoJson(video, mediaUrl(video)))
    }

    private fun thumbnail(id: String, out: OutputStream) {
        val video = findVisible(id)
        val thumb = video?.thumb?.let { File(it) }?.takeIf { it.isFile }
        if (thumb == null) {
            // Прозрачный GIF вместо 404: битая картинка в сетке выглядит хуже
            // пустого места, а браузер её ещё и перезапрашивает.
            return sendResponse(out, 200, "image/gif", LanPages.PLACEHOLDER_GIF)
        }
        sendFile(thumb, null, out, "image/jpeg")
    }

    // ---------- файлы ----------

    /**
     * Отдаёт файл из указанного корня библиотеки.
     *
     * Путь приходит от клиента, поэтому обязательна проверка канонического пути:
     * без неё запрос вида /media/../../databases/... вынес бы наружу личные
     * данные. Сравнение по canonicalPath, а не по строке, потому что ".." и
     * симлинки строкового сравнения не переживают.
     */
    private fun sendLibraryFile(req: Request, out: OutputStream, root: File, parts: List<String>) {
        // Гостю не отдаём файлы скрытых каналов: путь /media/<автор>/... легко
        // угадывается по названию, и без проверки скрытое видео забиралось бы
        // мимо страниц и каталога. Первый сегмент — имя автора.
        val author = parts.firstOrNull() ?: return sendText(out, 404, "Не найдено")
        if (root == library.videosRoot && library.isChannelHidden(author)) {
            return sendText(out, 404, "Не найдено")
        }
        val target = resolveInside(root, parts) ?: return sendText(out, 404, "Не найдено")
        if (!target.isFile) return sendText(out, 404, "Не найдено")
        sendFile(target, req.headers["range"], out, mimeOf(target))
    }

    /**
     * Отдача файла с поддержкой Range.
     *
     * Range обязателен для видео: без него браузер не даёт перемотку, а на
     * больших файлах вообще отказывается воспроизводить.
     */
    private fun sendFile(file: File, range: String?, out: OutputStream, mime: String) {
        val total = file.length()
        val parsed = parseRange(range, total)
        if (parsed == null && range != null && range.startsWith("bytes=")) {
            // Диапазон вне файла: по спецификации это 416 с указанием размера,
            // иначе браузер повторяет тот же неверный запрос по кругу.
            return sendResponse(
                out, 416, mime, ByteArray(0),
                extraHeaders = listOf("Content-Range: bytes */$total")
            )
        }
        val partial = parsed != null
        val start = parsed?.first ?: 0
        val end = parsed?.second ?: (total - 1)

        val length = end - start + 1
        val headers = mutableListOf("Accept-Ranges: bytes")
        if (partial) headers += "Content-Range: bytes $start-$end/$total"
        writeHead(out, if (partial) 206 else 200, mime, length, headers)

        runCatching {
            file.inputStream().use { input ->
                input.skip(start)
                val buffer = ByteArray(64 * 1024)
                var left = length
                while (left > 0) {
                    val n = input.read(buffer, 0, minOf(buffer.size.toLong(), left).toInt())
                    if (n <= 0) break
                    out.write(buffer, 0, n)
                    left -= n
                }
                out.flush()
            }
        }
    }

    // ---------- ответы ----------

    private fun writeHead(
        out: OutputStream,
        code: Int,
        mime: String,
        length: Long,
        extraHeaders: List<String> = emptyList()
    ) {
        val text = buildString {
            append("HTTP/1.1 ").append(code).append(' ').append(statusText(code)).append("\r\n")
            append("Content-Type: ").append(mime).append("\r\n")
            append("Content-Length: ").append(length).append("\r\n")
            extraHeaders.forEach { append(it).append("\r\n") }
            append("Connection: close\r\n\r\n")
        }
        out.write(text.toByteArray(Charsets.UTF_8))
    }

    private fun sendResponse(
        out: OutputStream,
        code: Int,
        mime: String,
        body: ByteArray,
        extraHeaders: List<String> = emptyList()
    ) {
        writeHead(out, code, mime, body.size.toLong(), extraHeaders)
        if (body.isNotEmpty()) out.write(body)
        out.flush()
    }

    private fun sendHtml(out: OutputStream, code: Int, html: String) =
        sendResponse(out, code, "text/html; charset=utf-8", html.toByteArray(Charsets.UTF_8))

    private fun sendJson(
        out: OutputStream,
        code: Int,
        json: String,
        extraHeaders: List<String> = emptyList()
    ) = sendResponse(
        out, code, "application/json; charset=utf-8",
        json.toByteArray(Charsets.UTF_8), extraHeaders
    )

    private fun sendText(out: OutputStream, code: Int, text: String) =
        sendResponse(out, code, "text/plain; charset=utf-8", text.toByteArray(Charsets.UTF_8))

    private fun sendRedirect(out: OutputStream, location: String) =
        sendResponse(
            out, 303, "text/plain; charset=utf-8", ByteArray(0),
            extraHeaders = listOf("Location: $location")
        )

    // ---------- данные ----------

    /** Каталог без скрытых каналов: гость видит то же, что и в вебе. */
    private fun visibleCatalog(): Catalog {
        val hidden = library.hiddenChannels()
        val catalog = library.catalog()
        if (hidden.isEmpty()) return catalog
        return catalog.copy(
            videos = catalog.videos.filterNot { it.author in hidden },
            shorts = catalog.shorts.filterNot { it.author in hidden },
            authors = catalog.authors.filterNot { it.name in hidden }
        )
    }

    private fun findVisible(id: String): VideoItem? {
        val video = library.findVideo(id) ?: return null
        return if (library.isChannelHidden(video.author)) null else video
    }

    private fun searchVisible(query: String): List<VideoItem> {
        val hidden = library.hiddenChannels()
        return library.search(query).filterNot { it.author in hidden }
    }

    /** Адрес файла видео для страницы: путь относительно корня библиотеки. */
    private fun mediaUrl(v: VideoItem): String {
        val path = v.videoPath ?: return ""
        val file = File(path)
        val prefix = if (v.source == "user") "/usermedia" else "/media"
        val root = if (v.source == "user") library.userVideosRoot else library.videosRoot
        val rel = runCatching {
            file.canonicalPath.removePrefix(root.canonicalPath).trimStart(File.separatorChar)
        }.getOrDefault(file.name)
        return prefix + "/" + rel.split(File.separatorChar).joinToString("/") { encodePath(it) }
    }

    /** Базовый адрес папки видео: к нему дописывается имя файла субтитров. */
    private fun subtitleBase(v: VideoItem): String = mediaUrl(v).substringBeforeLast('/')

    private fun encodePath(segment: String): String =
        runCatching { java.net.URLEncoder.encode(segment, "UTF-8").replace("+", "%20") }
            .getOrDefault(segment)

    companion object {
        private const val ACCEPT_TIMEOUT_MS = 500
        private const val READ_TIMEOUT_MS = 15_000
        private const val MAX_THREADS = 8
        private const val MAX_LINE = 8192
        private const val MAX_BODY = 64 * 1024

        internal fun statusText(code: Int): String = when (code) {
            200 -> "OK"
            206 -> "Partial Content"
            303 -> "See Other"
            401 -> "Unauthorized"
            403 -> "Forbidden"
            404 -> "Not Found"
            416 -> "Range Not Satisfiable"
            429 -> "Too Many Requests"
            else -> "OK"
        }

        /**
         * Разбирает заголовок Range в пару (начало, конец) включительно.
         *
         * null означает «отдавать файл целиком»: либо заголовка нет, либо
         * запрошенный диапазон вне файла — вызывающий различает эти случаи сам.
         * Вынесено в companion, чтобы правило проверялось тестами без сокетов.
         */
        internal fun parseRange(range: String?, total: Long): Pair<Long, Long>? {
            if (range == null || !range.startsWith("bytes=")) return null
            if (total <= 0) return null
            // Несколько диапазонов в одном запросе (bytes=0-1,5-6) браузеры для
            // видео не присылают, поэтому берём первый и не усложняем ответ
            // multipart-разметкой.
            val spec = range.removePrefix("bytes=").substringBefore(',')
            val from = spec.substringBefore('-').trim()
            val to = spec.substringAfter('-', "").trim()
            var start: Long
            var end = total - 1
            when {
                from.isNotEmpty() -> {
                    start = from.toLongOrNull() ?: return null
                    if (to.isNotEmpty()) end = to.toLongOrNull() ?: end
                }
                // bytes=-500: последние 500 байт.
                to.isNotEmpty() -> {
                    val tail = to.toLongOrNull() ?: return null
                    if (tail <= 0) return null
                    start = (total - tail).coerceAtLeast(0)
                }
                else -> return null
            }
            end = end.coerceAtMost(total - 1)
            if (start < 0 || start > end || start >= total) return null
            return start to end
        }

        /**
         * Путь внутри корня библиотеки или null, если он оттуда выводит.
         *
         * Сегменты приходят от клиента, поэтому проверка обязательна: без неё
         * запрос вида /media/../../databases/... вынес бы наружу личные данные.
         * Сравниваем канонические пути, а не строки: ".." и симлинки строкового
         * сравнения не переживают.
         */
        internal fun resolveInside(root: File, parts: List<String>): File? {
            if (parts.isEmpty()) return null
            // Пустые сегменты и "." дали бы путь вида a//b, а ".." отсекается
            // проверкой ниже; отбрасываем их сразу, чтобы не полагаться на неё
            // одну.
            if (parts.any { it.isBlank() || it == ".." || it == "." }) return null
            val target = File(root, parts.joinToString(File.separator))
            return runCatching {
                val base = root.canonicalPath
                val path = target.canonicalPath
                if (path.startsWith(base + File.separator)) target else null
            }.getOrNull()
        }

        internal fun mimeOf(file: File): String = when (file.extension.lowercase()) {
            "mp4" -> "video/mp4"
            "webm" -> "video/webm"
            "mkv" -> "video/x-matroska"
            "mov" -> "video/quicktime"
            "avi" -> "video/x-msvideo"
            "mp3" -> "audio/mpeg"
            "jpg", "jpeg" -> "image/jpeg"
            "png" -> "image/png"
            "webp" -> "image/webp"
            "gif" -> "image/gif"
            "vtt" -> "text/vtt; charset=utf-8"
            "srt" -> "text/plain; charset=utf-8"
            "json" -> "application/json; charset=utf-8"
            else -> "application/octet-stream"
        }
    }
}
