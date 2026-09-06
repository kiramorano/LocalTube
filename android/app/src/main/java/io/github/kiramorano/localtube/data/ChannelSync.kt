package io.github.kiramorano.localtube.data

import android.app.Application
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/** Видео канала, которого ещё нет в библиотеке. */
data class MissingVideo(
    val entry: RemoteEntry,
    val selected: Boolean = true
)

/** Состояние обхода одного канала. */
data class SyncState(
    val author: String,
    val running: Boolean = false,
    val message: String = "",
    val error: String? = null,
    val total: Int = 0,
    val missing: List<MissingVideo> = emptyList(),
    val skipped: List<String> = emptyList()
)

/**
 * Синхронизация канала: обход удалённого списка видео, поиск отсутствующих и
 * загрузка оформления канала.
 *
 * Повторяет /api/channel/<author>/sync и /remaining серверной версии. Занятые
 * каналы отмечаются под замком до старта корутины: иначе два нажатия подряд
 * запускали два обхода одного канала (та же гонка, что была на сервере).
 */
class ChannelSync(
    private val app: Application,
    private val library: Library,
    private val settings: Settings,
    private val downloads: DownloadManager
) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _states = MutableStateFlow<Map<String, SyncState>>(emptyMap())
    val states: StateFlow<Map<String, SyncState>> = _states.asStateFlow()

    private val busy = HashSet<String>()
    private val busyLock = Any()

    fun state(author: String): SyncState = _states.value[author] ?: SyncState(author)

    /**
     * Читает список видео канала и оставляет те, которых нет на диске.
     * Ничего не скачивает: выбор остаётся за пользователем, как в модальном
     * окне «Скачать остальные видео» на ПК.
     */
    fun scan(author: String, channelUrl: String? = null) {
        // Слот занимаем здесь, а не внутри корутины: между launch и первой
        // строкой тела успевает пройти второе нажатие.
        synchronized(busyLock) {
            if (busy.contains(author)) return
            busy.add(author)
        }
        put(author) {
            it.copy(running = true, error = null, message = "Получение списка видео...", missing = emptyList())
        }
        scope.launch {
            try {
                val url = channelUrl?.takeIf { it.isNotBlank() }
                    ?: library.channelUrlOf(author)
                if (url.isNullOrBlank()) {
                    put(author) {
                        it.copy(
                            running = false,
                            error = "Не удалось определить адрес канала: в info.json нет channel_url"
                        )
                    }
                    return@launch
                }
                val listing = Engine.listChannel(
                    channelUrl = url,
                    processId = "sync_${author.hashCode()}_${System.currentTimeMillis()}",
                    cookiesPath = library.cookiesPath(),
                    playerClient = settings.playerClient
                )
                val have = withContext(Dispatchers.IO) { library.downloadedIdsOf(author) }
                val missing = listing.entries
                    .filterNot { have.contains(it.id) }
                    .map { MissingVideo(it) }
                put(author) {
                    it.copy(
                        running = false,
                        total = listing.entries.size,
                        missing = missing,
                        skipped = listing.skipped,
                        message = if (missing.isEmpty()) {
                            "Новых видео нет: на канале ${listing.entries.size}, все скачаны"
                        } else {
                            "Найдено новых: ${missing.size} из ${listing.entries.size}"
                        }
                    )
                }
                // Оформление подтягиваем заодно: отдельная кнопка для этого не нужна.
                runCatching { fetchAssetsInternal(author, url) }
            } catch (e: Exception) {
                put(author) {
                    it.copy(running = false, error = (e.message ?: "ошибка").take(300))
                }
            } finally {
                synchronized(busyLock) { busy.remove(author) }
            }
        }
    }

    fun toggle(author: String, videoId: String) {
        put(author) { state ->
            state.copy(
                missing = state.missing.map {
                    if (it.entry.id == videoId) it.copy(selected = !it.selected) else it
                }
            )
        }
    }

    fun setAllSelected(author: String, selected: Boolean) {
        put(author) { state ->
            state.copy(missing = state.missing.map { it.copy(selected = selected) })
        }
    }

    /**
     * Ставит выбранные видео в общую очередь загрузок. Возвращает их число,
     * чтобы экран показал результат без повторного чтения состояния.
     */
    fun queueSelected(
        author: String,
        formatId: String,
        priority: TaskPriority,
        mergeFormat: String = Engine.DEFAULT_MERGE_FORMAT
    ): Int {
        val state = state(author)
        val chosen = state.missing.filter { it.selected }
        if (chosen.isEmpty()) return 0
        chosen.forEach { item ->
            downloads.add(
                url = item.entry.url,
                formatId = formatId,
                title = item.entry.title,
                priority = priority,
                mergeFormat = mergeFormat
            )
        }
        // Поставленные в очередь убираем из списка: повторное нажатие иначе
        // добавляло те же видео второй раз.
        put(author) { s ->
            val queued = chosen.map { it.entry.id }.toSet()
            s.copy(
                missing = s.missing.filterNot { queued.contains(it.entry.id) },
                message = "Добавлено в очередь: ${chosen.size}"
            )
        }
        return chosen.size
    }

    fun clear(author: String) {
        _states.update { it - author }
    }

    /** Скачивает аватар и баннер канала. Аналог download_avatars.py. */
    fun fetchAssets(author: String, channelUrl: String? = null) {
        scope.launch {
            val url = channelUrl?.takeIf { it.isNotBlank() } ?: library.channelUrlOf(author)
            if (url.isNullOrBlank()) return@launch
            runCatching { fetchAssetsInternal(author, url) }
        }
    }

    private suspend fun fetchAssetsInternal(author: String, channelUrl: String) {
        val assets = Engine.fetchChannelAssets(
            channelUrl = channelUrl,
            processId = "assets_${author.hashCode()}_${System.currentTimeMillis()}",
            cookiesPath = library.cookiesPath(),
            playerClient = settings.playerClient
        )
        withContext(Dispatchers.IO) {
            library.saveChannelMeta(author, assets)
            if (assets.avatarUrl.isNotBlank()) {
                download(assets.avatarUrl, library.avatarTarget(author, assets.avatarUrl))
            }
            if (assets.bannerUrl.isNotBlank()) {
                download(assets.bannerUrl, library.bannerTarget(author, assets.bannerUrl))
            }
            library.invalidateAvatars()
        }
    }

    /**
     * Простое скачивание файла. Пишем в .tmp и переименовываем: обрыв связи
     * иначе оставил бы обрезанную картинку, которую Coil кэширует как валидную.
     */
    private fun download(url: String, dest: File): Boolean {
        val tmp = File(dest.parentFile, dest.name + ".tmp")
        var conn: HttpURLConnection? = null
        return try {
            dest.parentFile?.mkdirs()
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = 15_000
                readTimeout = 30_000
                instanceFollowRedirects = true
            }
            if (conn.responseCode !in 200..299) return false
            conn.inputStream.use { input ->
                tmp.outputStream().use { output -> input.copyTo(output) }
            }
            if (tmp.length() <= 0) {
                tmp.delete()
                false
            } else {
                tmp.renameTo(dest) || runCatching {
                    tmp.copyTo(dest, overwrite = true); tmp.delete(); true
                }.getOrDefault(false)
            }
        } catch (e: Exception) {
            runCatching { tmp.delete() }
            false
        } finally {
            runCatching { conn?.disconnect() }
        }
    }

    private fun put(author: String, block: (SyncState) -> SyncState) {
        _states.update { map ->
            map + (author to block(map[author] ?: SyncState(author)))
        }
    }
}
