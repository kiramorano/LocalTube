package io.github.kiramorano.localtube.ui

import android.content.Intent
import android.content.pm.PackageManager
import androidx.test.core.app.ApplicationProvider
import io.github.kiramorano.localtube.LocalTubeApp
import io.github.kiramorano.localtube.ui.components.DONATE_URL
import io.github.kiramorano.localtube.ui.components.openExternalLink
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

/**
 * Открытие внешней ссылки на устройстве, где браузера нет.
 *
 * На Android TV браузер не входит в обязательный набор приложений, и
 * `startActivity` с ACTION_VIEW там бросает ActivityNotFoundException. Первая
 * версия кнопки «Поддержать автора» вызывала startActivity напрямую — то есть
 * нажатие на телевизоре роняло приложение. Тесты закрепляют, что исключение
 * перехвачено и вызывающий узнаёт об отказе по возвращённому значению.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class ExternalLinkTest {

    private val app: LocalTubeApp = ApplicationProvider.getApplicationContext()

    @Test
    fun `без браузера ссылка не открывается и не падает`() {
        // Robolectric по умолчанию отвечает на любой Intent, поэтому явно
        // включаем строгий режим: неразрешённый Intent должен привести к
        // исключению, как на настоящем ТВ без браузера.
        shadowOf(app.packageManager)
            .setShouldShowActivityChooser(false)
        shadowOf(app.packageManager).setResolveInfosForIntent(
            Intent(Intent.ACTION_VIEW, android.net.Uri.parse(DONATE_URL)),
            emptyList()
        )
        shadowOf(app).checkActivities(true)

        // Главное: вызов возвращает false, а не роняет приложение.
        assertFalse(openExternalLink(app, DONATE_URL))
    }

    @Test
    fun `с браузером ссылка открывается`() {
        shadowOf(app).checkActivities(false)

        assertTrue(openExternalLink(app, DONATE_URL))

        val started = shadowOf(app).nextStartedActivity
        assertEquals(Intent.ACTION_VIEW, started.action)
        assertEquals(DONATE_URL, started.data.toString())
    }

    @Test
    fun `внешний переход помечен новым заданием`() {
        shadowOf(app).checkActivities(false)
        openExternalLink(app, DONATE_URL)

        // Без FLAG_ACTIVITY_NEW_TASK запуск из application context бросает
        // AndroidRuntimeException: контекст приложения не привязан к задаче.
        val flags = shadowOf(app).nextStartedActivity.flags
        assertTrue(
            "нет FLAG_ACTIVITY_NEW_TASK",
            flags and Intent.FLAG_ACTIVITY_NEW_TASK != 0
        )
    }

    @Test
    fun `на ТВ браузера может не быть`() {
        // Пояснение к самому дефекту: leanback-устройство не обязано иметь
        // приложение для ACTION_VIEW, и код обязан это переживать.
        val hasLeanback = app.packageManager
            .hasSystemFeature(PackageManager.FEATURE_LEANBACK)
        // Робот не ТВ, проверка нужна лишь чтобы зафиксировать сам признак,
        // по которому MainActivity отличает телевизор.
        assertFalse(hasLeanback)
    }
}
