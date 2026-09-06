package io.github.kiramorano.localtube.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Тесты сборки команды yt-dlp.
 *
 * Engine.buildRequest раньше не проверялся ничем, хотя это единственное место,
 * где появляются --sub-langs и селектор формата. Поводом стала настоящая
 * поломка: по умолчанию стояло «ru,en» при включённом тумблере субтитров, и
 * yt-dlp получал языки, которых у видео нет.
 *
 * Проверяется итоговый список аргументов (buildCommand), а не внутренние поля:
 * именно он уходит в процесс.
 */
class EngineRequestTest {

    private val outDir = File(System.getProperty("java.io.tmpdir"), "lt-request-test")

    private fun command(
        formatId: String = "best",
        downloadSubs: Boolean = false,
        subLangs: String = "",
        audioLangs: List<String> = emptyList(),
        url: String = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    ): List<String> = Engine.buildRequest(
        url = url,
        formatId = formatId,
        outDir = outDir,
        downloadSubs = downloadSubs,
        subLangs = subLangs,
        cookiesPath = null,
        audioLangs = audioLangs
    ).buildCommand()

    /** Значение опции: yt-dlp принимает его следующим элементом списка. */
    private fun valueOf(cmd: List<String>, option: String): String? {
        val i = cmd.indexOf(option)
        return if (i >= 0 && i + 1 < cmd.size) cmd[i + 1] else null
    }

    // ---------- субтитры ----------

    @Test
    fun `empty subtitle languages add no subtitle options`() {
        // Главная проверка: пустые языки не дают ни --sub-langs с пустым
        // значением, ни осиротевшего --write-subs. Именно на этом ломалась
        // загрузка, когда по умолчанию стояло «ru,en».
        val cmd = command(downloadSubs = true, subLangs = "")

        assertFalse("--sub-langs", cmd.contains("--sub-langs"))
        assertFalse("--write-subs", cmd.contains("--write-subs"))
        assertFalse("--write-auto-subs", cmd.contains("--write-auto-subs"))
        assertFalse("пустой аргумент", cmd.contains(""))
    }

    @Test
    fun `subtitle options come as a whole block`() {
        val cmd = command(downloadSubs = true, subLangs = "ru,en")

        assertTrue(cmd.contains("--write-subs"))
        assertTrue(cmd.contains("--write-auto-subs"))
        assertEquals("ru,en", valueOf(cmd, "--sub-langs"))
    }

    @Test
    fun `subtitles switch off keeps languages unused`() {
        // Языки заданы, но тумблер выключен: дорожки не запрашиваются.
        val cmd = command(downloadSubs = false, subLangs = "ru,en")

        assertFalse(cmd.contains("--sub-langs"))
        assertFalse(cmd.contains("--write-subs"))
    }

    // ---------- формат и язык озвучки ----------

    @Test
    fun `format selector reaches the command`() {
        assertEquals("bestvideo*+bestaudio/best", valueOf(command(), "-f"))
    }

    @Test
    fun `audio language reaches the command`() {
        val cmd = command(audioLangs = listOf("ru"))

        assertEquals(
            "bestvideo*+bestaudio[language^=ru]/bestvideo*+bestaudio/best",
            valueOf(cmd, "-f")
        )
    }

    @Test
    fun `without audio language selector stays plain`() {
        assertEquals("bestvideo*+bestaudio/best", valueOf(command(audioLangs = emptyList()), "-f"))
    }

    @Test
    fun `tiktok keeps a single stream even with audio language`() {
        // Числовых id и раздельных потоков у TikTok нет: любой YouTube-селектор
        // кончается отказом «Requested format is not available».
        val cmd = command(
            audioLangs = listOf("ru"),
            url = "https://www.tiktok.com/@user/video/123"
        )

        assertEquals("best", valueOf(cmd, "-f"))
    }

    // ---------- прочее ----------

    @Test
    fun `merge format is normalized`() {
        // Неизвестный контейнер уходил в yt-dlp как есть и ронял склейку.
        val cmd = Engine.buildRequest(
            url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            formatId = "best",
            outDir = outDir,
            downloadSubs = false,
            subLangs = "",
            cookiesPath = null,
            mergeFormat = "avi"
        ).buildCommand()

        assertEquals(Engine.DEFAULT_MERGE_FORMAT, valueOf(cmd, "--merge-output-format"))
    }

    @Test
    fun `cookies are passed only when present`() {
        assertFalse(command().contains("--cookies"))

        val withCookies = Engine.buildRequest(
            url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            formatId = "best",
            outDir = outDir,
            downloadSubs = false,
            subLangs = "",
            cookiesPath = "/data/cookies.txt"
        ).buildCommand()
        assertEquals("/data/cookies.txt", valueOf(withCookies, "--cookies"))
    }

    @Test
    fun `resume is requested so a retry continues instead of restarting`() {
        assertTrue(command().contains("-c"))
    }
}
