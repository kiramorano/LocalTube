package io.github.kiramorano.localtube.data

/**
 * Страницы и JSON для гостей локальной сети.
 *
 * Вёрстка простая и самодостаточная: телефон отдаёт её любому браузеру в сети, и
 * тащить сюда стили десктопной версии незачем — там половина css завязана на
 * шаблоны Flask. Задача страниц — дать посмотреть библиотеку, а не повторить
 * интерфейс попиксельно.
 *
 * Правила мобильной вёрстки при этом повторены осознанно (тап-цели 44px, полка
 * для вертикальных Shorts, шрифт полей 16px): гость почти всегда заходит с
 * телефона. Разметку страниц измеряет tests/browser/lan-mobile-audit.cjs,
 * выгрузку для него делает LanPagesDumpTest.
 *
 * Всё, что приходит из данных, экранируется: названия видео содержат кавычки и
 * угловые скобки, и без экранирования страница ломается, а чужой заголовок мог
 * бы протащить скрипт.
 */
internal object LanPages {

    /** Прозрачный GIF 1x1: заглушка вместо отсутствующей обложки. */
    val PLACEHOLDER_GIF: ByteArray = byteArrayOf(
        0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x01, 0x00, 0x01, 0x00, 0x80.toByte(), 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x21, 0xF9.toByte(), 0x04, 0x01, 0x00, 0x00, 0x00,
        0x00, 0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x02, 0x02, 0x44,
        0x01, 0x00, 0x3B
    )

    fun escapeHtml(text: String): String = text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")
        .replace("'", "&#39;")

    fun escapeJson(text: String): String = buildString {
        for (ch in text) {
            when (ch) {
                '"' -> append("\\\"")
                '\\' -> append("\\\\")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                // Управляющие символы обязаны быть экранированы, иначе JSON
                // невалиден: они встречаются в описаниях видео.
                else -> if (ch < ' ') append("\\u%04x".format(ch.code)) else append(ch)
            }
        }
    }

    /**
     * Стили гостевых страниц.
     *
     * Числа здесь не произвольные, их задают два ограничения телефона:
     *
     * 1. Площадь под палец — 44x44 CSS-пикселя (Apple HIG и Material сходятся).
     *    Поле поиска было высотой 35px, кнопка входа — 33px, ссылка на главную —
     *    24px: по таким целям палец промахивается.
     * 2. Shorts вертикальные (9/16). В общей сетке карточка растягивалась на всю
     *    ширину, и одна обложка занимала 687px — 81% экрана телефона. Поэтому
     *    Shorts вынесены в горизонтальную полку с узкими карточками, как в
     *    веб-версии.
     */
    private const val STYLE = """
        :root { color-scheme: dark; --lt-bg: #0f0f0f; --lt-surface: #1c1c1c;
                --lt-text: #f1f1f1; --lt-muted: #aaa; --lt-border: #3a3a3a;
                --lt-accent: #3ea6ff; --lt-tap: 44px; }
        * { box-sizing: border-box; }
        html { -webkit-text-size-adjust: 100%; }
        body { margin: 0; font: 15px/1.4 system-ui, sans-serif;
               background: var(--lt-bg); color: var(--lt-text); }
        a { color: inherit; text-decoration: none; }

        header { display: flex; align-items: center; gap: 12px; padding: 8px 12px;
                 background: var(--lt-surface); position: sticky; top: 0; z-index: 5;
                 border-bottom: 1px solid var(--lt-border); }
        /* min-height и flex-центрирование: у строчной ссылки высота равна строке
           текста (24px), и как тап-цель она слишком мелкая. */
        header .home { display: inline-flex; align-items: center; min-height: var(--lt-tap);
                       padding: 0 4px; flex-shrink: 0; }
        header b { font-size: 17px; }
        header form { margin-left: auto; min-width: 0; }

        input[type=search], input[type=text], input[type=password] {
            min-height: var(--lt-tap); padding: 10px 12px; border-radius: 10px;
            border: 1px solid var(--lt-border); background: #101010; color: var(--lt-text);
            font-size: 16px; width: 100%; }
        /* 16px не случайно: при меньшем размере Safari на iOS зумит страницу при
           фокусе в поле, и вёрстка уезжает. */
        button { min-height: var(--lt-tap); padding: 11px 18px; border-radius: 22px;
                 border: 0; background: var(--lt-accent); color: #06121f;
                 font-size: 15px; font-weight: 600; cursor: pointer; }

        main { padding: 12px; }
        h2 { font-size: 16px; margin: 22px 0 10px; }

        .grid { display: grid; gap: 14px;
                grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); }
        .card img { width: 100%; aspect-ratio: 16/9; object-fit: cover;
                    border-radius: 12px; background: #222; display: block; }
        .card .t { margin-top: 7px; font-weight: 600; font-size: 15px; line-height: 1.35;
                   display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
                   overflow: hidden; overflow-wrap: anywhere; }
        .card .a { color: var(--lt-muted); font-size: 13px; margin-top: 3px;
                   overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

        /* Полка Shorts: горизонтальная прокрутка вместо сетки на всю ширину. */
        .shelf { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 8px;
                 scroll-snap-type: x proximity; -webkit-overflow-scrolling: touch;
                 scrollbar-width: none; }
        .shelf::-webkit-scrollbar { display: none; }
        .shelf .card { flex: 0 0 auto; width: min(150px, 40vw); scroll-snap-align: start; }
        .shelf .card img { aspect-ratio: 9/16; }

        video { width: 100%; max-height: 72vh; background: #000; border-radius: 12px;
                display: block; }
        .meta { margin-top: 14px; }
        .meta h1 { font-size: 19px; line-height: 1.3; margin: 0 0 8px;
                   overflow-wrap: anywhere; }
        /* Ссылка на канал — тоже тап-цель, а не просто подпись. */
        .meta .a { display: inline-flex; align-items: center; min-height: var(--lt-tap);
                   color: var(--lt-muted); }
        .desc { color: #bbb; white-space: pre-wrap; margin-top: 12px; font-size: 14px;
                background: var(--lt-surface); border-radius: 12px; padding: 12px;
                overflow-wrap: anywhere; }
        .empty { color: #888; padding: 30px 0; }

        .login { max-width: 340px; margin: 10vh auto; padding: 0 16px; text-align: center; }
        .login form { display: flex; flex-direction: column; gap: 12px; margin-top: 18px; }
        .err { color: #ff8a80; margin-top: 12px; font-size: 14px; }
        .hint { color: #999; font-size: 13px; margin-top: 14px; line-height: 1.45; }

        /* Узкие экраны: две колонки обычных видео не влезают, полка Shorts
           сужается вместе с ними. */
        @media (max-width: 400px) {
            .grid { grid-template-columns: minmax(0, 1fr); gap: 12px; }
            header form { flex: 1; }
        }
    """

    private fun page(title: String, body: String): String = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>$STYLE</style>
</head>
<body>
$body
</body>
</html>"""

    /** Страница ввода PIN. Работает без JavaScript: обычная форма. */
    fun unlockPage(error: String = ""): String = page(
        "LocalTube — вход",
        """
<div class="login">
  <b>LocalTube</b>
  <p class="hint">Введите PIN, показанный в настройках приложения на устройстве владельца.</p>
  <form method="post" action="/api/network/unlock">
    <input type="password" name="pin" inputmode="numeric" autocomplete="off"
           placeholder="PIN" maxlength="${LanAccess.PIN_LENGTH}" autofocus>
    <button type="submit">Войти</button>
  </form>
  ${if (error.isBlank()) "" else "<div class=\"err\">${escapeHtml(error)}</div>"}
</div>
"""
    )

    private fun header(query: String = ""): String = """
<header>
  <a class="home" href="/" aria-label="На главную"><b>LocalTube</b></a>
  <form method="get" action="/search" role="search">
    <input type="search" name="q" placeholder="Поиск в библиотеке"
           aria-label="Поиск в библиотеке" value="${escapeHtml(query)}">
  </form>
</header>
"""

    private fun card(v: VideoItem): String {
        val thumb = "/api/thumbnail/${escapeHtml(v.id)}"
        // Обложка декоративная (alt пустой), поэтому имя ссылке даёт aria-label:
        // без него скринридер читает только URL.
        val label = escapeHtml("${v.title}. Канал ${v.author}")
        return """
<a class="card" href="/watch/${escapeHtml(v.id)}" aria-label="$label">
  <img src="$thumb" alt="" loading="lazy">
  <div class="t">${escapeHtml(v.title)}</div>
  <div class="a">${escapeHtml(v.author)}</div>
</a>"""
    }

    /**
     * Раздел каталога. Shorts выводятся полкой с горизонтальной прокруткой:
     * в сетке вертикальная обложка 9/16 занимала почти весь экран телефона.
     */
    private fun section(title: String, items: List<VideoItem>, shorts: Boolean = false): String {
        if (items.isEmpty()) return ""
        val cls = if (shorts) "shelf shorts" else "grid"
        return """
<h2>${escapeHtml(title)}</h2>
<div class="$cls">${items.joinToString("") { card(it) }}</div>"""
    }

    fun indexPage(catalog: Catalog): String {
        val empty = catalog.videos.isEmpty() && catalog.shorts.isEmpty() &&
            catalog.userVideos.isEmpty()
        val body = if (empty) """<div class="empty">Библиотека пуста.</div>""" else buildString {
            append(section("Видео", catalog.videos))
            append(section("Shorts", catalog.shorts, shorts = true))
            append(section("Свои видео", catalog.userVideos))
        }
        return page("LocalTube", header() + "<main>$body</main>")
    }

    fun searchPage(query: String, results: List<VideoItem>): String {
        val body = if (results.isEmpty()) {
            """<div class="empty">Ничего не найдено по запросу «${escapeHtml(query)}».</div>"""
        } else {
            section("Найдено: ${results.size}", results)
        }
        // Запрос возвращается в поле: иначе на телефоне его надо набирать заново.
        return page("Поиск — LocalTube", header(query) + "<main>$body</main>")
    }

    /**
     * Страница просмотра. Субтитры подключаются как <track>: файлы уже лежат
     * рядом с видео, и браузер показывает их сам.
     */
    fun watchPage(
        v: VideoItem,
        mediaUrl: String,
        subtitles: List<Pair<String, String>>,
        subtitleBase: String
    ): String {
        val tracks = subtitles.joinToString("") { (lang, name) ->
            """<track kind="subtitles" srclang="${escapeHtml(lang)}" label="${escapeHtml(lang)}"
                    src="$subtitleBase/${escapeHtml(name)}">"""
        }
        val body = """
<main>
  <video controls autoplay playsinline poster="/api/thumbnail/${escapeHtml(v.id)}">
    <source src="${escapeHtml(mediaUrl)}" type="${escapeHtml(mimeFor(mediaUrl))}">
    $tracks
  </video>
  <div class="meta">
    <h1>${escapeHtml(v.title)}</h1>
    <a class="a" href="/channel/${escapeHtml(v.author)}"
       aria-label="Канал ${escapeHtml(v.author)}">${escapeHtml(v.author)}</a>
    ${if (v.description.isBlank()) "" else "<div class=\"desc\">${escapeHtml(v.description)}</div>"}
  </div>
</main>"""
        return page(v.title, header() + body)
    }

    fun channelPage(
        author: String,
        videos: List<VideoItem>,
        @Suppress("UNUSED_PARAMETER") mediaUrl: (VideoItem) -> String
    ): String {
        val body = """
<main>
  <h2>${escapeHtml(author)}</h2>
  <div class="grid">${videos.joinToString("") { card(it) }}</div>
</main>"""
        return page(author, header() + body)
    }

    // ---------- JSON ----------

    private fun videoObject(v: VideoItem, mediaUrl: String): String = buildString {
        append('{')
        append("\"id\":\"").append(escapeJson(v.id)).append("\",")
        append("\"title\":\"").append(escapeJson(v.title)).append("\",")
        append("\"author\":\"").append(escapeJson(v.author)).append("\",")
        append("\"is_short\":").append(v.isShort).append(',')
        append("\"duration\":").append(v.durationSec).append(',')
        append("\"source\":\"").append(escapeJson(v.source)).append("\",")
        append("\"thumb\":\"/api/thumbnail/").append(escapeJson(v.id)).append("\",")
        append("\"video_url\":\"").append(escapeJson(mediaUrl)).append('"')
        append('}')
    }

    fun catalogJson(catalog: Catalog): String = buildString {
        append('{')
        append("\"videos\":[")
        append(catalog.videos.joinToString(",") { videoObject(it, "") })
        append("],\"shorts\":[")
        append(catalog.shorts.joinToString(",") { videoObject(it, "") })
        append("],\"user_videos\":[")
        append(catalog.userVideos.joinToString(",") { videoObject(it, "") })
        append("],\"authors\":[")
        append(catalog.authors.joinToString(",") { a ->
            "{\"name\":\"${escapeJson(a.name)}\",\"count\":${a.videoCount}}"
        })
        append("]}")
    }

    fun searchJson(results: List<VideoItem>): String =
        "{\"results\":[" + results.joinToString(",") { videoObject(it, "") } + "]}"

    fun videoJson(v: VideoItem, mediaUrl: String): String = videoObject(v, mediaUrl)

    private fun mimeFor(url: String): String = when (url.substringAfterLast('.', "").lowercase()) {
        "webm" -> "video/webm"
        "mkv" -> "video/x-matroska"
        else -> "video/mp4"
    }
}
