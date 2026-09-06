package io.github.kiramorano.localtube.data

import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Тесты разбора форматов и селектора качества.
 *
 * Главное, что проверяется: раздельные потоки (1080p и выше) попадают в список.
 * Раньше фильтр требовал звуковую дорожку, и качество обрывалось на 720p.
 */
class EngineFormatsTest {

    private fun format(
        id: String,
        height: Int,
        vcodec: String = "avc1.640028",
        acodec: String = "none",
        fps: Int = 30,
        ext: String = "mp4",
        size: Long = 1_000_000
    ) = """
        {"format_id":"$id","height":$height,"vcodec":"$vcodec","acodec":"$acodec",
         "fps":$fps,"ext":"$ext","filesize":$size}
    """.trimIndent()

    private fun parse(vararg entries: String) =
        Engine.parseFormatsJson(JSONArray("[${entries.joinToString(",")}]"))

    @Test
    fun `video-only streams are offered`() {
        val formats = parse(
            format("137", 1080),
            format("22", 720, acodec = "mp4a.40.2")
        )
        val labels = formats.filter { it.isVideo }.map { it.resolution }
        assertTrue("1080p должен предлагаться", labels.contains("1080p"))
        assertTrue(labels.contains("720p"))
    }

    @Test
    fun `video-only stream is marked and prefixed`() {
        val formats = parse(format("137", 1080))
        val option = formats.first { it.resolution == "1080p" }
        assertTrue("поток без звука должен быть помечен", option.needsAudio)
        assertEquals("video:137", option.formatId)
    }

    @Test
    fun `stream with audio keeps plain id`() {
        val formats = parse(format("22", 720, acodec = "mp4a.40.2"))
        val option = formats.first { it.resolution == "720p" }
        assertFalse(option.needsAudio)
        assertEquals("22", option.formatId)
    }

    @Test
    fun `highest quality comes first`() {
        val formats = parse(
            format("18", 360, acodec = "mp4a.40.2"),
            format("137", 1080),
            format("271", 1440)
        )
        val heights = formats.filter { it.isVideo }.map { it.resolution }
        assertEquals(listOf("1440p", "1080p", "360p"), heights)
    }

    @Test
    fun `same height prefers higher fps`() {
        val formats = parse(
            format("137", 1080, fps = 30),
            format("299", 1080, fps = 60)
        )
        val option = formats.first { it.resolution == "1080p" }
        assertEquals(60, option.fps)
    }

    @Test
    fun `audio only formats are listed`() {
        val formats = parse(
            """{"format_id":"140","height":0,"vcodec":"none","acodec":"mp4a.40.2","ext":"m4a"}"""
        )
        val audio = formats.filter { !it.isVideo }
        assertEquals(1, audio.size)
        assertEquals("audio", audio.first().resolution)
    }

    @Test
    fun `formats without video codec are skipped from video list`() {
        val formats = parse("""{"format_id":"x","height":720,"vcodec":"none","acodec":"none"}""")
        assertTrue(formats.none { it.isVideo })
    }

    // ---------- селектор ----------

    @Test
    fun `best selector asks for merged best quality`() {
        // best[ext=mp4] давал только прогрессивный поток, то есть максимум 720p.
        assertEquals("bestvideo*+bestaudio/best", Engine.formatSelector("best"))
    }

    @Test
    fun `video-only selector adds audio`() {
        assertEquals("137+bestaudio/137", Engine.formatSelector("video:137"))
    }

    @Test
    fun `audio selector strips prefix`() {
        assertEquals("140", Engine.formatSelector("audio:140"))
    }

    @Test
    fun `plain id passes through`() {
        assertEquals("22", Engine.formatSelector("22"))
    }

    // ---------- контейнер ----------

    @Test
    fun `known containers are kept`() {
        // Тот же список, что в диалоге канала веб-версии.
        assertEquals(listOf("mp4", "mkv", "webm"), Engine.MERGE_FORMATS)
        Engine.MERGE_FORMATS.forEach {
            assertEquals(it, Engine.normalizeMergeFormat(it))
        }
        assertEquals("mkv", Engine.normalizeMergeFormat("MKV"))
        assertEquals("webm", Engine.normalizeMergeFormat("  webm "))
    }

    @Test
    fun `unknown container falls back to mp4`() {
        // Значение уходит в командную строку yt-dlp: произвольную строку туда
        // пускать нельзя.
        assertEquals("mp4", Engine.DEFAULT_MERGE_FORMAT)
        assertEquals("mp4", Engine.normalizeMergeFormat("avi"))
        assertEquals("mp4", Engine.normalizeMergeFormat(""))
        assertEquals("mp4", Engine.normalizeMergeFormat(null))
        assertEquals("mp4", Engine.normalizeMergeFormat("mp4; rm -rf /"))
    }

    // ---------- повторы ----------

    @Test
    fun `retry sleep uses a syntax yt-dlp accepts`() {
        // Раньше здесь стоял список "1,10". yt-dlp считает его синтаксической
        // ошибкой и завершается до начала загрузки, из-за чего падала любая
        // задача. Допустимы только exp=, linear= или одно число.
        val v = Engine.RETRY_SLEEP
        assertFalse("список через запятую yt-dlp не принимает", v.contains(","))
        assertTrue(
            "ожидается exp=/linear=/число, получено: $v",
            v.matches(Regex("""^(exp|linear)=\d+(\.\d+)?(:\d+(\.\d+)?){0,2}$""")) ||
                v.matches(Regex("""^\d+(\.\d+)?$"""))
        )
    }

    // ---------- язык аудиодорожки ----------
    // Случаи повторяют tests/test_download_prefs.py: селектор на телефоне и на
    // сервере должен получаться один и тот же, иначе один и тот же ролик
    // окажется в общей библиотеке с разной озвучкой.

    @Test
    fun `audio selector untouched without langs`() {
        assertEquals(
            "bestvideo+bestaudio/best",
            Engine.audioFormatSelector("bestvideo+bestaudio/best", emptyList())
        )
    }

    @Test
    fun `audio selector adds language filter`() {
        // Фильтр вешается на аудиочасть: у видеопотока поля language нет.
        val out = Engine.audioFormatSelector("bestvideo+bestaudio/best", listOf("ru"))
        assertTrue(out, out.startsWith("bestvideo+bestaudio[language^=ru]/"))
    }

    @Test
    fun `audio selector keeps original as fallback`() {
        // У большинства видео одна дорожка и вообще без языка: без запаса
        // не скачалось бы ничего.
        val out = Engine.audioFormatSelector("bestvideo+bestaudio/best", listOf("ru"))
        assertTrue(out, out.endsWith("bestvideo+bestaudio/best"))
    }

    @Test
    fun `audio selector respects language order`() {
        // Порядок в настройках — это приоритет: сначала русская, потом английская.
        val out = Engine.audioFormatSelector("bestvideo+bestaudio/best", listOf("ru", "en"))
        assertTrue(out, out.indexOf("language^=ru") < out.indexOf("language^=en"))
    }

    @Test
    fun `audio selector uses prefix match`() {
        // ru должен подходить и для ru-RU: точного совпадения YouTube не даёт.
        val out = Engine.audioFormatSelector("bestvideo+bestaudio/best", listOf("ru"))
        assertTrue("строгое равенство отсекает ru-RU", out.contains("language^=ru"))
        assertFalse("нужен ^=, а не =", out.contains("language=ru"))
    }

    @Test
    fun `audio selector handles audio only`() {
        // Выбор «Только звук» тоже должен уметь язык.
        val out = Engine.audioFormatSelector("bestaudio/best", listOf("en"))
        assertTrue(out, out.startsWith("bestaudio[language^=en]/"))
    }

    @Test
    fun `audio selector handles numeric video format`() {
        val out = Engine.audioFormatSelector("137+bestaudio/137", listOf("en"))
        assertTrue(out, out.contains("137+bestaudio[language^=en]"))
    }

    @Test
    fun `audio selector skips single stream selector`() {
        // У TikTok селектор «best»: фильтр языка сделал бы формат недостижимым
        // («Requested format is not available»).
        assertEquals("best", Engine.audioFormatSelector("best", listOf("ru")))
        assertEquals("worst", Engine.audioFormatSelector("worst", listOf("ru")))
    }

    @Test
    fun `audio selector survives empty selector`() {
        assertEquals("", Engine.audioFormatSelector("", listOf("ru")))
    }

    @Test
    fun `audio selector ignores blank langs`() {
        // Поле настроек пишется на каждый символ, поэтому «ru,» и « » — обычное
        // состояние. Пустой код дал бы «bestaudio[language^=]» и отказ загрузки.
        assertEquals(
            "bestvideo+bestaudio/best",
            Engine.audioFormatSelector("bestvideo+bestaudio/best", listOf(" ", ""))
        )
    }

    @Test
    fun `audio selector skips selector without audio part`() {
        // Числовой формат без bestaudio: вешать фильтр некуда, а исходный
        // селектор терять нельзя.
        assertEquals("22", Engine.audioFormatSelector("22", listOf("ru")))
    }

    @Test
    fun `tiktok selector keeps single stream with audio language set`() {
        // Сквозная проверка: настройка языка не должна портить TikTok, как и
        // test_ydl_opts_skip_audio_language_for_tiktok на сервере.
        val url = "https://www.tiktok.com/@a/video/123"
        val selector = Engine.audioFormatSelector(Engine.formatSelector("best", url), listOf("ru"))
        assertEquals("best", selector)
    }

    // ---------- скорость ----------

    @Test
    fun `speed is parsed from progress line`() {
        val line = "[download]  45.2% of 100.00MiB at 2.50MiB/s ETA 00:22"
        assertEquals("2.50MiB/s", Engine.parseSpeed(line))
    }

    @Test
    fun `speed is empty when line has none`() {
        assertEquals("", Engine.parseSpeed("[download] Destination: video.mp4"))
    }

}
