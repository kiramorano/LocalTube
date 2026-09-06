package io.github.kiramorano.localtube.ui.components

import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentHeight
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
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import io.github.kiramorano.localtube.data.Author
import io.github.kiramorano.localtube.data.Playlist
import io.github.kiramorano.localtube.data.VideoItem
import io.github.kiramorano.localtube.ui.theme.LocalIsAero
import io.github.kiramorano.localtube.ui.theme.LocalIsTv
import io.github.kiramorano.localtube.ui.theme.LtRadius
import io.github.kiramorano.localtube.ui.theme.LtSpace
import io.github.kiramorano.localtube.ui.theme.LtTap
import io.github.kiramorano.localtube.ui.theme.LtTheme
import io.github.kiramorano.localtube.ui.theme.LtType
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

/** Размер и цвет строки «автор · размер · длительность» как в вебе. */
private fun metaLine(v: VideoItem): String = buildString {
    append(v.author)
    // .video-meta в вебе: автор · NN МБ · M:SS
    if (v.sizeMb > 0) append(" · ${String.format("%.0f", v.sizeMb)} МБ")
    val date = formatUploadDate(v.uploadDate)
    if (date.isNotBlank()) append(" · $date")
}

/**
 * Карточка видео как в веб-версии: превью 16/9 со скруглением 12dp, под ним
 * кружок автора 36dp, заголовок 16sp в две строки и серая строка автора с
 * размером и датой. Без рамки и подложки — в вебе карточка тоже лежит прямо
 * на фоне.
 */
@Composable
fun VideoCard(
    v: VideoItem,
    onClick: () -> Unit,
    short: Boolean = false,
    isFavorite: Boolean = false,
    onToggleFavorite: (() -> Unit)? = null,
    onOpenChannel: (() -> Unit)? = null,
    onHideChannel: (() -> Unit)? = null,
    onDelete: (() -> Unit)? = null,
    /** «Сохранить в плейлист»: null убирает пункт из меню. */
    onSaveToCollection: (() -> Unit)? = null,
    /** Подпись пункта удаления: в плейлисте это «Убрать», а не «Удалить видео». */
    deleteLabel: String = "Удалить видео"
) {
    val colors = LtTheme.colors
    val sizes = LtTheme.sizes
    var menuOpen by remember { mutableStateOf(false) }
    // Рамка вокруг карточки в фокусе: на телевизоре иначе не видно, где курсор.
    val interactionSource = remember { MutableInteractionSource() }
    val focused by interactionSource.collectIsFocusedAsState()
    val hasCardBg = colors.cardBg.alpha > 0f

    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(sizes.cornerRadius))
            // Подложка есть только у тем, которые её задают (Midnight, Glass,
            // Aero). В dark и light карточка сливается с фоном, как в вебе.
            .background(colors.cardBg)
            .tvFocusBorder(focused, colors.brandRed)
            .clickable(interactionSource = interactionSource, indication = LocalIndication.current, onClick = onClick)
    ) {
        Box {
            AsyncThumb(
                path = v.thumb,
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(if (short) 9f / 16f else 16f / 9f)
                    .clip(RoundedCornerShape(sizes.cornerRadius))
                    .background(colors.thumbPlaceholder)
            )
            if (v.durationSec > 0) {
                // Длительность в правом нижнем углу превью, как на YouTube.
                Text(
                    formatDuration(v.durationSec),
                    color = Color.White,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Medium,
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .padding(6.dp)
                        .background(Color(0xCC000000), RoundedCornerShape(4.dp))
                        .padding(horizontal = 5.dp, vertical = 2.dp)
                )
            }
            if (onToggleFavorite != null) {
                // Область нажатия 48dp, а кружок внутри остаётся маленьким:
                // раньше нажималось ровно 32dp по размеру кружка, и палец
                // попадал через раз. Просто увеличить кружок нельзя — он
                // закроет кадр, поэтому область растёт, а рисунок нет.
                Box(
                    Modifier
                        .align(Alignment.TopEnd)
                        .size(LtTap.min)
                        .clickable(onClick = onToggleFavorite),
                    contentAlignment = Alignment.Center
                ) {
                    Box(
                        Modifier
                            .size(LtTap.visual)
                            .clip(CircleShape)
                            .background(Color(0x99000000)),
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            if (isFavorite) Icons.Filled.Star else Icons.Outlined.StarBorder,
                            contentDescription = if (isFavorite) "Убрать из избранного" else "В избранное",
                            tint = if (isFavorite) colors.favoriteGold else Color.White,
                            modifier = Modifier.size(19.dp)
                        )
                    }
                }
            }
        }
        Row(
            Modifier
                .fillMaxWidth()
                // .video-details в вебе: padding 12px, gap 12px. У тем с
                // подложкой добавляются боковые отступы, иначе текст лежит
                // вплотную к краю плитки.
                .padding(
                    top = 12.dp,
                    bottom = if (hasCardBg) 12.dp else 8.dp,
                    start = if (hasCardBg) 10.dp else 0.dp,
                    end = if (hasCardBg) 4.dp else 0.dp
                ),
            verticalAlignment = Alignment.Top
        ) {
            // .video-author-avatar: кружок 36px на #5c6bc0 с первой буквой.
            Box(
                Modifier
                    .padding(end = 12.dp)
                    .size(36.dp)
                    .clip(CircleShape)
                    .background(Color(0xFF5C6BC0)),
                contentAlignment = Alignment.Center
            ) {
                if (v.authorAvatar != null) {
                    AsyncThumb(v.authorAvatar, Modifier.fillMaxSize())
                } else {
                    Text(
                        v.author.take(1).uppercase(),
                        color = Color.White,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Medium
                    )
                }
            }
            Column(Modifier.weight(1f)) {
                Text(
                    v.title,
                    color = colors.textPrimary,
                    fontSize = sizes.titleSize,
                    lineHeight = sizes.titleLineHeight,
                    fontWeight = FontWeight.Medium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    metaLine(v),
                    color = colors.textSecondary,
                    fontSize = sizes.metaSize,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 4.dp)
                )
            }
            if (onOpenChannel != null || onHideChannel != null || onDelete != null ||
                onSaveToCollection != null
            ) {
                Box {
                    // Штатный размер IconButton — 48dp; здесь он был урезан до
                    // 32dp, хотя сама иконка всё равно рисуется на 20dp.
                    IconButton(onClick = { menuOpen = true }) {
                        Icon(
                            Icons.Filled.MoreVert,
                            contentDescription = "Ещё",
                            tint = colors.textSecondary,
                            modifier = Modifier.size(20.dp)
                        )
                    }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        onSaveToCollection?.let {
                            DropdownMenuItem(
                                text = { Text("Сохранить в плейлист") },
                                onClick = { menuOpen = false; it() })
                        }
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
                                text = { Text(deleteLabel) },
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
    emptyText: String = "Здесь пока пусто",
    /** Показывать пункт «Сохранить в плейлист». Диалог держит сама сетка. */
    allowSaveToCollection: Boolean = true,
    deleteLabel: String = "Удалить видео"
) {
    if (items.isEmpty()) {
        EmptyBox(emptyText)
        return
    }
    val sizes = LtTheme.sizes
    val minWidth = if (short) sizes.shortCardWidth else sizes.videoCardMinWidth
    // Диалог живёт в сетке, а не в каждой карточке: иначе на экране из сотни
    // видео создавалось бы столько же моделей SaveToCollectionViewModel.
    var saveTarget by remember { mutableStateOf<String?>(null) }

    LazyVerticalGrid(
        columns = GridCells.Adaptive(minWidth),
        contentPadding = PaddingValues(sizes.gridGap),
        horizontalArrangement = Arrangement.spacedBy(sizes.gridGap),
        verticalArrangement = Arrangement.spacedBy(sizes.gridGap),
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
                onDelete = onDelete?.let { cb -> { cb(v) } },
                onSaveToCollection = if (allowSaveToCollection) ({ saveTarget = v.id }) else null,
                deleteLabel = deleteLabel
            )
        }
    }

    saveTarget?.let { id ->
        SaveToCollectionDialog(videoId = id, onDismiss = { saveTarget = null })
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
            val colors = LtTheme.colors
            val interactionSource = remember { MutableInteractionSource() }
            val focused by interactionSource.collectIsFocusedAsState()
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .tvFocusBorder(focused, colors.brandRed)
                    .clickable(
                        interactionSource = interactionSource,
                        indication = LocalIndication.current,
                        enabled = onOpen != null
                    ) { onOpen?.invoke(a.name) }
                    .padding(6.dp)
            ) {
                Box(
                    Modifier
                        .size(72.dp)
                        .clip(CircleShape)
                        // Как в сайдбаре веб-версии: кружок #8e24aa.
                        .background(Color(0xFF8E24AA)),
                    contentAlignment = Alignment.Center
                ) {
                    if (a.avatar != null) {
                        AsyncThumb(a.avatar, Modifier.fillMaxSize())
                    } else {
                        Text(
                            a.name.take(1).uppercase(),
                            color = Color.White,
                            style = MaterialTheme.typography.titleLarge
                        )
                    }
                }
                Text(
                    a.name,
                    color = colors.textPrimary,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 6.dp)
                )
                if (a.videoCount > 0) {
                    Text(
                        "${a.videoCount} видео",
                        style = MaterialTheme.typography.labelSmall,
                        color = colors.textSecondary
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
            val colors = LtTheme.colors
            val sizes = LtTheme.sizes
            val interactionSource = remember { MutableInteractionSource() }
            val focused by interactionSource.collectIsFocusedAsState()
            Column(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(sizes.cornerRadius))
                    .tvFocusBorder(focused, colors.brandRed)
                    .clickable(
                        interactionSource = interactionSource,
                        indication = LocalIndication.current
                    ) { onOpen(p.id) }
            ) {
                AsyncThumb(
                    p.thumbnail,
                    Modifier
                        .fillMaxWidth()
                        .aspectRatio(16f / 9f)
                        .clip(RoundedCornerShape(sizes.cornerRadius))
                        .background(colors.thumbPlaceholder)
                )
                Column(Modifier.padding(vertical = 10.dp)) {
                    Text(
                        p.title,
                        color = colors.textPrimary,
                        fontSize = sizes.titleSize,
                        lineHeight = sizes.titleLineHeight,
                        fontWeight = FontWeight.Medium,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis
                    )
                    Text(
                        "${p.uploader} · ${p.videoCount} видео",
                        color = colors.textSecondary,
                        fontSize = sizes.metaSize,
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

/**
 * Карточка-секция: настройки и очередь. В dark/light у видеокарточки фона нет
 * (она сливается со страницей), а секции как раз нужны как отдельные блоки —
 * берём modalBg и обводим border, как `section` в templates/settings.html.
 */
@Composable
fun LtPanel(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit
) {
    val colors = LtTheme.colors
    val shape = RoundedCornerShape(LtTheme.sizes.cornerRadius)
    val bg = if (colors.cardBg.alpha > 0f) colors.cardBg else colors.modalBg
    Column(
        modifier
            .fillMaxWidth()
            .clip(shape)
            .background(bg)
            .border(1.dp, colors.border, shape)
            .padding(LtSpace.x4),
        verticalArrangement = Arrangement.spacedBy(LtSpace.x3),
        content = content
    )
}

/**
 * Горизонтальная полка: используется для Shorts и рекомендаций. Ширина карточки
 * берётся из темы, как .short-card (210px) в веб-версии.
 */
@Composable
fun VideoShelf(
    items: List<VideoItem>,
    onOpen: (String) -> Unit,
    short: Boolean = false,
    favorites: Set<String> = emptySet(),
    onToggleFavorite: ((String) -> Unit)? = null
) {
    val sizes = LtTheme.sizes
    LazyRow(
        contentPadding = PaddingValues(horizontal = sizes.gridGap),
        horizontalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        items(items, key = { it.id + it.source }) { v ->
            Box(Modifier.width(if (short) sizes.shortCardWidth else 220.dp)) {
                VideoCard(
                    v = v,
                    onClick = { onOpen(v.id) },
                    short = short,
                    isFavorite = favorites.contains(v.id),
                    onToggleFavorite = onToggleFavorite?.let { cb -> { cb(v.id) } }
                )
            }
        }
    }
}

/** Заголовок раздела: как <h2> в веб-версии (📹 Мои видео, 📱 Shorts). */
@Composable
fun SectionHeader(
    text: String,
    modifier: Modifier = Modifier,
    action: String? = null,
    onAction: (() -> Unit)? = null
) {
    val colors = LtTheme.colors
    Row(
        modifier
            .fillMaxWidth()
            .padding(horizontal = LtTheme.sizes.gridGap, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text,
            color = colors.textPrimary,
            fontSize = 20.sp,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.weight(1f)
        )
        if (action != null && onAction != null) {
            // Кликабельный текст: без минимальной высоты на палец приходилось
            // около 28dp (14sp плюс 4dp сверху и снизу). Отступ по вертикали
            // задавать нельзя — он растянет строку заголовка, поэтому область
            // добирается heightIn и центрируется.
            Text(
                action,
                color = colors.textSecondary,
                fontSize = LtType.md,
                modifier = Modifier
                    .clip(RoundedCornerShape(LtRadius.sm))
                    .clickable(onClick = onAction)
                    .defaultMinSize(minHeight = LtTap.min)
                    .wrapContentHeight(Alignment.CenterVertically)
                    .padding(horizontal = LtSpace.x3)
            )
        }
    }
}

/** Полоса-разделитель вокруг полки Shorts: .shorts-shelf-container в вебе. */
@Composable
fun ShelfDivider() {
    Box(
        Modifier
            .fillMaxWidth()
            .height(4.dp)
            .background(LtTheme.colors.buttonHover)
    )
}

/** Рамка вокруг сфокусированного элемента: нужна для навигации пультом. */
fun Modifier.tvFocusBorder(focused: Boolean, color: Color): Modifier =
    if (focused) this.border(3.dp, color, RoundedCornerShape(10.dp)) else this
