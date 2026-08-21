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

    private val _theme = MutableStateFlow(AppTheme.from(prefs.getString(KEY_THEME, null)))
    val themeFlow: StateFlow<AppTheme> = _theme.asStateFlow()

    private val _downloadSubs = MutableStateFlow(prefs.getBoolean(KEY_SUBS, true))
    val downloadSubsFlow: StateFlow<Boolean> = _downloadSubs.asStateFlow()

    private val _subLangs = MutableStateFlow(prefs.getString(KEY_SUB_LANGS, "ru,en") ?: "ru,en")
    val subLangsFlow: StateFlow<String> = _subLangs.asStateFlow()

    private val _notifications = MutableStateFlow(prefs.getBoolean(KEY_NOTIFICATIONS, true))
    val notificationsFlow: StateFlow<Boolean> = _notifications.asStateFlow()

    private val _preferHighest = MutableStateFlow(prefs.getBoolean(KEY_PREFER_HIGHEST, true))
    val preferHighestFlow: StateFlow<Boolean> = _preferHighest.asStateFlow()

    private val _sort = MutableStateFlow(CatalogSort.from(prefs.getString(KEY_SORT, null)))
    val sortFlow: StateFlow<CatalogSort> = _sort.asStateFlow()

    private val _autoplayNext = MutableStateFlow(prefs.getBoolean(KEY_AUTOPLAY, true))
    val autoplayNextFlow: StateFlow<Boolean> = _autoplayNext.asStateFlow()

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

    companion object {
        private const val KEY_THEME = "app_theme"
        private const val KEY_SUBS = "download_subs"
        private const val KEY_SUB_LANGS = "sub_langs"
        private const val KEY_NOTIFICATIONS = "notifications"
        private const val KEY_PREFER_HIGHEST = "prefer_highest"
        private const val KEY_SORT = "catalog_sort"
        private const val KEY_AUTOPLAY = "autoplay_next"
    }
}
