package io.github.kiramorano.localtube.data

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.flow.MutableStateFlow

object ServerManager {
    private lateinit var prefs: SharedPreferences
    val serverUrl = MutableStateFlow("")

    fun init(context: Context) {
        prefs = context.applicationContext.getSharedPreferences("localtube", Context.MODE_PRIVATE)
        serverUrl.value = prefs.getString("server", "") ?: ""
    }

    fun hasServer(): Boolean = serverUrl.value.isNotBlank()

    fun save(url: String) {
        val trimmed = url.trim().trimEnd('/')
        prefs.edit().putString("server", trimmed).apply()
        serverUrl.value = trimmed
    }

    fun api(): LocalTubeApi = LocalTubeApi(serverUrl.value)
}
