package io.github.kiramorano.localtube.data

import android.app.Notification
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

/**
 * Foreground-сервис на время загрузок.
 *
 * Без него система вправе убить процесс во время долгого скачивания: раньше
 * загрузка шла в обычной корутине приложения, и стоило свернуть приложение,
 * как длинная загрузка не доживала до конца.
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
        // На Android 10+ тип обязателен и должен совпадать с манифестом, иначе
        // на 14+ система бросает MissingForegroundServiceTypeException.
        val started = runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(
                    NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
                )
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
        }.isSuccess
        // Если перейти в foreground не дали (запуск из фона на Android 12+),
        // сервис нужно немедленно погасить: иначе система убьёт всё приложение
        // с ошибкой «did not then call Service.startForeground()».
        if (!started) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        return START_NOT_STICKY
    }

    companion object {
        const val EXTRA_TEXT = "text"
        const val NOTIFICATION_ID = 4711
    }
}
