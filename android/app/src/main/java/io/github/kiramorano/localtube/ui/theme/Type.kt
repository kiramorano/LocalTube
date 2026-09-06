package io.github.kiramorano.localtube.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp

/**
 * Шкала текста. Те же ступени, что в вебе (--lt-text-* из static/css/ui.css),
 * чтобы приложение и браузер показывали одинаковые размеры.
 *
 * Раньше размеры стояли литералами по файлам: в интерфейсе одновременно
 * встречались 10, 12, 13, 14, 16 и 20sp, причём 10sp — подписи нижней панели,
 * которые на телефоне читаются с трудом. `MaterialTheme` при этом получал
 * только цвета, поэтому `MaterialTheme.typography.*` (а это больше восьмидесяти
 * обращений) отдавал дефолты Material, ни с чем в проекте не согласованные.
 */
object LtType {
    /** Подписи и мелкие пометки. Ниже опускаться нельзя: перестаёт читаться. */
    val xs: TextUnit = 12.sp
    /** Второстепенный текст: счётчики, даты. */
    val sm: TextUnit = 13.sp
    /** Основной текст интерфейса. */
    val md: TextUnit = 14.sp
    val lg: TextUnit = 15.sp
    /** Заголовки карточек. */
    val xl: TextUnit = 16.sp
    /** Заголовки разделов. */
    val xxl: TextUnit = 20.sp

    /** Множители межстрочного расстояния: --lt-leading-tight и --lt-leading. */
    const val LEADING_TIGHT = 1.3f
    const val LEADING = 1.45f
}

/** Межстрочное расстояние от размера шрифта: в вебе это безразмерный множитель. */
private fun TextUnit.leading(ratio: Float): TextUnit = (value * ratio).sp

/**
 * Слоты Material заполняются шкалой LtType.
 *
 * Слоты выбраны по тому, как они уже используются в экранах, чтобы правка не
 * меняла вид случайным образом: `bodySmall` — второстепенный текст,
 * `bodyMedium` — основной, `titleMedium` — заголовок карточки,
 * `titleLarge` — заголовок раздела.
 */
val LtTypography = Typography(
    titleLarge = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = LtType.xxl,
        lineHeight = LtType.xxl.leading(LtType.LEADING_TIGHT)
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Medium,
        fontSize = LtType.xl,
        lineHeight = LtType.xl.leading(LtType.LEADING_TIGHT)
    ),
    titleSmall = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Medium,
        fontSize = LtType.md,
        lineHeight = LtType.md.leading(LtType.LEADING_TIGHT)
    ),
    bodyLarge = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = LtType.xl,
        lineHeight = LtType.xl.leading(LtType.LEADING)
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = LtType.md,
        lineHeight = LtType.md.leading(LtType.LEADING)
    ),
    bodySmall = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = LtType.sm,
        lineHeight = LtType.sm.leading(LtType.LEADING)
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Medium,
        fontSize = LtType.md,
        lineHeight = LtType.md.leading(LtType.LEADING_TIGHT)
    ),
    labelMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Medium,
        fontSize = LtType.sm,
        lineHeight = LtType.sm.leading(LtType.LEADING_TIGHT)
    ),
    // Дефолтный labelSmall в Material — 11sp. Подписи нижней панели набраны
    // именно им, а 11sp на телефоне уже на грани читаемости.
    labelSmall = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Medium,
        fontSize = LtType.xs,
        lineHeight = LtType.xs.leading(LtType.LEADING_TIGHT)
    )
)
