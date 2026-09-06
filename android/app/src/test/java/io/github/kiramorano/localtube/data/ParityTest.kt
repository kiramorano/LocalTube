package io.github.kiramorano.localtube.data

import io.github.kiramorano.localtube.ui.PipHelper
import io.github.kiramorano.localtube.ui.screens.formatSubscribers
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Тесты паритета с настольной версией: пресеты конвертации, эквалайзер,
 * разбор оформления канала и обход разделов канала.
 *
 * Всё проверяемое здесь — чистые функции: они специально вынесены из классов,
 * которым нужен Context, чтобы правила можно было проверять без эмулятора.
 */
class ParityTest {

    // ---------- пресеты конвертации ----------

    @Test
    fun `presets cover the same qualities as the desktop version`() {
        // custom_quality.py предлагает эти варианты; расхождение означало бы,
        // что на телефоне часть кнопок «Другое качество» отсутствует.
        val ids = Ffmpeg.Preset.entries.map { it.id }.toSet()
        assertTrue(ids.containsAll(setOf("2160", "1440", "1080", "720", "480", "144")))
        assertTrue(ids.containsAll(setOf("enhance", "enhance_2160")))
    }

    @Test
    fun `preset ids become file names without collisions`() {
        val names = Ffmpeg.Preset.entries.map { "video_${it.id}.mp4" }
        assertEquals(names.size, names.toSet().size)
    }

    @Test
    fun `preset resolves by id and rejects unknown ones`() {
        assertEquals(Ffmpeg.Preset.Q1080, Ffmpeg.Preset.from("1080"))
        // null, а не подстановка ближайшего: неизвестный id приходит только из
        // испорченных данных, и молча конвертировать не в то качество нельзя.
        assertNull(Ffmpeg.Preset.from("999"))
        assertNull(Ffmpeg.Preset.from(null))
    }

    @Test
    fun `every preset has a label and description for the picker`() {
        Ffmpeg.Preset.entries.forEach {
            assertTrue(it.id, it.label.isNotBlank())
            assertTrue(it.id, it.description.isNotBlank())
        }
    }

    // ---------- окружение ffmpeg ----------

    @Test
    fun `ffmpeg library path covers both packages`() {
        // libavcodec лежит в ffmpeg/usr/lib, а libc++_shared.so — только в
        // python/usr/lib, и он нужен librubberband.so из состава ffmpeg. Раньше
        // второго пути не было, и ffmpeg не запускался вовсе: молча не работали
        // пресеты качества, MP3 и превью.
        val path = Ffmpeg.joinLibraryPath("/data/data/app/no_backup/youtubedl-android/packages")
        val parts = path.split(":")
        assertEquals(2, parts.size)
        assertTrue(parts[0].endsWith("/ffmpeg/usr/lib"))
        assertTrue(parts[1].endsWith("/python/usr/lib"))
    }

    @Test
    fun `ffmpeg library path uses the android separator`() {
        // File.pathSeparator под Windows дал бы «;», который Android не понимает.
        val path = Ffmpeg.joinLibraryPath("/packages")
        assertFalse(path.contains(";"))
        assertFalse(path.contains("\\"))
    }

    // ---------- разбор вывода ffmpeg ----------

    @Test
    fun `progress line is parsed into milliseconds`() {
        // 01:02:03.50 -> сотые доли, а не миллисекунды: .50 это 500 мс.
        assertEquals(
            (1 * 3600 + 2 * 60 + 3) * 1000L + 500,
            Ffmpeg.parseProgressMs("frame= 120 fps=30 time=01:02:03.50 bitrate=1000kbits/s")
        )
    }

    @Test
    fun `line without time gives no progress`() {
        assertNull(Ffmpeg.parseProgressMs("Press [q] to stop, [?] for help"))
    }

    @Test
    fun `progress accepts a comma as the decimal separator`() {
        assertEquals(63_250L, Ffmpeg.parseProgressMs("time=00:01:03,25"))
    }

    @Test
    fun `duration line is parsed`() {
        assertEquals(
            (10 * 60 + 5) * 1000L + 250,
            Ffmpeg.parseDurationMs("  Duration: 00:10:05.25, start: 0.000000, bitrate: 800 kb/s")
        )
    }

    @Test
    fun `progress line is not mistaken for a duration`() {
        assertNull(Ffmpeg.parseDurationMs("frame= 10 time=00:00:01.00"))
    }

    // ---------- эквалайзер ----------

    @Test
    fun `preset resolves by id and falls back to off`() {
        assertEquals(AudioEffects.Preset.BASS, AudioEffects.Preset.from("bass"))
        assertEquals(AudioEffects.Preset.OFF, AudioEffects.Preset.from("no-such-preset"))
        assertEquals(AudioEffects.Preset.OFF, AudioEffects.Preset.from(null))
    }

    @Test
    fun `every preset defines a gain for every frequency`() {
        // Иначе gainForFrequency упал бы с IndexOutOfBounds на нужной полосе.
        AudioEffects.Preset.entries.forEach {
            assertEquals(it.id, AudioEffects.FREQUENCIES.size, it.gainsDb.size)
        }
    }

    @Test
    fun `off preset leaves every band flat`() {
        listOf(60, 230, 1000, 9000, 20000).forEach {
            assertEquals(0.0, AudioEffects.gainForFrequency(AudioEffects.Preset.OFF, it), 0.001)
        }
    }

    @Test
    fun `gain at a defined frequency matches the preset exactly`() {
        val bass = AudioEffects.Preset.BASS
        assertEquals(bass.gainsDb.first(), AudioEffects.gainForFrequency(bass, 60), 0.001)
        assertEquals(bass.gainsDb[1], AudioEffects.gainForFrequency(bass, 170), 0.001)
    }

    @Test
    fun `gain between two points is interpolated, not snapped`() {
        // 230 Гц лежит между 170 (6 дБ) и 350 (4 дБ): значение должно быть
        // строго между ними, иначе половина настройки терялась бы.
        val g = AudioEffects.gainForFrequency(AudioEffects.Preset.BASS, 230)
        assertTrue("получено $g", g < 6.0 && g > 4.0)
        assertNotEquals(6.0, g, 0.001)
    }

    @Test
    fun `frequencies outside the range clamp to the edge gains`() {
        val treble = AudioEffects.Preset.TREBLE
        assertEquals(treble.gainsDb.first(), AudioEffects.gainForFrequency(treble, 20), 0.001)
        assertEquals(treble.gainsDb.last(), AudioEffects.gainForFrequency(treble, 20000), 0.001)
    }

    @Test
    fun `bass preset lifts lows and leaves highs alone`() {
        val p = AudioEffects.Preset.BASS
        assertTrue(AudioEffects.gainForFrequency(p, 60) > 0)
        assertEquals(0.0, AudioEffects.gainForFrequency(p, 14000), 0.001)
    }

    // ---------- оформление канала ----------

    @Test
    fun `largest square thumbnail becomes the avatar`() {
        val j = JSONObject().put(
            "thumbnails",
            JSONArray()
                .put(thumb("small.jpg", 48, 48))
                .put(thumb("big.jpg", 900, 900))
                .put(thumb("mid.jpg", 176, 176))
        )
        assertEquals("big.jpg", Engine.parseChannelAssets(j).avatarUrl)
    }

    @Test
    fun `wide thumbnail becomes the banner, not the avatar`() {
        val j = JSONObject().put(
            "thumbnails",
            JSONArray()
                .put(thumb("avatar.jpg", 176, 176))
                .put(thumb("banner.jpg", 2560, 424))
        )
        val assets = Engine.parseChannelAssets(j)
        assertEquals("banner.jpg", assets.bannerUrl)
        assertEquals("avatar.jpg", assets.avatarUrl)
    }

    @Test
    fun `banner is recognised by id when sizes are missing`() {
        val j = JSONObject().put(
            "thumbnails",
            JSONArray()
                .put(JSONObject().put("url", "b.jpg").put("id", "banner_uncropped"))
                .put(thumb("a.jpg", 176, 176))
        )
        val assets = Engine.parseChannelAssets(j)
        assertEquals("b.jpg", assets.bannerUrl)
        assertEquals("a.jpg", assets.avatarUrl)
    }

    @Test
    fun `thumbnails without url are skipped`() {
        val j = JSONObject().put(
            "thumbnails",
            JSONArray()
                .put(JSONObject().put("width", 900).put("height", 900))
                .put(thumb("ok.jpg", 100, 100))
        )
        assertEquals("ok.jpg", Engine.parseChannelAssets(j).avatarUrl)
    }

    @Test
    fun `channel without thumbnails yields empty assets instead of failing`() {
        val assets = Engine.parseChannelAssets(JSONObject().put("channel", "Имя"))
        assertEquals("Имя", assets.title)
        assertEquals("", assets.avatarUrl)
        assertEquals("", assets.bannerUrl)
    }

    @Test
    fun `uploader is used when channel field is absent`() {
        val assets = Engine.parseChannelAssets(JSONObject().put("uploader", "Автор"))
        assertEquals("Автор", assets.title)
    }

    @Test
    fun `subscriber count is read from channel_follower_count`() {
        val assets = Engine.parseChannelAssets(JSONObject().put("channel_follower_count", 1234567))
        assertEquals(1_234_567L, assets.subscribers)
    }

    private fun thumb(url: String, w: Int, h: Int) =
        JSONObject().put("url", url).put("width", w).put("height", h)

    // ---------- разделы канала ----------

    @Test
    fun `channel tabs cover videos shorts and streams`() {
        val urls = Engine.channelTabUrls("https://www.youtube.com/@someone")
        assertEquals(3, urls.size)
        assertTrue(urls.any { it.endsWith("/videos") })
        assertTrue(urls.any { it.endsWith("/shorts") })
        assertTrue(urls.any { it.endsWith("/streams") })
    }

    @Test
    fun `existing tab suffix is not duplicated`() {
        val urls = Engine.channelTabUrls("https://www.youtube.com/@someone/videos")
        assertTrue(urls.none { it.contains("/videos/videos") })
    }

    @Test
    fun `trailing slash does not produce double slashes`() {
        val urls = Engine.channelTabUrls("https://www.youtube.com/@someone/")
        assertTrue(urls.none { it.contains("@someone//") })
    }

    // ---------- player_client ----------

    @Test
    fun `player client list starts with auto and has no duplicates`() {
        assertEquals("", Settings.PLAYER_CLIENTS.first())
        assertEquals(Settings.PLAYER_CLIENTS.size, Settings.PLAYER_CLIENTS.toSet().size)
    }

    @Test
    fun `every player client has a label`() {
        Settings.PLAYER_CLIENTS.forEach {
            assertTrue(it, Settings.playerClientLabel(it).isNotBlank())
        }
        assertEquals("Авто", Settings.playerClientLabel(""))
    }

    // ---------- коды языков ----------

    @Test
    fun `audio langs are off by default like on the server`() {
        // download_prefs.DEFAULTS["audio_langs"] = []: обновление приложения не
        // должно молча менять озвучку у скачиваемых видео.
        assertEquals("", Settings.DEFAULT_AUDIO_LANGS)
    }

    @Test
    fun `lang list drops blanks and trailing commas`() {
        // Поле настроек пишется на каждый символ, поэтому «ru,» — обычное
        // состояние. Дословно доехав до --sub-langs, оно ломало загрузку.
        assertEquals("ru,en", Settings.normalizeLangs(" ru , en "))
        assertEquals("ru", Settings.normalizeLangs("ru,"))
        assertEquals("", Settings.normalizeLangs(" , "))
        assertEquals("", Settings.normalizeLangs(null))
    }

    @Test
    fun `lang list keeps regional codes`() {
        // pt-BR и zh-Hans YouTube отдаёт именно так.
        assertEquals("pt-BR", Settings.normalizeLangs("pt-BR"))
        assertEquals("zh-Hans", Settings.normalizeLangs("zh-Hans"))
    }

    @Test
    fun `lang list rejects unsafe codes`() {
        // Код уходит в имя файла субтитров и в фильтр [language^=...]:
        // «../../evil» увёл бы запись за пределы папки, а пробел ломает разбор
        // селектора yt-dlp. Тот же шаблон, что LANG_RE в download_prefs.py.
        assertEquals("", Settings.normalizeLangs("../../evil"))
        assertEquals("", Settings.normalizeLangs("ru ru"))
        assertEquals("", Settings.normalizeLangs("ru;rm -rf /"))
        assertEquals("", Settings.normalizeLangs("русский"))
        // Годное рядом с мусорным сохраняется: набор языков не должен пропадать
        // целиком из-за одной опечатки.
        assertEquals("ru,en", Settings.normalizeLangs("ru,!!,en"))
    }

    @Test
    fun `lang list drops duplicates`() {
        // Как _clean_langs на сервере: повтор означал бы повторную загрузку того
        // же файла субтитров, а в селекторе — лишнюю одинаковую ветку.
        assertEquals("ru,en", Settings.normalizeLangs("ru,en,ru"))
    }

    // ---------- имя в шапке ----------

    @Test
    fun `empty user name falls back to the default`() {
        // Иначе кружок с первой буквой в шапке оставался пустым.
        assertEquals(Settings.DEFAULT_USER_NAME, Settings.normalizeUserName(""))
        assertEquals(Settings.DEFAULT_USER_NAME, Settings.normalizeUserName("   "))
        assertEquals(Settings.DEFAULT_USER_NAME, Settings.normalizeUserName(null))
    }

    @Test
    fun `user name is trimmed and limited`() {
        assertEquals("Кира", Settings.normalizeUserName("  Кира  "))
        assertEquals(Settings.MAX_USER_NAME, Settings.normalizeUserName("я".repeat(200)).length)
    }

    // ---------- PiP ----------

    /** Пропорции как число: пара мало читаема в утверждениях. */
    private fun pipRatio(w: Int, h: Int): Double {
        val (rw, rh) = PipHelper.aspectRatio(w, h)
        return rw.toDouble() / rh
    }

    @Test
    fun `pip keeps the real aspect ratio when it is allowed`() {
        assertEquals(1920.0 / 1080, pipRatio(1920, 1080), 0.001)
    }

    @Test
    fun `unknown video size falls back to 16 by 9`() {
        // До первого кадра ExoPlayer отдаёт нули, а Rational(0,0) система не
        // принимает и бросает исключение.
        assertEquals(16.0 / 9, pipRatio(0, 0), 0.001)
    }

    @Test
    fun `too wide video is clamped to the system limit`() {
        val r = pipRatio(4000, 500)
        assertTrue("получено $r", r <= 2.39)
    }

    @Test
    fun `too tall video is clamped to the system limit`() {
        // Вертикальные Shorts: 9:16 внутри границ, а 1:5 уже нет.
        val r = pipRatio(500, 2500)
        assertTrue("получено $r", r >= 1 / 2.39 - 0.001)
    }

    @Test
    fun `vertical shorts keep their own ratio`() {
        assertEquals(1080.0 / 1920, pipRatio(1080, 1920), 0.001)
    }

    // ---------- подписчики ----------

    @Test
    fun `subscribers are shortened to millions and thousands`() {
        assertTrue(formatSubscribers(1_234_567).startsWith("1,2 млн"))
        assertTrue(formatSubscribers(12_300_000).startsWith("12 млн"))
        assertTrue(formatSubscribers(1_500).startsWith("1,5 тыс."))
        assertTrue(formatSubscribers(45_000).startsWith("45 тыс."))
    }

    @Test
    fun `small subscriber counts are shown as is`() {
        assertEquals("999 подписчиков", formatSubscribers(999))
        assertEquals("0 подписчиков", formatSubscribers(0))
    }

    // ---------- проверка названий коллекций ----------

    @Test
    fun `watch later id matches the server`() {
        // Файл userdata.json переносится с ПК: другой id означал бы, что
        // «Смотреть позже» с компьютера превратится в обычную коллекцию.
        assertEquals("watch-later", VideoCollection.WATCH_LATER_ID)
    }

    @Test
    fun `collection limits match userdata py`() {
        assertEquals(100, VideoCollection.TITLE_LIMIT)
        assertEquals(1000, VideoCollection.VIDEOS_LIMIT)
        assertEquals(200, VideoCollection.COUNT_LIMIT)
    }
}
