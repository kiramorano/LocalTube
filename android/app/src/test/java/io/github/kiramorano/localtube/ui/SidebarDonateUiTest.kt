package io.github.kiramorano.localtube.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import io.github.kiramorano.localtube.LocalTubeApp
import io.github.kiramorano.localtube.data.Author
import io.github.kiramorano.localtube.ui.components.DONATE_URL
import io.github.kiramorano.localtube.ui.components.LtSidebar
import io.github.kiramorano.localtube.ui.theme.LocalTubeTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Боковое меню: пункт поддержки автора.
 *
 * В веб-версии ссылка лежит в двух местах — в боковой панели всех пяти шаблонов
 * с ней и отдельной секцией в настройках (tests/test_templates.py это
 * закрепляет). В Android её не было ни там, ни там, и портирование, которое
 * добавило бы только настройки, оставило бы половину работы: до настроек нужно
 * дойти, а меню открыто на каждом экране.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33], qualifiers = "w411dp-h891dp-xhdpi")
class SidebarDonateUiTest {

    @get:Rule
    val rule = createComposeRule()

    private var donateClicks = 0
    private var unavailable = 0

    private fun show() {
        rule.setContent {
            WithWidth(360) {
                LocalTubeTheme {
                    LtSidebar(
                        currentRoute = "home",
                        authors = listOf(Author(name = "Канал", avatar = null, videoCount = 1)),
                        hiddenChannels = emptyList(),
                        onNavigate = {},
                        onOpenChannel = {},
                        onUnhideChannel = {},
                        onDonateClick = { donateClicks++ },
                        onDonateUnavailable = { unavailable++ }
                    )
                }
            }
        }
        rule.waitForIdle()
    }

    @Test
    fun `в меню есть пункт поддержки автора`() {
        show()

        rule.onNodeWithText("Поддержать автора").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun `пункт меню открывает Donationalerts`() {
        show()

        rule.onNodeWithText("Поддержать автора").performScrollTo().performClick()
        rule.waitForIdle()

        // Проверяем сам адрес: опечатка в ссылке иначе прошла бы незамеченной.
        val started = org.robolectric.Shadows.shadowOf(
            androidx.test.core.app.ApplicationProvider
                .getApplicationContext<LocalTubeApp>()
        ).nextStartedActivity
        assertEquals(android.content.Intent.ACTION_VIEW, started.action)
        assertEquals(DONATE_URL, started.data.toString())
    }

    @Test
    fun `нажатие закрывает выдвижное меню`() {
        show()

        // Уходим в браузер, и меню — в отличие от перехода по разделу — само не
        // закрывается: при возврате в приложение оно висело бы поверх экрана.
        rule.onNodeWithText("Поддержать автора").performScrollTo().performClick()
        rule.waitForIdle()

        assertEquals(1, donateClicks)
    }

    @Test
    fun `без браузера меню не закрывается молча`() {
        // На ТВ браузера может не быть. Раньше здесь был бы краш; теперь пункт
        // сообщает о невозможности перехода, а AppRoot уводит в настройки, где
        // показывается QR. Меню при этом закрывать нельзя как «успех».
        org.robolectric.Shadows.shadowOf(
            androidx.test.core.app.ApplicationProvider
                .getApplicationContext<LocalTubeApp>()
        ).checkActivities(true)
        show()

        rule.onNodeWithText("Поддержать автора").performScrollTo().performClick()
        rule.waitForIdle()

        assertEquals("успешного перехода не было", 0, donateClicks)
        assertEquals("не сообщили о невозможности", 1, unavailable)
    }

    @Test
    fun `адрес поддержки совпадает с веб-версией`() {
        // Единственный источник адреса на всё приложение: настройки и меню
        // ссылаются на одну константу, поэтому разъехаться они не могут.
        assertEquals("https://www.donationalerts.com/r/localteam", DONATE_URL)
    }

    @Test
    fun `пункт настроек остаётся на месте`() {
        show()

        // Поддержка добавлена после настроек: важно, что она не вытеснила
        // существующий пункт.
        rule.onNodeWithText("Настройки").performScrollTo().assertIsDisplayed()
        rule.onNodeWithText("Главная").performScrollTo().assertIsDisplayed()
    }
}
