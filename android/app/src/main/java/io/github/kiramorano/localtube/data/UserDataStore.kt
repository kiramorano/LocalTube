package io.github.kiramorano.localtube.data

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/**
 * Избранное, история просмотров, скрытые каналы и позиции воспроизведения.
 *
 * Файл userdata.json повторяет формат серверной версии, поэтому библиотеку с
 * ПК можно переносить вместе с личными данными.
 */
class UserDataStore(context: Context) {

    private val file = File(context.filesDir, "userdata.json")
    private val lock = Any()

    /**
     * Запись идёт в одном фоновом потоке. Раньше persist() выполнялся прямо в
     * обработчике нажатия: markWatched на каждом открытии видео и savePosition
     * при выходе из плеера переписывали весь JSON на главном потоке.
     */
    private val ioDispatcher = Executors.newSingleThreadExecutor { r ->
        Thread(r, "userdata-io").apply { isDaemon = true }
    }.asCoroutineDispatcher()
    private val scope = CoroutineScope(SupervisorJob() + ioDispatcher)

    /** Конфляция: подряд идущие изменения складываются в одну запись файла. */
    private val saveRequests = MutableSharedFlow<Unit>(
        replay = 1,
        extraBufferCapacity = 0,
        onBufferOverflow = BufferOverflow.DROP_OLDEST
    )

    private val _data = MutableStateFlow(load())
    val data: StateFlow<UserData> = _data.asStateFlow()

    val current: UserData get() = _data.value

    init {
        scope.launch {
            saveRequests.collect {
                runCatching { persist(_data.value) }
            }
        }
    }

    private fun load(): UserData {
        val json = JsonStore.read(file) ?: return UserData()
        return UserData(
            favorites = json.stringList("favorites"),
            history = json.stringList("history"),
            hiddenChannels = json.stringList("hidden_channels"),
            positions = json.longMap("positions"),
            collections = json.collectionList()
        )
    }

    private fun persist(data: UserData) {
        val json = JSONObject().apply {
            put("favorites", JSONArray(data.favorites))
            put("history", JSONArray(data.history))
            put("hidden_channels", JSONArray(data.hiddenChannels))
            put("positions", JSONObject().also { obj ->
                data.positions.forEach { (id, pos) -> obj.put(id, pos) }
            })
            // Коллекции пишутся в том же формате, что на сервере. Ключ нельзя
            // просто опустить: тогда перенос userdata.json с ПК на телефон и
            // обратно молча терял все личные плейлисты.
            put("collections", JSONArray().also { arr ->
                data.collections.forEach { c ->
                    arr.put(JSONObject().apply {
                        put("id", c.id)
                        put("title", c.title)
                        put("videos", JSONArray(c.videos))
                        put("created_at", c.createdAt)
                    })
                }
            })
            put("updated_at", System.currentTimeMillis() / 1000.0)
        }
        JsonStore.write(file, json)
    }

    private fun mutate(block: (UserData) -> UserData) {
        synchronized(lock) {
            _data.value = block(_data.value)
        }
        saveRequests.tryEmit(Unit)
    }

    fun isFavorite(id: String) = _data.value.favorites.contains(id)

    /**
     * Устанавливает избранность. Явное значение, а не переключение: иначе
     * запрос, отправленный до загрузки данных, сделает обратное задуманному.
     */
    fun setFavorite(id: String, favorite: Boolean) = mutate { data ->
        val list = data.favorites.toMutableList()
        if (favorite && !list.contains(id)) list.add(0, id)
        if (!favorite) list.remove(id)
        data.copy(favorites = list)
    }

    fun toggleFavorite(id: String): Boolean {
        var next = false
        synchronized(lock) {
            val data = _data.value
            next = !data.favorites.contains(id)
            val list = data.favorites.toMutableList()
            if (next) list.add(0, id) else list.remove(id)
            _data.value = data.copy(favorites = list)
        }
        saveRequests.tryEmit(Unit)
        return next
    }

    fun isChannelHidden(author: String) = _data.value.hiddenChannels.contains(author)

    fun setChannelHidden(author: String, hidden: Boolean) = mutate { data ->
        val list = data.hiddenChannels.toMutableList()
        if (hidden && !list.contains(author)) list.add(author)
        if (!hidden) list.remove(author)
        data.copy(hiddenChannels = list)
    }

    /** Переключение под тем же замком, что и чтение: иначе два быстрых нажатия дают один результат. */
    fun toggleChannelHidden(author: String): Boolean {
        var next = false
        synchronized(lock) {
            val data = _data.value
            next = !data.hiddenChannels.contains(author)
            val list = data.hiddenChannels.toMutableList()
            if (next) list.add(author) else list.remove(author)
            _data.value = data.copy(hiddenChannels = list)
        }
        saveRequests.tryEmit(Unit)
        return next
    }

    /** Помечает видео просмотренным, поднимая его в начало истории. */
    fun markWatched(id: String) = mutate { data ->
        val list = data.history.toMutableList()
        list.remove(id)
        list.add(0, id)
        // История не должна расти бесконечно.
        data.copy(history = list.take(HISTORY_LIMIT))
    }

    fun savePosition(id: String, positionMs: Long) = mutate { data ->
        data.copy(positions = trimPositions(data.positions, id, positionMs))
    }

    fun position(id: String): Long = _data.value.positions[id] ?: 0L

    fun clearFavorites() = mutate { it.copy(favorites = emptyList()) }

    fun clearHistory() = mutate { it.copy(history = emptyList()) }

    fun clearHiddenChannels() = mutate { it.copy(hiddenChannels = emptyList()) }

    /**
     * Убирает из личных данных записи об удалённых видео.
     *
     * Коллекции тоже чистятся: иначе в личном плейлисте оставались записи,
     * которые нельзя открыть, а счётчик видео врал.
     */
    fun pruneMissing(existingIds: Set<String>) = mutate { data ->
        data.copy(
            favorites = data.favorites.filter { existingIds.contains(it) },
            history = data.history.filter { existingIds.contains(it) },
            positions = data.positions.filterKeys { existingIds.contains(it) },
            collections = data.collections.map { c ->
                c.copy(videos = c.videos.filter { existingIds.contains(it) })
            }
        )
    }

    // ---------- коллекции (личные плейлисты) ----------

    fun collections(): List<VideoCollection> = _data.value.collections

    fun collection(id: String): VideoCollection? = _data.value.collections.firstOrNull { it.id == id }

    /**
     * Создаёт коллекцию. Возвращает id либо текст ошибки: причину отказа надо
     * показать пользователю, а не молча ничего не сделать.
     */
    fun createCollection(title: String): CollectionResult {
        val clean = title.trim()
        checkTitle(clean, skipId = null)?.let { return CollectionResult.Error(it) }
        var newId = ""
        synchronized(lock) {
            val data = _data.value
            if (data.collections.size >= VideoCollection.COUNT_LIMIT) {
                return CollectionResult.Error(
                    "Больше ${VideoCollection.COUNT_LIMIT} плейлистов не поддерживается"
                )
            }
            val id = java.util.UUID.randomUUID().toString().replace("-", "").substring(0, 12)
            newId = id
            _data.value = data.copy(
                collections = data.collections + VideoCollection(
                    id = id,
                    title = clean,
                    createdAt = System.currentTimeMillis() / 1000.0
                )
            )
        }
        saveRequests.tryEmit(Unit)
        return CollectionResult.Ok(newId)
    }

    fun renameCollection(id: String, title: String): CollectionResult {
        if (id == VideoCollection.WATCH_LATER_ID) {
            return CollectionResult.Error("«${VideoCollection.WATCH_LATER_TITLE}» нельзя переименовать")
        }
        val clean = title.trim()
        checkTitle(clean, skipId = id)?.let { return CollectionResult.Error(it) }
        synchronized(lock) {
            val data = _data.value
            if (data.collections.none { it.id == id }) {
                return CollectionResult.Error("Плейлист не найден")
            }
            _data.value = data.copy(
                collections = data.collections.map {
                    if (it.id == id) it.copy(title = clean) else it
                }
            )
        }
        saveRequests.tryEmit(Unit)
        return CollectionResult.Ok(id)
    }

    fun deleteCollection(id: String): CollectionResult {
        // «Смотреть позже» встроенный: на сервере он тоже защищён от удаления,
        // иначе кнопка на странице видео вела бы в никуда.
        if (id == VideoCollection.WATCH_LATER_ID) {
            return CollectionResult.Error("«${VideoCollection.WATCH_LATER_TITLE}» нельзя удалить")
        }
        synchronized(lock) {
            val data = _data.value
            if (data.collections.none { it.id == id }) {
                return CollectionResult.Error("Плейлист не найден")
            }
            _data.value = data.copy(collections = data.collections.filterNot { it.id == id })
        }
        saveRequests.tryEmit(Unit)
        return CollectionResult.Ok(id)
    }

    /**
     * Проверяет название так же, как _check_title на сервере: непустое, в
     * пределах лимита и не совпадающее с существующим без учёта регистра.
     * Возвращает текст ошибки либо null.
     */
    internal fun checkTitle(title: String, skipId: String?): String? {
        if (title.isEmpty()) return "Название не может быть пустым"
        if (title.length > VideoCollection.TITLE_LIMIT) {
            return "Название длиннее ${VideoCollection.TITLE_LIMIT} символов"
        }
        val folded = title.lowercase()
        if (folded == VideoCollection.WATCH_LATER_TITLE.lowercase() &&
            skipId != VideoCollection.WATCH_LATER_ID
        ) {
            return "Название «${VideoCollection.WATCH_LATER_TITLE}» занято встроенным списком"
        }
        val clash = _data.value.collections.firstOrNull {
            it.id != skipId && it.title.lowercase() == folded
        }
        return if (clash != null) "Плейлист «${clash.title}» уже есть" else null
    }

    /**
     * Гарантирует существование коллекции «Смотреть позже».
     *
     * Она материализуется при первом использовании, как _resolve_collection_id
     * на сервере: держать пустой встроенный плейлист в файле незачем.
     */
    private fun ensureWatchLaterLocked(data: UserData): UserData =
        if (data.collections.any { it.id == VideoCollection.WATCH_LATER_ID }) data
        else data.copy(
            collections = listOf(
                VideoCollection(
                    id = VideoCollection.WATCH_LATER_ID,
                    title = VideoCollection.WATCH_LATER_TITLE,
                    createdAt = System.currentTimeMillis() / 1000.0
                )
            ) + data.collections
        )

    /**
     * Добавляет видео в коллекцию. Возвращает true, если оно там оказалось
     * (в том числе если уже было): вызывающему важен итог, а не факт вставки.
     */
    fun addToCollection(collectionId: String, videoId: String): Boolean {
        if (videoId.isBlank()) return false
        var ok = false
        synchronized(lock) {
            var data = _data.value
            if (collectionId == VideoCollection.WATCH_LATER_ID) data = ensureWatchLaterLocked(data)
            val target = data.collections.firstOrNull { it.id == collectionId } ?: return false
            if (target.videos.contains(videoId)) {
                _data.value = data
                ok = true
            } else if (target.videos.size >= VideoCollection.VIDEOS_LIMIT) {
                _data.value = data
                return false
            } else {
                ok = true
                _data.value = data.copy(
                    collections = data.collections.map {
                        if (it.id == collectionId) it.copy(videos = it.videos + videoId) else it
                    }
                )
            }
        }
        saveRequests.tryEmit(Unit)
        return ok
    }

    fun removeFromCollection(collectionId: String, videoId: String): Boolean {
        var ok = false
        synchronized(lock) {
            val data = _data.value
            val target = data.collections.firstOrNull { it.id == collectionId } ?: return false
            if (!target.videos.contains(videoId)) return false
            ok = true
            _data.value = data.copy(
                collections = data.collections.map {
                    if (it.id == collectionId) it.copy(videos = it.videos - videoId) else it
                }
            )
        }
        saveRequests.tryEmit(Unit)
        return ok
    }

    /** Переключает «Смотреть позже» и возвращает новое состояние. */
    fun toggleWatchLater(videoId: String): Boolean {
        val inList = collection(VideoCollection.WATCH_LATER_ID)?.videos?.contains(videoId) == true
        if (inList) {
            removeFromCollection(VideoCollection.WATCH_LATER_ID, videoId)
            return false
        }
        return addToCollection(VideoCollection.WATCH_LATER_ID, videoId)
    }

    fun isInWatchLater(videoId: String): Boolean =
        collection(VideoCollection.WATCH_LATER_ID)?.videos?.contains(videoId) == true

    fun clearCollections() = mutate { it.copy(collections = emptyList()) }

    companion object {
        const val HISTORY_LIMIT = 500
        const val POSITION_LIMIT = 500

        /**
         * Обновляет позицию и, при переполнении, выбрасывает самые старые
         * записи. Раньше сортировка шла по id видео, поэтому лимит мог удалить
         * только что записанную позицию, а «продолжить с места» переставало
         * работать для половины библиотеки.
         */
        internal fun trimPositions(
            positions: Map<String, Long>,
            id: String,
            positionMs: Long
        ): Map<String, Long> {
            // LinkedHashMap хранит порядок вставки: последняя запись — свежая.
            val next = LinkedHashMap<String, Long>(positions.size + 1)
            next.putAll(positions)
            next.remove(id)
            // Совсем начало не запоминаем: возобновлять нечего.
            if (positionMs >= 5_000) next[id] = positionMs
            if (next.size <= POSITION_LIMIT) return next
            val drop = next.size - POSITION_LIMIT
            val out = LinkedHashMap<String, Long>(POSITION_LIMIT)
            next.entries.forEachIndexed { index, e ->
                if (index >= drop) out[e.key] = e.value
            }
            return out
        }
    }
}

private fun JSONObject.stringList(key: String): List<String> {
    val arr = optJSONArray(key) ?: return emptyList()
    val out = LinkedHashSet<String>()
    for (i in 0 until arr.length()) {
        val value = arr.optString(i).trim()
        if (value.isNotEmpty()) out.add(value)
    }
    return out.toList()
}

/**
 * Читает коллекции. Записи без id пропускаются: на них нельзя сослаться, а
 * LazyColumn с двумя пустыми ключами падает.
 */
private fun JSONObject.collectionList(): List<VideoCollection> {
    val arr = optJSONArray("collections") ?: return emptyList()
    val out = mutableListOf<VideoCollection>()
    val seen = HashSet<String>()
    for (i in 0 until arr.length()) {
        val o = arr.optJSONObject(i) ?: continue
        val id = o.optString("id").trim()
        if (id.isEmpty() || !seen.add(id)) continue
        val videosArr = o.optJSONArray("videos")
        val videos = LinkedHashSet<String>()
        if (videosArr != null) {
            for (j in 0 until videosArr.length()) {
                val v = videosArr.optString(j).trim()
                if (v.isNotEmpty()) videos.add(v)
            }
        }
        out += VideoCollection(
            id = id,
            title = o.optString("title").ifBlank {
                if (id == VideoCollection.WATCH_LATER_ID) VideoCollection.WATCH_LATER_TITLE else "Без названия"
            },
            videos = videos.toList(),
            createdAt = o.optDouble("created_at", 0.0)
        )
    }
    return out
}

/** Порядок ключей сохраняем: он задаёт возраст записи для лимита позиций. */
private fun JSONObject.longMap(key: String): Map<String, Long> {
    val obj = optJSONObject(key) ?: return emptyMap()
    val out = LinkedHashMap<String, Long>()
    obj.keys().forEach { k -> out[k] = obj.optLong(k, 0L) }
    return out
}
