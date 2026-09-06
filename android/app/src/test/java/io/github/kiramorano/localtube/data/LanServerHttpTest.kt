package io.github.kiramorano.localtube.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.nio.file.Files

/**
 * Проверка сервера целиком: поднимаем его на свободном порту и стучимся
 * настоящими HTTP-запросами.
 *
 * Юнит-тесты на parseRange и resolveInside проверяют правила по отдельности, но
 * не то, что ответ собирается и разбирается клиентом. Здесь проверяется как раз
 * склейка: коды, заголовки, cookie и запрет для гостя без PIN.
 */
class LanServerHttpTest {

    // ---------- вспомогательное ----------

    private fun get(
        port: Int,
        path: String,
        cookie: String? = null,
        range: String? = null
    ): Response {
        val conn = URL("http://127.0.0.1:$port$path").openConnection() as HttpURLConnection
        conn.instanceFollowRedirects = false
        cookie?.let { conn.setRequestProperty("Cookie", it) }
        range?.let { conn.setRequestProperty("Range", it) }
        conn.connectTimeout = TIMEOUT
        conn.readTimeout = TIMEOUT
        return conn.readResponse()
    }

    private fun post(port: Int, path: String, body: String, contentType: String): Response {
        val conn = URL("http://127.0.0.1:$port$path").openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.doOutput = true
        conn.instanceFollowRedirects = false
        conn.setRequestProperty("Content-Type", contentType)
        conn.connectTimeout = TIMEOUT
        conn.readTimeout = TIMEOUT
        conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        return conn.readResponse()
    }

    private fun HttpURLConnection.readResponse(): Response {
        val code = responseCode
        // errorStream у кодов 4xx и 5xx: inputStream на них бросает исключение.
        val text = runCatching {
            (errorStream ?: inputStream).readBytes().toString(Charsets.UTF_8)
        }.getOrDefault("")
        val headers = headerFields
            .filterKeys { it != null }
            .mapKeys { it.key.lowercase() }
            .mapValues { it.value.firstOrNull().orEmpty() }
        disconnect()
        return Response(code, headers, text)
    }

    private data class Response(val code: Int, val headers: Map<String, String>, val body: String)

    /**
     * Поднимает сервер на свободном порту и выполняет блок.
     *
     * Порт запрашиваем нулевой, а фактический берём из activePort: фиксированный
     * номер ломал бы тесты на машине, где он занят.
     */
    private fun withServer(
        hidden: Set<String> = emptySet(),
        block: (port: Int, cookie: String) -> Unit
    ) {
        val root = Files.createTempDirectory("lt-http").toFile()
        val source = FakeSource(root, hidden)
        val server = LanServer(source, FakeGuard())
        assertTrue("сервер не поднялся: ${server.lastError}", server.start(0))
        try {
            block(server.activePort, "${LanAccess.TOKEN_COOKIE}=$TOKEN")
        } finally {
            server.stop()
            root.deleteRecursively()
        }
    }

    // ---------- доступ ----------

    @Test
    fun `guest without pin is redirected to the login page`() {
        withServer { port, _ ->
            val res = get(port, "/")
            assertEquals(303, res.code)
            assertEquals("/unlock", res.headers["location"])
        }
    }

    @Test
    fun `api request without pin answers 401 json`() {
        withServer { port, _ ->
            val res = get(port, "/api/catalog")
            // Именно 401 и JSON: редирект в ответ на fetch показал бы странице
            // HTML вместо данных.
            assertEquals(401, res.code)
            assertTrue(res.headers["content-type"].orEmpty().startsWith("application/json"))
            assertTrue(res.body.contains("guest"))
        }
    }

    @Test
    fun `media file without pin is not served`() {
        withServer { port, _ ->
            // Прямая ссылка на файл — самый простой способ обойти страницы, и
            // без проверки она работала бы.
            assertEquals(303, get(port, "/media/Автор/vid/video.mp4").code)
        }
    }

    @Test
    fun `ping and login page work without a pin`() {
        withServer { port, _ ->
            val ping = get(port, "/api/network/ping")
            assertEquals(200, ping.code)
            assertEquals("LocalTube", org.json.JSONObject(ping.body).getString("app"))

            val login = get(port, "/unlock")
            assertEquals(200, login.code)
            assertTrue(login.headers["content-type"].orEmpty().startsWith("text/html"))
            assertTrue(login.body.contains("name=\"pin\""))
        }
    }

    @Test
    fun `correct pin from a form sets the cookie and redirects home`() {
        withServer { port, _ ->
            val res = post(
                port, "/api/network/unlock",
                "pin=$PIN", "application/x-www-form-urlencoded"
            )
            assertEquals(303, res.code)
            assertEquals("/", res.headers["location"])
            val cookie = res.headers["set-cookie"].orEmpty()
            assertTrue(cookie.contains(LanAccess.TOKEN_COOKIE))
            // HttpOnly обязателен: без него ключ доступен любому скрипту.
            assertTrue(cookie.contains("HttpOnly"))
        }
    }

    @Test
    fun `correct pin from json returns ok`() {
        withServer { port, _ ->
            val res = post(port, "/api/network/unlock", """{"pin":"$PIN"}""", "application/json")
            assertEquals(200, res.code)
            assertTrue(org.json.JSONObject(res.body).getBoolean("ok"))
            assertTrue(res.headers["set-cookie"].orEmpty().contains(LanAccess.TOKEN_COOKIE))
        }
    }

    @Test
    fun `wrong pin is rejected and reports remaining attempts`() {
        withServer { port, _ ->
            val res = post(port, "/api/network/unlock", """{"pin":"000000"}""", "application/json")
            assertEquals(403, res.code)
            assertTrue(org.json.JSONObject(res.body).has("attempts_left"))
        }
    }

    // ---------- содержимое ----------

    @Test
    fun `authorized guest sees the catalog page and json`() {
        withServer { port, cookie ->
            val page = get(port, "/", cookie = cookie)
            assertEquals(200, page.code)
            assertTrue(page.body.contains("LocalTube"))

            val json = get(port, "/api/catalog", cookie = cookie)
            assertEquals(200, json.code)
            val videos = org.json.JSONObject(json.body).getJSONArray("videos")
            assertEquals(1, videos.length())
            assertEquals("Тест", videos.getJSONObject(0).getString("title"))
        }
    }

    @Test
    fun `watch page embeds the video source`() {
        withServer { port, cookie ->
            val res = get(port, "/watch/vid", cookie = cookie)
            assertEquals(200, res.code)
            assertTrue(res.body.contains("<video"))
            assertTrue(res.body.contains("/media/"))
        }
    }

    @Test
    fun `channel page lists the videos`() {
        withServer { port, cookie ->
            val res = get(port, "/channel/%D0%90%D0%B2%D1%82%D0%BE%D1%80", cookie = cookie)
            assertEquals(200, res.code)
            assertTrue(res.body.contains("Тест"))
        }
    }

    @Test
    fun `search finds a video by title`() {
        withServer { port, cookie ->
            val res = get(port, "/api/search?q=%D0%A2%D0%B5%D1%81%D1%82", cookie = cookie)
            assertEquals(200, res.code)
            assertEquals(1, org.json.JSONObject(res.body).getJSONArray("results").length())
        }
    }

    @Test
    fun `unknown path answers 404`() {
        withServer { port, cookie ->
            assertEquals(404, get(port, "/nothing/here", cookie = cookie).code)
        }
    }

    @Test
    fun `missing thumbnail falls back to a placeholder image`() {
        withServer { port, cookie ->
            val res = get(port, "/api/thumbnail/nope", cookie = cookie)
            // 200 с прозрачным GIF, а не 404: битая картинка в сетке выглядит
            // хуже пустого места и перезапрашивается браузером.
            assertEquals(200, res.code)
            assertEquals("image/gif", res.headers["content-type"])
        }
    }

    // ---------- файлы ----------

    @Test
    fun `video file is served whole with accept ranges`() {
        withServer { port, cookie ->
            val res = get(port, "/media/%D0%90%D0%B2%D1%82%D0%BE%D1%80/vid/video.mp4", cookie = cookie)
            assertEquals(200, res.code)
            assertEquals("video/mp4", res.headers["content-type"])
            // Без Accept-Ranges браузер не даёт перемотку.
            assertEquals("bytes", res.headers["accept-ranges"])
            assertEquals(CONTENT, res.body)
        }
    }

    @Test
    fun `range request returns partial content`() {
        withServer { port, cookie ->
            val res = get(
                port, "/media/%D0%90%D0%B2%D1%82%D0%BE%D1%80/vid/video.mp4",
                cookie = cookie, range = "bytes=2-5"
            )
            assertEquals(206, res.code)
            assertEquals("bytes 2-5/${CONTENT.length}", res.headers["content-range"])
            assertEquals(CONTENT.substring(2, 6), res.body)
        }
    }

    @Test
    fun `range beyond the file answers 416`() {
        withServer { port, cookie ->
            val res = get(
                port, "/media/%D0%90%D0%B2%D1%82%D0%BE%D1%80/vid/video.mp4",
                cookie = cookie, range = "bytes=9999-"
            )
            assertEquals(416, res.code)
            assertEquals("bytes */${CONTENT.length}", res.headers["content-range"])
        }
    }

    @Test
    fun `path traversal over http is refused`() {
        withServer { port, cookie ->
            // Именно так добираются до cookies.txt и userdata.json в настоящем
            // приложении: они лежат рядом с корнем библиотеки.
            val res = get(port, "/media/..%2F..%2Fsecret.txt", cookie = cookie)
            assertEquals(404, res.code)
            assertFalse(res.body.contains("секрет"))
        }
    }

    @Test
    fun `hidden channel is invisible everywhere`() {
        withServer(hidden = setOf("Автор")) { port, cookie ->
            // Каталог, страница, канал и сам файл: путь угадывается по имени
            // канала, поэтому проверка нужна во всех четырёх местах.
            val catalog = get(port, "/api/catalog", cookie = cookie)
            assertEquals(0, org.json.JSONObject(catalog.body).getJSONArray("videos").length())
            assertEquals(404, get(port, "/watch/vid", cookie = cookie).code)
            assertEquals(404, get(port, "/channel/%D0%90%D0%B2%D1%82%D0%BE%D1%80", cookie = cookie).code)
            assertEquals(
                404,
                get(port, "/media/%D0%90%D0%B2%D1%82%D0%BE%D1%80/vid/video.mp4", cookie = cookie).code
            )
        }
    }

    // ---------- жизненный цикл ----------

    @Test
    fun `stopped server refuses connections`() {
        val root = Files.createTempDirectory("lt-http").toFile()
        try {
            val server = LanServer(FakeSource(root), FakeGuard())
            assertTrue(server.start(0))
            val port = server.activePort
            assertEquals(200, get(port, "/api/network/ping").code)
            server.stop()
            assertFalse(server.isRunning)
            // Сокет должен быть закрыт: иначе выключенный тумблер продолжал бы
            // раздавать библиотеку.
            assertTrue(runCatching { get(port, "/api/network/ping") }.isFailure)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun `busy port is reported instead of crashing`() {
        val root = Files.createTempDirectory("lt-http").toFile()
        try {
            val first = LanServer(FakeSource(root), FakeGuard())
            assertTrue(first.start(0))
            val second = LanServer(FakeSource(root), FakeGuard())
            try {
                // Занятый порт — обычная ситуация на телефоне, и она должна
                // превращаться в сообщение, а не в падение.
                assertFalse(second.start(first.activePort))
                assertTrue(second.lastError.isNotBlank())
                assertEquals(0, second.activePort)
            } finally {
                first.stop()
                second.stop()
            }
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun `restart on another port moves the server`() {
        val root = Files.createTempDirectory("lt-http").toFile()
        try {
            val server = LanServer(FakeSource(root), FakeGuard())
            assertTrue(server.start(0))
            val old = server.activePort
            assertTrue(server.start(0))
            val new = server.activePort
            try {
                assertEquals(200, get(new, "/api/network/ping").code)
                // Прежний порт должен освободиться: иначе после смены порта
                // библиотека раздавалась бы по двум адресам.
                assertTrue(old == new || runCatching { get(old, "/api/network/ping") }.isFailure)
            } finally {
                server.stop()
            }
        } finally {
            root.deleteRecursively()
        }
    }

    companion object {
        private const val CONTENT = "0123456789"
        private const val PIN = "123456"
        private const val TOKEN = "test-token"
        private const val TIMEOUT = 5000
    }

    // ---------- подстановки ----------

    /** Библиотека из одного видео во временной папке. */
    private class FakeSource(
        root: File,
        private val hidden: Set<String> = emptySet()
    ) : LanServer.Source {

        override val videosRoot = File(root, "videos").apply { mkdirs() }
        override val userVideosRoot = File(root, "user_videos").apply { mkdirs() }
        override val avatarsDir = File(root, "avatars").apply { mkdirs() }
        override val bannersDir = File(avatarsDir, "banners").apply { mkdirs() }

        private val video: VideoItem

        init {
            val folder = File(videosRoot, "Автор/vid").apply { mkdirs() }
            File(folder, "video.mp4").writeText(CONTENT)
            // Файл за пределами корня: цель проверки на обход пути.
            File(root, "secret.txt").writeText("секрет")
            video = VideoItem(
                id = "vid",
                title = "Тест",
                author = "Автор",
                thumb = null,
                videoPath = File(folder, "video.mp4").absolutePath,
                sizeMb = 0.0,
                isShort = false,
                source = "youtube"
            )
        }

        override fun catalog(): Catalog = Catalog(
            videos = listOf(video),
            shorts = emptyList(),
            authors = listOf(Author("Автор", null, 1)),
            playlists = emptyList(),
            userVideos = emptyList()
        )

        override fun findVideo(id: String): VideoItem? = video.takeIf { it.id == id }

        override fun videosOf(author: String): List<VideoItem> =
            if (author == video.author) listOf(video) else emptyList()

        override fun search(query: String): List<VideoItem> =
            if (query.isNotBlank() && video.title.contains(query, ignoreCase = true)) {
                listOf(video)
            } else emptyList()

        override fun subtitlesOf(v: VideoItem): List<Pair<String, String>> = emptyList()

        override fun isChannelHidden(author: String): Boolean = author in hidden

        override fun hiddenChannels(): Set<String> = hidden
    }

    /** Проверка прав с заранее известным PIN и ключом. */
    private class FakeGuard : LanServer.Guard {
        override fun isValidToken(token: String?): Boolean = token == TOKEN
        override fun checkPin(input: String?, address: String): LanAccess.PinResult =
            if (input == PIN) LanAccess.PinResult.Ok(TOKEN) else LanAccess.PinResult.Wrong(9)
    }
}
