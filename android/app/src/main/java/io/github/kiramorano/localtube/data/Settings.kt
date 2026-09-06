package io.github.kiramorano.localtube.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Настройки приложения.
 *
 * Значения отдаются через StateFlow: раньше они читались из SharedPreferences
 * напрямую, поэтому смена темы применялась только после перезапуска — Compose
 * не видел изменения и не перерисовывался.
 */
class Settings(context: Context) {

    private val prefs = context.getSharedPreferences("localtube", Context.MODE_PRIVATE)

    init {
        migrateSubtitleDefaults()
    }

    /**
     * Снимает у обновившихся установок прежние языки субтитров «ru,en».
     *
     * Новое значение по умолчанию помогает только чистой установке: у остальных
     * старое лежит в SharedPreferences, и загрузка ломалась бы дальше. Правка
     * разовая и помечена флагом, чтобы не затирать languages, выставленные
     * пользователем вручную уже после обновления.
     */
    private fun migrateSubtitleDefaults() {
        if (prefs.getBoolean(KEY_SUBS_MIGRATED, false)) return
        val editor = prefs.edit().putBoolean(KEY_SUBS_MIGRATED, true)
        if (prefs.getString(KEY_SUB_LANGS, null) == LEGACY_SUB_LANGS) {
            editor.putString(KEY_SUB_LANGS, DEFAULT_SUB_LANGS)
                .putBoolean(KEY_SUBS, DEFAULT_DOWNLOAD_SUBS)
        }
        editor.apply()
    }

    private val _theme = MutableStateFlow(AppTheme.from(prefs.getString(KEY_THEME, null)))
    val themeFlow: StateFlow<AppTheme> = _theme.asStateFlow()

    private val _downloadSubs = MutableStateFlow(prefs.getBoolean(KEY_SUBS, DEFAULT_DOWNLOAD_SUBS))
    val downloadSubsFlow: StateFlow<Boolean> = _downloadSubs.asStateFlow()

    private val _subLangs = MutableStateFlow(
        prefs.getString(KEY_SUB_LANGS, DEFAULT_SUB_LANGS) ?: DEFAULT_SUB_LANGS
    )
    val subLangsFlow: StateFlow<String> = _subLangs.asStateFlow()

    private val _audioLangs = MutableStateFlow(
        prefs.getString(KEY_AUDIO_LANGS, DEFAULT_AUDIO_LANGS) ?: DEFAULT_AUDIO_LANGS
    )
    val audioLangsFlow: StateFlow<String> = _audioLangs.asStateFlow()

    private val _notifications = MutableStateFlow(prefs.getBoolean(KEY_NOTIFICATIONS, true))
    val notificationsFlow: StateFlow<Boolean> = _notifications.asStateFlow()

    private val _preferHighest = MutableStateFlow(prefs.getBoolean(KEY_PREFER_HIGHEST, true))
    val preferHighestFlow: StateFlow<Boolean> = _preferHighest.asStateFlow()

    private val _sort = MutableStateFlow(CatalogSort.from(prefs.getString(KEY_SORT, null)))
    val sortFlow: StateFlow<CatalogSort> = _sort.asStateFlow()

    private val _autoplayNext = MutableStateFlow(prefs.getBoolean(KEY_AUTOPLAY, true))
    val autoplayNextFlow: StateFlow<Boolean> = _autoplayNext.asStateFlow()

    private val _playerClient = MutableStateFlow(prefs.getString(KEY_PLAYER_CLIENT, "") ?: "")
    val playerClientFlow: StateFlow<String> = _playerClient.asStateFlow()

    private val _backgroundPlayback = MutableStateFlow(prefs.getBoolean(KEY_BACKGROUND, false))
    val backgroundPlaybackFlow: StateFlow<Boolean> = _backgroundPlayback.asStateFlow()

    private val _equalizerPreset = MutableStateFlow(prefs.getString(KEY_EQ_PRESET, "off") ?: "off")
    val equalizerPresetFlow: StateFlow<String> = _equalizerPreset.asStateFlow()

    private val _bassBoost = MutableStateFlow(prefs.getInt(KEY_BASS_BOOST, 0))
    val bassBoostFlow: StateFlow<Int> = _bassBoost.asStateFlow()

    private val _externalStorage = MutableStateFlow(prefs.getBoolean(KEY_EXTERNAL_STORAGE, false))
    val externalStorageFlow: StateFlow<Boolean> = _externalStorage.asStateFlow()

    private val _lanEnabled = MutableStateFlow(prefs.getBoolean(KEY_LAN_ENABLED, false))
    val lanEnabledFlow: StateFlow<Boolean> = _lanEnabled.asStateFlow()

    private val _lanPort = MutableStateFlow(prefs.getInt(KEY_LAN_PORT, DEFAULT_LAN_PORT))
    val lanPortFlow: StateFlow<Int> = _lanPort.asStateFlow()

    private val _userName =
        MutableStateFlow(prefs.getString(KEY_USER_NAME, DEFAULT_USER_NAME) ?: DEFAULT_USER_NAME)
    val userNameFlow: StateFlow<String> = _userName.asStateFlow()

    var theme: AppTheme
        get() = _theme.value
        set(value) {
            prefs.edit().putString(KEY_THEME, value.id).apply()
            _theme.value = value
        }

    var downloadSubs: Boolean
        get() = _downloadSubs.value
        set(value) {
            prefs.edit().putBoolean(KEY_SUBS, value).apply()
            _downloadSubs.value = value
        }

    var subLangs: String
        get() = _subLangs.value
        set(value) {
            prefs.edit().putString(KEY_SUB_LANGS, value).apply()
            _subLangs.value = value
        }

    /**
     * Приоритет языков аудиодорожки, через запятую. Пусто — дорожку выбирает
     * YouTube, как было до появления настройки.
     */
    var audioLangs: String
        get() = _audioLangs.value
        set(value) {
            prefs.edit().putString(KEY_AUDIO_LANGS, value).apply()
            _audioLangs.value = value
        }

    var enableNotifications: Boolean
        get() = _notifications.value
        set(value) {
            prefs.edit().putBoolean(KEY_NOTIFICATIONS, value).apply()
            _notifications.value = value
        }

    /** Предлагать раздельные потоки (1080p и выше), склеивая их с аудио. */
    var preferHighest: Boolean
        get() = _preferHighest.value
        set(value) {
            prefs.edit().putBoolean(KEY_PREFER_HIGHEST, value).apply()
            _preferHighest.value = value
        }

    var sort: CatalogSort
        get() = _sort.value
        set(value) {
            prefs.edit().putString(KEY_SORT, value.id).apply()
            _sort.value = value
        }

    var autoplayNext: Boolean
        get() = _autoplayNext.value
        set(value) {
            prefs.edit().putBoolean(KEY_AUTOPLAY, value).apply()
            _autoplayNext.value = value
        }

    /**
     * player_client для yt-dlp. Пустая строка — «как решит yt-dlp»; остальные
     * значения совпадают с auth_options.py на сервере.
     */
    var playerClient: String
        get() = _playerClient.value
        set(value) {
            val clean = if (value in PLAYER_CLIENTS) value else ""
            prefs.edit().putString(KEY_PLAYER_CLIENT, clean).apply()
            _playerClient.value = clean
        }

    /** Продолжать воспроизведение при сворачивании приложения. */
    var backgroundPlayback: Boolean
        get() = _backgroundPlayback.value
        set(value) {
            prefs.edit().putBoolean(KEY_BACKGROUND, value).apply()
            _backgroundPlayback.value = value
        }

    var equalizerPreset: String
        get() = _equalizerPreset.value
        set(value) {
            prefs.edit().putString(KEY_EQ_PRESET, value).apply()
            _equalizerPreset.value = value
        }

    /** Усиление басов в милибелах, 0 — выключено. */
    var bassBoost: Int
        get() = _bassBoost.value
        set(value) {
            val clamped = value.coerceIn(0, 1000)
            prefs.edit().putInt(KEY_BASS_BOOST, clamped).apply()
            _bassBoost.value = clamped
        }

    /** Хранить библиотеку на карте памяти. Применяется после перезапуска. */
    var externalStorage: Boolean
        get() = _externalStorage.value
        set(value) {
            prefs.edit().putBoolean(KEY_EXTERNAL_STORAGE, value).apply()
            _externalStorage.value = value
        }

    var lanEnabled: Boolean
        get() = _lanEnabled.value
        set(value) {
            prefs.edit().putBoolean(KEY_LAN_ENABLED, value).apply()
            _lanEnabled.value = value
        }

    var lanPort: Int
        get() = _lanPort.value
        set(value) {
            // Порты ниже 1024 недоступны без root, выше 65535 не существуют.
            val clamped = value.coerceIn(1024, 65535)
            prefs.edit().putInt(KEY_LAN_PORT, clamped).apply()
            _lanPort.value = clamped
        }

    /**
     * Имя в шапке, как username в настройках веб-версии. Пустое значение
     * возвращается к «Гость»: иначе кружок с первой буквой оставался пустым.
     */
    var userName: String
        get() = _userName.value
        set(value) {
            val clean = normalizeUserName(value)
            prefs.edit().putString(KEY_USER_NAME, clean).apply()
            _userName.value = clean
        }

    companion object {
        private const val KEY_THEME = "app_theme"
        private const val KEY_SUBS = "download_subs"
        private const val KEY_SUB_LANGS = "sub_langs"
        private const val KEY_AUDIO_LANGS = "audio_langs"
        private const val KEY_SUBS_MIGRATED = "subs_migrated"
        private const val KEY_NOTIFICATIONS = "notifications"
        private const val KEY_PREFER_HIGHEST = "prefer_highest"
        private const val KEY_SORT = "catalog_sort"
        private const val KEY_AUTOPLAY = "autoplay_next"
        private const val KEY_PLAYER_CLIENT = "player_client"
        private const val KEY_BACKGROUND = "background_playback"
        private const val KEY_EQ_PRESET = "equalizer_preset"
        private const val KEY_BASS_BOOST = "bass_boost"
        private const val KEY_EXTERNAL_STORAGE = "external_storage"
        private const val KEY_LAN_ENABLED = "lan_enabled"
        private const val KEY_LAN_PORT = "lan_port"
        private const val KEY_USER_NAME = "user_name"

        const val DEFAULT_LAN_PORT = 8733

        /**
         * Языки субтитров по умолчанию — пусто, как в веб-версии
         * (download_prefs.DEFAULTS). Раньше стояло «ru,en», и загрузка ломалась:
         * yt-dlp получал --sub-langs с языками, которых у видео нет, а часть
         * роликов отдаёт на запрос субтитров ошибку вместо пустого списка.
         * Пустое значение означает «субтитры не запрашивать вовсе»:
         * Engine.buildRequest пропускает весь блок --write-subs/--sub-langs.
         */
        const val DEFAULT_SUB_LANGS = ""

        /**
         * Прежнее значение по умолчанию. Снимается один раз при обновлении:
         * иначе у уже установленных копий загрузка ломалась бы и дальше.
         */
        const val LEGACY_SUB_LANGS = "ru,en"

        /**
         * Субтитры по умолчанию выключены — как в вебе (subtitles_enabled=False).
         * Включённый тумблер при пустых языках вводил в заблуждение: настройка
         * выглядела рабочей, а дорожки не скачивались.
         */
        const val DEFAULT_DOWNLOAD_SUBS = false

        /**
         * Язык аудиодорожки по умолчанию не задан — как в вебе
         * (download_prefs.DEFAULTS["audio_langs"] = []). Дорожку выбирает
         * YouTube, то есть поведение прежнее.
         */
        const val DEFAULT_AUDIO_LANGS = ""

        const val DEFAULT_USER_NAME = "Гость"

        /** Длина имени: в шапке всё равно обрезается по ширине. */
        const val MAX_USER_NAME = 40

        /**
         * Код языка, каким его понимает yt-dlp: ru, en, pt-BR, zh-Hans.
         *
         * Тот же шаблон, что LANG_RE в download_prefs.py. Проверка нужна не для
         * красоты: код уходит и в имя файла субтитров, где «../../evil» увёл бы
         * запись за пределы папки, и в фильтр формата, где пробел внутри
         * `[language^=...]` ломает разбор селектора yt-dlp.
         */
        private val LANG_RE = Regex("""^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$""")

        /**
         * Список языков без пустых элементов, пробелов по краям и мусорных
         * кодов: «ru, , en» даёт «ru,en», а « , » — пустую строку. Используется
         * и для субтитров, и для аудиодорожек.
         *
         * Нормализуется не в сеттере, а перед передачей в yt-dlp: поля в
         * настройках пишутся на каждый символ, и сеттер стирал бы запятую прямо
         * во время набора «ru,en». Без этой чистки висячая запятая доезжала до
         * --sub-langs дословно — задачи из синхронизации канала идут в обход
         * фильтра Engine.chooseSubLangs.
         *
         * Непонятный код молча отбрасывается, а не роняет загрузку: пока
         * пользователь набирает «ru,e», промежуточное «e» — обычное состояние
         * поля, и показывать на него ошибку было бы навязчиво.
         *
         * Повторы убираются, как в _clean_langs на сервере: «ru,ru» означало бы
         * повторную загрузку того же файла субтитров.
         */
        fun normalizeLangs(value: String?): String =
            value.orEmpty()
                .split(',')
                .map { it.trim() }
                .filter { it.isNotEmpty() && LANG_RE.matches(it) }
                .distinct()
                .joinToString(",")

        /**
         * Имя без пробелов по краям и не длиннее MAX_USER_NAME. Пустое
         * возвращается к «Гость»: пустой кружок в шапке выглядел бы поломкой.
         */
        fun normalizeUserName(value: String?): String =
            value?.trim()?.take(MAX_USER_NAME)?.ifBlank { DEFAULT_USER_NAME } ?: DEFAULT_USER_NAME

        /** Допустимые player_client: тот же закрытый список, что на сервере. */
        val PLAYER_CLIENTS = listOf(
            "", "tv", "web", "web_safari", "web_embedded", "mweb", "android", "android_vr", "ios"
        )

        fun playerClientLabel(id: String): String = when (id) {
            "" -> "Авто"
            "tv" -> "TV"
            "web" -> "Web"
            "web_safari" -> "Web Safari"
            "web_embedded" -> "Web Embedded"
            "mweb" -> "Mobile Web"
            "android" -> "Android"
            "android_vr" -> "Android VR"
            "ios" -> "iOS"
            else -> id
        }
    }
}
