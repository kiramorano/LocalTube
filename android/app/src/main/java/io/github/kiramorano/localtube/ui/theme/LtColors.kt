package io.github.kiramorano.localtube.ui.theme

import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp

/**
 * Цвета и размеры один в один из веб-версии (templates/index.html), чтобы
 * приложение выглядело так же, как LocalTube в браузере.
 */
@Immutable
data class LtColors(
    val background: Color,
    val textPrimary: Color,
    val textSecondary: Color,
    val border: Color,
    val iconInactive: Color,
    val buttonBg: Color,
    val buttonHover: Color,
    val searchBg: Color,
    val modalBg: Color,
    val brandRed: Color = Color(0xFFFF0000),
    /** Фон превью до загрузки картинки: как .video-thumb в вебе. */
    val thumbPlaceholder: Color = Color(0xFF272727),
    val favoriteGold: Color = Color(0xFFFFD700),
    /**
     * Текст поверх акцентной заливки.
     *
     * Отдельным полем, потому что белый годится не всякому акценту: у Midnight
     * и Glass акцент светло-синий, и белая подпись на нём почти не читается
     * (в вебе это --lt-accent-contrast).
     */
    val onAccent: Color = Color.White,
    /**
     * Фон карточки видео, если тема его задаёт.
     *
     * В dark и light карточка сливается с фоном страницы, как в вебе. У Midnight
     * это отдельный слой (#151a24), у Glass и Aero — полупрозрачное стекло.
     */
    val cardBg: Color = Color.Transparent
)

/**
 * Второстепенный текст на тёмных темах: почти белый, не серый #AAA.
 * Полностью тот же белый, что у заголовков, слил бы иерархию.
 */
private val OnDarkSecondary = Color(0xFFE6E6E6)

/** --yt-* из :root[data-theme="dark"]. */
val DarkLtColors = LtColors(
    background = Color(0xFF0F0F0F),
    textPrimary = Color.White,
    textSecondary = OnDarkSecondary,
    border = Color(0xFF3F3F3F),
    iconInactive = Color.White,
    buttonBg = Color(0xFF272727),
    buttonHover = Color(0xFF3F3F3F),
    searchBg = Color(0xFF121212),
    modalBg = Color(0xFF212121)
)

/** --yt-* из :root[data-theme="light"]. */
val LightLtColors = LtColors(
    background = Color(0xFFFFFFFF),
    textPrimary = Color(0xFF0F0F0F),
    textSecondary = Color(0xFF606060),
    border = Color(0xFFE5E5E5),
    iconInactive = Color(0xFF030303),
    buttonBg = Color(0xFFF2F2F2),
    buttonHover = Color(0xFFE0E0E0),
    searchBg = Color(0xFFF8F8F8),
    modalBg = Color(0xFFFFFFFF),
    thumbPlaceholder = Color(0xFFE5E5E5)
)

/**
 * Midnight: тёмная тема с холодным синеватым подтоном.
 *
 * Значения из static/css/themes/midnight.css. Прозрачности здесь нет — только
 * слои поверхностей, поэтому карточке нужен свой фон (в dark его нет).
 */
val MidnightLtColors = LtColors(
    background = Color(0xFF0B0E14),
    textPrimary = Color.White,
    textSecondary = OnDarkSecondary,
    border = Color(0xFF262D3B),
    iconInactive = Color.White,
    buttonBg = Color(0xFF1D2432),
    buttonHover = Color(0xFF27303F),
    searchBg = Color(0xFF11161F),
    modalBg = Color(0xFF1A2030),
    // --lt-accent темы, а не бренд-красный: им набраны кнопки и фокус.
    brandRed = Color(0xFF62B6FF),
    onAccent = Color(0xFF08111C),
    thumbPlaceholder = Color(0xFF151A24),
    cardBg = Color(0xFF151A24)
)

/**
 * Glass: тёмное стекло на градиентных пятнах.
 *
 * Значения из static/css/themes/glass.css. Поверхности полупрозрачные, поэтому
 * фон рисуется градиентом под всем интерфейсом (Theme.kt), а панели пропускают
 * его сквозь себя. Настоящего размытия (backdrop-filter) в Compose нет, но при
 * непрозрачности 7-17% разница почти незаметна.
 */
val GlassLtColors = LtColors(
    background = Color(0xFF0D1220),
    textPrimary = Color.White,
    textSecondary = OnDarkSecondary,
    border = Color(0x29FFFFFF),
    iconInactive = Color.White,
    buttonBg = Color(0x1AFFFFFF),
    buttonHover = Color(0x2BFFFFFF),
    searchBg = Color(0x17FFFFFF),
    // Модалка почти непрозрачная: сквозь неё не должен читаться текст под ней.
    modalBg = Color(0xF5171E30),
    brandRed = Color(0xFF7CC4FF),
    onAccent = Color(0xFF071120),
    thumbPlaceholder = Color(0x14FFFFFF),
    cardBg = Color(0x12FFFFFF)
)

/**
 * Frutiger Aero: стеклянные панели на голубом градиенте.
 *
 * Текст здесь тёмный, как у светлой темы. Белый на #B3D9F0 даёт контраст
 * около 1.5 и не читается — это та же ловушка, из‑за которой в вебе
 * пропали подписи нижней панели.
 */
val AeroLtColors = LtColors(
    background = Color(0xFFB3D9F0),
    textPrimary = Color(0xFF0B2942),
    textSecondary = Color(0xFF14507A),
    border = Color(0x66FFFFFF),
    iconInactive = Color(0xFF0B2942),
    buttonBg = Color(0x59FFFFFF),
    buttonHover = Color(0x8CFFFFFF),
    searchBg = Color(0x73FFFFFF),
    modalBg = Color(0xE6FFFFFF),
    // Акцент этой темы — синий вместо красного. Был светлый #0EA5E9, но он
    // работает только как заливка декоративных элементов: белый текст на нём
    // давал контраст 2.77, а сам цвет на голубом фоне темы — 1.86. Между тем
    // этим же цветом набраны ссылки («О канале», имя автора под плеером) и
    // залиты кнопки с белой подписью. Тёмный оттенок той же гаммы даёт 7.56 на
    // белом тексте и 5.08 на фоне темы.
    brandRed = Color(0xFF075985),
    thumbPlaceholder = Color(0x4DFFFFFF),
    // Стекло карточки: в вебе rgba(255,255,255,0.12) поверх обоев.
    cardBg = Color(0x1FFFFFFF)
)

/** Размеры из веб-версии: те же 56px шапки и 240px сайдбара. */
@Immutable
data class LtSizes(
    val headerHeight: Dp = 56.dp,
    val sidebarWidth: Dp = 240.dp,
    /** --video-card-min-width, уменьшенное для мобильных экранов. */
    val videoCardMinWidth: Dp = 310.dp,
    val shortCardWidth: Dp = 210.dp,
    val gridGap: Dp = 20.dp,
    /**
     * Отступ от краёв экрана. На телевизорах края обрезаются (overscan), и
     * крайние карточки без запаса уходят за границу картинки.
     */
    val screenPadding: Dp = 0.dp,
    val cornerRadius: Dp = 12.dp,
    val titleSize: TextUnit = 16.sp,
    val metaSize: TextUnit = 14.sp,
    val titleLineHeight: TextUnit = 22.sp
)

val LocalLtColors = staticCompositionLocalOf { DarkLtColors }
val LocalLtSizes = staticCompositionLocalOf { LtSizes() }

/** Короткий доступ: LtTheme.colors и LtTheme.sizes. */
object LtTheme {
    val colors: LtColors
        @Composable get() = LocalLtColors.current
    val sizes: LtSizes
        @Composable get() = LocalLtSizes.current
}
