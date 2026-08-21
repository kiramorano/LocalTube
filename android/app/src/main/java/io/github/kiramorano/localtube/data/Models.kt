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
    val addedAt: String = "",
    /** upload_date в формате yyyyMMdd; для своих видео пусто. */
    val uploadDate: String = "",
    val channelUrl: String = "",
    /** Доступные локально варианты качества (video_1080.mp4 и подобные). */
    val qualities: List<String> = emptyList()
) {
    /** Ключ сортировки по дате: сначала дата публикации, иначе дата добавления. */
    val sortKey: String get() = if (uploadDate.isNotBlank()) uploadDate else addedAt
}

data class Author(val name: String, val avatar: String?, val videoCount: Int = 0)

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
) {
    companion object {
        val EMPTY = Catalog(emptyList(), emptyList(), emptyList(), emptyList(), emptyList())
    }
}

data class FormatOption(
    val formatId: String,
    val label: String,
    val isVideo: Boolean,
    val resolution: String,
    val ext: String,
    val sizeMb: Double,
    val fps: Int,
    val codec: String,
    /** true, если поток без звука и его придётся склеивать с аудио. */
    val needsAudio: Boolean = false
)

enum class TaskStatus { WAITING, DOWNLOADING, COMPLETED, ERROR, CANCELED }

/** Приоритеты как в серверной очереди: high обслуживается первым. */
enum class TaskPriority(val order: Int, val label: String) {
    HIGH(0, "Высокий"),
    NORMAL(1, "Обычный"),
    LOW(2, "Низкий")
}

data class DownloadTask(
    val id: String,
    val title: String,
    val url: String,
    val formatId: String,
    val status: TaskStatus,
    val progress: Float,
    val addedAt: Long,
    val error: String?,
    val subLangs: String? = null,
    val priority: TaskPriority = TaskPriority.NORMAL,
    val etaSeconds: Long = 0,
    val speed: String = "",
    val attempts: Int = 0
) {
    val isFinished: Boolean
        get() = status == TaskStatus.COMPLETED ||
                status == TaskStatus.ERROR ||
                status == TaskStatus.CANCELED

    val statusText: String
        get() = when (status) {
            TaskStatus.WAITING -> "В очереди"
            TaskStatus.DOWNLOADING -> buildString {
                append("Скачивание ${progress.toInt()}%")
                if (speed.isNotBlank()) append(" · $speed")
                if (etaSeconds > 0) append(" · осталось ${formatEta(etaSeconds)}")
            }
            TaskStatus.COMPLETED -> "Готово"
            TaskStatus.ERROR -> "Ошибка: ${error ?: ""}"
            TaskStatus.CANCELED -> "Отменено"
        }
}

private fun formatEta(seconds: Long): String {
    if (seconds < 60) return "${seconds}с"
    val minutes = seconds / 60
    if (minutes < 60) return "${minutes}м"
    return "${minutes / 60}ч ${minutes % 60}м"
}

/** Личные данные пользователя. Аналог userdata.json в серверной версии. */
data class UserData(
    val favorites: List<String> = emptyList(),
    val history: List<String> = emptyList(),
    val hiddenChannels: List<String> = emptyList(),
    /** id видео -> позиция воспроизведения в миллисекундах. */
    val positions: Map<String, Long> = emptyMap()
)

enum class AppTheme(val id: String, val label: String) {
    DARK("dark", "Тёмная"),
    LIGHT("light", "Светлая"),
    AERO("aero", "Frutiger Aero");

    companion object {
        fun from(id: String?): AppTheme = entries.firstOrNull { it.id == id } ?: DARK
    }
}

enum class CatalogSort(val id: String, val label: String) {
    NEWEST("newest", "Сначала новые"),
    OLDEST("oldest", "Сначала старые"),
    TITLE("title", "По названию"),
    SIZE("size", "По размеру"),
    RANDOM("random", "Случайно");

    companion object {
        fun from(id: String?): CatalogSort = entries.firstOrNull { it.id == id } ?: NEWEST
    }
}
