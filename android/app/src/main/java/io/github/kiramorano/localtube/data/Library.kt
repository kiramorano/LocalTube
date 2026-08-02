package io.github.kiramorano.localtube.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

class Library(context: Context) {
    val root = File(context.filesDir, "videos")
    val userRoot = File(context.filesDir, "user_videos")
    val playlistsRoot = File(context.filesDir, "playlists")
    val avatarsRoot = File(context.filesDir, "avatars")
    val tmpRoot = File(context.filesDir, "tmp")

    private val videoExts = setOf("mp4", "mkv", "webm", "avi", "mov")
    private val imageExts = setOf("jpg", "jpeg", "png", "webp")

    init {
        for (d in listOf(root, userRoot, playlistsRoot, avatarsRoot, tmpRoot)) d.mkdirs()
    }

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

    private fun videoFromFolder(authorDir: File, vfolder: File): VideoItem? {
        val video = findVideoFile(vfolder) ?: return null
        val meta = readJson(File(vfolder, "info.json")) ?: JSONObject()
        val id = meta.optString("id").ifEmpty { vfolder.name }
        return VideoItem(
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
            addedAt = meta.optString("upload_date", "")
        )
    }

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

    fun scan(): Catalog {
        val videos = mutableListOf<VideoItem>()
        val shorts = mutableListOf<VideoItem>()
        val authorsSet = linkedSetOf<String>()

        root.listFiles()?.forEach { authorDir ->
            if (!authorDir.isDirectory) return@forEach
            authorDir.listFiles()?.forEach { vfolder ->
                if (!vfolder.isDirectory) return@forEach
                val item = videoFromFolder(authorDir, vfolder) ?: return@forEach
                if (item.isShort) shorts += item else videos += item
                authorsSet += item.author
            }
        }

        val userVideos = userRoot.listFiles()
            ?.filter { it.isDirectory }
            ?.mapNotNull { userVideoFromFolder(it) }
            ?.sortedByDescending { it.addedAt } ?: emptyList()

        val authors = authorsSet.sorted().map { Author(it, avatarFor(it)) }

        return Catalog(
            videos = videos.shuffled(),
            shorts = shorts,
            authors = authors,
            playlists = scanPlaylists(),
            userVideos = userVideos
        )
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
        val result = mutableListOf<VideoItem>()
        root.listFiles()?.forEach { authorDir ->
            if (!authorDir.isDirectory) return@forEach
            authorDir.listFiles()?.forEach { vfolder ->
                if (!vfolder.isDirectory) return@forEach
                val item = videoFromFolder(authorDir, vfolder) ?: return@forEach
                if (item.title.lowercase().contains(q) || item.author.lowercase().contains(q)) {
                    result += item
                }
            }
        }
        userRoot.listFiles()?.forEach { folder ->
            if (!folder.isDirectory) return@forEach
            val item = userVideoFromFolder(folder) ?: return@forEach
            if (item.title.lowercase().contains(q) || item.author.lowercase().contains(q)) {
                result += item
            }
        }
        return result
    }

    fun findVideo(id: String): VideoItem? {
        root.listFiles()?.forEach { authorDir ->
            if (!authorDir.isDirectory) return@forEach
            authorDir.listFiles()?.forEach { vfolder ->
                if (vfolder.isDirectory) {
                    val item = videoFromFolder(authorDir, vfolder) ?: return@forEach
                    if (item.id == id) return item
                }
            }
        }
        val user = userRoot.listFiles()?.firstOrNull { it.name == id }?.let { userVideoFromFolder(it) }
        return user
    }

    fun videoFile(v: VideoItem): File? =
        if (v.videoPath != null && File(v.videoPath).isFile) File(v.videoPath) else null

    fun subtitleFiles(v: VideoItem): List<File> {
        val f = videoFile(v) ?: return emptyList()
        return f.parentFile?.listFiles()
            ?.filter { it.isFile && it.extension.lowercase() == "vtt" }
            ?.sortedBy { it.name } ?: emptyList()
    }

    fun recommended(id: String, limit: Int = 15): List<VideoItem> {
        val all = root.listFiles().orEmpty()
            .filter { it.isDirectory }
            .flatMap { a -> a.listFiles().orEmpty().filter { it.isDirectory }.mapNotNull { videoFromFolder(a, it) } }
            .filter { it.id != id && !it.isShort }
            .shuffled()
        return all.take(limit)
    }

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
        return id
    }

    fun editUserVideo(id: String, title: String, description: String, author: String): Boolean {
        val folder = File(userRoot, id)
        val meta = readJson(File(folder, "meta.json")) ?: return false
        meta.put("title", title.ifBlank { "Без названия" })
        meta.put("description", description)
        meta.put("author", author.ifBlank { "Гость" })
        writeJson(File(folder, "meta.json"), meta)
        return true
    }

    fun deleteUserVideo(id: String): Boolean {
        val folder = File(userRoot, id)
        if (!folder.isDirectory) return false
        folder.deleteRecursively()
        return true
    }

    private fun readJson(f: File): JSONObject? {
        return try {
            if (f.isFile) JSONObject(f.readText(Charsets.UTF_8)) else null
        } catch (_: Exception) {
            null
        }
    }

    private fun writeJson(f: File, o: JSONObject) {
        try {
            f.writeText(o.toString(2), Charsets.UTF_8)
        } catch (_: Exception) {
        }
    }
}
