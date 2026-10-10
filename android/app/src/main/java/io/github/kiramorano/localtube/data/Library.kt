package io.github.kiramorano.localtube.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

/**
 * Файловая библиотека. Раскладка повторяет серверную версию, поэтому каталог с
 * ПК можно перенести копированием.
 *
 * Разобранные папки кэшируются: полное пересканирование читало info.json
 * каждого видео при каждом вызове, а вызывается он на каждом открытии экрана.
 */
class Library(context: Context, storageRoot: File? = null) {
    private val ctx = context.applicationContext

    /**
     * Корень библиотеки. По умолчанию filesDir, но может указывать на карту
     * памяти: видео занимают гигабайты, а на многих устройствах внутренней
     * памяти под них не хватает.
     */
    val base: File = storageRoot ?: ctx.filesDir
    val root = File(base, "videos")
    val userRoot = File(base, "user_videos")
    val playlistsRoot = File(base, "playlists")
    val avatarsRoot = File(base, "avatars")
    val bannersRoot = File(avatarsRoot, "banners")
    val metaRoot = File(avatarsRoot, "meta")
    val tmpRoot = File(base, "tmp")

    // cookies и личные данные всегда во внутренней памяти: на съёмном носителе
    // они пропадут вместе с картой, а восстановить их нельзя.
    private val cookiesFile = File(ctx.filesDir, "cookies.txt")

    private val videoExts = setOf("mp4", "mkv", "webm", "avi", "mov")
    private val imageExts = setOf("jpg", "jpeg", "png", "webp")
    private val subtitleExts = setOf("vtt", "srt")

    /** Отпечаток папки -> разобранное видео. */
    private data class CacheEntry(val fingerprint: String, val item: VideoItem)

    private val scanCache = HashMap<String, CacheEntry>()
    private val cacheLock = Any()

    @Volatile
    private var cachedCatalog: Catalog? = null

    @Volatile
    private var catalogBuiltAt = 0L

    @Volatile
    private var avatarCache: Map<String, String>? = null

    @Volatile
    private var avatarCacheStamp = -1L

    init {
        for (d in listOf(root, userRoot, playlistsRoot, avatarsRoot, bannersRoot, metaRoot, tmpRoot)) {
            d.mkdirs()
        }
    }

    fun cookiesPath(): String? = cookiesFile.takeIf { it.isFile }?.absolutePath

    fun saveCookies(uri: android.net.Uri): Boolean {
        return try {
            val ins = ctx.contentResolver.openInputStream(uri) ?: return false
            ins.use { input ->
                cookiesFile.outputStream().use { output -> input.copyTo(output) }
            }
            true
        } catch (e: Exception) {
            false
        }
    }

    fun clearCookies() {
        cookiesFile.delete()
    }

    fun cookiesInfo(): Pair<Boolean, Long> =
        if (cookiesFile.isFile) true to cookiesFile.length() else false to 0L

    fun safeName(text: String): String {
        val cleaned = text.replace(Regex("[\\\\/:*?\"<>|]"), "_")
        return cleaned.trimEnd(' ', '.').trim().ifEmpty { "unknown" }
    }

    fun isShort(meta: JSONObject): Boolean = Companion.isShort(meta)

    fun findVideoFile(folder: File): File? {
        for (ext in videoExts) {
            val f = File(folder, "video.$ext")
            if (f.isFile) return f
        }
        return folder.listFiles()?.firstOrNull { it.isFile && it.extension.lowercase() in videoExts }
    }

    fun findThumb(folder: File): File? {
        val pref = File(folder, "thumbnail.jpg")
        if (pref.isFile) return pref
        return folder.listFiles()?.firstOrNull { it.isFile && it.extension.lowercase() in imageExts }
    }

    fun avatarFor(author: String): String? = avatarIndex()[safeName(author)]

    /**
     * Карта «имя канала -> файл аватара». Строится одним обходом папки: раньше
     * avatarFor() перечитывал каталог на каждый вызов, а он нужен для каждой
     * карточки в сетке.
     */
    private fun avatarIndex(): Map<String, String> {
        val stamp = avatarsRoot.lastModified()
        avatarCache?.let { if (avatarCacheStamp == stamp) return it }
        val map = HashMap<String, String>()
        // Только файлы верхнего уровня: banners/ и meta/ — подпапки этой же
        // директории, и их содержимое аватарами не является.
        avatarsRoot.listFiles()?.forEach { f ->
            if (f.isFile && f.extension.lowercase() in imageExts) {
                map.putIfAbsent(f.nameWithoutExtension, f.absolutePath)
            }
        }
        avatarCache = map
        avatarCacheStamp = stamp
        return map
    }

    /**
     * Дешёвый отпечаток папки: время правки самой папки плюс размер и время
     * правки видеофайла и info.json. Если он совпал, папку можно не открывать.
     */
    private fun fingerprint(folder: File, video: File?, meta: File): String = buildString {
        append(folder.lastModified() / 1000)
        append(':')
        append(video?.length() ?: 0).append('/').append((video?.lastModified() ?: 0) / 1000)
        append(':')
        append(meta.length()).append('/').append(meta.lastModified() / 1000)
    }

    private fun videoFromFolder(authorDir: File, vfolder: File): VideoItem? {
        val video = findVideoFile(vfolder) ?: return null
        val metaFile = File(vfolder, "info.json")
        val key = vfolder.absolutePath
        val print = fingerprint(vfolder, video, metaFile)

        synchronized(cacheLock) {
            scanCache[key]?.let { if (it.fingerprint == print) return it.item }
        }

        val meta = readJson(metaFile) ?: JSONObject()
        val item = itemFromMeta(
            meta = meta,
            folderName = vfolder.name,
            authorFallback = authorDir.name,
            videoPath = video.absolutePath,
            sizeMb = if (video.length() > 0) video.length() / 1024.0 / 1024.0 else 0.0,
            thumb = findThumb(vfolder)?.absolutePath,
            qualities = qualitiesIn(vfolder)
        )
        synchronized(cacheLock) { scanCache[key] = CacheEntry(print, item) }
        return item
    }

    /** Локально сконвертированные варианты: video_1080.mp4 и подобные. */
    private fun qualitiesIn(folder: File): List<String> =
        folder.listFiles()
            ?.filter { it.isFile && it.name.startsWith("video_") && it.extension.lowercase() in videoExts }
            ?.map { it.nameWithoutExtension.removePrefix("video_") }
            ?.sortedByDescending { it.filter(Char::isDigit).toIntOrNull() ?: 0 }
            ?: emptyList()

    private fun userVideoFromFolder(folder: File): VideoItem? {
        val meta = readJson(File(folder, "meta.json")) ?: return null
        val videoExt = meta.optString("video_ext", "mp4")
        val video = File(folder, "video.$videoExt")
        if (!video.isFile) return null
        val thumbExt = meta.optString("thumb_ext", "").ifBlank { null }
        return VideoItem(
            id = meta.optString("id"),
            title = meta.optString("title").ifEmpty { "Без названия" },
            author = meta.optString("author").ifEmpty { "Гость" },
            thumb = thumbExt?.let { File(folder, "thumb.$it").takeIf { f -> f.isFile }?.absolutePath },
            videoPath = video.absolutePath,
            sizeMb = if (video.length() > 0) video.length() / 1024.0 / 1024.0 else 0.0,
            isShort = false,
            source = "user",
            description = meta.optString("description", ""),
            addedAt = meta.optString("added_at", "")
        )
    }

    /**
     * Возвращает каталог, переиспользуя собранный не позднее maxAgeMs назад.
     * Экраны нередко запрашивают каталог по несколько раз подряд.
     */
    fun catalog(maxAgeMs: Long = FRESH_WINDOW_MS): Catalog {
        val cached = cachedCatalog
        if (cached != null && System.currentTimeMillis() - catalogBuiltAt <= maxAgeMs) return cached
        return scan()
    }

    fun scan(): Catalog {
        val videos = mutableListOf<VideoItem>()
        val shorts = mutableListOf<VideoItem>()
        val counts = HashMap<String, Int>()
        val seenPaths = HashSet<String>()

        root.listFiles()?.forEach { authorDir ->
            if (!authorDir.isDirectory) return@forEach
            authorDir.listFiles()?.forEach { vfolder ->
                if (!vfolder.isDirectory) return@forEach
                seenPaths += vfolder.absolutePath
                val parsed = videoFromFolder(authorDir, vfolder) ?: return@forEach
                // Аватар канала нужен карточке: в вебе он есть у каждого видео.
                val item = parsed.copy(authorAvatar = avatarFor(parsed.author))
                if (item.isShort) shorts += item else videos += item
                counts[item.author] = (counts[item.author] ?: 0) + 1
            }
        }

        // Чистим кэш от исчезнувших папок, иначе он растёт бесконечно.
        synchronized(cacheLock) {
            (scanCache.keys - seenPaths).forEach { scanCache.remove(it) }
        }

        val userVideos = userRoot.listFiles()
            ?.filter { it.isDirectory }
            ?.mapNotNull { userVideoFromFolder(it) }
            ?.sortedByDescending { it.addedAt } ?: emptyList()

        val authors = counts.keys.sorted().map { Author(it, avatarFor(it), counts[it] ?: 0) }

        val catalog = Catalog(
            // Порядок задаётся сортировкой в UI, а не случайной перестановкой.
            videos = videos.sortedByDescending { it.sortKey },
            shorts = shorts.sortedByDescending { it.sortKey },
            authors = authors,
            playlists = scanPlaylists(),
            userVideos = userVideos
        )
        cachedCatalog = catalog
        catalogBuiltAt = System.currentTimeMillis()
        return catalog
    }

    /** Сбрасывает кэш: вызывается после загрузки, удаления или правки видео. */
    fun invalidate() {
        synchronized(cacheLock) { scanCache.clear() }
        cachedCatalog = null
        catalogBuiltAt = 0
    }

    fun scanPlaylists(): List<Playlist> {
        val out = mutableListOf<Playlist>()
        playlistsRoot.listFiles()?.forEach { folder ->
            if (!folder.isDirectory) return@forEach
            val meta = readJson(File(folder, "playlist.json")) ?: return@forEach
            val id = meta.optString("id").ifEmpty { folder.name }
            val entriesArr = meta.optJSONArray("videos") ?: JSONArray()
            val entries = mutableListOf<PlaylistEntry>()
            for (i in 0 until entriesArr.length()) {
                val o = entriesArr.optJSONObject(i) ?: continue
                val vid = o.optString("id")
                if (vid.isBlank()) continue
                // Папка на диске названа через safeName, а в старых playlist.json
                // лежит сырое имя автора: без нормализации канал с символами
                // \ / : * ? " < > | не находился, и запись была непроигрываемой.
                val author = safeName(o.optString("author"))
                val authorDir = File(root, author)
                val entry = videoFromFolder(authorDir, File(authorDir, vid))
                entries += PlaylistEntry(
                    id = vid,
                    title = o.optString("title").ifEmpty { "Без названия" },
                    videoPath = entry?.videoPath,
                    thumb = entry?.thumb
                )
            }
            val thumbPath = findThumb(folder)?.absolutePath
            out += Playlist(
                id = id,
                title = meta.optString("title").ifEmpty { folder.name },
                uploader = meta.optString("uploader", "Unknown"),
                thumbnail = thumbPath,
                videoCount = meta.optInt("video_count", entries.size),
                entries = entries
            )
        }
        return out
    }

    fun search(query: String): List<VideoItem> {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return emptyList()
        val catalog = catalog()
        return (catalog.videos + catalog.shorts + catalog.userVideos).filter {
            it.title.lowercase().contains(q) || it.author.lowercase().contains(q)
        }
    }

    fun findVideo(id: String): VideoItem? {
        val catalog = catalog()
        return (catalog.videos + catalog.shorts + catalog.userVideos).firstOrNull { it.id == id }
    }

    fun videosOf(author: String): List<VideoItem> {
        val catalog = catalog()
        return (catalog.videos + catalog.shorts)
            .filter { it.author == author }
            .sortedByDescending { it.sortKey }
    }

    fun videoFile(v: VideoItem): File? =
        if (v.videoPath != null && File(v.videoPath).isFile) File(v.videoPath) else null

    fun subtitleFiles(v: VideoItem): List<File> {
        val f = videoFile(v) ?: return emptyList()
        return f.parentFile?.listFiles()
            ?.filter { it.isFile && it.extension.lowercase() in subtitleExts }
            ?.sortedBy { it.name } ?: emptyList()
    }

    /** Папка видео: нужна для конвертации, субтитров и mp3. */
    fun folderOf(v: VideoItem): File? = videoFile(v)?.parentFile

    /**
     * Язык дорожки из имени файла. yt-dlp пишет <id>.<lang>.vtt, а после
     * раскладки остаётся <lang>.vtt — оба варианта дают одно и то же имя.
     */
    fun subtitleLang(f: File): String {
        val name = f.nameWithoutExtension
        return name.substringAfterLast('.', name).ifBlank { name }
    }

    fun deleteSubtitle(v: VideoItem, file: File): Boolean {
        val folder = folderOf(v) ?: return false
        // Проверка родителя обязательна: имя приходит из UI, и без неё можно
        // было бы удалить файл за пределами папки видео.
        if (file.parentFile?.absolutePath != folder.absolutePath) return false
        if (!file.isFile) return false
        val ok = file.delete()
        if (ok) invalidate()
        return ok
    }

    /** Импорт своего файла субтитров рядом с видео. */
    fun importSubtitle(v: VideoItem, uri: android.net.Uri, lang: String): File? {
        val folder = folderOf(v) ?: return null
        val cleanLang = safeName(lang.trim().ifEmpty { "user" }).take(20)
        val dest = File(folder, "$cleanLang.vtt")
        return try {
            ctx.contentResolver.openInputStream(uri)?.use { input ->
                dest.outputStream().use { output -> input.copyTo(output) }
            } ?: return null
            if (dest.length() <= 0) {
                dest.delete()
                null
            } else {
                invalidate()
                dest
            }
        } catch (e: Exception) {
            runCatching { dest.delete() }
            null
        }
    }

    /** MP3, извлечённый ранее: кнопка должна предлагать «Открыть», а не «Извлечь». */
    fun audioFile(v: VideoItem): File? =
        folderOf(v)?.let { File(it, "audio.mp3") }?.takeIf { it.isFile && it.length() > 0 }

    /** Путь к локально сконвертированному варианту качества. */
    fun qualityFile(v: VideoItem, quality: String): File? =
        folderOf(v)?.let { File(it, "video_$quality.mp4") }?.takeIf { it.isFile }

    // ---------- оформление канала ----------

    fun bannerFor(author: String): String? {
        val name = safeName(author)
        return bannersRoot.listFiles()
            ?.firstOrNull { it.isFile && it.nameWithoutExtension == name && it.extension.lowercase() in imageExts }
            ?.absolutePath
    }

    fun channelMeta(author: String): ChannelAssets? {
        val json = JsonStore.read(File(metaRoot, safeName(author) + ".json")) ?: return null
        return ChannelAssets(
            title = json.optString("title", author),
            avatarUrl = json.optString("avatar_url", ""),
            bannerUrl = json.optString("banner_url", ""),
            description = json.optString("description", ""),
            subscribers = json.optLong("subscribers", 0),
            channelUrl = json.optString("channel_url", "")
        )
    }

    fun saveChannelMeta(author: String, assets: ChannelAssets) {
        val json = JSONObject().apply {
            put("title", assets.title.ifBlank { author })
            put("avatar_url", assets.avatarUrl)
            put("banner_url", assets.bannerUrl)
            put("description", assets.description)
            put("subscribers", assets.subscribers)
            put("channel_url", assets.channelUrl)
        }
        JsonStore.write(File(metaRoot, safeName(author) + ".json"), json)
    }

    /**
     * Удаляет meta-файл канала — аналог channel_assets.clear_channel_meta на ПК.
     * Используется при импорте: чтобы не смешать описание и подписчики из чужого
     * канала с теми же имя. Удаляем основной файл и резервную копию (.json.bak,
     * которую создаёт JsonStore.write).
     */
    fun clearChannelMeta(author: String) {
        val safe = safeName(author)
        for (name in listOf("$safe.json", "$safe.json.bak")) {
            val f = File(metaRoot, name)
            if (f.isFile) f.delete()
        }
    }

    /** Файл аватара канала для записи: расширение берём из адреса. */
    fun avatarTarget(author: String, url: String): File =
        File(avatarsRoot, safeName(author) + "." + imageExtOf(url))

    fun bannerTarget(author: String, url: String): File =
        File(bannersRoot, safeName(author) + "." + imageExtOf(url))

    private fun imageExtOf(url: String): String {
        val ext = url.substringAfterLast('.', "").substringBefore('?').lowercase()
        return if (ext in imageExts) ext else "jpg"
    }

    /** Сбрасывает кэш аватаров: после скачивания карточки должны их увидеть. */
    fun invalidateAvatars() {
        avatarCache = null
        avatarCacheStamp = -1
        invalidate()
    }

    /** Все id библиотеки: для чистки личных данных от удалённых видео. */
    fun allIds(): Set<String> {
        val c = catalog()
        return (c.videos + c.shorts + c.userVideos).map { it.id }.toSet()
    }

    /** Видео канала по адресу из info.json: нужно для синхронизации. */
    fun channelUrlOf(author: String): String? =
        videosOf(author).firstOrNull { it.channelUrl.isNotBlank() }?.channelUrl
            ?: channelMeta(author)?.channelUrl?.takeIf { it.isNotBlank() }

    /** Уже скачанные id канала: чтобы не предлагать их повторно. */
    fun downloadedIdsOf(author: String): Set<String> = videosOf(author).map { it.id }.toSet()

    /** Рекомендации: без текущего видео и без скрытых каналов. */
    fun recommended(id: String, limit: Int = 15, hidden: Set<String> = emptySet()): List<VideoItem> {
        val catalog = catalog()
        return catalog.videos
            .filter { it.id != id && !hidden.contains(it.author) }
            .shuffled()
            .take(limit)
    }

    /** Следующее видео для автозапуска: того же автора, иначе любое. */
    fun nextAfter(id: String, hidden: Set<String> = emptySet()): VideoItem? {
        val catalog = catalog()
        val current = catalog.videos.firstOrNull { it.id == id } ?: return null
        val visible = catalog.videos.filter { !hidden.contains(it.author) }
        val sameAuthor = visible.filter { it.author == current.author }
        val pool = if (sameAuthor.size > 1) sameAuthor else visible
        val index = pool.indexOfFirst { it.id == id }
        if (index < 0) return pool.firstOrNull { it.id != id }
        return pool.getOrNull(index + 1) ?: pool.firstOrNull { it.id != id }
    }

    fun deleteVideo(v: VideoItem): Boolean {
        if (v.source == "user") return deleteUserVideo(v.id)
        val file = videoFile(v) ?: return false
        val folder = file.parentFile ?: return false
        val ok = folder.deleteRecursively()
        // Автор без видео больше не нужен в списке каналов. Удаляем только
        // прямую подпапку videos/: иначе для чужой раскладки под нож попала бы
        // сама папка библиотеки.
        folder.parentFile?.let { parent ->
            if (parent.parentFile?.absolutePath == root.absolutePath &&
                parent.listFiles()?.isEmpty() == true
            ) parent.delete()
        }
        invalidate()
        return ok
    }

    // avatarsRoot обходится рекурсивно и покрывает banners/ и meta/, поэтому
    // отдельно их складывать нельзя: размер удвоился бы.
    fun storageUsedBytes(): Long = listOf(root, userRoot, playlistsRoot, avatarsRoot, tmpRoot)
        .sumOf { dir -> dir.walkBottomUp().filter { it.isFile }.sumOf { it.length() } }

    /**
     * Добавляет своё видео. Обложка необязательна: если её нет, вызывающий
     * может вытащить кадр через Ffmpeg.extractThumbnail и позвать
     * setUserThumbnail — как делает download_thumbnails.py на сервере.
     */
    fun addUserVideo(
        src: File,
        title: String,
        description: String,
        author: String,
        thumb: File? = null
    ): String {
        val id = UUID.randomUUID().toString().substring(0, 8)
        val folder = File(userRoot, id).apply { mkdirs() }
        val ext = src.extension.lowercase().ifEmpty { "mp4" }
        src.copyTo(File(folder, "video.$ext"), overwrite = true)
        val meta = JSONObject()
        meta.put("id", id)
        meta.put("title", title.ifBlank { "Без названия" })
        meta.put("description", description)
        meta.put("author", author.ifBlank { "Гость" })
        meta.put("video_ext", ext)
        if (thumb != null && thumb.isFile) {
            val thumbExt = thumb.extension.lowercase().takeIf { it in imageExts } ?: "jpg"
            thumb.copyTo(File(folder, "thumb.$thumbExt"), overwrite = true)
            meta.put("thumb_ext", thumbExt)
        }
        meta.put("added_at", SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault()).format(Date()))
        writeJson(File(folder, "meta.json"), meta)
        invalidate()
        return id
    }

    /** Папка своего видео: нужна, чтобы положить туда обложку. */
    fun userVideoFolder(id: String): File? = File(userRoot, id).takeIf { it.isDirectory }

    /** Прописывает обложку своему видео после её появления на диске. */
    fun setUserThumbnail(id: String, ext: String): Boolean {
        val folder = userVideoFolder(id) ?: return false
        val meta = readJson(File(folder, "meta.json")) ?: return false
        meta.put("thumb_ext", ext.lowercase().takeIf { it in imageExts } ?: "jpg")
        writeJson(File(folder, "meta.json"), meta)
        invalidate()
        return true
    }

    fun editUserVideo(id: String, title: String, description: String, author: String): Boolean {
        val folder = File(userRoot, id)
        val meta = readJson(File(folder, "meta.json")) ?: return false
        meta.put("title", title.ifBlank { "Без названия" })
        meta.put("description", description)
        meta.put("author", author.ifBlank { "Гость" })
        writeJson(File(folder, "meta.json"), meta)
        invalidate()
        return true
    }

    fun deleteUserVideo(id: String): Boolean {
        val folder = File(userRoot, id)
        if (!folder.isDirectory) return false
        folder.deleteRecursively()
        invalidate()
        return true
    }

    private fun readJson(f: File): JSONObject? = JsonStore.read(f)

    private fun writeJson(f: File, o: JSONObject) {
        JsonStore.write(f, o)
    }

    companion object {
        /** Окно свежести каталога: короткое, чтобы новые видео появлялись сразу. */
        const val FRESH_WINDOW_MS = 2_000L

        /**
         * Признак Shorts. Вынесено в companion, чтобы правило проверялось
         * тестами напрямую, без Context и копии логики в тесте.
         */
        fun isShort(meta: JSONObject): Boolean {
            // TikTok — лента коротких вертикальных роликов, там короткое всё.
            // Проверка стоит первой, потому что flat-обход профиля часто не
            // отдаёт width/height, и правило h > w до неё бы не добралось.
            if (sourceOf(meta) == "tiktok") return true
            val h = meta.optInt("height", 0)
            val w = meta.optInt("width", 0)
            if (h > 0 && w > 0 && h > w) return true
            val title = meta.optString("title", "").lowercase()
            if (title.contains("#shorts") || title.contains("#short")) return true
            if (meta.optString("webpage_url", "").contains("/shorts/")) return true
            // Короткое видео без известной ширины: раньше здесь стояло ещё и h > w,
            // из-за чего условие никогда не выполнялось (вертикальные ушли выше).
            val dur = meta.optLong("duration", 0)
            return dur in 1..60 && w == 0
        }

        /**
         * Платформа видео по его info.json.
         *
         * Читается из метаданных, а не из пути: папка называется по автору и id,
         * и по ней платформу не определить. Совпадает с сервером
         * (app.py source_from_metadata), иначе одно видео в каталоге телефона и
         * в веб-версии получило бы разный источник.
         */
        fun sourceOf(meta: JSONObject): String = UrlKind.sourceOf(
            meta.optString("extractor_key").ifBlank { meta.optString("ie_key") },
            meta.optString("webpage_url").ifBlank { meta.optString("original_url") }
        )

        /**
         * Собирает элемент каталога из info.json.
         *
         * Вынесено в companion вместе с isShort и sourceOf: иначе проверить,
         * что платформа и признак Shorts действительно попадают в каталог,
         * можно только через файловую систему и Context.
         */
        fun itemFromMeta(
            meta: JSONObject,
            folderName: String,
            authorFallback: String,
            videoPath: String,
            sizeMb: Double,
            thumb: String? = null,
            qualities: List<String> = emptyList()
        ): VideoItem = VideoItem(
            id = meta.optString("id").ifEmpty { folderName },
            title = meta.optString("title").ifEmpty { "Видео $folderName" },
            author = meta.optString("uploader").ifEmpty { authorFallback },
            thumb = thumb,
            videoPath = videoPath,
            sizeMb = sizeMb,
            isShort = isShort(meta),
            source = sourceOf(meta),
            durationSec = meta.optLong("duration", 0),
            description = meta.optString("description", ""),
            addedAt = meta.optString("upload_date", ""),
            uploadDate = meta.optString("upload_date", ""),
            channelUrl = meta.optString("channel_url", "").ifEmpty { meta.optString("uploader_url", "") },
            qualities = qualities
        )
    }
}
