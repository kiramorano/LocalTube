package io.github.kiramorano.localtube.data

data class VideoItem(
    val id: String,
    val title: String,
    val author: String,
    val thumb: String?,
    val videoPath: String?,
    val sizeMb: Double,
    val isShort: Boolean,
    val source: String,
    val durationSec: Long = 0,
    val description: String = "",
    val addedAt: String = ""
)

data class Author(val name: String, val avatar: String?)

data class PlaylistEntry(val id: String, val title: String, val videoPath: String?, val thumb: String?)

data class Playlist(
    val id: String,
    val title: String,
    val uploader: String,
    val thumbnail: String?,
    val videoCount: Int,
    val entries: List<PlaylistEntry>
)

data class Catalog(
    val videos: List<VideoItem>,
    val shorts: List<VideoItem>,
    val authors: List<Author>,
    val playlists: List<Playlist>,
    val userVideos: List<VideoItem>
)

data class FormatOption(
    val formatId: String,
    val label: String,
    val isVideo: Boolean,
    val resolution: String,
    val ext: String,
    val sizeMb: Double,
    val fps: Int,
    val codec: String
)

enum class TaskStatus { WAITING, DOWNLOADING, COMPLETED, ERROR, CANCELED }

data class DownloadTask(
    val id: String,
    val title: String,
    val url: String,
    val formatId: String,
    val status: TaskStatus,
    val progress: Float,
    val addedAt: Long,
    val error: String?,
    val subLangs: String? = null
) {
    val statusText: String
        get() = when (status) {
            TaskStatus.WAITING -> "В очереди"
            TaskStatus.DOWNLOADING -> "Скачивание... ${progress.toInt()}%"
            TaskStatus.COMPLETED -> "Готово"
            TaskStatus.ERROR -> "Ошибка: ${error ?: ""}"
            TaskStatus.CANCELED -> "Отменено"
        }
}
