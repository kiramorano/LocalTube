package io.github.kiramorano.localtube.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.kiramorano.localtube.R
import io.github.kiramorano.localtube.ui.theme.LtBreakpoints
import io.github.kiramorano.localtube.ui.theme.LtRadius
import io.github.kiramorano.localtube.ui.theme.LtSpace
import io.github.kiramorano.localtube.ui.theme.LtTap
import io.github.kiramorano.localtube.ui.theme.LtTheme
import io.github.kiramorano.localtube.ui.theme.LtType

/**
 * Шапка: логотип слева, поиск по центру (на широком экране — поле, на узком —
 * кружок), справа аватар. Высота 56dp, как --yt-header-height в вебе.
 *
 * Раньше справа стояли поиск, шестерёнка, имя и кружок — четыре цели в ряд,
 * все кроме поиска вели в настройки. На телефоне это сжималось в кашу.
 * Шестерёнка убрана: профиль и так открывает настройки, как в вебе по кружку.
 */
@Composable
fun LtHeader(
    onMenuClick: (() -> Unit)? = null,
    onSearchClick: () -> Unit = {},
    onSettingsClick: () -> Unit = {},
    onLogoClick: (() -> Unit)? = null,
    userName: String = "Гость",
    actions: @Composable (() -> Unit)? = null
) {
    val colors = LtTheme.colors
    val compact = LtBreakpoints.isCompact(LocalConfiguration.current.screenWidthDp)
    val initial = userName.trim().take(1).ifBlank { "Г" }.uppercase()

    Column(Modifier.fillMaxWidth().background(colors.background)) {
        Row(
            Modifier
                .fillMaxWidth()
                .height(LtTheme.sizes.headerHeight)
                .padding(horizontal = LtSpace.x2),
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (onMenuClick != null) {
                IconButton(onClick = onMenuClick) {
                    Icon(Icons.Filled.Menu, "Меню", tint = colors.iconInactive)
                }
            }
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .clip(RoundedCornerShape(LtRadius.sm))
                    .then(
                        if (onLogoClick != null) {
                            Modifier.clickable(onClick = onLogoClick)
                        } else {
                            Modifier
                        }
                    )
                    .padding(
                        start = if (onMenuClick == null) LtSpace.x3 else LtSpace.x1,
                        end = LtSpace.x2,
                        top = LtSpace.x1,
                        bottom = LtSpace.x1
                    )
            ) {
                Image(
                    painter = painterResource(R.drawable.ic_logo),
                    contentDescription = null,
                    // Знак квадратный (вьюпорт 24×24), поэтому и рамка квадратная.
                    // Растягивало его не это место, а intrinsic-размер 30dp×20dp
                    // в самом ic_logo.xml: ContentScale.Fit сохраняет пропорции
                    // intrinsic-размера, а не вьюпорта, и size() тут не помогал.
                    modifier = Modifier.size(28.dp)
                )
                Text(
                    "LocalTube",
                    color = colors.textPrimary,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    modifier = Modifier.padding(start = 8.dp)
                )
            }
            if (compact) {
                Spacer(Modifier.weight(1f))
                actions?.invoke()
                IconButton(onClick = onSearchClick) {
                    Icon(Icons.Filled.Search, "Поиск", tint = colors.iconInactive)
                }
            } else {
                Box(
                    Modifier
                        .weight(1f)
                        .padding(horizontal = LtSpace.x4)
                ) {
                    Row(
                        Modifier
                            .align(Alignment.Center)
                            .widthIn(max = 480.dp)
                            .fillMaxWidth()
                            .height(40.dp)
                            .clip(RoundedCornerShape(LtRadius.pill))
                            .background(colors.searchBg)
                            .border(1.dp, colors.border, RoundedCornerShape(LtRadius.pill))
                            .clickable(onClick = onSearchClick)
                            .padding(horizontal = LtSpace.x4)
                            .semantics {
                                role = Role.Button
                                contentDescription = "Поиск"
                            },
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            Icons.Filled.Search,
                            contentDescription = null,
                            tint = colors.textSecondary,
                            modifier = Modifier.size(18.dp)
                        )
                        Text(
                            "Поиск по библиотеке",
                            color = colors.textSecondary,
                            fontSize = LtType.md,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(start = LtSpace.x2)
                        )
                    }
                }
                actions?.invoke()
            }
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .height(LtTap.min)
                    .clip(RoundedCornerShape(LtRadius.pill))
                    .clickable(onClick = onSettingsClick)
                    .padding(horizontal = LtSpace.x2)
                    .semantics { contentDescription = "Настройки, $userName" }
            ) {
                if (!compact) {
                    Text(
                        userName,
                        color = colors.textPrimary,
                        fontSize = LtType.sm,
                        fontWeight = FontWeight.Medium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier
                            .widthIn(max = 120.dp)
                            .padding(end = 8.dp)
                    )
                }
                Box(
                    Modifier
                        .size(32.dp)
                        .clip(CircleShape)
                        .background(Color(0xFF8E24AA)),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        initial,
                        color = Color.White,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                }
            }
        }
        LtDivider()
    }
}

@Composable
fun LtDivider(modifier: Modifier = Modifier) {
    Box(
        modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(LtTheme.colors.border)
    )
}
