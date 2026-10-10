package io.github.kiramorano.localtube.data

/**
 * Разбор ссылок на видео: какая это платформа и что именно за страница.
 *
 * Выделено отдельно, потому что от ответа зависят аргументы yt-dlp. YouTube и
 * TikTok обслуживает один и тот же движок, но набор опций у них разный:
 * `youtube:player_client` TikTok-экстрактор не понимает, а YouTube-селектор
 * формата (`bestvideo+bestaudio`) у TikTok даёт «Requested format is not
 * available» — там видео и звук всегда в одном потоке.
 *
 * Правила повторяют веб-версию (utils.py is_tiktok_url, app.py
 * is_supported_download_url и is_tiktok_profile_url): каталог общий, и
 * расхождение в разборе означало бы, что телефон и сервер по одной ссылке
 * ведут себя по-разному.
 */
internal object UrlKind {

    private val TIKTOK_HOSTS = setOf(
        "tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"
    )
    private val YOUTUBE_HOSTS = setOf(
        "youtube.com", "m.youtube.com", "music.youtube.com",
        "youtu.be", "youtube-nocookie.com"
    )

    /** Короткие ссылки-редиректы: сам адрес не говорит, что за ролик внутри. */
    private val SHORT_TIKTOK_HOSTS = setOf("vm.tiktok.com", "vt.tiktok.com")

    /**
     * Хост без `www.` и схемы, или пустая строка.
     *
     * Свой разбор вместо android.net.Uri: этот код читают юнит-тесты на JVM, где
     * фреймворк недоступен, а правила достаточно простые.
     */
    internal fun host(url: String?): String {
        val text = url.orEmpty().trim()
        val scheme = text.substringBefore("://", "")
        // Только http(s): ftp:// и просто текст ссылками не считаем.
        if (!scheme.equals("http", true) && !scheme.equals("https", true)) return ""
        val rest = text.substringAfter("://", "")
        if (rest.isEmpty()) return ""
        return rest.substringBefore('/')
            .substringBefore('?')
            .substringBefore('#')
            // Логин в адресе: хост стоит после @.
            .substringAfterLast('@')
            .substringBefore(':')
            .lowercase()
            .removePrefix("www.")
    }

    /** Путь ссылки, разбитый на непустые части. */
    private fun segments(url: String): List<String> {
        val rest = url.trim().substringAfter("://", "")
        val path = rest.substringAfter('/', "").substringBefore('?').substringBefore('#')
        return path.split('/').filter { it.isNotBlank() }
    }

    fun isTikTok(url: String?): Boolean = host(url) in TIKTOK_HOSTS

    fun isYouTube(url: String?): Boolean = host(url) in YOUTUBE_HOSTS

    /**
     * Ссылку можно отдавать движку.
     *
     * У YouTube достаточно домена: форм адресов слишком много, и лишняя строгость
     * отсекала бы живые ссылки. У TikTok домен проверяется вместе с путём —
     * иначе в очередь попадает главная страница сайта, и загрузка падает уже
     * в фоне, когда пользователь этого не видит.
     */
    fun isSupported(url: String?): Boolean {
        val host = host(url)
        if (host in YOUTUBE_HOSTS) return true
        if (host !in TIKTOK_HOSTS) return false
        val parts = segments(url.orEmpty())
        // Куда ведёт vm/vt-ссылка, знает только редирект: проверяем, что за
        // доменом вообще что-то есть.
        if (host in SHORT_TIKTOK_HOSTS) return parts.isNotEmpty()
        // Короткая ссылка «Поделиться»: tiktok.com/t/<code>. Раскрывает yt-dlp
        // через редирект — задача попадает в очередь как есть.
        if (parts.size == 2 && parts[0] == "t" && parts[1].length >= 3 &&
            parts[1].all { it.isLetterOrDigit() }
        ) return true
        // Обычный ролик: /@author/video/1234567890123456789.
        if (parts.size >= 3 && parts[0].startsWith("@") &&
            parts[1] == "video" && parts[2].all { it.isDigit() }
        ) return true
        // Профиль: /@author.
        if (parts.size == 1 && parts[0].startsWith("@") && parts[0].length > 1) return true
        // Мобильная форма: m.tiktok.com/v/1234567890123456789.html.
        return host == "m.tiktok.com" && parts.size >= 2 && parts[0] == "v" &&
            parts[1].removeSuffix(".html").let { it.isNotEmpty() && it.all { c -> c.isDigit() } }
    }

    /**
     * Ссылка на профиль TikTok, а не на конкретный ролик.
     *
     * Профиль нельзя скачать одной задачей: его разворачивают в список роликов.
     */
    fun isProfile(url: String?): Boolean {
        if (host(url) != "tiktok.com") return false
        val parts = segments(url.orEmpty())
        return parts.size == 1 && parts[0].startsWith("@") && parts[0].length > 1
    }

    /**
     * Платформа по метаданным yt-dlp, а не по имени папки.
     *
     * yt-dlp пишет extractor_key=TikTok и tiktok.com в webpage_url. Поле source
     * нужно интерфейсу и обмену по сети; неизвестные экстракторы остаются
     * youtube, как в веб-версии (app.py source_from_metadata).
     */
    fun sourceOf(extractorKey: String?, webpageUrl: String?): String {
        val extractor = extractorKey.orEmpty().lowercase()
        val page = webpageUrl.orEmpty().lowercase()
        return if (extractor.startsWith("tiktok") || page.contains("tiktok.com")) {
            "tiktok"
        } else {
            "youtube"
        }
    }

    /**
     * Адрес ролика для повторного обращения к платформе (субтитры, обновление).
     *
     * У своих файлов адреса нет. У TikTok его нельзя собрать из одного id:
     * в ссылку входит имя автора. Без сохранённого профиля возвращаем null,
     * чтобы не уйти на YouTube с чужим идентификатором.
     */
    fun watchUrl(source: String, id: String, channelUrl: String): String? {
        if (source == "user" || id.isBlank()) return null
        if (source == "tiktok") {
            val profile = channelUrl.trim().trimEnd('/')
            return if (isProfile(profile)) "$profile/video/$id" else null
        }
        return "https://www.youtube.com/watch?v=$id"
    }

    /**
     * Сообщение об отказе: то же, что отдаёт сервер на неподдерживаемую ссылку
     * (app.py, «Поддерживаются ссылки YouTube и TikTok»).
     */
    const val UNSUPPORTED_MESSAGE = "Ссылка не поддерживается"
}
