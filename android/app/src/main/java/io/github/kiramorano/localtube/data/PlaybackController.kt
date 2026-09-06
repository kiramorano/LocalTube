package io.github.kiramorano.localtube.data

import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.media3.exoplayer.ExoPlayer

/**
 * Общий экземпляр плеера для экрана и сервиса фонового воспроизведения.
 *
 * Зачем это нужно: MediaSessionService обязан отдать системе плеер, а экран
 * плеера управляет тем же воспроизведением напрямую (скорость, дорожки
 * субтитров, эквалайзер по audioSessionId). Если бы сервис создавал свой
 * ExoPlayer, одно видео играло бы дважды. Через MediaController экран тоже мог
 * бы управлять сервисом, но контроллер не отдаёт audioSessionId, без которого
 * системный эквалайзер не подключить.
 *
 * Владельцы считаются ссылками: плеер живёт, пока его держит хотя бы экран или
 * сервис.
 */
object PlaybackController {

    private var player: ExoPlayer? = null
    private var refs = 0

    /** Возвращает общий плеер, создавая его при первом обращении. */
    fun acquire(context: Context): ExoPlayer {
        refs++
        player?.let { return it }
        // Контекст приложения: плеер переживает поворот экрана, и держать
        // ссылку на активность значило бы утечку.
        val created = ExoPlayer.Builder(context.applicationContext).build()
        player = created
        return created
    }

    /**
     * Отпускает ссылку. Освобождение отложено на следующий проход очереди
     * сообщений: при переходе с одного видео на другое старый экран
     * освобождается уже после того, как новый захватил плеер, но обратный
     * порядок тоже возможен, и без задержки плеер успевал бы умереть между
     * двумя экранами.
     */
    fun release() {
        if (refs > 0) refs--
        if (refs > 0) return
        Handler(Looper.getMainLooper()).post {
            if (refs == 0) {
                player?.release()
                player = null
            }
        }
    }

    /** Текущий плеер или null: нужен для проверок без захвата ссылки. */
    val current: ExoPlayer?
        get() = player
}
