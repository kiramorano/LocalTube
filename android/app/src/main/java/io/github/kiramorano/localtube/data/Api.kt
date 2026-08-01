package io.github.kiramorano.localtube.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

private inline fun <T> JSONArray?.mapObjects(crossinline f: (JSONObject) -> T): List<T> {
    if (this == null) return emptyList()
    return (0 until length()).map { f(getJSONObject(it)) }
}

class LocalTubeApi(private val baseUrl: String) {

    private val jsonMedia = "application/json; charset=utf-8".toMediaType()
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(180, TimeUnit.SECONDS)
        .build()

    fun absolute(relative: String): String = baseUrl.trimEnd('/') + "/" + relative.trimStart('/')

    private fun url(path: String): String = absolute(path)

    private fun parseBody(resp: Response): JSONObject {
        val body = resp.body?.string().orEmpty()
        return if (body.isBlank()) JSONObject() else try {
            JSONObject(body)
        } catch (_: Exception) {
            JSONObject()
        }
    }

    private suspend fun get(path: String): JSONObject = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url(path)).get().build()
        client.newCall(req).execute().use { parseBody(it) }
    }

    private suspend fun post(path: String, json: String = "{}"): JSONObject = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url(path)).post(json.toRequestBody(jsonMedia)).build()
        client.newCall(req).execute().use { parseBody(it) }
    }

    suspend fun catalog(): Catalog = withContext(Dispatchers.IO) {
        val j = get("api/catalog")
        Catalog(
            videos = j.optJSONArray("videos").mapObjects { VideoItem.fromJson(it) },
            shorts = j.optJSONArray("shorts").mapObjects { VideoItem.fromJson(it) },
            authors = j.optJSONArray("authors").mapObjects {
                Author(it.optString("name"), it.optString("avatar").takeIf { a -> a.isNotEmpty() })
            },
            playlists = j.optJSONArray("playlists").mapObjects {
                Playlist(
                    it.optString("id"),
                    it.optString("title"),
                    it.optString("uploader"),
                    it.optString("thumbnail").takeIf { t -> t.isNotEmpty() },
                    it.optInt("video_count")
                )
            },
            userVideos = j.optJSONArray("user_videos").mapObjects { VideoItem.fromJson(it) }
        )
    }

    suspend fun video(id: String): VideoDetail = withContext(Dispatchers.IO) {
        val j = get("api/video/$id")
        VideoDetail(
            id = j.optString("id"),
            title = j.optString("title", "Без названия"),
            author = j.optString("author", "Unknown"),
            description = j.optString("description"),
            videoUrl = j.optString("video_url").takeIf { it.isNotEmpty() },
            mimeType = j.optString("mime_type", "video/mp4"),
            isShort = j.optBoolean("is_short"),
            thumb = j.optString("thumb").takeIf { it.isNotEmpty() },
            authorAvatar = j.optString("author_avatar").takeIf { it.isNotEmpty() },
            sizeMb = j.optDouble("file_size_mb", 0.0),
            recommended = j.optJSONArray("recommended").mapObjects { VideoItem.fromJson(it) }
        )
    }

    suspend fun search(query: String): List<VideoItem> = withContext(Dispatchers.IO) {
        val j = get("api/search?q=" + URLEncoder.encode(query, "UTF-8"))
        j.optJSONArray("results").mapObjects { VideoItem.fromJson(it) }
    }

    suspend fun queueList(): QueueSnapshot = withContext(Dispatchers.IO) {
        val j = get("api/queue/list")
        QueueSnapshot(
            tasks = j.optJSONArray("tasks").mapObjects {
                QueueItem(it.optString("id"), it.optString("title"), it.optString("status"), it.optInt("progress"))
            },
            paused = j.optBoolean("paused")
        )
    }

    suspend fun queueAdd(urls: List<String>, formatId: String?, title: String): Boolean = withContext(Dispatchers.IO) {
        val body = JSONObject()
        val arr = JSONArray()
        urls.forEach { arr.put(it) }
        body.put("urls", arr)
        body.put("format_id", formatId ?: "")
        body.put("title", title)
        post("api/queue/add", body.toString()).optString("status") == "ok"
    }

    suspend fun queueRemove(id: String) = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url("api/queue/remove/$id")).delete().build()
        client.newCall(req).execute().close()
    }

    suspend fun queuePause() = post("api/queue/pause")
    suspend fun queueResume() = post("api/queue/resume")
    suspend fun queueClear() = post("api/queue/clear")

    suspend fun directFormats(videoUrl: String): List<FormatItem> = withContext(Dispatchers.IO) {
        val body = JSONObject().put("url", videoUrl).toString()
        val j = post("api/direct_formats", body)
        j.optJSONArray("formats").mapObjects {
            FormatItem(
                type = it.optString("type"),
                formatId = it.optString("format_id").takeIf { f -> f.isNotEmpty() },
                resolution = it.optString("resolution"),
                codec = it.optString("codec"),
                sizeMb = it.optDouble("size_mb", 0.0)
            )
        }
    }

    suspend fun upload(
        title: String,
        description: String,
        username: String,
        videoFile: File,
        thumbFile: File?
    ): String = withContext(Dispatchers.IO) {
        val mb = MultipartBody.Builder().setType(MultipartBody.FORM)
        mb.addFormDataPart("username", username)
        mb.addFormDataPart("title", title)
        mb.addFormDataPart("description", description)
        mb.addFormDataPart("video_file", videoFile.name, videoFile.asRequestBody("video/*".toMediaType()))
        if (thumbFile != null) {
            mb.addFormDataPart("thumbnail_file", thumbFile.name, thumbFile.asRequestBody("image/*".toMediaType()))
        }
        val req = Request.Builder().url(url("api/user_video/upload")).post(mb.build()).build()
        client.newCall(req).execute().use { parseBody(it).optString("status", "error") }
    }
}
