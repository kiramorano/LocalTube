package io.github.kiramorano.localtube.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasScrollAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import io.github.kiramorano.localtube.LocalTubeApp
import io.github.kiramorano.localtube.data.AppTheme
import io.github.kiramorano.localtube.data.Settings
import io.github.kiramorano.localtube.ui.screens.SettingsScreen
import io.github.kiramorano.localtube.ui.theme.LocalTubeTheme
import io.github.kiramorano.localtube.vm.SettingsViewModel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Экран настроек переписан на карточки, и раньше он не проверялся ничем, кроме
 * компиляции. Тесты закрепляют то, что чинилось руками: единственный заголовок
 * (вторая шапка от `CenterAlignedTopAppBar` убрана), карточки на своих местах и
 * версия, которая берётся из манифеста, а не из литерала в коде.
 *
 * Экран прокручивается целиком (`verticalScroll`), поэтому в отличие от очереди
 * все узлы скомпонованы сразу и хватает `performScrollTo()`.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33], qualifiers = "w411dp-h891dp-xhdpi")
class SettingsScreenUiTest {

    @get:Rule
    val rule = createComposeRule()

    private fun show(widthDp: Int = 360, theme: AppTheme = AppTheme.DARK) {
        rule.setContent {
            WithWidth(widthDp) {
                LocalTubeTheme(theme = theme) {
                    // Своя модель на каждый показ: viewModel() без владельца
                    // переиспользует экземпляр между тестами, и экран доставался
                    // с состоянием от предыдущего.
                    SettingsScreen(
                        vm = SettingsViewModel(
                            androidx.test.core.app.ApplicationProvider.getApplicationContext()
                        )
                    )
                }
            }
        }
        rule.waitForIdle()
    }

    @Test
    fun `заголовок экрана единственный`() {
        show()

        // Вторая шапка была настоящим дефектом: заголовок дублировался с
        // LtHeader. Проверяем, что «Настройки» на экране один.
        assertEquals(1, rule.onAllNodesWithText("Настройки").fetchSemanticsNodes().size)
        rule.onNodeWithText("Настройки").assertIsDisplayed()
    }

    @Test
    fun `карточки настроек на месте`() {
        show()

        // Заголовки девяти карточек: если секция потеряется при правке вёрстки,
        // тест это поймает.
        listOf(
            "Профиль",
            "Оформление",
            "Каталог",
            "Воспроизведение",
            "Загрузка",
            "Хранилище",
            "Локальная сеть",
            "Доступ к YouTube",
            "Cookies",
            "Мои данные",
            "Обслуживание"
        ).forEach { title ->
            rule.onNodeWithText(title).performScrollTo().assertIsDisplayed()
        }
    }

    @Test
    fun `версия берётся из манифеста`() {
        show()

        // Строка собиралась из литерала и отставала от build.gradle. Теперь
        // versionName приходит через Engine.appVersion, поэтому ждём номер из
        // сборки, а не зашитый текст.
        //
        // Сверяемся с настоящим versionName пакета: у ТВ-флейвора он «1.8.5-tv»,
        // и жёсткая строка ломала бы прогон testTvDebugUnitTest.
        val context = androidx.test.core.app.ApplicationProvider
            .getApplicationContext<LocalTubeApp>()
        val version = context.packageManager
            .getPackageInfo(context.packageName, 0).versionName
        // Иначе пустая версия («LocalTube Android ») прошла бы проверку.
        assertTrue("versionName=$version", version.orEmpty().first().isDigit())
        rule.onNodeWithText("LocalTube Android $version")
            .performScrollTo()
            .assertIsDisplayed()
    }

    @Test
    fun `чипы тем переключают оформление`() {
        show()

        rule.onNodeWithText("Midnight").performScrollTo().performClick()
        rule.waitForIdle()

        val settings = androidx.test.core.app.ApplicationProvider
            .getApplicationContext<LocalTubeApp>()
            .repository.settings
        assertEquals(AppTheme.MIDNIGHT, settings.themeFlow.value)
    }

    @Test
    fun `все темы предлагаются к выбору`() {
        show()

        // Midnight и Glass добавлялись руками: чип легко забыть.
        AppTheme.entries.forEach { theme ->
            rule.onNodeWithText(theme.label).performScrollTo().assertIsDisplayed()
        }
    }

    @Test
    fun `экран прокручивается`() {
        show()

        // Настройки не влезают в экран: без прокрутки нижние карточки были бы
        // недоступны. Последняя карточка достижима только скроллом, поэтому её
        // видимость и есть доказательство работающей прокрутки.
        assertTrue(
            rule.onAllNodes(hasScrollAction()).fetchSemanticsNodes().isNotEmpty()
        )
        rule.onNodeWithText("Обслуживание").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun `поле языков субтитров пустое по умолчанию`() {
        // Заранее вписанные «ru,en» ломали загрузку: yt-dlp получал языки,
        // которых у видео нет. Пример остаётся подсказкой, а не значением.
        val settings = androidx.test.core.app.ApplicationProvider
            .getApplicationContext<LocalTubeApp>()
            .repository.settings
        settings.subLangs = Settings.DEFAULT_SUB_LANGS
        settings.downloadSubs = Settings.DEFAULT_DOWNLOAD_SUBS
        show()

        rule.onNodeWithText("Языки субтитров (через запятую)").performScrollTo()
        // Подсказка показывает, что пустое поле значит «не скачивать».
        rule.onNodeWithText("Пусто — субтитры не скачиваются").assertIsDisplayed()
        // Пример виден placeholder-ом, но в настройках его нет.
        assertEquals("", settings.subLangs)
    }

    @Test
    fun `поле языка озвучки пустое по умолчанию`() {
        val settings = androidx.test.core.app.ApplicationProvider
            .getApplicationContext<LocalTubeApp>()
            .repository.settings
        settings.audioLangs = Settings.DEFAULT_AUDIO_LANGS
        show()

        rule.onNodeWithText("Язык озвучки (через запятую)").performScrollTo().assertIsDisplayed()
        rule.onNodeWithText("Пусто — дорожку выбирает YouTube").assertIsDisplayed()
    }

    @Test
    fun `имя профиля вводится и применяется`() {
        show()

        rule.onNodeWithText("Имя").performScrollTo().performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Имя").performTextReplacement("Кира")
        rule.onNodeWithText("Сохранить имя").performScrollTo().performClick()
        rule.waitForIdle()

        val settings = androidx.test.core.app.ApplicationProvider
            .getApplicationContext<LocalTubeApp>()
            .repository.settings
        assertEquals("Кира", settings.userNameFlow.value)
    }

    @Test
    fun `экран рисуется на планшетной ширине`() {
        // Ряды кнопок переведены на FlowRow: на широком экране они не должны
        // ломать разметку.
        show(widthDp = 840)

        rule.onNodeWithText("Настройки").assertIsDisplayed()
        rule.onNodeWithText("Оформление").performScrollTo().assertIsDisplayed()
    }

}

/**
 * Каждая тема — отдельный прогон экрана настроек: палитры Midnight и Glass
 * добавлялись позже остальных, и падение композиции в одной из них иначе
 * осталось бы незамеченным.
 */
@RunWith(org.robolectric.ParameterizedRobolectricTestRunner::class)
@Config(sdk = [33], qualifiers = "w411dp-h891dp-xhdpi")
class SettingsScreenThemeUiTest(private val theme: AppTheme) {

    @get:Rule
    val rule = createComposeRule()

    @Test
    fun `настройки рисуются в теме`() {
        rule.setContent {
            WithWidth(360) {
                LocalTubeTheme(theme = theme) {
                    SettingsScreen(
                        vm = SettingsViewModel(
                            androidx.test.core.app.ApplicationProvider.getApplicationContext()
                        )
                    )
                }
            }
        }
        rule.waitForIdle()

        rule.onNodeWithText("Настройки").assertIsDisplayed()
        rule.onNodeWithText("Профиль").performScrollTo().assertIsDisplayed()
    }

    companion object {
        @JvmStatic
        @org.robolectric.ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun themes(): Collection<Array<Any>> = AppTheme.entries.map { arrayOf<Any>(it) }
    }
}
