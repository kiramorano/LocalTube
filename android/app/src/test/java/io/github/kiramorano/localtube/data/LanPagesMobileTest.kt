package io.github.kiramorano.localtube.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Проверка мобильной вёрстки гостевых страниц.
 *
 * Гость почти всегда заходит с телефона, поэтому правила из static/css/mobile.css
 * повторены и здесь. Тесты сторожат именно те места, где вёрстка уже ломалась:
 * мелкие тап-цели, Shorts во всю ширину экрана и потеря запроса после поиска.
 *
 * Геометрию (реальные размеры в пикселях) измеряет
 * tests/browser/lan-mobile-audit.cjs; тут проверяются причины, а не следствия.
 */
class LanPagesMobileTest {

    private fun video(
        id: String = "vid",
        title: String = "Тест",
        author: String = "Автор",
        isShort: Boolean = false,
        description: String = ""
    ) = VideoItem(
        id = id,
        title = title,
        author = author,
        thumb = null,
        videoPath = "/tmp/$id.mp4",
        sizeMb = 1.0,
        isShort = isShort,
        source = "youtube",
        description = description
    )

    private fun style(): String {
        // Стили попадают в любую страницу, берём самую простую.
        val html = LanPages.unlockPage()
        val from = html.indexOf("<style>")
        val to = html.indexOf("</style>")
        assertTrue("на странице нет блока стилей", from >= 0 && to > from)
        return html.substring(from, to)
    }

    // ---------- площадь под палец ----------

    @Test
    fun `text fields and buttons are at least 44 pixels tall`() {
        val css = style()
        // Поле поиска было 35px, кнопка входа 33px: по таким целям палец мажет.
        assertTrue(
            "у поля ввода нет min-height под палец",
            Regex("""input\[type=search][^{]*\{[^}]*min-height: var\(--lt-tap\)""")
                .containsMatchIn(css)
        )
        assertTrue(
            "у кнопки нет min-height под палец",
            Regex("""\bbutton \{[^}]*min-height: var\(--lt-tap\)""").containsMatchIn(css)
        )
        assertTrue("тап-цель меньше 44px", css.contains("--lt-tap: 44px"))
    }

    @Test
    fun `header link to home is a tap target, not a bare line of text`() {
        val css = style()
        // У строчной ссылки высота равна строке текста (24px), поэтому нужен
        // отдельный класс с min-height.
        assertTrue(
            "ссылка на главную не растянута до тап-цели",
            Regex("""header \.home \{[^}]*min-height: var\(--lt-tap\)""").containsMatchIn(css)
        )
        assertTrue(
            "в разметке шапки нет класса home",
            LanPages.indexPage(Catalog.EMPTY).contains("class=\"home\"")
        )
    }

    @Test
    fun `channel link on the watch page is a tap target`() {
        val css = style()
        assertTrue(
            "ссылка на канал не растянута до тап-цели",
            Regex("""\.meta \.a \{[^}]*min-height: var\(--lt-tap\)""").containsMatchIn(css)
        )
    }

    @Test
    fun `input font is large enough that ios does not zoom the page`() {
        // Safari на iOS зумит страницу при фокусе в поле с шрифтом меньше 16px,
        // и вёрстка уезжает за экран.
        val css = style()
        val block = Regex("""input\[type=search][^{]*\{([^}]*)}""").find(css)?.groupValues?.get(1)
        assertTrue("не найден блок стилей поля ввода", block != null)
        assertTrue("шрифт поля меньше 16px — iOS зумит страницу", block!!.contains("font-size: 16px"))
    }

    // ---------- Shorts ----------

    @Test
    fun `shorts go to a horizontal shelf instead of a full width grid`() {
        val page = LanPages.indexPage(
            Catalog(
                videos = emptyList(),
                shorts = listOf(video(id = "s1", isShort = true)),
                authors = emptyList(),
                playlists = emptyList(),
                userVideos = emptyList()
            )
        )
        // В общей сетке обложка 9/16 занимала 687px — 81% экрана телефона.
        assertTrue("Shorts выводятся не полкой", page.contains("class=\"shelf shorts\""))
        assertFalse("Shorts снова попали в сетку", page.contains("class=\"grid shorts\""))

        val css = style()
        assertTrue(
            "полка не прокручивается по горизонтали",
            Regex("""\.shelf \{[^}]*overflow-x: auto""").containsMatchIn(css)
        )
        assertTrue(
            "карточка полки не ограничена по ширине",
            Regex("""\.shelf \.card \{[^}]*width: min\(""").containsMatchIn(css)
        )
    }

    @Test
    fun `normal videos stay in the grid`() {
        val page = LanPages.indexPage(
            Catalog(
                videos = listOf(video()),
                shorts = emptyList(),
                authors = emptyList(),
                playlists = emptyList(),
                userVideos = emptyList()
            )
        )
        assertTrue("обычные видео должны остаться сеткой", page.contains("class=\"grid\""))
    }

    @Test
    fun `narrow screens get a single column`() {
        val css = style()
        val media = Regex("""@media \(max-width: 400px\) \{(.*?)\n {8}}""", RegexOption.DOT_MATCHES_ALL)
            .find(css)?.groupValues?.get(1)
        assertTrue("нет медиазапроса под узкие экраны", media != null)
        assertTrue(
            "на узком экране сетка не в одну колонку",
            media!!.contains("grid-template-columns: minmax(0, 1fr)")
        )
    }

    // ---------- поиск ----------

    @Test
    fun `search keeps the query in the field`() {
        // Иначе уточнять запрос на телефоне приходится набором с нуля.
        val page = LanPages.searchPage("кошки", listOf(video()))
        assertTrue("запрос не вернулся в поле поиска", page.contains("value=\"кошки\""))
    }

    @Test
    fun `search field value is escaped`() {
        val page = LanPages.searchPage("\"><script>alert(1)</script>", emptyList())
        assertFalse("запрос протащил скрипт в разметку", page.contains("<script>alert(1)"))
        assertTrue(page.contains("&quot;&gt;&lt;script&gt;"))
    }

    @Test
    fun `empty query leaves the field empty`() {
        assertTrue(LanPages.indexPage(Catalog.EMPTY).contains("value=\"\""))
    }

    // ---------- доступность ----------

    @Test
    fun `card link has a readable name`() {
        // Обложка декоративная (alt пустой), поэтому имя ссылке даёт aria-label:
        // без него скринридер читает только адрес.
        val page = LanPages.channelPage("Автор", listOf(video(title = "Тест"))) { "" }
        assertTrue(
            "у карточки нет доступного имени",
            page.contains("aria-label=\"Тест. Канал Автор\"")
        )
        assertTrue("обложка должна быть декоративной", page.contains("alt=\"\""))
    }

    @Test
    fun `card label is escaped`() {
        val page = LanPages.channelPage("Автор", listOf(video(title = "\"злой\" <b>"))) { "" }
        assertFalse("кавычка разорвала атрибут", page.contains("aria-label=\"\"злой\""))
        assertTrue(page.contains("&quot;"))
    }

    @Test
    fun `search field and form are labelled`() {
        val page = LanPages.indexPage(Catalog.EMPTY)
        assertTrue("у поля поиска нет подписи", page.contains("aria-label=\"Поиск в библиотеке\""))
        assertTrue("форма поиска не помечена как поиск", page.contains("role=\"search\""))
        assertTrue("у ссылки на главную нет подписи", page.contains("aria-label=\"На главную\""))
    }

    // ---------- общее ----------

    @Test
    fun `every page declares the mobile viewport`() {
        val pages = listOf(
            "index" to LanPages.indexPage(Catalog.EMPTY),
            "unlock" to LanPages.unlockPage(),
            "search" to LanPages.searchPage("q", emptyList()),
            "watch" to LanPages.watchPage(video(), "/media/a.mp4", emptyList(), "/subtitles/vid"),
            "channel" to LanPages.channelPage("Автор", listOf(video())) { "" }
        )
        for ((name, html) in pages) {
            assertTrue(
                "на странице $name нет meta viewport — телефон отрисует её как десктоп",
                html.contains("""<meta name="viewport" content="width=device-width, initial-scale=1">""")
            )
        }
    }

    @Test
    fun `long titles wrap instead of stretching the page sideways`() {
        val css = style()
        // Длинное слово без пробелов иначе растягивает страницу и появляется
        // горизонтальный скролл.
        for (sel in listOf("""\.card \.t""", """\.meta h1""", """\.desc""")) {
            assertTrue(
                "нет переноса длинных слов в $sel",
                Regex("""$sel \{[^}]*overflow-wrap: anywhere""").containsMatchIn(css)
            )
        }
    }

    @Test
    fun `theme colours come from variables, not hardcoded values`() {
        val css = style()
        // Хардкод цвета в одном месте уже приводил к тёмному тексту на тёмном фоне.
        assertTrue(css.contains("--lt-bg: #0f0f0f"))
        assertTrue(
            "фон body должен браться из переменной",
            Regex("""body \{[^}]*background: var\(--lt-bg\)""").containsMatchIn(css)
        )
    }

    @Test
    fun `video player leaves room for the title below it`() {
        val css = style()
        // 78vh занимало почти весь экран вместе с шапкой: заголовок уходил
        // за сгиб, и было непонятно, что играет.
        val block = Regex("""\bvideo \{([^}]*)}""").find(css)?.groupValues?.get(1)
        assertTrue("не найден блок стилей плеера", block != null)
        val vh = Regex("""max-height: (\d+)vh""").find(block!!)?.groupValues?.get(1)?.toInt()
        assertEquals(72, vh)
    }
}
