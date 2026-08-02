package io.github.kiramorano.localtube.data

import android.content.Context

class Settings(context: Context) {
    private val sp = context.getSharedPreferences("localtube", Context.MODE_PRIVATE)

    var darkTheme: Boolean
        get() = sp.getBoolean("dark_theme", true)
        set(v) = sp.edit().putBoolean("dark_theme", v).apply()

    var downloadSubs: Boolean
        get() = sp.getBoolean("download_subs", true)
        set(v) = sp.edit().putBoolean("download_subs", v).apply()

    var subLangs: String
        get() = sp.getString("sub_langs", "ru,en") ?: "ru,en"
        set(v) = sp.edit().putString("sub_langs", v).apply()

    var defaultFormat: String
        get() = sp.getString("default_format", "best") ?: "best"
        set(v) = sp.edit().putString("default_format", v).apply()

    var enableNotifications: Boolean
        get() = sp.getBoolean("notifications", true)
        set(v) = sp.edit().putBoolean("notifications", v).apply()
}
