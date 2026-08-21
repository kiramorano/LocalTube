package io.github.kiramorano.localtube.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Избранное, история просмотров, скрытые каналы и позиции воспроизведения.
 *
 * Файл userdata.json повторяет формат серверной версии, поэтому библиотеку с
 * ПК можно переносить вместе с личными данными.
 */
class UserDataStore(context: Context) {

    private val file = File(context.filesDir, "userdata.json")
    private val lock = Any()

    private val _data = MutableStateFlow(load())
    val data: StateFlow<UserData> = _data.asStateFlow()

    val current: UserData get() = _data.value

    private fun load(): UserData {
        val json = JsonStore.read(file) ?: return UserData()
        return UserData(
            favorites = json.stringList("favorites"),
            history = json.stringList("history"),
            hiddenChannels = json.stringList("hidden_channels"),
            positions = json.longMap("positions")
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
            put("updated_at", System.currentTimeMillis() / 1000.0)
        }
        JsonStore.write(file, json)
    }

    private fun mutate(block: (UserData) -> UserData) {
        synchronized(lock) {
            val updated = block(_data.value)
            _data.value = updated
            persist(updated)
        }
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
        val next = !isFavorite(id)
        setFavorite(id, next)
        return next
    }

    fun isChannelHidden(author: String) = _data.value.hiddenChannels.contains(author)

    fun setChannelHidden(author: String, hidden: Boolean) = mutate { data ->
        val list = data.hiddenChannels.toMutableList()
        if (hidden && !list.contains(author)) list.add(author)
        if (!hidden) list.remove(author)
        data.copy(hiddenChannels = list)
    }

    fun toggleChannelHidden(author: String): Boolean {
        val next = !isChannelHidden(author)
        setChannelHidden(author, next)
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
        val positions = data.positions.toMutableMap()
        // Совсем начало и почти конец не запоминаем: возобновлять нечего.
        if (positionMs < 5_000) positions.remove(id) else positions[id] = positionMs
        data.copy(positions = positions.entries
            .sortedByDescending { it.key }
            .take(POSITION_LIMIT)
            .associate { it.key to it.value })
    }

    fun position(id: String): Long = _data.value.positions[id] ?: 0L

    fun clearFavorites() = mutate { it.copy(favorites = emptyList()) }

    fun clearHistory() = mutate { it.copy(history = emptyList()) }

    fun clearHiddenChannels() = mutate { it.copy(hiddenChannels = emptyList()) }

    /** Убирает из личных данных записи об удалённых видео. */
    fun pruneMissing(existingIds: Set<String>) = mutate { data ->
        data.copy(
            favorites = data.favorites.filter { existingIds.contains(it) },
            history = data.history.filter { existingIds.contains(it) },
            positions = data.positions.filterKeys { existingIds.contains(it) }
        )
    }

    companion object {
        const val HISTORY_LIMIT = 500
        const val POSITION_LIMIT = 500
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

private fun JSONObject.longMap(key: String): Map<String, Long> {
    val obj = optJSONObject(key) ?: return emptyMap()
    val out = HashMap<String, Long>()
    obj.keys().forEach { k -> out[k] = obj.optLong(k, 0L) }
    return out
}
