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
