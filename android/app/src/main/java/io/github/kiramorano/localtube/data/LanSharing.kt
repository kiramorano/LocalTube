package io.github.kiramorano.localtube.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File

/**
 * Управление раздачей библиотеки в локальную сеть.
 *
 * Отдельный класс, а не логика в экране настроек: сервер должен переживать
 * поворот экрана и уход в другой раздел, а состояние (адреса, порт, PIN) нужно
 * сразу нескольким экранам.
 */
class LanSharing(
    context: Context,
    library: Library,
    userData: UserDataStore,
    private val settings: Settings
) {

    val access = LanAccess(context)
    private val server = LanServer(LibrarySource(library, userData), AccessGuard(access))

    private val _state = MutableStateFlow(State(pin = access.pin))
    val state: StateFlow<State> = _state.asStateFlow()

    /**
     * Состояние раздачи для интерфейса.
     *
     * @param addresses адреса, по которым устройство видно в сети
     * @param error причина, по которой сервер не запустился
     */
    data class State(
        val running: Boolean = false,
        val port: Int = 0,
        val addresses: List<String> = emptyList(),
        val pin: String = "",
        val error: String = ""
    ) {
        /** Ссылка для гостя: первый пригодный адрес. */
        val url: String
            get() = addresses.firstOrNull()?.let { LanAccess.urlFor(it, port) }.orEmpty()
    }

    init {
        // Настройка включена с прошлого запуска: поднимаем сервер сразу, иначе
        // тумблер показывал бы «включено» при выключенной раздаче.
        if (settings.lanEnabled) start()
    }

    fun start() {
        val ok = server.start(settings.lanPort)
        settings.lanEnabled = ok
        _state.value = State(
            running = ok,
            port = server.activePort,
            addresses = LanAccess.localAddresses(),
            pin = access.pin,
            error = if (ok) "" else "Не удалось занять порт ${settings.lanPort}: ${server.lastError}"
        )
    }

    fun stop() {
        server.stop()
        settings.lanEnabled = false
        _state.value = _state.value.copy(running = false, port = 0, error = "")
    }

    fun toggle() {
        if (_state.value.running) stop() else start()
    }

    /** Перезапуск после смены порта: слушающий сокет порт на ходу не меняет. */
    fun restartIfRunning() {
        if (_state.value.running) start()
    }

    /** Обновляет список адресов: при переходе на другую сеть они меняются. */
    fun refreshAddresses() {
        _state.value = _state.value.copy(addresses = LanAccess.localAddresses())
    }

    /**
     * Новый PIN. Все ранее впущенные устройства теряют доступ — это и есть
     * способ «выгнать всех».
     */
    fun regeneratePin() {
        _state.value = _state.value.copy(pin = access.regenerate())
    }

    /**
     * Переходник от файловой библиотеки к тому узкому набору, который нужен
     * серверу. Скрытые каналы учитываются здесь, а не в самом сервере: правило
     * «гостю не показывать» живёт в личных данных, и серверу о них знать нечего.
     */
    private class LibrarySource(
        private val library: Library,
        private val userData: UserDataStore
    ) : LanServer.Source {
        override val videosRoot: File get() = library.root
        override val userVideosRoot: File get() = library.userRoot
        override val avatarsDir: File get() = library.avatarsRoot
        override val bannersDir: File get() = library.bannersRoot

        override fun catalog(): Catalog = library.catalog()
        override fun findVideo(id: String): VideoItem? = library.findVideo(id)
        override fun videosOf(author: String): List<VideoItem> = library.videosOf(author)
        override fun search(query: String): List<VideoItem> = library.search(query)

        override fun subtitlesOf(v: VideoItem): List<Pair<String, String>> =
            library.subtitleFiles(v).map { library.subtitleLang(it) to it.name }

        override fun isChannelHidden(author: String): Boolean = userData.isChannelHidden(author)
        override fun hiddenChannels(): Set<String> = userData.current.hiddenChannels.toSet()
    }

    private class AccessGuard(private val access: LanAccess) : LanServer.Guard {
        override fun isValidToken(token: String?): Boolean = access.isValidToken(token)
        override fun checkPin(input: String?, address: String): LanAccess.PinResult =
            access.checkPin(input, address)
    }
}
