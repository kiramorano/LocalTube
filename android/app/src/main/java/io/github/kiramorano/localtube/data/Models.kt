package io.github.kiramorano.localtube.data

import org.json.JSONObject

data class VideoItem(
    val id: String,
    val title: String,
    val author: String,
    val thumb: String?,
    val videoUrl: String?,
    val sizeMb: Double,
    val isShort: Boolean,
    val source: String,
    val authorAvatar: String?
) {
    companion object {
        fun fromJson(o: JSONObject) = VideoItem(
            id = o.optString("id"),
            title = o.optString("title", "Без названия"),
            author = o.optString("author", "Unknown"),
            thumb = o.optString("thumb").takeIf { it.isNotEmpty() },
            videoUrl = o.optString("video_url").takeIf { it.isNotEmpty() },
            sizeMb = o.optDouble("size_mb", 0.0),
            isShort = o.optBoolean("is_short"),
            source = o.optString("source", "youtube"),
            authorAvatar = o.optString("author_avatar").takeIf { it.isNotEmpty() }
        )
    }
}

data class Author(val name: String, val avatar: String?)

data class Playlist(
    val id: String,
    val title: String,
    val uploader: String,
    val thumbnail: String?,
    val videoCount: Int
)

data class Catalog(
    val videos: List<VideoItem>,
    val shorts: List<VideoItem>,
    val authors: List<Author>,
    val playlists: List<Playlist>,
    val userVideos: List<VideoItem>
)

data class VideoDetail(
    val id: String,
    val title: String,
    val author: String,
    val description: String,
    val videoUrl: String?,
    val mimeType: String,
    val isShort: Boolean,
    val thumb: String?,
    val authorAvatar: String?,
    val sizeMb: Double,
    val recommended: List<VideoItem>
)

data class QueueItem(
    val id: String,
    val title: String,
    val status: String,
    val progress: Int
)

data class QueueSnapshot(
    val tasks: List<QueueItem>,
    val paused: Boolean
)

data class FormatItem(
    val type: String,
    val formatId: String?,
    val resolution: String,
    val codec: String,
    val sizeMb: Double
)
