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
    val qualities: List<String> = emptyList(),
    /** Аватар канала: в вебе он показан на карточке рядом с названием. */
    val authorAvatar: String? = null
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

/**
 * Вид задачи в очереди. Видео скачивается через yt-dlp с форматом и субтитрами;
 * оформление канала — аватаркой и шапкой через отдельный путь без процентов.
 */
enum class TaskKind {
    VIDEO {
        override val supportsPriority: Boolean = true
    },
    CHANNEL_ASSETS {
        override val supportsPriority: Boolean = false
    };

    /**
     * У оформления свой исполнитель и не участвует в общем порядке воркера:
     * приоритетный чип обещал бы настройку, которая ничего не меняет.
     */
    abstract val supportsPriority: Boolean
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
    val attempts: Int = 0,
    /** Контейнер для склейки видео и звука: mp4, mkv или webm. */
    val mergeFormat: String = Engine.DEFAULT_MERGE_FORMAT,
    /**
     * Вид задачи. По умолчанию VIDEO: очередь, записанная до появления
     * оформления, не содержит поля kind, и старые задачи не должны уйти
     * в неправильный исполнитель.
     */
    val kind: TaskKind = TaskKind.VIDEO,
    /** Автор канала для задач оформления: нужен для дедупликации. */
    val author: String = ""
) {
    val isFinished: Boolean
        get() = status == TaskStatus.COMPLETED ||
                status == TaskStatus.ERROR ||
                status == TaskStatus.CANCELED

    val supportsPriority: Boolean
        get() = kind.supportsPriority

    val statusText: String
        get() = when (kind) {
            TaskKind.CHANNEL_ASSETS -> when (status) {
                // Прогресс шаговый: запрос → аватарка → шапка. Проценты бы
                // выглядели как зависшая задача на запросе метаданных.
                TaskStatus.WAITING -> "В очереди"
                TaskStatus.DOWNLOADING -> when {
                    progress < 1 -> "Запрос данных канала"
                    progress < 50 -> "Аватарка"
                    else -> "Шапка канала"
                }
                TaskStatus.COMPLETED -> "Готово"
                TaskStatus.ERROR -> "Ошибка: ${error ?: ""}"
                TaskStatus.CANCELED -> "Отменено"
            }
            TaskKind.VIDEO -> when (status) {
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
}

private fun formatEta(seconds: Long): String {
    if (seconds < 60) return "${seconds}с"
    val minutes = seconds / 60
    if (minutes < 60) return "${minutes}м"
    return "${minutes / 60}ч ${minutes % 60}м"
}

/**
 * Личный плейлист (коллекция). Аналог collections в серверном userdata.json:
 * те же поля id/title/videos/created_at, чтобы файл переносился между ПК и
 * телефоном без потери данных.
 */
data class VideoCollection(
    val id: String,
    val title: String,
    val videos: List<String> = emptyList(),
    val createdAt: Double = 0.0
) {
    companion object {
        /** Встроенный плейлист «Смотреть позже»: тот же id, что на сервере. */
        const val WATCH_LATER_ID = "watch-later"
        const val WATCH_LATER_TITLE = "Смотреть позже"

        /** Лимиты серверной версии: userdata.py. */
        const val TITLE_LIMIT = 100
        const val VIDEOS_LIMIT = 1000
        const val COUNT_LIMIT = 200
    }
}

/**
 * Итог операции с коллекцией: либо id, либо текст ошибки для показа.
 * Логический true/false здесь не годится — причину отказа («такое название уже
 * есть», «достигнут лимит») пользователь должен видеть.
 */
sealed interface CollectionResult {
    data class Ok(val id: String) : CollectionResult
    data class Error(val message: String) : CollectionResult

    val errorOrNull: String? get() = (this as? Error)?.message
    val idOrNull: String? get() = (this as? Ok)?.id
}

/** Личные данные пользователя. Аналог userdata.json в серверной версии. */
data class UserData(
    val favorites: List<String> = emptyList(),
    val history: List<String> = emptyList(),
    val hiddenChannels: List<String> = emptyList(),
    /** id видео -> позиция воспроизведения в миллисекундах. */
    val positions: Map<String, Long> = emptyMap(),
    val collections: List<VideoCollection> = emptyList()
)

enum class AppTheme(val id: String, val label: String) {
    DARK("dark", "Тёмная"),
    LIGHT("light", "Светлая"),
    MIDNIGHT("midnight", "Midnight"),
    GLASS("glass", "Glass"),
    // id как в вебе (static/js/theme.js): каталог и настройки общие, и
    // расхождение означало бы разную тему на телефоне и в браузере.
    AERO("frutiger-aero", "Frutiger Aero");

    companion object {
        /**
         * Тема по сохранённому идентификатору.
         *
         * "aero" — прежний идентификатор этой сборки, до выравнивания с вебом.
         * Он остаётся читаемым, иначе у тех, кто уже выбрал Frutiger Aero,
         * после обновления молча включилась бы тёмная тема.
         */
        fun from(id: String?): AppTheme = when (id) {
            "aero" -> AERO
            else -> entries.firstOrNull { it.id == id } ?: DARK
        }
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
