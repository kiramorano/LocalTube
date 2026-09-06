package io.github.kiramorano.localtube.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasScrollToNodeAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import io.github.kiramorano.localtube.data.AppTheme
import io.github.kiramorano.localtube.data.TaskPriority
import io.github.kiramorano.localtube.ui.screens.DownloadsScreen
import io.github.kiramorano.localtube.ui.theme.LocalTubeTheme
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Экран очереди в рантайме.
 *
 * Экран переписан целиком: убрана вторая шапка (CenterAlignedTopAppBar поверх
 * LtHeader), секции собраны в LtPanel. Проверяется, что при этом ничего не
 * потерялось — поле ссылки, приоритеты, фильтры, пауза и подсказка про TikTok.
 */
@RunWith(RobolectricTestRunner::class)
// Размер окна задаётся явно: по умолчанию Robolectric даёт мелкий экран, и
// элементы ниже сгиба считаются не показанными, хотя на телефоне видны.
@Config(sdk = [33], qualifiers = "w411dp-h891dp-xhdpi")
class DownloadsScreenUiTest {

    @get:Rule
    val rule = createComposeRule()

    /**
     * Очередь живёт в репозитории приложения и переживает пересоздание экрана:
     * задачи и пауза, оставшиеся от предыдущего теста, меняли подзаголовок и
     * содержимое списка. Robolectric держит Application на весь класс, поэтому
     * состояние сбрасывается вручную перед каждым тестом — иначе результат
     * зависит от порядка запуска.
     */
    @Before
    fun resetQueue() {
        val downloads = androidx.test.core.app.ApplicationProvider
            .getApplicationContext<io.github.kiramorano.localtube.LocalTubeApp>()
            .repository.downloads
        downloads.setPaused(false)
        downloads.tasks.value.forEach { downloads.remove(it.id) }
        // setPaused() пишет queue.json асинхронно (persist() уходит в scope), и
        // тест «пауза переключается» успевал оставить в файле paused=true.
        // Robolectric держит Application на весь класс, поэтому ждём, пока
        // запись закончится, и подчищаем файл: иначе результат зависит от
        // порядка тестов.
        val queueFile = java.io.File(
            androidx.test.core.app.ApplicationProvider
                .getApplicationContext<io.github.kiramorano.localtube.LocalTubeApp>()
                .filesDir,
            "queue.json"
        )
        val deadline = System.currentTimeMillis() + 5_000
        while (System.currentTimeMillis() < deadline) {
            val text = runCatching { queueFile.readText() }.getOrDefault("")
            if (!text.contains("\"paused\":true") && !downloads.paused.value) break
            Thread.sleep(20)
        }
    }

    private fun show(widthDp: Int = 360, theme: AppTheme = AppTheme.DARK, url: String? = null) {
        rule.setContent {
            WithWidth(widthDp) {
                LocalTubeTheme(theme = theme) {
                    // Модель создаётся своя на каждый показ: viewModel() без
                    // владельца переиспользует экземпляр между тестами, и экран
                    // доставался с состоянием от предыдущего.
                    DownloadsScreen(
                        initialUrl = url,
                        vm = io.github.kiramorano.localtube.vm.DownloadsViewModel(
                            androidx.test.core.app.ApplicationProvider.getApplicationContext()
                        )
                    )
                }
            }
        }
    }

    @Test
    fun `видны заголовок, поле ссылки и кнопка качеств`() {
        show()

        rule.onNodeWithText("Очередь").assertIsDisplayed()
        rule.onNodeWithText("Ссылка на видео или плейлист").assertIsDisplayed()
        rule.onNodeWithText("Показать качества").assertIsDisplayed()
    }

    @Test
    fun `второй шапки на экране нет`() {
        // Раньше CenterAlignedTopAppBar с надписью «Загрузки» рисовался прямо
        // под LtHeader: две панели друг над другом.
        show()

        assertEquals(0, rule.onAllNodesWithText("Загрузки").fetchSemanticsNodes().size)
    }

    @Test
    fun `подсказка называет обе платформы`() {
        // Иначе неочевидно, что кроме YouTube принимается и TikTok.
        // Placeholder в Material3 появляется только у поля в фокусе, поэтому
        // сначала ставим курсор.
        show()

        rule.onNodeWithText("Ссылка на видео или плейлист").performClick()
        rule.waitForIdle()

        rule.onNodeWithText("Вставьте ссылку YouTube или TikTok").assertIsDisplayed()
    }

    @Test
    fun `все приоритеты предлагаются`() {
        show()

        // Экран прокручиваемый, а окно теста невысокое: до чипов нужно
        // доскроллить, иначе узел есть, но не показан.
        TaskPriority.entries.forEach { p ->
            rule.onNodeWithText(p.label).performScrollTo().assertIsDisplayed()
        }
    }

    @Test
    fun `пустая очередь сообщает об этом`() {
        show()

        // Подзаголовок под «Очередью»: он существует с первого кадра. Проверять
        // видимость нельзя — список прокручен вниз к заглушке, и шапка со
        // счётчиком уходит за верхний край.
        //
        // Пауза сбрасывается в @Before, но состояние очереди перечитывается с
        // диска асинхронно, и подзаголовок может успеть показать «На паузе».
        rule.onNodeWithText("Нет задач").assertExists()
        // Заглушка списка лежит в LazyColumn и до прокрутки не скомпонована:
        // performScrollTo() ищет уже существующий узел, поэтому нужен
        // performScrollToNode() по самому списку.
        rule.onNode(hasScrollToNodeAction())
            .performScrollToNode(hasText("Очередь пуста"))
        rule.waitForIdle()
        rule.onNodeWithText("Очередь пуста").assertIsDisplayed()
    }

    @Test
    fun `ссылка из поделиться попадает в поле`() {
        // Ссылка идёт от MainActivity через AppRoot и раньше терялась по пути.
        val url = "https://www.tiktok.com/@creator/video/7461234567890123456"
        show(url = url)

        rule.onNodeWithText(url).assertIsDisplayed()
    }

    @Test
    fun `пауза переключается и меняет подпись`() {
        show()

        rule.onNodeWithContentDescription("Пауза").performClick()
        rule.waitForIdle()

        // После нажатия кнопка предлагает продолжить, а строка состояния
        // сообщает о паузе.
        rule.onNodeWithContentDescription("Продолжить").assertIsDisplayed()
        rule.onNodeWithText("На паузе").assertIsDisplayed()
    }

    @Test
    fun `неподдерживаемая ссылка отклоняется без сети`() {
        // Проверка идёт до запуска движка: yt-dlp в тесте недоступен, и если
        // экран полез бы в сеть, сообщения об ошибке мы бы не увидели.
        show()

        rule.onNodeWithText("Ссылка на видео или плейлист")
            .performTextInput("https://example.org/video")
        rule.onNodeWithText("Показать качества").performClick()
        rule.waitForIdle()

        rule.onNodeWithText("Поддерживаются ссылки YouTube и TikTok").assertIsDisplayed()
    }

    @Test
    fun `кнопка качеств не запускается на пустом поле`() {
        show()

        // fetch("") выходит сразу: ошибки быть не должно, экран остаётся как был.
        rule.onNodeWithText("Показать качества").performClick()
        rule.waitForIdle()

        assertEquals(
            0,
            rule.onAllNodesWithText("Поддерживаются ссылки YouTube и TikTok")
                .fetchSemanticsNodes().size
        )
    }

    @Test
    fun `фильтры не показываются на пустой очереди`() {
        // Фильтровать нечего: ряд чипов на пустом экране только занимал бы
        // место. Тест закрепляет это, чтобы правка вёрстки не добавила их
        // безусловно.
        show()

        assertEquals(0, rule.onAllNodesWithText("Ошибки").fetchSemanticsNodes().size)
        assertEquals(0, rule.onAllNodesWithText("Готовые").fetchSemanticsNodes().size)
    }

    @Test
    fun `задача из очереди видна со статусом и кнопкой отмены`() {
        // Проверяем реальную задачу, а не только пустое состояние: TaskRow
        // переписан вместе с экраном.
        val downloads = androidx.test.core.app.ApplicationProvider
            .getApplicationContext<io.github.kiramorano.localtube.LocalTubeApp>()
            .repository.downloads
        downloads.add(
            url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            formatId = "best",
            title = "Тестовый ролик",
            priority = TaskPriority.HIGH
        )
        show()

        rule.onNodeWithText("Тестовый ролик").performScrollTo().assertIsDisplayed()
        // Фильтры появились вместе с задачей.
        rule.onNodeWithText("Ошибки").assertExists()
        // Действие зависит от состояния: yt-dlp в JVM недоступен, поэтому
        // задача либо ждёт очереди, либо уже упала. Важно, что действие есть в
        // любом случае — строка без кнопки означала бы задачу, которую нельзя
        // ни снять, ни повторить.
        val actions = listOf("Отмена", "Повторить", "Убрать").sumOf { label ->
            rule.onAllNodesWithText(label).fetchSemanticsNodes().size
        }
        assertEquals(1, actions)
    }

    @Test
    fun `экран рисуется на планшетной ширине`() {
        show(widthDp = 900)

        rule.onNodeWithText("Очередь").assertIsDisplayed()
        rule.onNodeWithText("Показать качества").assertIsDisplayed()
    }
}

/** Очередь в каждой теме: у Glass и Aero поверхности полупрозрачные. */
@RunWith(org.robolectric.ParameterizedRobolectricTestRunner::class)
@Config(sdk = [33])
class DownloadsScreenThemeUiTest(private val theme: AppTheme) {

    @get:Rule
    val rule = createComposeRule()

    @Test
    fun `очередь рисуется в теме`() {
        rule.setContent {
            WithWidth(360) {
                LocalTubeTheme(theme = theme) { DownloadsScreen() }
            }
        }

        rule.onNodeWithText("Очередь").assertIsDisplayed()
        rule.onNodeWithText("Показать качества").assertIsDisplayed()
    }

    companion object {
        @JvmStatic
        @org.robolectric.ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun themes(): Collection<Array<Any>> = AppTheme.entries.map { arrayOf<Any>(it) }
    }
}
