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
class Library(context: Context) {
    private val ctx = context.applicationContext
    val root = File(ctx.filesDir, "videos")
    val userRoot = File(ctx.filesDir, "user_videos")
    val playlistsRoot = File(ctx.filesDir, "playlists")
    val avatarsRoot = File(ctx.filesDir, "avatars")
    val tmpRoot = File(ctx.filesDir, "tmp")
    private val cookiesFile = File(ctx.filesDir, "cookies.txt")

    private val videoExts = setOf("mp4", "mkv", "webm", "avi", "mov")
    private val imageExts = setOf("jpg", "jpeg", "png", "webp")

    /** Отпечаток папки -> разобранное видео. */
    private data class CacheEntry(val fingerprint: String, val item: VideoItem)

    private val scanCache = HashMap<String, CacheEntry>()
    private val cacheLock = Any()

    @Volatile
    private var cachedCatalog: Catalog? = null

    @Volatile
    private var catalogBuiltAt = 0L

    init {
        for (d in listOf(root, userRoot, playlistsRoot, avatarsRoot, tmpRoot)) d.mkdirs()
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

    fun isShort(meta: JSONObject): Boolean {
        val h = meta.optInt("height", 0)
        val w = meta.optInt("width", 0)
        if (h > 0 && w > 0 && h > w) return true
        val title = meta.optString("title", "").lowercase()
        if (title.contains("#shorts") || title.contains("#short")) return true
        if (meta.optString("webpage_url", "").contains("/shorts/")) return true
        val dur = meta.optLong("duration", 0)
        return dur > 0 && dur <= 60 && h > w
    }

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

    fun avatarFor(author: String): String? {
        val base = safeName(author)
        return avatarsRoot.listFiles()?.firstOrNull {
            it.isFile && it.extension.lowercase() in imageExts && it.nameWithoutExtension == base
        }?.absolutePath
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
        val id = meta.optString("id").ifEmpty { vfolder.name }
        val item = VideoItem(
            id = id,
            title = meta.optString("title").ifEmpty { "Видео ${vfolder.name}" },
            author = meta.optString("uploader").ifEmpty { authorDir.name },
            thumb = findThumb(vfolder)?.absolutePath,
            videoPath = video.absolutePath,
            sizeMb = if (video.length() > 0) video.length() / 1024.0 / 1024.0 else 0.0,
            isShort = isShort(meta),
            source = "youtube",
            durationSec = meta.optLong("duration", 0),
            description = meta.optString("description", ""),
            addedAt = meta.optString("upload_date", ""),
            uploadDate = meta.optString("upload_date", ""),
            channelUrl = meta.optString("channel_url", "").ifEmpty { meta.optString("uploader_url", "") },
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
                val item = videoFromFolder(authorDir, vfolder) ?: return@forEach
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
                val author = o.optString("author")
                val vfolder = File(File(root, author), vid)
                val entry = videoFromFolder(File(root, author), vfolder)
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
            ?.filter { it.isFile && it.extension.lowercase() == "vtt" }
            ?.sortedBy { it.name } ?: emptyList()
    }

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
        val file = videoFile(v) ?: return false
        val folder = file.parentFile ?: return false
        val ok = folder.deleteRecursively()
        // Автор без видео больше не нужен в списке каналов.
        folder.parentFile?.let { if (it.listFiles()?.isEmpty() == true) it.delete() }
        invalidate()
        return ok
    }

    fun storageUsedBytes(): Long = listOf(root, userRoot, playlistsRoot, avatarsRoot, tmpRoot)
        .sumOf { dir -> dir.walkBottomUp().filter { it.isFile }.sumOf { it.length() } }

    fun addUserVideo(src: File, title: String, description: String, author: String): String {
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
        meta.put("added_at", SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault()).format(Date()))
        writeJson(File(folder, "meta.json"), meta)
        invalidate()
        return id
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
    }
}
