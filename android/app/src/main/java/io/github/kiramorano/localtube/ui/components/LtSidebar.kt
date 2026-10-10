package io.github.kiramorano.localtube.ui.components

import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.automirrored.filled.PlaylistPlay
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.kiramorano.localtube.data.Author
import io.github.kiramorano.localtube.ui.theme.LtRadius
import io.github.kiramorano.localtube.ui.theme.LtSpace
import io.github.kiramorano.localtube.ui.theme.LtTap
import io.github.kiramorano.localtube.ui.theme.LtTheme
import io.github.kiramorano.localtube.ui.theme.LtType

data class SidebarEntry(val route: String, val label: String, val icon: ImageVector)

/** Разделы в том же порядке, что в сайдбаре веб-версии. */
val sidebarEntries = listOf(
    SidebarEntry("home", "Главная", Icons.Filled.Home),
    SidebarEntry("shorts_feed", "Shorts", Icons.Filled.PlayCircle),
    SidebarEntry("favorites", "Избранное", Icons.Filled.Star),
    SidebarEntry("collections", "Мои плейлисты", Icons.AutoMirrored.Filled.PlaylistPlay),
    SidebarEntry("history", "История", Icons.Filled.History),
    SidebarEntry("downloads", "Очередь", Icons.Filled.Download),
    SidebarEntry("myvideos", "Мои видео", Icons.Filled.VideoLibrary)
)

/**
 * Боковое меню как в браузере: разделы, список каналов библиотеки, блок
 * скрытых каналов и настройки внизу. Ширина 240dp — как --yt-sidebar-width.
 */
@Composable
fun LtSidebar(
    currentRoute: String?,
    authors: List<Author>,
    hiddenChannels: List<String>,
    onNavigate: (String) -> Unit,
    onOpenChannel: (String) -> Unit,
    onUnhideChannel: (String) -> Unit,
    onImportClick: () -> Unit,
    onDonateClick: () -> Unit,
    onDonateUnavailable: () -> Unit,
    modifier: Modifier = Modifier
) {
    val colors = LtTheme.colors
    Column(
        modifier
            .width(LtTheme.sizes.sidebarWidth)
            .fillMaxHeight()
            .background(colors.background)
            .verticalScroll(rememberScrollState())
            .padding(vertical = 12.dp, horizontal = 8.dp)
    ) {
        sidebarEntries.forEach { entry ->
            SidebarItem(
                label = entry.label,
                icon = entry.icon,
                selected = currentRoute == entry.route,
                onClick = { onNavigate(entry.route) }
            )
        }

        SidebarDivider()

        if (authors.isNotEmpty()) {
            SidebarTitle("Каналы")
            authors.forEach { author ->
                SidebarChannel(author = author, onClick = { onOpenChannel(author.name) })
            }
            SidebarDivider()
        }

        SidebarTitle("Скрытые каналы")
        if (hiddenChannels.isEmpty()) {
            Text(
                "Нет скрытых каналов",
                color = colors.textSecondary,
                fontSize = 13.sp,
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
            )
        } else {
            hiddenChannels.forEach { name ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        name,
                        color = colors.textPrimary,
                        fontSize = 13.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f)
                    )
                    // ButtonDefaults.MinHeight — 40dp, до нормы Material не
                    // дотягивает.
                    TextButton(
                        onClick = { onUnhideChannel(name) },
                        modifier = Modifier.heightIn(min = LtTap.min)
                    ) {
                        Text("Показать", fontSize = LtType.xs, color = colors.brandRed)
                    }
                }
            }
        }

        SidebarDivider()
        SidebarItem(
            label = "Настройки",
            icon = Icons.Filled.Settings,
            selected = currentRoute == "settings",
            onClick = { onNavigate("settings") }
        )
        SidebarItem(
            label = "Импорт канала",
            icon = Icons.Filled.CloudUpload,
            selected = false,
            onClick = { onImportClick() }
        )
        // Поддержка автора: как в веб-версии ссылка в сайдбаре и в настройках.
        // На ТВ браузера может не быть — тогда коллбек сообщает об этом, и
        // AppRoot показывает QR или направляет в настройки.
        val ctx = LocalContext.current
        SidebarItem(
            label = "Поддержать автора",
            icon = Icons.Filled.Star,
            selected = false,
            onClick = {
                if (openExternalLink(ctx, DONATE_URL)) {
                    onDonateClick()
                } else {
                    onDonateUnavailable()
                }
            }
        )
    }
}

@Composable
private fun SidebarItem(
    label: String,
    icon: ImageVector,
    selected: Boolean,
    onClick: () -> Unit
) {
    val colors = LtTheme.colors
    // Подсветка фокуса: на ТВ сайдбар — основная навигация, и без рамки
    // непонятно, на каком пункте стоит курсор.
    val interactionSource = remember { MutableInteractionSource() }
    val focused by interactionSource.collectIsFocusedAsState()
    Row(
        Modifier
            .fillMaxWidth()
            // Было 44dp (иконка 24dp плюс по 10dp): чуть ниже нормы Material.
            .heightIn(min = LtTap.min)
            .clip(RoundedCornerShape(LtRadius.sm))
            .tvFocusBorder(focused, colors.brandRed)
            .background(if (selected) colors.buttonHover else Color.Transparent)
            .clickable(
                interactionSource = interactionSource,
                indication = LocalIndication.current,
                onClick = onClick
            )
            .padding(horizontal = LtSpace.x3),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(LtSpace.x4)
    ) {
        Icon(icon, contentDescription = null, tint = colors.textPrimary, modifier = Modifier.size(24.dp))
        Text(
            label,
            color = colors.textPrimary,
            fontSize = 14.sp,
            fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
private fun SidebarChannel(author: Author, onClick: () -> Unit) {
    val colors = LtTheme.colors
    val interactionSource = remember { MutableInteractionSource() }
    val focused by interactionSource.collectIsFocusedAsState()
    Row(
        Modifier
            .fillMaxWidth()
            // Было 44dp (кружок 28dp плюс по 8dp).
            .heightIn(min = LtTap.min)
            .clip(RoundedCornerShape(LtRadius.sm))
            .tvFocusBorder(focused, colors.brandRed)
            .clickable(
                interactionSource = interactionSource,
                indication = LocalIndication.current,
                onClick = onClick
            )
            .padding(horizontal = LtSpace.x3),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(LtSpace.x4)
    ) {
        // Кружок 28dp с первой буквой: как в вебе.
        Box(
            Modifier
                .size(28.dp)
                .clip(CircleShape)
                .background(Color(0xFF8E24AA)),
            contentAlignment = Alignment.Center
        ) {
            if (author.avatar != null) {
                AsyncThumb(author.avatar, Modifier.fillMaxSize())
            } else {
                Text(
                    author.name.take(1).uppercase(),
                    color = Color.White,
                    fontSize = 12.sp
                )
            }
        }
        Text(
            author.name,
            color = colors.textPrimary,
            fontSize = 14.sp,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
private fun SidebarTitle(text: String) {
    Text(
        text,
        color = LtTheme.colors.textPrimary,
        fontSize = 16.sp,
        fontWeight = FontWeight.Medium,
        modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
    )
}

@Composable
private fun SidebarDivider() {
    Box(Modifier.padding(vertical = 12.dp)) {
        Box(
            Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(LtTheme.colors.border)
        )
    }
}
