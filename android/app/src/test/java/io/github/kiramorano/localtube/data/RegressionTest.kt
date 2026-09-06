package io.github.kiramorano.localtube.data

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Тесты на исправленные дефекты. Каждый метод соответствует поведению, которое
 * до правки было сломано: перечитывать их стоит вместе с комментариями в коде.
 */
class RegressionTest {

    // ---------- Engine: раскадровки не должны выглядеть как аудио ----------

    @Test
    fun `storyboard formats are not offered as audio`() {
        // У раскадровки оба кодека равны "none": раньше она попадала в список
        // как «Аудио mhtml» и загрузка такого формата всегда падала.
        val formats = Engine.parseFormatsJson(
            JSONArray(
                """[{"format_id":"sb0","vcodec":"none","acodec":"none","ext":"mhtml"}]"""
            )
        )
        assertTrue("раскадровка не формат для скачивания", formats.isEmpty())
    }

    @Test
    fun `audio format without id is skipped`() {
        val formats = Engine.parseFormatsJson(
            JSONArray("""[{"format_id":"","vcodec":"none","acodec":"mp4a.40.2","ext":"m4a"}]""")
        )
        assertTrue(formats.isEmpty())
    }

    @Test
    fun `real audio format is still offered`() {
        val formats = Engine.parseFormatsJson(
            JSONArray("""[{"format_id":"140","vcodec":"none","acodec":"mp4a.40.2","ext":"m4a"}]""")
        )
        assertEquals(1, formats.size)
        assertFalse(formats.first().isVideo)
    }

    // ---------- Engine: языки субтитров ----------

    @Test
    fun `sub langs match ignoring case`() {
        // yt-dlp отдаёт zh-Hans и pt-BR: приведённая к нижнему регистру
        // настройка с ними никогда не совпадала.
        val chosen = Engine.chooseSubLangs(listOf("zh-Hans", "pt-BR", "en"), listOf("ZH-hans"))
        assertEquals(listOf("zh-Hans"), chosen)
    }

    @Test
    fun `sub langs match base language`() {
        val chosen = Engine.chooseSubLangs(listOf("ru-RU", "en-US"), listOf("ru"))
        assertEquals(listOf("ru-RU"), chosen)
    }

    @Test
    fun `sub langs without match download nothing`() {
        // Раньше подставлялись два первых доступных языка, которых никто не просил.
        val chosen = Engine.chooseSubLangs(listOf("de", "fr"), listOf("ru", "en"))
        assertTrue(chosen.isEmpty())
    }

    @Test
    fun `sub langs keep preference order and skip blanks`() {
        val chosen = Engine.chooseSubLangs(listOf("en", "ru"), listOf("ru", " ", "en"))
        assertEquals(listOf("ru", "en"), chosen)
    }

    @Test
    fun `sub langs empty when nothing available`() {
        assertTrue(Engine.chooseSubLangs(emptyList(), listOf("ru")).isEmpty())
    }

    @Test
    fun `subtitles are off by default`() {
        // Раньше по умолчанию стояло «ru,en» при включённом тумблере, и загрузка
        // ломалась на видео без таких дорожек. Веб-версия
        // (download_prefs.DEFAULTS) субтитры тоже не качает без спроса.
        assertEquals("", Settings.DEFAULT_SUB_LANGS)
        assertFalse(Settings.DEFAULT_DOWNLOAD_SUBS)
    }


    // ---------- UserDataStore: вытеснение позиций ----------

    @Test
    fun `saved position is never evicted by the limit`() {
        // Сортировка шла по id видео, поэтому лимит мог выбросить позицию,
        // записанную прямо сейчас.
        val full = LinkedHashMap<String, Long>()
        repeat(UserDataStore.POSITION_LIMIT) { i -> full["zzz-video-$i"] = 1_000L }
        val next = UserDataStore.trimPositions(full, "aaa-newest", 60_000L)
        assertEquals(UserDataStore.POSITION_LIMIT, next.size)
        assertEquals(60_000L, next["aaa-newest"])
    }

    @Test
    fun `oldest position is evicted first`() {
        val positions = LinkedHashMap<String, Long>()
        repeat(UserDataStore.POSITION_LIMIT) { i -> positions["v$i"] = i.toLong() + 5_000L }
        val next = UserDataStore.trimPositions(positions, "fresh", 9_000L)
        assertNull("самая старая запись должна уйти", next["v0"])
        assertEquals(9_000L, next["fresh"])
    }

    @Test
    fun `position near start is forgotten`() {
        val next = UserDataStore.trimPositions(mapOf("v" to 30_000L), "v", 1_000L)
        assertNull(next["v"])
    }

    @Test
    fun `repeated save moves entry to the end`() {
        val positions = linkedMapOf("a" to 6_000L, "b" to 7_000L)
        val next = UserDataStore.trimPositions(positions, "a", 8_000L)
        assertEquals(listOf("b", "a"), next.keys.toList())
        assertEquals(8_000L, next["a"])
    }

    // ---------- DownloadManager: результат загрузки ----------

    @Test
    fun `audio results are recognised as downloaded files`() {
        // Загрузка «только звук» всегда падала с «yt-dlp не вернул файлы»,
        // потому что расширения m4a и opus не проверялись.
        assertTrue("m4a" in DownloadManager.AUDIO_EXTS)
        assertTrue("opus" in DownloadManager.AUDIO_EXTS)
        assertTrue("mp3" in DownloadManager.AUDIO_EXTS)
        assertTrue("mp4" in DownloadManager.VIDEO_EXTS)
        assertTrue("mkv" in DownloadManager.VIDEO_EXTS)
    }

    @Test
    fun `video and audio extensions do not overlap`() {
        assertTrue((DownloadManager.VIDEO_EXTS intersect DownloadManager.AUDIO_EXTS).isEmpty())
    }

    // ---------- Library: определение Shorts ----------

    @Test
    fun `vertical video is a short`() {
        assertTrue(isShort("""{"height":1920,"width":1080}"""))
    }

    @Test
    fun `short duration without known width is a short`() {
        // Раньше условие содержало ещё и h > w и не выполнялось никогда.
        assertTrue(isShort("""{"duration":45}"""))
    }

    @Test
    fun `landscape long video is not a short`() {
        assertFalse(isShort("""{"height":1080,"width":1920,"duration":600}"""))
    }

    @Test
    fun `landscape short video is not a short`() {
        // Ширина известна и это горизонтальное видео: коротким роликом не считаем.
        assertFalse(isShort("""{"height":1080,"width":1920,"duration":30}"""))
    }

    @Test
    fun `shorts url marks a short`() {
        assertTrue(isShort("""{"webpage_url":"https://youtube.com/shorts/abc"}"""))
    }

    @Test
    fun `shorts hashtag marks a short`() {
        assertTrue(isShort("""{"title":"Смешно #Shorts"}"""))
    }

    private fun isShort(json: String): Boolean = Library.isShort(JSONObject(json))
}
