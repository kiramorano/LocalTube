package io.github.kiramorano.localtube.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.ComposeContentTestRule
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import io.github.kiramorano.localtube.data.AppTheme
import io.github.kiramorano.localtube.ui.components.LtHeader
import io.github.kiramorano.localtube.ui.theme.LocalTubeTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Шапка проверяется композицией, а не на глаз.
 *
 * Повод: до этого ни один экран не проверялся в рантайме — интерфейс считался
 * рабочим, если компилируется. Шапку при этом переписали целиком (убрали
 * шестерёнку, на широком экране добавили поле поиска), и потерю доступа к
 * настройкам поймать было нечем.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class LtHeaderUiTest {

    @get:Rule
    val rule = createComposeRule()

    @Test
    fun `на телефоне видны логотип, поиск, меню и аватар`() {
        rule.setHeader(widthDp = 360)

        rule.onNodeWithText("LocalTube").assertIsDisplayed()
        rule.onNodeWithContentDescription("Поиск").assertIsDisplayed()
        rule.onNodeWithContentDescription("Меню").assertIsDisplayed()
        rule.onNodeWithContentDescription("Настройки, Кира").assertIsDisplayed()
    }

    @Test
    fun `настройки открываются с аватара`() {
        // Шестерёнку убрали: если аватар перестанет вести в настройки, попасть
        // туда с телефона будет нечем — нижней панели у настроек нет.
        var opened = 0
        rule.setHeader(widthDp = 360, onSettingsClick = { opened++ })

        rule.onNodeWithContentDescription("Настройки, Кира").performClick()

        assertEquals(1, opened)
    }

    @Test
    fun `поиск открывается иконкой на телефоне`() {
        var searched = 0
        rule.setHeader(widthDp = 360, onSearchClick = { searched++ })

        rule.onNodeWithContentDescription("Поиск").performClick()

        assertEquals(1, searched)
    }

    @Test
    fun `на широком экране поиск это поле, и оно нажимается`() {
        var searched = 0
        rule.setHeader(widthDp = 900, onSearchClick = { searched++ })

        // Поле с подписью, а не только иконка: на планшете места хватает.
        rule.onNodeWithText("Поиск по библиотеке").assertIsDisplayed()
        rule.onNodeWithContentDescription("Поиск").performClick()

        assertEquals(1, searched)
    }

    @Test
    fun `имя показывается там, где хватает ширины`() {
        rule.setHeader(widthDp = 900)

        rule.onNodeWithText("Кира").assertIsDisplayed()
    }

    @Test
    fun `на телефоне имя не занимает место в шапке`() {
        // Раньше имя стояло рядом с кружком всегда, и справа на узком экране
        // оказывались четыре цели в ряд.
        rule.setHeader(widthDp = 360)

        assertEquals(0, rule.onAllNodesWithText("Кира").fetchSemanticsNodes().size)
    }

    @Test
    fun `кнопка меню исчезает при постоянном сайдбаре`() {
        // На широком экране меню уже открыто: гамбургер не нужен.
        rule.setHeader(widthDp = 900, onMenuClick = null)

        assertEquals(
            0,
            rule.onAllNodesWithContentDescription("Меню").fetchSemanticsNodes().size
        )
    }

    @Test
    fun `логотип ведёт на главную`() {
        var home = 0
        rule.setHeader(widthDp = 360, onLogoClick = { home++ })

        rule.onNodeWithText("LocalTube").performClick()

        assertEquals(1, home)
    }

    @Test
    fun `пустое имя не оставляет кружок без буквы`() {
        // userName приходит из настроек и может быть пустым: take(1) от пустой
        // строки дал бы кружок без подписи.
        rule.setHeader(widthDp = 360, userName = "  ")

        rule.onNodeWithText("Г").assertIsDisplayed()
    }

    @Test
    fun `имя из одной буквы не ломает инициал`() {
        rule.setHeader(widthDp = 360, userName = "я")

        rule.onNodeWithText("Я").assertIsDisplayed()
    }
}

/**
 * Шапка в каждой теме отдельным прогоном.
 *
 * Glass и Aero задают полупрозрачные поверхности, Midnight — свои слои. Тема
 * влияет и на цвет, и на радиус, поэтому проверяется, что композиция не падает
 * ни в одной из пяти.
 */
@RunWith(org.robolectric.ParameterizedRobolectricTestRunner::class)
@Config(sdk = [33])
class LtHeaderThemeUiTest(private val theme: AppTheme) {

    @get:Rule
    val rule = createComposeRule()

    @Test
    fun `шапка рисуется в теме`() {
        rule.setHeader(widthDp = 360, theme = theme)

        rule.onNodeWithText("LocalTube").assertIsDisplayed()
        rule.onNodeWithContentDescription("Настройки, Кира").assertIsDisplayed()
    }

    companion object {
        @JvmStatic
        @org.robolectric.ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun themes(): Collection<Array<Any>> = AppTheme.entries.map { arrayOf<Any>(it) }
    }
}

/** Общая обвязка: тема, ширина экрана и сама шапка. */
internal fun ComposeContentTestRule.setHeader(
    widthDp: Int,
    theme: AppTheme = AppTheme.DARK,
    onMenuClick: (() -> Unit)? = {},
    onSearchClick: () -> Unit = {},
    onSettingsClick: () -> Unit = {},
    onLogoClick: (() -> Unit)? = null,
    userName: String = "Кира"
) = setContent {
    WithWidth(widthDp) {
        LocalTubeTheme(theme = theme) {
            LtHeader(
                onMenuClick = onMenuClick,
                onSearchClick = onSearchClick,
                onSettingsClick = onSettingsClick,
                onLogoClick = onLogoClick,
                userName = userName
            )
        }
    }
}

/**
 * Подменяет ширину экрана: раскладка выбирается по LocalConfiguration
 * (LtBreakpoints.isCompact), а Robolectric по умолчанию даёт узкие 320dp.
 */
@Composable
internal fun WithWidth(widthDp: Int, content: @Composable () -> Unit) {
    val base = LocalConfiguration.current
    val configuration = android.content.res.Configuration(base).apply {
        screenWidthDp = widthDp
    }
    CompositionLocalProvider(LocalConfiguration provides configuration) {
        Column { content() }
    }
}
