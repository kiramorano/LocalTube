package io.github.kiramorano.localtube.ui.theme

import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Контраст цветов темы.
 *
 * Повод конкретный: в веб-версии нижняя панель темы Frutiger Aero оказалась
 * белым текстом на светлом стекле — контраст 1.03 вместо 4.5, надписи не
 * читались вовсе. Палитры приложения собраны из тех же значений, поэтому
 * проверяем их числом, а не на глаз: скриншот такую ошибку показывает, но
 * только если в него посмотреть.
 *
 * Порог 4.5:1 — требование WCAG AA для основного текста, 3:1 — для крупного и
 * для границ элементов управления.
 */
class ColorContrastTest {

    private companion object {
        const val AA_TEXT = 4.5
        const val AA_LARGE = 3.0
    }

    /** Относительная яркость по WCAG 2.1. */
    private fun luminance(color: Long): Double {
        fun channel(v: Int): Double {
            val s = v / 255.0
            return if (s <= 0.03928) s / 12.92 else Math.pow((s + 0.055) / 1.055, 2.4)
        }
        val r = channel(((color shr 16) and 0xFF).toInt())
        val g = channel(((color shr 8) and 0xFF).toInt())
        val b = channel((color and 0xFF).toInt())
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }

    /**
     * Полупрозрачный цвет накладывается на подложку: у Aero панели заданы как
     * белый с альфой, и без смешивания контраст считался бы от чистого белого.
     */
    private fun flatten(color: Long, background: Long): Long {
        val alpha = ((color shr 24) and 0xFF) / 255.0
        if (alpha >= 1.0) return color and 0xFFFFFF
        fun mix(shift: Int): Long {
            val fg = (color shr shift) and 0xFF
            val bg = (background shr shift) and 0xFF
            return Math.round(fg * alpha + bg * (1 - alpha))
        }
        return (mix(16) shl 16) or (mix(8) shl 8) or mix(0)
    }

    private fun contrast(foreground: Long, background: Long): Double {
        val bg = background and 0xFFFFFF
        val fg = flatten(foreground, bg)
        val l1 = luminance(fg)
        val l2 = luminance(bg)
        val lighter = maxOf(l1, l2)
        val darker = minOf(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)
    }

    private val palettes = listOf(
        "dark" to DarkLtColors,
        "light" to LightLtColors,
        "midnight" to MidnightLtColors,
        "glass" to GlassLtColors,
        "aero" to AeroLtColors
    )

    /** Цвет из Compose обратно в число: сравнивать удобнее в целых. */
    private fun argb(color: androidx.compose.ui.graphics.Color): Long {
        val a = Math.round(color.alpha * 255).toLong()
        val r = Math.round(color.red * 255).toLong()
        val g = Math.round(color.green * 255).toLong()
        val b = Math.round(color.blue * 255).toLong()
        return (a shl 24) or (r shl 16) or (g shl 8) or b
    }

    @Test
    fun `основной текст читается на фоне темы`() {
        for ((name, palette) in palettes) {
            val ratio = contrast(argb(palette.textPrimary), argb(palette.background))
            assertTrue(
                "$name: основной текст на фоне даёт %.2f, нужно $AA_TEXT".format(ratio),
                ratio >= AA_TEXT
            )
        }
    }

    @Test
    fun `второстепенный текст читается на фоне темы`() {
        // Даты, счётчики просмотров, метаданные под заголовком.
        for ((name, palette) in palettes) {
            val ratio = contrast(argb(palette.textSecondary), argb(palette.background))
            assertTrue(
                "$name: второстепенный текст даёт %.2f, нужно $AA_TEXT".format(ratio),
                ratio >= AA_TEXT
            )
        }
    }

    @Test
    fun `текст читается на кнопках`() {
        // Кнопка берёт фон buttonBg, а текст наследует textPrimary: в Aero фон
        // полупрозрачный, поэтому смешивается с подложкой темы.
        for ((name, palette) in palettes) {
            val bg = flatten(argb(palette.buttonBg), argb(palette.background))
            val ratio = contrast(argb(palette.textPrimary), bg)
            assertTrue(
                "$name: текст на кнопке даёт %.2f, нужно $AA_TEXT".format(ratio),
                ratio >= AA_TEXT
            )
        }
    }

    @Test
    fun `текст читается в модальных окнах`() {
        for ((name, palette) in palettes) {
            val bg = flatten(argb(palette.modalBg), argb(palette.background))
            val ratio = contrast(argb(palette.textPrimary), bg)
            assertTrue(
                "$name: текст в окне даёт %.2f, нужно $AA_TEXT".format(ratio),
                ratio >= AA_TEXT
            )
        }
    }

    @Test
    fun `текст читается на подсвеченном пункте меню`() {
        // Активный пункт сайдбара и пилюля выбранного пункта нижней панели
        // залиты buttonHover: именно на этом месте в вебе текст пропадал.
        for ((name, palette) in palettes) {
            val bg = flatten(argb(palette.buttonHover), argb(palette.background))
            val ratio = contrast(argb(palette.textPrimary), bg)
            assertTrue(
                "$name: текст на подсветке даёт %.2f, нужно $AA_TEXT".format(ratio),
                ratio >= AA_TEXT
            )
        }
    }

    @Test
    fun `неактивный пункт панели отличим от фона`() {
        // Подписи невыбранных пунктов набраны textSecondary поверх фона панели.
        for ((name, palette) in palettes) {
            val ratio = contrast(argb(palette.textSecondary), argb(palette.background))
            assertTrue(
                "$name: неактивный пункт даёт %.2f, нужно $AA_LARGE".format(ratio),
                ratio >= AA_LARGE
            )
        }
    }

    @Test
    fun `иконки видны на фоне темы`() {
        for ((name, palette) in palettes) {
            val ratio = contrast(argb(palette.iconInactive), argb(palette.background))
            assertTrue(
                "$name: иконки дают %.2f, нужно $AA_LARGE".format(ratio),
                ratio >= AA_LARGE
            )
        }
    }

    @Test
    fun `подпись на акценте читается`() {
        // Кнопки с заливкой primary берут onAccent, а не всегда белый:
        // у Midnight и Glass акцент светло-синий, и белая подпись на нём
        // не читается (в теме это --lt-accent-contrast).
        for ((name, palette) in palettes) {
            val ratio = contrast(argb(palette.onAccent), argb(palette.brandRed))
            assertTrue(
                "$name: подпись на акценте даёт %.2f, нужно $AA_LARGE".format(ratio),
                ratio >= AA_LARGE
            )
        }
    }

    @Test
    fun `расчёт контраста согласуется с известными значениями`() {
        // Проверка самой проверки: без неё тест мог бы всё пропускать.
        assertTrue("чёрное на белом должно давать 21", contrast(0xFF000000, 0xFFFFFF) > 20.9)
        assertTrue("белое на белом должно давать 1", contrast(0xFFFFFFFF, 0xFFFFFF) < 1.01)
        // Прозрачный белый поверх белого фона остаётся белым: контраст 1.
        assertTrue(
            "полупрозрачный белый на белом должен давать 1",
            contrast(0x80FFFFFF, 0xFFFFFF) < 1.01
        )
    }
}
