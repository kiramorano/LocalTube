package io.github.kiramorano.localtube.ui.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import io.github.kiramorano.localtube.data.AppTheme

/** Признак темы Aero: панели становятся полупрозрачными поверх градиента. */
val LocalIsAero = staticCompositionLocalOf { false }

/**
 * Признак темы со стеклянными поверхностями (Glass, Aero).
 *
 * Отдельно от LocalIsAero: полупрозрачность нужна обеим темам, а голубой
 * градиент и радиус 20dp — только Aero.
 */
val LocalIsGlassy = staticCompositionLocalOf { false }

/** Признак телевизора: увеличенные отступы и подсветка фокуса. */
val LocalIsTv = staticCompositionLocalOf { false }

/**
 * Пороги ширины экрана.
 *
 * Раньше их было два в разных файлах: `compact` считался от 600dp в
 * MainActivity, а постоянный сайдбар включался от 720dp в AppRoot. В зазоре
 * 600-719dp (обычный 7-дюймовый планшет) получалось несогласованное состояние:
 * карточки уже «большие», 260dp, но переключаться между разделами всё ещё
 * приходилось нижней панелью, хотя места под сайдбар хватало.
 *
 * Границы совпадают с классами Material (compact < 600 <= medium < 840) и с
 * медиазапросами веб-версии, где мобильная раскладка живёт до 600px.
 */
object LtBreakpoints {
    /** Ниже — телефон: одна колонка разделов, нижняя панель. */
    const val COMPACT_MAX_DP = 600

    /** От этой ширины сайдбар помещается рядом с контентом. */
    const val SIDEBAR_MIN_DP = 600

    fun isCompact(widthDp: Int): Boolean = widthDp < COMPACT_MAX_DP

    /**
     * На телевизоре сайдбар нужен всегда: пульт не попадает по мелким целям, а
     * ширины там заведомо достаточно.
     */
    fun hasPermanentSidebar(widthDp: Int, isTv: Boolean): Boolean =
        isTv || widthDp >= SIDEBAR_MIN_DP
}

@Composable
fun LocalTubeTheme(
    theme: AppTheme = AppTheme.DARK,
    isTv: Boolean = false,
    compact: Boolean = false,
    content: @Composable () -> Unit
) {
    val lt = when (theme) {
        AppTheme.DARK -> DarkLtColors
        AppTheme.LIGHT -> LightLtColors
        AppTheme.MIDNIGHT -> MidnightLtColors
        AppTheme.GLASS -> GlassLtColors
        AppTheme.AERO -> AeroLtColors
    }

    // Material-схема выводится из тех же цветов: диалоги и системные
    // компоненты должны совпадать с остальным интерфейсом.
    val scheme = if (theme == AppTheme.LIGHT || theme == AppTheme.AERO) {
        lightColorScheme(
            primary = lt.brandRed,
            onPrimary = lt.onAccent,
            background = lt.background,
            onBackground = lt.textPrimary,
            surface = lt.background,
            onSurface = lt.textPrimary,
            surfaceVariant = lt.buttonBg,
            onSurfaceVariant = lt.textSecondary,
            outline = lt.border,
            outlineVariant = lt.border
        )
    } else {
        darkColorScheme(
            primary = lt.brandRed,
            onPrimary = lt.onAccent,
            background = lt.background,
            onBackground = lt.textPrimary,
            surface = lt.background,
            onSurface = lt.textPrimary,
            surfaceVariant = lt.buttonBg,
            onSurfaceVariant = lt.textSecondary,
            outline = lt.border,
            outlineVariant = lt.border
        )
    }

    val sizes = LtSizes(
        // На телефоне карточка во всю ширину: 310px как в вебе оставили бы
        // одну колонку с огромными отступами.
        videoCardMinWidth = if (compact) 170.dp else if (isTv) 300.dp else 260.dp,
        shortCardWidth = if (compact) 140.dp else if (isTv) 210.dp else 180.dp,
        gridGap = if (compact) 12.dp else 20.dp,
        // Запас под overscan: на ТВ телевизор обрезает до 5% по краям.
        screenPadding = if (isTv) 24.dp else 0.dp,
        // 16dp — --lt-radius-lg веб-версии (было 12dp, как у старой разметки).
        // Aero скругляет сильнее: там карточка выглядит стеклянной плиткой.
        cornerRadius = if (theme == AppTheme.AERO) 20.dp else 16.dp
    )

    // LocalContentColor задаёт цвет Text без явного color= : в Material 3
    // значение по умолчанию чёрное, и без него заголовки в Box (а не Surface)
    // оказались чёрными на чёмном фоне. Подбираем цвет основного текста темы.
    CompositionLocalProvider(
        LocalIsAero provides (theme == AppTheme.AERO),
        LocalIsGlassy provides (theme == AppTheme.AERO || theme == AppTheme.GLASS),
        LocalIsTv provides isTv,
        LocalLtColors provides lt,
        LocalLtSizes provides sizes,
        LocalContentColor provides lt.textPrimary
    ) {
        // Раньше передавались только цвета, поэтому больше восьмидесяти
        // обращений к MaterialTheme.typography.* отдавали дефолты Material,
        // ни с чем в проекте не согласованные.
        MaterialTheme(
            colorScheme = scheme,
            typography = LtTypography,
            shapes = LtShapes
        ) {
            // Фон рисуется здесь, под всем интерфейсом: у Glass и Aero панели
            // полупрозрачные и должны пропускать его сквозь себя.
            val background = Modifier
                .fillMaxSize()
                .then(
                    when (theme) {
                        AppTheme.AERO -> Modifier.background(
                            Brush.verticalGradient(
                                listOf(
                                    Color(0xFF7EC8F0),
                                    Color(0xFFB3E5FC),
                                    Color(0xFFD7F5E3)
                                )
                            )
                        )
                        // Два цветных пятна из веб-темы: синее сверху слева,
                        // сиреневое сверху справа (radial-gradient в glass.css).
                        AppTheme.GLASS -> Modifier
                            .background(lt.background)
                            .background(
                                Brush.linearGradient(
                                    0f to Color(0x474084FF),
                                    0.55f to Color(0x00000000),
                                    1f to Color(0x338C5AFF)
                                )
                            )
                        else -> Modifier.background(lt.background)
                    }
                )
            Box(background) { content() }
        }
    }
}
