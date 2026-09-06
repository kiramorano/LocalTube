package io.github.kiramorano.localtube.data

import android.app.PendingIntent
import android.content.Intent
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService

/**
 * Сервис фонового воспроизведения.
 *
 * Нужен для двух вещей: звук не обрывается при сворачивании приложения и
 * появляется системная панель управления (уведомление, экран блокировки,
 * наушники, кнопки пульта). Без foreground-сервиса система вправе усыпить
 * процесс, и фоновое воспроизведение прерывалось бы через несколько секунд.
 *
 * Плеер берётся из PlaybackController, то есть тот же самый, которым управляет
 * экран: свой ExoPlayer здесь дал бы двойной звук.
 *
 * Сервис запускается только когда включена настройка «фоновое
 * воспроизведение»: иначе висящее уведомление появлялось бы у пользователей,
 * которые фон не просили.
 */
@UnstableApi
class PlaybackService : MediaSessionService() {

    private var session: MediaSession? = null

    override fun onCreate() {
        super.onCreate()
        val player = PlaybackController.acquire(this)
        val builder = MediaSession.Builder(this, player)
        // Нажатие на уведомление возвращает в приложение: иначе система
        // открывает пустой экран, а пользователь теряет место просмотра.
        launchIntent()?.let { builder.setSessionActivity(it) }
        session = builder.build()
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    /**
     * Пользователь убрал приложение из списка задач. Если воспроизведение уже
     * остановлено, сервис можно гасить: уведомление молчащего плеера только
     * мешает.
     */
    override fun onTaskRemoved(rootIntent: Intent?) {
        val player = session?.player
        if (player == null || !player.playWhenReady || player.mediaItemCount == 0) {
            stopSelf()
        }
    }

    override fun onDestroy() {
        session?.release()
        session = null
        // Плеер общий, поэтому не release(), а отпускание ссылки: экран может
        // продолжать играть то же видео на переднем плане.
        PlaybackController.release()
        super.onDestroy()
    }

    private fun launchIntent(): PendingIntent? {
        val intent = packageManager.getLaunchIntentForPackage(packageName) ?: return null
        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        return PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }
}
