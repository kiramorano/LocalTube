package io.github.kiramorano.localtube.ui.theme

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Дизайн-система: пороги адаптивности, шкала текста, цели нажатия.
 *
 * Инструментальных тестов в проекте нет (androidTest отсутствует, зависимостей
 * ui-test тоже), поэтому проверяется то, что доступно обычному JVM-тесту:
 * значения токенов и чистая логика раскладки. Этого хватает, чтобы поймать
 * возврат к прежним ошибкам:
 *
 * * два несогласованных порога ширины в разных файлах;
 * * цель нажатия меньше 48dp;
 * * подписи мельче 12sp;
 * * пункт панели, который ни на одном экране не подсвечен.
 *
 * Compose-функции здесь не вызываются: без Robolectric композиция в JVM не
 * запускается, а тянуть его ради проверки констант незачем.
 */
class DesignSystemTest {

    // --- Пороги ширины ----------------------------------------------------

    @Test
    fun `телефон считается узким экраном`() {
        // Популярные телефоны: 360dp у бюджетных, 393dp у Pixel, 430dp у крупных.
        for (width in listOf(320, 360, 393, 412, 430, 480, 599)) {
            assertTrue("$width dp должен быть узким", LtBreakpoints.isCompact(width))
        }
    }

    @Test
    fun `планшет узким не считается`() {
        for (width in listOf(600, 720, 800, 840, 1280)) {
            assertFalse("$width dp не узкий", LtBreakpoints.isCompact(width))
        }
    }

    @Test
    fun `порог узкого экрана и порог сайдбара совпадают`() {
        // Раньше они расходились: 600dp против 720dp. В зазоре карточки уже
        // укрупнялись, а сайдбара ещё не было — раскладка ни телефонная, ни
        // планшетная. Проверяем именно совпадение, а не конкретное число:
        // сдвинуть границу можно, разъехаться — нет.
        assertEquals(
            "пороги разъехались: раскладка станет несогласованной",
            LtBreakpoints.COMPACT_MAX_DP,
            LtBreakpoints.SIDEBAR_MIN_DP
        )
    }

    @Test
    fun `узкий экран и постоянный сайдбар исключают друг друга`() {
        // Иначе на одном экране оказались бы и сайдбар, и нижняя панель: два
        // способа навигации сразу, отнимающие место у содержимого.
        for (width in 200..1400 step 20) {
            val compact = LtBreakpoints.isCompact(width)
            val sidebar = LtBreakpoints.hasPermanentSidebar(width, isTv = false)
            assertFalse("$width dp: и узкий экран, и постоянный сайдбар", compact && sidebar)
            assertTrue("$width dp: ни узкий экран, ни сайдбар", compact || sidebar)
        }
    }

    @Test
    fun `на телевизоре сайдбар есть при любой ширине`() {
        // Пульт не попадает по мелким целям, а нижняя панель на ТВ требует
        // прохода фокусом через весь экран.
        for (width in listOf(320, 600, 960, 1920)) {
            assertTrue(
                "$width dp на ТВ без сайдбара",
                LtBreakpoints.hasPermanentSidebar(width, isTv = true)
            )
        }
    }

    // --- Цели нажатия -----------------------------------------------------

    @Test
    fun `минимальная цель нажатия не ниже требования Material`() {
        assertTrue(
            "цель нажатия ${LtTap.min} меньше 48dp: палец будет промахиваться",
            LtTap.min.value >= 48f
        )
    }

    @Test
    fun `видимый кружок меньше области нажатия`() {
        // Кнопки поверх превью нельзя увеличивать: они закроют кадр. Область
        // растёт, рисунок остаётся прежним.
        assertTrue(
            "видимый размер ${LtTap.visual} не меньше области ${LtTap.min}",
            LtTap.visual.value < LtTap.min.value
        )
    }

    // --- Шкала текста -----------------------------------------------------

    @Test
    fun `шкала текста возрастает`() {
        val scale = listOf(LtType.xs, LtType.sm, LtType.md, LtType.lg, LtType.xl, LtType.xxl)
        for (i in 1 until scale.size) {
            assertTrue(
                "ступень ${scale[i]} не больше предыдущей ${scale[i - 1]}",
                scale[i].value > scale[i - 1].value
            )
        }
    }

    @Test
    fun `самый мелкий текст не меньше 12sp`() {
        // Дефолтный labelSmall в Material — 11sp, и подписи нижней панели были
        // набраны ещё мельче, 10sp.
        assertTrue("${LtType.xs} мельче 12sp", LtType.xs.value >= 12f)
    }

    @Test
    fun `шкала совпадает с веб-версией`() {
        // Токены --lt-text-* из static/css/ui.css. Расхождение означает, что
        // приложение и браузер показывают разный размер текста.
        assertEquals(12f, LtType.xs.value, 0f)
        assertEquals(13f, LtType.sm.value, 0f)
        assertEquals(14f, LtType.md.value, 0f)
        assertEquals(15f, LtType.lg.value, 0f)
        assertEquals(16f, LtType.xl.value, 0f)
        assertEquals(20f, LtType.xxl.value, 0f)
    }

    @Test
    fun `подписи в типографике не мельче нижней ступени шкалы`() {
        // MaterialTheme раньше получал только цвета, и MaterialTheme.typography
        // отдавал дефолты Material — в том числе labelSmall на 11sp.
        val slots = listOf(
            "labelSmall" to LtTypography.labelSmall,
            "bodySmall" to LtTypography.bodySmall,
            "bodyMedium" to LtTypography.bodyMedium,
            "titleMedium" to LtTypography.titleMedium,
            "titleLarge" to LtTypography.titleLarge
        )
        for ((name, style) in slots) {
            assertTrue("$name без размера", style.fontSize.value > 0f)
            assertTrue(
                "$name (${style.fontSize}) мельче ${LtType.xs}",
                style.fontSize.value >= LtType.xs.value
            )
        }
    }

    @Test
    fun `межстрочное расстояние задано и больше размера шрифта`() {
        // Без lineHeight заголовок в две строки слипается.
        val slots = listOf(
            "bodyMedium" to LtTypography.bodyMedium,
            "titleMedium" to LtTypography.titleMedium,
            "titleLarge" to LtTypography.titleLarge
        )
        for ((name, style) in slots) {
            assertTrue("$name без lineHeight", style.lineHeight.value > 0f)
            assertTrue(
                "$name: lineHeight ${style.lineHeight} не больше кегля ${style.fontSize}",
                style.lineHeight.value > style.fontSize.value
            )
        }
    }

    // --- Скругления и отступы --------------------------------------------

    @Test
    fun `скругления совпадают с веб-версией`() {
        // Токены --lt-radius-* из static/css/ui.css.
        assertEquals(8f, LtRadius.sm.value, 0f)
        assertEquals(12f, LtRadius.md.value, 0f)
        assertEquals(16f, LtRadius.lg.value, 0f)
    }

    @Test
    fun `отступы идут шагом по четыре`() {
        // Шаг 4dp — сетка Material, она же --lt-space-* в вебе.
        val steps = listOf(LtSpace.x1, LtSpace.x2, LtSpace.x3, LtSpace.x4, LtSpace.x5, LtSpace.x6, LtSpace.x8)
        for (step in steps) {
            assertEquals("$step не кратен 4dp", 0f, step.value % 4f, 0f)
        }
        for (i in 1 until steps.size) {
            assertTrue("$  ${steps[i]} не больше предыдущего", steps[i].value > steps[i - 1].value)
        }
    }

    @Test
    fun `формы Material заполнены значениями шкалы`() {
        // Пустой Shapes означал бы возврат к дефолтам Material, из-за которых
        // радиусы в интерфейсе разъезжались.
        assertNotNull(LtShapes.small)
        assertNotNull(LtShapes.medium)
        assertNotNull(LtShapes.large)
    }
}
