package io.github.kiramorano.localtube.ui.theme

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createComposeRule
import io.github.kiramorano.localtube.data.AppTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Цвет текста по умолчанию внутри темы.
 *
 * Здесь ловится конкретный баг: название видео под плеером (PlayerScreen) и
 * название канала на его странице (ChannelScreen) заданы как Text без явного
 * color. Такой текст берёт LocalContentColor, а его дефолт в Material 3 —
 * чёрный. Интерфейс приложения рисуется в Box, а не в Surface, поэтому подменить
 * цвет было нечему: на тёмных темах заголовки выходили чёрными на чёрном.
 *
 * Тест проверяет не палитру (её уже проверяет ColorContrastTest), а именно то,
 * что тема раздаёт цвет наследуемым текстам.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class ContentColorTest {

    @get:Rule
    val rule = createComposeRule()

    /**
     * Читает LocalContentColor сразу для всех тем.
     *
     * setContent можно вызвать только один раз на тест, поэтому все темы
     * складываются в одну композицию, а не проверяются в цикле с перезапуском.
     */
    private fun contentColors(): Map<AppTheme, Color> {
        val seen = mutableMapOf<AppTheme, Color>()
        rule.setContent {
            Column {
                AppTheme.entries.forEach { theme ->
                    LocalTubeTheme(theme = theme) {
                        seen[theme] = LocalContentColor.current
                    }
                }
            }
        }
        rule.waitForIdle()
        assertEquals("прочитаны не все темы", AppTheme.entries.size, seen.size)
        return seen
    }

    @Test
    fun `тёмные темы наследуют белый текст`() {
        // Именно это раньше не работало: заголовки без явного color оказывались
        // чёрными. Белый здесь — не косметика, а условие читаемости.
        val colors = contentColors()
        listOf(AppTheme.DARK, AppTheme.MIDNIGHT, AppTheme.GLASS).forEach { theme ->
            assertEquals("$theme", Color.White, colors.getValue(theme))
        }
    }

    @Test
    fun `светлая тема наследует тёмный текст`() {
        val c = contentColors().getValue(AppTheme.LIGHT)
        assertTrue("светлая тема должна быть тёмной по тексту: $c", c.luminance() < 0.2f)
    }

    @Test
    fun `ни одна тема не оставляет чёрный текст на тёмном фоне`() {
        // Обобщение бага: цвет по умолчанию обязан быть контрастным к фону
        // темы, какой бы тема ни была.
        val colors = contentColors()
        AppTheme.entries.forEach { theme ->
            val ratio = contrast(colors.getValue(theme), paletteOf(theme).background)
            assertTrue("$theme: контраст текста по умолчанию $ratio", ratio >= 4.5)
        }
    }

    @Test
    fun `цвет по умолчанию совпадает с textPrimary темы`() {
        // Заголовки должны быть того же цвета, что и остальной основной текст:
        // иначе на одном экране получится два разных «основных» цвета.
        val colors = contentColors()
        AppTheme.entries.forEach { theme ->
            assertEquals("$theme", paletteOf(theme).textPrimary, colors.getValue(theme))
        }
    }

    private fun paletteOf(theme: AppTheme): LtColors = when (theme) {
        AppTheme.DARK -> DarkLtColors
        AppTheme.LIGHT -> LightLtColors
        AppTheme.MIDNIGHT -> MidnightLtColors
        AppTheme.GLASS -> GlassLtColors
        AppTheme.AERO -> AeroLtColors
    }

    private fun Color.luminance(): Float {
        fun ch(v: Float): Float =
            if (v <= 0.03928f) v / 12.92f else Math.pow(((v + 0.055f) / 1.055f).toDouble(), 2.4).toFloat()
        return 0.2126f * ch(red) + 0.7152f * ch(green) + 0.0722f * ch(blue)
    }

    private fun contrast(fg: Color, bg: Color): Double {
        val l1 = fg.luminance().toDouble()
        val l2 = bg.luminance().toDouble()
        val hi = maxOf(l1, l2)
        val lo = minOf(l1, l2)
        return (hi + 0.05) / (lo + 0.05)
    }
}
