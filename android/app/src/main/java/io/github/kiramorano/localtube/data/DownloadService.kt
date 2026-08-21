package io.github.kiramorano.localtube.data

import android.app.Notification
import android.app.Service
import android.content.Intent
import android.os.IBinder

/**
 * Foreground-сервис на время загрузок.
 *
 * Без него система вправе убить процесс во время долгого скачивания: раньше
 * загрузка шла в обычной корутине приложения.
 */
class DownloadService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val text = intent?.getStringExtra(EXTRA_TEXT) ?: "Загрузка видео"
        val notification: Notification = Notification.Builder(this, "downloads")
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("LocalTube")
            .setContentText(text)
            .setOngoing(true)
            .build()
        runCatching { startForeground(NOTIFICATION_ID, notification) }
        return START_NOT_STICKY
    }

    companion object {
        const val EXTRA_TEXT = "text"
        const val NOTIFICATION_ID = 4711
    }
}
