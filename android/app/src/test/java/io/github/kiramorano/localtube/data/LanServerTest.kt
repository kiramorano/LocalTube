package io.github.kiramorano.localtube.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

/**
 * Тесты раздачи библиотеки в локальную сеть.
 *
 * Проверяются те правила, ошибка в которых стоит дороже всего: выход за пределы
 * корня библиотеки, разбор Range (без него не работает перемотка) и
 * экранирование в HTML и JSON. Всё это чистые функции, вынесенные из классов с
 * Context, поэтому эмулятор не нужен.
 */
class LanServerTest {

    // ---------- пути ----------

    @Test
    fun `path inside the library root resolves`() {
        val root = Files.createTempDirectory("lt-root").toFile()
        try {
            val file = File(root, "Автор/видео/video.mp4")
            file.parentFile?.mkdirs()
            file.writeText("x")
            val resolved = LanServer.resolveInside(root, listOf("Автор", "видео", "video.mp4"))
            assertEquals(file.canonicalPath, resolved?.canonicalPath)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun `parent directory traversal is rejected`() {
        val root = Files.createTempDirectory("lt-root").toFile()
        try {
            // Классическая попытка выйти к личным данным приложения. Без этой
            // проверки гость забрал бы cookies.txt и userdata.json.
            assertNull(LanServer.resolveInside(root, listOf("..", "..", "cookies.txt")))
            assertNull(LanServer.resolveInside(root, listOf("Автор", "..", "..", "secret")))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun `empty and dot segments are rejected`() {
        val root = Files.createTempDirectory("lt-root").toFile()
        try {
            assertNull(LanServer.resolveInside(root, emptyList()))
            assertNull(LanServer.resolveInside(root, listOf("")))
            assertNull(LanServer.resolveInside(root, listOf(".", "video.mp4")))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun `sibling directory with the same prefix is rejected`() {
        val base = Files.createTempDirectory("lt-base").toFile()
        try {
            // videos и videos_private начинаются одинаково: сравнение без
            // разделителя пути пустило бы гостя во вторую папку.
            val root = File(base, "videos").apply { mkdirs() }
            File(base, "videos_private").mkdirs()
            assertNull(LanServer.resolveInside(root, listOf("..", "videos_private", "x")))
        } finally {
            base.deleteRecursively()
        }
    }

    // ---------- Range ----------

    @Test
    fun `absent range means the whole file`() {
        assertNull(LanServer.parseRange(null, 1000))
        // Не-Range заголовок вида bytes 0-99 (без знака равенства) игнорируем.
        assertNull(LanServer.parseRange("bytes 0-99", 1000))
    }

    @Test
    fun `range with both bounds is parsed`() {
        assertEquals(100L to 199L, LanServer.parseRange("bytes=100-199", 1000))
    }

    @Test
    fun `open ended range runs to the end of the file`() {
        // Именно такой запрос браузер присылает первым при открытии видео.
        assertEquals(0L to 999L, LanServer.parseRange("bytes=0-", 1000))
        assertEquals(500L to 999L, LanServer.parseRange("bytes=500-", 1000))
    }

    @Test
    fun `suffix range returns the tail`() {
        assertEquals(900L to 999L, LanServer.parseRange("bytes=-100", 1000))
        // Хвост больше файла — это весь файл, а не отрицательное смещение.
        assertEquals(0L to 999L, LanServer.parseRange("bytes=-5000", 1000))
    }

    @Test
    fun `range beyond the file is rejected`() {
        // null здесь означает 416: продолжать с обрезанным диапазоном нельзя,
        // иначе браузер получит не то, что просил, и застрянет.
        assertNull(LanServer.parseRange("bytes=1000-1200", 1000))
        assertNull(LanServer.parseRange("bytes=1500-", 1000))
        assertNull(LanServer.parseRange("bytes=200-100", 1000))
    }

    @Test
    fun `range end is clamped to the file size`() {
        assertEquals(900L to 999L, LanServer.parseRange("bytes=900-5000", 1000))
    }

    @Test
    fun `malformed range does not crash`() {
        assertNull(LanServer.parseRange("bytes=abc-def", 1000))
        assertNull(LanServer.parseRange("bytes=-", 1000))
        assertNull(LanServer.parseRange("bytes=", 1000))
        assertNull(LanServer.parseRange("bytes=0-99", 0))
    }

    @Test
    fun `only the first range of a list is used`() {
        // Составные диапазоны требуют multipart-ответа; для видео браузеры их
        // не присылают, поэтому берём первый и не усложняем сервер.
        assertEquals(0L to 99L, LanServer.parseRange("bytes=0-99,200-299", 1000))
    }

    // ---------- MIME ----------

    @Test
    fun `video files get a playable mime type`() {
        // video/mp4 обязателен: с octet-stream браузер предлагает скачать файл
        // вместо воспроизведения.
        assertEquals("video/mp4", LanServer.mimeOf(File("video.mp4")))
        assertEquals("video/webm", LanServer.mimeOf(File("video.WEBM")))
        assertEquals("text/vtt; charset=utf-8", LanServer.mimeOf(File("ru.vtt")))
        assertEquals("application/octet-stream", LanServer.mimeOf(File("info.bin")))
    }

    @Test
    fun `status line has text for every code the server sends`() {
        listOf(200, 206, 303, 401, 403, 404, 416, 429).forEach { code ->
            assertTrue(code.toString(), LanServer.statusText(code).isNotBlank())
        }
    }

    // ---------- экранирование ----------

    @Test
    fun `html special characters are escaped`() {
        // Заголовок видео приходит с YouTube и содержит что угодно: без
        // экранирования он ломал бы страницу и мог протащить скрипт.
        val escaped = LanPages.escapeHtml("""<script>alert("x")</script>&'""")
        assertFalse(escaped.contains("<script>"))
        assertFalse(escaped.contains("\""))
        assertTrue(escaped.contains("&lt;script&gt;"))
        assertTrue(escaped.contains("&amp;"))
    }

    @Test
    fun `json escaping handles quotes and control characters`() {
        val escaped = LanPages.escapeJson("текст \"в кавычках\"\nи с табом\tвнутри")
        assertTrue(escaped.contains("\\\""))
        assertTrue(escaped.contains("\\n"))
        assertTrue(escaped.contains("\\t"))
        // Символ переноса строки в сыром виде делает JSON невалидным.
        assertFalse(escaped.contains("\n"))
    }

    @Test
    fun `json escaping keeps cyrillic as is`() {
        // Экранировать кириллицу в \u не нужно: ответ отдаётся в UTF-8, а
        // раздутый вдвое JSON только тратит трафик.
        assertEquals("Привет", LanPages.escapeJson("Привет"))
    }

    @Test
    fun `catalog json survives a title with quotes`() {
        val video = VideoItem(
            id = "abc",
            title = """Видео "с кавычками" и \слэшем""",
            author = "Автор",
            thumb = null,
            videoPath = null,
            sizeMb = 0.0,
            isShort = false,
            source = "youtube"
        )
        val json = LanPages.catalogJson(
            Catalog(listOf(video), emptyList(), emptyList(), emptyList(), emptyList())
        )
        // Главное — что результат разбирается: сломанный JSON оставил бы гостя
        // с пустой страницей без объяснений.
        val parsed = org.json.JSONObject(json)
        val first = parsed.getJSONArray("videos").getJSONObject(0)
        assertEquals(video.title, first.getString("title"))
        assertEquals("/api/thumbnail/abc", first.getString("thumb"))
    }

    @Test
    fun `placeholder gif is a valid gif header`() {
        val header = String(LanPages.PLACEHOLDER_GIF.copyOfRange(0, 6), Charsets.US_ASCII)
        assertEquals("GIF89a", header)
    }

    @Test
    fun `unlock page contains a form that works without javascript`() {
        val html = LanPages.unlockPage()
        assertTrue(html.contains("""method="post""""))
        assertTrue(html.contains("/api/network/unlock"))
        assertTrue(html.contains("""name="pin""""))
    }

    @Test
    fun `unlock page shows the error text escaped`() {
        val html = LanPages.unlockPage("Неверный PIN <b>")
        assertTrue(html.contains("Неверный PIN &lt;b&gt;"))
    }

    // ---------- PIN и ключи ----------

    @Test
    fun `generated pin has the same length as on the desktop`() {
        repeat(20) {
            val pin = LanAccess.randomPin()
            assertEquals(LanAccess.PIN_LENGTH, pin.length)
            assertTrue(pin, pin.all(Char::isDigit))
        }
    }

    @Test
    fun `pins differ between generations`() {
        // Совпадение шестизначных PIN возможно, но 20 одинаковых подряд
        // означали бы неинициализированный генератор.
        val pins = (1..20).map { LanAccess.randomPin() }.toSet()
        assertTrue(pins.size > 1)
    }

    @Test
    fun `token is a stable hmac and changes with the secret`() {
        val a = LanAccess.hmac("secret-1", "123456")
        val b = LanAccess.hmac("secret-1", "123456")
        val c = LanAccess.hmac("secret-2", "123456")
        val d = LanAccess.hmac("secret-1", "654321")
        assertEquals(a, b)
        // Смена секрета отключает все впущенные устройства — на этом построен
        // сброс PIN, отдельного списка сессий нет.
        assertNotEquals(a, c)
        assertNotEquals(a, d)
        assertEquals(64, a.length)
    }

    @Test
    fun `constant time comparison matches equality`() {
        assertTrue(LanAccess.constantTimeEquals("123456", "123456"))
        assertFalse(LanAccess.constantTimeEquals("123456", "123457"))
        assertFalse(LanAccess.constantTimeEquals("123456", "12345"))
        assertTrue(LanAccess.constantTimeEquals("", ""))
    }

    @Test
    fun `non ascii pin is rejected before comparison`() {
        // Кириллица в поле PIN на сервере валила проверку доступа, а вместе с
        // ней все страницы: сначала отсекаем, потом сравниваем.
        assertNull(LanAccess.asciiOrNull("пароль"))
        assertNull(LanAccess.asciiOrNull("1".repeat(100)))
        assertEquals("123456", LanAccess.asciiOrNull("123456"))
        assertNull(LanAccess.asciiOrNull(null))
    }

    @Test
    fun `guest url is built from host and port`() {
        assertEquals("http://192.168.1.5:8733", LanAccess.urlFor("192.168.1.5", 8733))
    }

    @Test
    fun `default port is inside the allowed range`() {
        // Порты ниже 1024 на Android недоступны без root: сервер просто не
        // поднялся бы, а причина была бы не видна.
        assertTrue(Settings.DEFAULT_LAN_PORT in 1024..65535)
    }

    // ---------- QR ----------

    @Test
    fun `qr matrix is square and has a quiet zone`() {
        val m = QrCode.matrix("http://192.168.1.5:8733", border = 2)
        assertTrue("сторона ${m.size}", m.size >= 21 + 4)
        m.forEach { assertEquals(m.size, it.size) }
        // Светлое поле обязательно: без него сканеры код не находят.
        val edges = m.first().toList() + m.last().toList() +
            m.map { it.first() } + m.map { it.last() }
        assertFalse(edges.any { it })
    }

    @Test
    fun `qr matrix has dark modules`() {
        // Пустая матрица тоже «квадратная», поэтому проверяем, что точки есть.
        val m = QrCode.matrix("http://192.168.1.5:8733")
        assertTrue(m.any { row -> row.any { it } })
    }

    @Test
    fun `longer url needs a bigger qr`() {
        val short = QrCode.matrix("http://10.0.0.2:8733")
        val long = QrCode.matrix("http://10.0.0.2:8733/watch/" + "a".repeat(300))
        assertTrue("${short.size} vs ${long.size}", long.size > short.size)
    }

    @Test
    fun `qr border is clamped and applied`() {
        // Отрицательная рамка раньше дала бы отрицательный размер массива.
        assertEquals(QrCode.matrix("test", border = 0).size + 4, QrCode.matrix("test", border = 2).size)
        assertEquals(QrCode.matrix("test", border = 0).size, QrCode.matrix("test", border = -5).size)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `blank text is not encoded`() {
        // Раздача выключена — адреса нет; молча рисовать пустой код не надо.
        QrCode.matrix("   ")
    }
}
