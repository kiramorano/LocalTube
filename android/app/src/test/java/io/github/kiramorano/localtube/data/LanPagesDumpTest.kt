package io.github.kiramorano.localtube.data

import org.junit.Test
import java.io.File

/**
 * Вспомогательный прогон: сохраняет страницы гостевого сервера в HTML-файлы,
 * чтобы их можно было измерить настоящим браузером.
 *
 * Это не проверка, а выгрузка: тест всегда проходит. Путь задаётся через
 * -Dlt.dump.dir, без него прогон ничего не делает.
 */
class LanPagesDumpTest {

    @Test
    fun `dump pages for browser audit`() {
        // Переменная окружения, а не -D: системные свойства Gradle до JVM
        // тестов не доходят, а окружение наследуется.
        val dir = System.getenv("LT_DUMP_DIR") ?: return
        val out = File(dir).apply { mkdirs() }

        val many = (1..12).map { i ->
            VideoItem(
                id = "v$i",
                title = "Очень длинное название видео номер $i, которое должно обрезаться на телефоне",
                author = "Канал с длинным именем $i",
                thumb = null,
                videoPath = "/tmp/v$i.mp4",
                sizeMb = 12.5,
                isShort = false,
                source = "youtube",
                durationSec = 754,
                description = "Описание видео.\nВторая строка описания."
            )
        }
        val shorts = (1..6).map { i ->
            VideoItem(
                id = "s$i",
                title = "Shorts номер $i с длинным заголовком",
                author = "Автор $i",
                thumb = null,
                videoPath = "/tmp/s$i.mp4",
                sizeMb = 3.0,
                isShort = true,
                source = "youtube"
            )
        }
        val catalog = Catalog(
            videos = many,
            shorts = shorts,
            authors = listOf(Author("Канал с длинным именем 1", null, 12)),
            playlists = emptyList(),
            userVideos = many.take(3)
        )

        File(out, "index.html").writeText(LanPages.indexPage(catalog))
        File(out, "unlock.html").writeText(LanPages.unlockPage())
        File(out, "unlock-error.html").writeText(LanPages.unlockPage("Неверный PIN, осталось 9 попыток"))
        File(out, "search.html").writeText(LanPages.searchPage("длинное", many))
        File(out, "search-empty.html").writeText(LanPages.searchPage("нет такого", emptyList()))
        File(out, "watch.html").writeText(
            LanPages.watchPage(
                many.first(),
                "/media/Автор/vid/video.mp4",
                listOf("ru" to "ru.vtt", "en" to "en.vtt"),
                "/subtitles/vid"
            )
        )
        File(out, "channel.html").writeText(
            LanPages.channelPage("Канал с длинным именем 1", many) { "/media/x.mp4" }
        )
        File(out, "empty.html").writeText(
            LanPages.indexPage(
                Catalog(emptyList(), emptyList(), emptyList(), emptyList(), emptyList())
            )
        )
        println("dumped to ${out.absolutePath}")
    }
}
