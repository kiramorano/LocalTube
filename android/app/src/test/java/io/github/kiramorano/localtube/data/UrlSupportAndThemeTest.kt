package io.github.kiramorano.localtube.data

import androidx.compose.ui.graphics.Color
import io.github.kiramorano.localtube.ui.theme.AeroLtColors
import io.github.kiramorano.localtube.ui.theme.DarkLtColors
import io.github.kiramorano.localtube.ui.theme.GlassLtColors
import io.github.kiramorano.localtube.ui.theme.LightLtColors
import io.github.kiramorano.localtube.ui.theme.MidnightLtColors
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

/**
 * Разбор ссылок, селектор формата и палитры тем.
 *
 * Сеть не используется: проверяются только разбор ссылок, селектор формата и
 * палитры. Эталон — tests/test_tiktok.py и файлы тем в static/css/themes.
 * Звёздочку в пути к CSS писать нельзя: Kotlin считает вложенные блочные
 * комментарии, и последовательность из слэша со звёздой открыла бы второй.
 */
class UrlSupportAndThemeTest {

    // ---------- ссылки ----------

    @Test
    fun `youtube urls are supported`() {
        listOf(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/@someone",
            "https://www.youtube.com/shorts/abc12345678"
        ).forEach { assertTrue(it, UrlKind.isSupported(it)) }
    }

    @Test
    fun `second platform urls are supported`() {
        listOf(
            "https://www.tiktok.com/@creator/video/7461234567890123456",
            "https://m.tiktok.com/v/7461234567890123456.html",
            "https://vm.tiktok.com/ZM123AbCd/",
            "https://vt.tiktok.com/ZM123AbCd/",
            "https://www.tiktok.com/@creator",
            // Короткая ссылка «Поделиться»: tiktok.com/t/ZP8ctXots. Раскрывает
            // сам yt-dlp через редирект — задача должна попадать в очередь как есть.
            "https://www.tiktok.com/t/ZP8ctXots",
            "https://tiktok.com/t/ZP8ctXots",
            "https://m.tiktok.com/t/ZP8ctXots",
            "https://www.tiktok.com/t/ZP8ctXots?is_from_webapp=1"
        ).forEach { assertTrue(it, UrlKind.isSupported(it)) }
    }

    @Test
    fun `unsupported urls are rejected`() {
        listOf(
            "ftp://www.tiktok.com/@creator/video/7461234567890123456",
            "https://not-tiktok.com/@creator/video/7461234567890123456",
            "https://www.tiktok.com/",
            "https://example.org/video",
            "просто текст",
            ""
        ).forEach { assertFalse(it, UrlKind.isSupported(it)) }
    }

    @Test
    fun `profile is recognised separately from a video`() {
        assertTrue(UrlKind.isProfile("https://www.tiktok.com/@creator"))
        assertFalse(UrlKind.isProfile("https://www.tiktok.com/@creator/video/7461234567890123456"))
        assertFalse(UrlKind.isProfile("https://www.youtube.com/@someone"))
        // Голый @ без имени — не профиль.
        assertFalse(UrlKind.isProfile("https://www.tiktok.com/@"))
    }

    @Test
    fun `www prefix does not change the host`() {
        assertEquals("tiktok.com", UrlKind.host("https://www.tiktok.com/@creator"))
        assertEquals("youtube.com", UrlKind.host("HTTPS://WWW.YOUTUBE.COM/watch?v=abc"))
    }

    // ---------- метаданные ----------

    @Test
    fun `source is set from extractor`() {
        assertEquals("tiktok", UrlKind.sourceOf("TikTok", ""))
        assertEquals("tiktok", UrlKind.sourceOf("tiktokuser", ""))
        assertEquals(
            "tiktok",
            UrlKind.sourceOf("", "https://www.tiktok.com/@creator/video/1")
        )
        assertEquals("youtube", UrlKind.sourceOf("Youtube", "https://www.youtube.com/watch?v=abc"))
        // Неизвестные экстракторы остаются youtube, как в веб-версии.
        assertEquals("youtube", UrlKind.sourceOf("Vimeo", "https://vimeo.com/1"))
    }

    @Test
    fun `catalog item keeps the platform from metadata`() {
        // Раньше source был литералом "youtube": ролик второго сервиса в каталоге
        // телефона и на сервере получал разный источник.
        val meta = JSONObject()
            .put("id", "7461234567890123456")
            .put("title", "Ролик")
            .put("uploader", "Creator")
            .put("extractor_key", "TikTok")
            .put("webpage_url", "https://www.tiktok.com/@creator/video/7461234567890123456")
            .put("uploader_url", "https://www.tiktok.com/@creator")
        val item = Library.itemFromMeta(
            meta = meta,
            folderName = "7461234567890123456",
            authorFallback = "Creator",
            videoPath = "/tmp/video.mp4",
            sizeMb = 1.0
        )
        assertEquals("tiktok", item.source)
        assertTrue("Вертикальный ролик должен быть Shorts", item.isShort)
        assertEquals("https://www.tiktok.com/@creator", item.channelUrl)
        // По сохранённому профилю ссылка на ролик собирается обратно.
        assertEquals(
            "https://www.tiktok.com/@creator/video/7461234567890123456",
            UrlKind.watchUrl(item.source, item.id, item.channelUrl)
        )
    }

    @Test
    fun `catalog item stays youtube for youtube metadata`() {
        val meta = JSONObject()
            .put("id", "dQw4w9WgXcQ")
            .put("extractor_key", "Youtube")
            .put("webpage_url", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            .put("width", 1920)
            .put("height", 1080)
            .put("duration", 600)
        val item = Library.itemFromMeta(
            meta = meta,
            folderName = "dQw4w9WgXcQ",
            authorFallback = "Автор",
            videoPath = "/tmp/v.mp4",
            sizeMb = 2.0
        )
        assertEquals("youtube", item.source)
        assertFalse(item.isShort)
    }

    @Test
    fun `library source matches metadata`() {
        val second = JSONObject()
            .put("extractor_key", "TikTok")
            .put("webpage_url", "https://www.tiktok.com/@creator/video/1")
        assertEquals("tiktok", Library.sourceOf(second))
        val youtube = JSONObject()
            .put("extractor_key", "Youtube")
            .put("webpage_url", "https://www.youtube.com/watch?v=abc")
        assertEquals("youtube", Library.sourceOf(youtube))
    }

    @Test
    fun `vertical video is a short even without dimensions`() {
        // extract_flat профиля часто не отдаёт width/height: без этого правила
        // ролик попадал бы в обычную сетку.
        val meta = JSONObject()
            .put("extractor_key", "TikTok")
            .put("id", "7461234567890123456")
        assertTrue(Library.isShort(meta))
    }

    @Test
    fun `landscape youtube video is still not a short`() {
        val meta = JSONObject()
            .put("height", 1080)
            .put("width", 1920)
            .put("duration", 30)
            .put("extractor_key", "Youtube")
        assertFalse(Library.isShort(meta))
    }

    // ---------- движок ----------

    @Test
    fun `second platform format selector is a single stream`() {
        val url = "https://www.tiktok.com/@creator/video/7461234567890123456"
        // YouTube-селектор (bestvideo+bestaudio) давал отказ формата.
        assertEquals("best", Engine.formatSelector("best", url))
        assertEquals("best", Engine.formatSelector("bestvideo[height<=720]+bestaudio/best", url))
        assertEquals("best", Engine.formatSelector("video:137", url))
        assertEquals("bestaudio/best", Engine.formatSelector("audio:140", url))
        assertEquals("bestaudio/best", Engine.formatSelector("bestaudio/best", url))
    }

    @Test
    fun `youtube format selector is unchanged`() {
        val url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assertEquals("bestvideo*+bestaudio/best", Engine.formatSelector("best", url))
        assertEquals("137+bestaudio/137", Engine.formatSelector("video:137", url))
        assertEquals("140", Engine.formatSelector("audio:140", url))
        assertEquals("22", Engine.formatSelector("22", url))
        // Без URL поведение прежнее: тесты EngineFormatsTest вызывают так.
        assertEquals("bestvideo*+bestaudio/best", Engine.formatSelector("best"))
    }

    @Test
    fun `second platform profile is listed once, without youtube tabs`() {
        val urls = Engine.channelTabUrls("https://www.tiktok.com/@creator")
        assertEquals(listOf("https://www.tiktok.com/@creator"), urls)
        assertTrue(urls.none { it.endsWith("/videos") })
        assertTrue(urls.none { it.endsWith("/shorts") })
        assertTrue(urls.none { it.endsWith("/streams") })
    }

    @Test
    fun `youtube channel still expands into three tabs`() {
        val urls = Engine.channelTabUrls("https://www.youtube.com/@someone")
        assertEquals(3, urls.size)
        assertTrue(urls.any { it.endsWith("/videos") })
    }

    @Test
    fun `second platform does not get youtube player client args`() {
        val url = "https://www.tiktok.com/@creator/video/7461234567890123456"
        assertNull(Engine.extractorArgsFor(url, "web"))
        assertNull(Engine.extractorArgsFor(url, "android"))
        assertEquals(
            "youtube:player_client=web",
            Engine.extractorArgsFor("https://www.youtube.com/watch?v=abc", "web")
        )
        assertNull(Engine.extractorArgsFor("https://www.youtube.com/watch?v=abc", ""))
    }

    @Test
    fun `fallback url for a second platform profile stays on it`() {
        val profile = "https://www.tiktok.com/@creator"
        assertEquals(
            "$profile/video/7461234567890123456",
            Engine.fallbackWatchUrl("7461234567890123456", profile)
        )
        assertEquals(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            Engine.fallbackWatchUrl("dQw4w9WgXcQ", "https://www.youtube.com/@someone")
        )
    }

    @Test
    fun `watch url for second platform uses the saved profile`() {
        assertEquals(
            "https://www.tiktok.com/@creator/video/7461234567890123456",
            UrlKind.watchUrl("tiktok", "7461234567890123456", "https://www.tiktok.com/@creator")
        )
        // Без профиля ссылку по id собрать нельзя.
        assertNull(UrlKind.watchUrl("tiktok", "7461234567890123456", ""))
        assertEquals(
            "https://www.youtube.com/watch?v=abc",
            UrlKind.watchUrl("youtube", "abc", "")
        )
        assertNull(UrlKind.watchUrl("user", "abc", ""))
    }

    // ---------- темы ----------

    @Test
    fun `theme ids match the web version`() {
        assertEquals("dark", AppTheme.DARK.id)
        assertEquals("light", AppTheme.LIGHT.id)
        assertEquals("midnight", AppTheme.MIDNIGHT.id)
        assertEquals("glass", AppTheme.GLASS.id)
        assertEquals("frutiger-aero", AppTheme.AERO.id)
    }

    @Test
    fun `legacy aero id still opens frutiger aero`() {
        // До выравнивания с вебом тема хранилась как "aero". После обновления
        // она не должна молча стать тёмной.
        assertEquals(AppTheme.AERO, AppTheme.from("aero"))
        assertEquals(AppTheme.AERO, AppTheme.from("frutiger-aero"))
        assertEquals(AppTheme.MIDNIGHT, AppTheme.from("midnight"))
        assertEquals(AppTheme.GLASS, AppTheme.from("glass"))
        assertEquals(AppTheme.DARK, AppTheme.from("nonsense"))
    }

    @Test
    fun `five themes are offered`() {
        assertEquals(5, AppTheme.entries.size)
        assertEquals(
            listOf("Тёмная", "Светлая", "Midnight", "Glass", "Frutiger Aero"),
            AppTheme.entries.map { it.label }
        )
    }

    @Test
    fun `midnight palette matches the web theme`() {
        // static/css/themes/midnight.css --yt-*, кроме текста: на телефоне
        // тёмные темы набраны белым, а не холодным серо-голубым веба.
        assertEquals(Color(0xFF0B0E14), MidnightLtColors.background)
        assertEquals(Color(0xFF151A24), MidnightLtColors.cardBg)
        assertEquals(Color.White, MidnightLtColors.textPrimary)
        assertEquals(Color(0xFFE6E6E6), MidnightLtColors.textSecondary)
        assertEquals(Color(0xFF262D3B), MidnightLtColors.border)
        assertEquals(Color(0xFF62B6FF), MidnightLtColors.brandRed)
        assertEquals(Color(0xFF08111C), MidnightLtColors.onAccent)
    }

    @Test
    fun `glass palette is translucent and uses the web accent`() {
        // static/css/themes/glass.css: карточка rgba(255,255,255,.07)
        assertEquals(Color(0xFF0D1220), GlassLtColors.background)
        assertEquals(Color.White, GlassLtColors.textPrimary)
        assertEquals(Color(0xFF7CC4FF), GlassLtColors.brandRed)
        assertEquals(Color(0xFF071120), GlassLtColors.onAccent)
        assertTrue(
            "карточка Glass должна быть полупрозрачной",
            GlassLtColors.cardBg.alpha > 0f && GlassLtColors.cardBg.alpha < 0.2f
        )
    }

    @Test
    fun `dark and light keep a transparent card so they blend with the page`() {
        assertEquals(0f, DarkLtColors.cardBg.alpha)
        assertEquals(0f, LightLtColors.cardBg.alpha)
        assertTrue("у Aero должна быть стеклянная подложка", AeroLtColors.cardBg.alpha > 0f)
    }

    @Test
    fun `dark themes use white text, light themes keep dark text`() {
        // На тёмных темах серый #AAA читался как «грязный». Светлые темы
        // белым текстом не набираются: у Light и Aero фон светлый.
        listOf(DarkLtColors, MidnightLtColors, GlassLtColors).forEach { palette ->
            assertEquals(Color.White, palette.textPrimary)
            assertEquals(Color.White, palette.iconInactive)
        }
        assertEquals(Color(0xFF0F0F0F), LightLtColors.textPrimary)
        assertEquals(Color(0xFF0B2942), AeroLtColors.textPrimary)
    }

    @Test
    fun `unsupported url message matches the server`() {
        assertEquals("Ссылка не поддерживается", UrlKind.UNSUPPORTED_MESSAGE)
    }
}

@RunWith(Parameterized::class)
class UrlSupportCases(private val url: String, private val supported: Boolean) {

    @Test
    fun `url support matches the web table`() {
        assertEquals(url, supported, UrlKind.isSupported(url))
    }

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun data(): Collection<Array<Any>> = listOf(
            arrayOf("https://www.tiktok.com/@creator/video/7461234567890123456", true),
            arrayOf("https://m.tiktok.com/v/7461234567890123456.html", true),
            arrayOf("https://vm.tiktok.com/ZM123AbCd/", true),
            arrayOf("https://vt.tiktok.com/ZM123AbCd/", true),
            arrayOf("https://www.tiktok.com/@creator", true),
            arrayOf("https://www.tiktok.com/t/ZP8ctXots", true),
            arrayOf("https://tiktok.com/t/ZP8ctXots", true),
            arrayOf("https://www.tiktok.com/t/ZP8ctXots?is_from_webapp=1", true),
            arrayOf("https://www.tiktok.com/t/", false),
            arrayOf("https://www.tiktok.com/t/ab", false),
            arrayOf("https://www.tiktok.com/t/ZP8ct.Xots", false),
            arrayOf("https://www.tiktok.com/t/ZP8ctXots/extra", false),
            arrayOf("https://www.tiktok.com/@creator/t", false),
            arrayOf("https://not-tiktok.com/t/ZP8ctXots", false),
            arrayOf("ftp://www.tiktok.com/@creator/video/7461234567890123456", false),
            arrayOf("https://not-tiktok.com/@creator/video/7461234567890123456", false),
            arrayOf("https://www.tiktok.com/", false)
        )
    }
}
