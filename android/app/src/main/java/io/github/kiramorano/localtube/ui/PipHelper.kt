package io.github.kiramorano.localtube.ui

import android.app.Activity
import android.app.PictureInPictureParams
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.util.Rational

/**
 * Картинка в картинке. Вынесено из плеера: проверок здесь больше, чем логики,
 * и держать их внутри экрана значило бы смешивать воспроизведение с
 * особенностями платформы.
 *
 * Режим появился в API 26 (это же minSdk), но у части устройств — телевизоры и
 * прошивки без поддержки — функции нет вовсе, поэтому доступность проверяется,
 * а не предполагается.
 */
object PipHelper {

    fun isSupported(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return false
        return context.packageManager
            .hasSystemFeature(PackageManager.FEATURE_PICTURE_IN_PICTURE)
    }

    /**
     * Переводит окно в режим PiP с пропорциями видео.
     *
     * Android принимает соотношение сторон только в диапазоне примерно от
     * 1:2.39 до 2.39:1; выход за границы приводит к IllegalArgumentException, а
     * не к автоматической подгонке, поэтому значение ограничивается заранее.
     */
    fun enter(activity: Activity?, videoWidth: Int, videoHeight: Int): Boolean {
        if (activity == null) return false
        if (!isSupported(activity)) return false
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return false
        val (w, h) = aspectRatio(videoWidth, videoHeight)
        return runCatching {
            activity.enterPictureInPictureMode(
                PictureInPictureParams.Builder().setAspectRatio(Rational(w, h)).build()
            )
        }.getOrDefault(false)
    }

    /**
     * Пропорции для PiP в допустимых системой границах, как пара «ширина к
     * высоте».
     *
     * Возвращается пара, а не Rational: в юнит-тестах android.util.Rational —
     * заглушка без реализации, и проверить правило через неё нельзя.
     */
    internal fun aspectRatio(width: Int, height: Int): Pair<Int, Int> {
        // Неизвестный размер: до первого кадра ExoPlayer отдаёт нули.
        if (width <= 0 || height <= 0) return 16 to 9
        val value = width.toDouble() / height
        return when {
            value > MAX_RATIO -> 239 to 100
            value < MIN_RATIO -> 100 to 239
            else -> width to height
        }
    }

    /** Границы, которые задаёт сама система. */
    private const val MAX_RATIO = 2.39
    private const val MIN_RATIO = 1 / 2.39
}
