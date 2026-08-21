package io.github.kiramorano.localtube.ui.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import io.github.kiramorano.localtube.data.AppTheme

private val DarkColors = darkColorScheme(
    primary = Color(0xFFFF4040),
    onPrimary = Color(0xFFFFFFFF),
    secondary = Color(0xFF90A4AE),
    background = Color(0xFF0F0F0F),
    onBackground = Color(0xFFF1F1F1),
    surface = Color(0xFF1E1E1E),
    onSurface = Color(0xFFF1F1F1),
    surfaceVariant = Color(0xFF2A2A2A),
    onSurfaceVariant = Color(0xFFAAAAAA)
)

private val LightColors = lightColorScheme(
    primary = Color(0xFFCC0000),
    onPrimary = Color(0xFFFFFFFF),
    secondary = Color(0xFF546E7A),
    background = Color(0xFFFFFFFF),
    onBackground = Color(0xFF0F0F0F),
    surface = Color(0xFFF9F9F9),
    onSurface = Color(0xFF0F0F0F),
    surfaceVariant = Color(0xFFE8E8E8),
    onSurfaceVariant = Color(0xFF606060)
)

/**
 * Frutiger Aero: стеклянные панели на голубом градиенте — та же тема, что в
 * веб-версии. Полупрозрачные поверхности поверх фонового градиента.
 */
private val AeroColors = lightColorScheme(
    primary = Color(0xFF0EA5E9),
    onPrimary = Color(0xFFFFFFFF),
    secondary = Color(0xFF34D399),
    background = Color(0xFFB3D9F0),
    onBackground = Color(0xFF0B2942),
    surface = Color(0xCCFFFFFF),
    onSurface = Color(0xFF0B2942),
    surfaceVariant = Color(0x99FFFFFF),
    onSurfaceVariant = Color(0xFF14507A),
    outline = Color(0x66FFFFFF)
)

/** Признак темы Aero: экраны добавляют полупрозрачность поверх градиента. */
val LocalIsAero = staticCompositionLocalOf { false }

/** Признак телевизора: увеличенные отступы и подсветка фокуса. */
val LocalIsTv = staticCompositionLocalOf { false }

@Composable
fun LocalTubeTheme(
    theme: AppTheme = AppTheme.DARK,
    isTv: Boolean = false,
    content: @Composable () -> Unit
) {
    val colors = when (theme) {
        AppTheme.DARK -> DarkColors
        AppTheme.LIGHT -> LightColors
        AppTheme.AERO -> AeroColors
    }
    CompositionLocalProvider(
        LocalIsAero provides (theme == AppTheme.AERO),
        LocalIsTv provides isTv
    ) {
        MaterialTheme(colorScheme = colors) {
            if (theme == AppTheme.AERO) {
                Box(
                    Modifier
                        .fillMaxSize()
                        .background(
                            Brush.verticalGradient(
                                listOf(
                                    Color(0xFF7EC8F0),
                                    Color(0xFFB3E5FC),
                                    Color(0xFFD7F5E3)
                                )
                            )
                        )
                ) { content() }
            } else {
                content()
            }
        }
    }
}
