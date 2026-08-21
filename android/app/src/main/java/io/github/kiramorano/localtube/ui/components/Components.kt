package io.github.kiramorano.localtube.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.painter.ColorPainter
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import io.github.kiramorano.localtube.data.Author
import io.github.kiramorano.localtube.data.Playlist
import io.github.kiramorano.localtube.data.VideoItem
import io.github.kiramorano.localtube.ui.theme.LocalIsAero
import io.github.kiramorano.localtube.ui.theme.LocalIsTv
import java.io.File

@Composable
fun AsyncThumb(
    path: String?,
    modifier: Modifier = Modifier,
    contentScale: ContentScale = ContentScale.Crop
) {
    val placeholder = ColorPainter(MaterialTheme.colorScheme.surfaceVariant)
    val model = remember(path) {
        path?.let { File(it) }
    }
    AsyncImage(
        model = ImageRequest.Builder(androidx.compose.ui.platform.LocalContext.current)
            .data(model)
            .crossfade(true)
            .build(),
        contentDescription = null,
        modifier = modifier,
        contentScale = contentScale,
        placeholder = placeholder,
        error = placeholder
    )
}

/** Длительность в формате 7:05 или 1:07:05. */
fun formatDuration(seconds: Long): String {
    if (seconds <= 0) return ""
    val h = seconds / 3600
    val m = (seconds % 3600) / 60
    val s = seconds % 60
    return if (h > 0) String.format("%d:%02d:%02d", h, m, s) else String.format("%d:%02d", m, s)
}

/** Дата публикации из формата yyyyMMdd в читаемый вид. */
fun formatUploadDate(raw: String): String {
    if (raw.length != 8 || raw.any { !it.isDigit() }) return ""
    val months = listOf(
        "янв", "фев", "мар", "апр", "мая", "июн",
        "июл", "авг", "сен", "окт", "ноя", "дек"
    )
    val month = raw.substring(4, 6).toIntOrNull() ?: return ""
    val day = raw.substring(6, 8).toIntOrNull() ?: return ""
    return "$day ${months.getOrElse(month - 1) { "" }} ${raw.substring(0, 4)}"
}

@Composable
fun VideoCard(
    v: VideoItem,
    onClick: () -> Unit,
    short: Boolean = false,
    isFavorite: Boolean = false,
    onToggleFavorite: (() -> Unit)? = null,
    onOpenChannel: (() -> Unit)? = null,
    onHideChannel: (() -> Unit)? = null,
    onDelete: (() -> Unit)? = null
) {
    val aero = LocalIsAero.current
    var menuOpen by remember { mutableStateOf(false) }
    Card(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (aero) MaterialTheme.colorScheme.surface.copy(alpha = 0.7f)
            else MaterialTheme.colorScheme.surface
        )
    ) {
        Box {
            AsyncThumb(
                path = v.thumb,
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(if (short) 9f / 16f else 16f / 9f)
            )
            if (v.durationSec > 0) {
                Text(
                    formatDuration(v.durationSec),
                    color = Color.White,
                    style = MaterialTheme.typography.labelSmall,
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .padding(6.dp)
                        .background(Color(0xCC000000), RoundedCornerShape(4.dp))
                        .padding(horizontal = 5.dp, vertical = 2.dp)
                )
            }
            if (onToggleFavorite != null) {
                IconButton(
                    onClick = onToggleFavorite,
                    modifier = Modifier.align(Alignment.TopEnd)
                ) {
                    Icon(
                        if (isFavorite) Icons.Filled.Star else Icons.Outlined.StarBorder,
                        contentDescription = if (isFavorite) "Убрать из избранного" else "В избранное",
                        tint = if (isFavorite) Color(0xFFFFD700) else Color.White
                    )
                }
            }
        }
        Row(
            Modifier
                .fillMaxWidth()
                .padding(start = 10.dp, end = 2.dp, top = 8.dp, bottom = 10.dp),
            verticalAlignment = Alignment.Top
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    v.title,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    buildString {
                        append(v.author)
                        val date = formatUploadDate(v.uploadDate)
                        if (date.isNotBlank()) append(" · $date")
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            if (onOpenChannel != null || onHideChannel != null || onDelete != null) {
                Box {
                    IconButton(onClick = { menuOpen = true }) {
                        Icon(Icons.Filled.MoreVert, contentDescription = "Ещё")
                    }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        onOpenChannel?.let {
                            DropdownMenuItem(
                                text = { Text("Открыть канал") },
                                onClick = { menuOpen = false; it() })
                        }
                        onHideChannel?.let {
                            DropdownMenuItem(
                                text = { Text("Скрыть канал") },
                                onClick = { menuOpen = false; it() })
                        }
                        onDelete?.let {
                            DropdownMenuItem(
                                text = { Text("Удалить видео") },
                                onClick = { menuOpen = false; it() })
                        }
                    }
                }
            }
        }
    }
}

/**
 * Сетка видео. Число колонок зависит от ширины: на телефоне одна-две, на
 * планшете и телевизоре больше — раньше было жёстко две на любом экране.
 */
@Composable
fun VideoGrid(
    items: List<VideoItem>,
    onOpen: (String) -> Unit,
    short: Boolean = false,
    favorites: Set<String> = emptySet(),
    onToggleFavorite: ((String) -> Unit)? = null,
    onOpenChannel: ((String) -> Unit)? = null,
    onHideChannel: ((String) -> Unit)? = null,
    onDelete: ((VideoItem) -> Unit)? = null,
    emptyText: String = "Здесь пока пусто"
) {
    if (items.isEmpty()) {
        EmptyBox(emptyText)
        return
    }
    val minWidth = if (short) 150.dp else if (LocalIsTv.current) 260.dp else 190.dp
    LazyVerticalGrid(
        columns = GridCells.Adaptive(minWidth),
        contentPadding = PaddingValues(12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        items(items, key = { it.id + it.source }) { v ->
            VideoCard(
                v = v,
                onClick = { onOpen(v.id) },
                short = short,
                isFavorite = favorites.contains(v.id),
                onToggleFavorite = onToggleFavorite?.let { cb -> { cb(v.id) } },
                onOpenChannel = onOpenChannel?.let { cb -> { cb(v.author) } },
                onHideChannel = onHideChannel?.let { cb -> { cb(v.author) } },
                onDelete = onDelete?.let { cb -> { cb(v) } }
            )
        }
    }
}

@Composable
fun AuthorsGrid(
    authors: List<Author>,
    onOpen: ((String) -> Unit)? = null
) {
    if (authors.isEmpty()) {
        EmptyBox("Каналов пока нет")
        return
    }
    LazyVerticalGrid(
        columns = GridCells.Adaptive(120.dp),
        contentPadding = PaddingValues(12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        items(authors, key = { it.name }) { a ->
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(enabled = onOpen != null) { onOpen?.invoke(a.name) }
                    .padding(6.dp)
            ) {
                Box(
                    Modifier
                        .size(72.dp)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.surfaceVariant),
                    contentAlignment = Alignment.Center
                ) {
                    if (a.avatar != null) {
                        AsyncThumb(a.avatar, Modifier.fillMaxSize())
                    } else {
                        Text(
                            a.name.take(1).uppercase(),
                            style = MaterialTheme.typography.titleLarge
                        )
                    }
                }
                Text(
                    a.name,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 6.dp)
                )
                if (a.videoCount > 0) {
                    Text(
                        "${a.videoCount} видео",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

@Composable
fun PlaylistsGrid(playlists: List<Playlist>, onOpen: (String) -> Unit) {
    if (playlists.isEmpty()) {
        EmptyBox("Плейлистов пока нет")
        return
    }
    LazyVerticalGrid(
        columns = GridCells.Adaptive(190.dp),
        contentPadding = PaddingValues(12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxSize()
    ) {
        items(playlists, key = { it.id }) { p ->
            Card(onClick = { onOpen(p.id) }, modifier = Modifier.fillMaxWidth()) {
                AsyncThumb(
                    p.thumbnail,
                    Modifier
                        .fillMaxWidth()
                        .aspectRatio(16f / 9f)
                )
                Column(Modifier.padding(10.dp)) {
                    Text(
                        p.title,
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis
                    )
                    Text(
                        "${p.uploader} · ${p.videoCount} видео",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1
                    )
                }
            }
        }
    }
}

@Composable
fun LoadingBox() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
fun ErrorBox(message: String, onRetry: (() -> Unit)? = null) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(message, color = MaterialTheme.colorScheme.error)
        if (onRetry != null) {
            TextButton(onClick = onRetry, modifier = Modifier.padding(top = 8.dp)) {
                Text("Повторить")
            }
        }
    }
}

@Composable
fun EmptyBox(text: String) {
    Box(
        Modifier
            .fillMaxSize()
            .padding(24.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(text, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Горизонтальная полка: используется для Shorts и рекомендаций. */
@Composable
fun VideoShelf(
    items: List<VideoItem>,
    onOpen: (String) -> Unit,
    short: Boolean = false
) {
    LazyRow(
        contentPadding = PaddingValues(horizontal = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        items(items, key = { it.id }) { v ->
            Box(Modifier.width(if (short) 140.dp else 220.dp)) {
                VideoCard(v = v, onClick = { onOpen(v.id) }, short = short)
            }
        }
    }
}

@Composable
fun SectionHeader(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.Bold,
        modifier = modifier.padding(horizontal = 14.dp, vertical = 8.dp)
    )
}

/** Рамка вокруг сфокусированного элемента: нужна для навигации пультом. */
fun Modifier.tvFocusBorder(focused: Boolean, color: Color): Modifier =
    if (focused) this.border(3.dp, color, RoundedCornerShape(10.dp)) else this
