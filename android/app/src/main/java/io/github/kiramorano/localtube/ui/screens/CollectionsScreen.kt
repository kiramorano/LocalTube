package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.PlaylistPlay
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.WatchLater
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.VideoCollection
import io.github.kiramorano.localtube.ui.components.AsyncThumb
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.ui.components.VideoGrid
import io.github.kiramorano.localtube.ui.components.tvFocusBorder
import io.github.kiramorano.localtube.ui.theme.LtSpace
import io.github.kiramorano.localtube.ui.theme.LtTap
import io.github.kiramorano.localtube.ui.theme.LtTheme
import io.github.kiramorano.localtube.ui.theme.LtType
import io.github.kiramorano.localtube.vm.CollectionsViewModel

/**
 * Список своих плейлистов. Аналог раздела «Плейлисты» и страницы
 * /collection/<id> в веб-версии: «Смотреть позже» всегда первым и защищён от
 * переименования и удаления.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CollectionsScreen(
    onOpenCollection: (String) -> Unit,
    vm: CollectionsViewModel = viewModel()
) {
    val colors = LtTheme.colors
    val userData by vm.userData.collectAsStateWithLifecycle()
    var createOpen by remember { mutableStateOf(false) }
    var renameTarget by remember { mutableStateOf<VideoCollection?>(null) }
    var deleteTarget by remember { mutableStateOf<VideoCollection?>(null) }

    LaunchedEffect(Unit) { vm.load() }

    val collections = vm.collections(userData)

    Column(Modifier.fillMaxSize()) {
        CenterAlignedTopAppBar(
            title = { Text("Мои плейлисты") },
            actions = {
                IconButton(onClick = { createOpen = true }) {
                    Icon(Icons.Filled.Add, contentDescription = "Создать плейлист")
                }
            }
        )

        // Сообщения показываем строкой над списком: всплывающее уведомление на
        // ТВ пользователь может не заметить.
        vm.error?.let { Notice(it, isError = true) { vm.clearMessages() } }
        vm.message?.let { Notice(it, isError = false) { vm.clearMessages() } }

        if (vm.loading && vm.catalog == null) {
            LoadingBox()
        } else if (collections.isEmpty()) {
            EmptyBox("Плейлистов пока нет. Создайте первый кнопкой «+».")
        } else {
            LazyColumn(
                contentPadding = PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
                modifier = Modifier.fillMaxSize()
            ) {
                items(collections, key = { it.id }) { c ->
                    val videos = vm.videosOf(c)
                    CollectionRow(
                        collection = c,
                        count = c.videos.size,
                        thumb = videos.firstOrNull()?.thumb,
                        onClick = { onOpenCollection(c.id) },
                        onRename = if (c.id == VideoCollection.WATCH_LATER_ID) null
                        else ({ renameTarget = c }),
                        onDelete = if (c.id == VideoCollection.WATCH_LATER_ID) null
                        else ({ deleteTarget = c })
                    )
                }
            }
        }
    }

    if (createOpen) {
        TitleDialog(
            title = "Новый плейлист",
            initial = "",
            confirmLabel = "Создать",
            onDismiss = { createOpen = false },
            onConfirm = { text ->
                createOpen = false
                vm.create(text)
            }
        )
    }

    renameTarget?.let { target ->
        TitleDialog(
            title = "Переименовать плейлист",
            initial = target.title,
            confirmLabel = "Сохранить",
            onDismiss = { renameTarget = null },
            onConfirm = { text ->
                renameTarget = null
                vm.rename(target.id, text)
            }
        )
    }

    deleteTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("Удалить «${target.title}»?") },
            text = { Text("Сами видео останутся на диске, удалится только список.") },
            confirmButton = {
                TextButton(onClick = {
                    deleteTarget = null
                    vm.delete(target.id)
                }) { Text("Удалить") }
            },
            dismissButton = {
                TextButton(onClick = { deleteTarget = null }) { Text("Отмена") }
            }
        )
    }
}

/**
 * Содержимое одного плейлиста. Отдельный экран, а не раскрывающийся список:
 * так же, как /collection/<id> на ПК, и видео открываются обычной сеткой.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CollectionDetailScreen(
    collectionId: String,
    onBack: () -> Unit,
    onOpenVideo: (String) -> Unit,
    vm: CollectionsViewModel = viewModel()
) {
    val userData by vm.userData.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.load() }

    val collection = userData.collections.firstOrNull { it.id == collectionId }

    Column(Modifier.fillMaxSize()) {
        CenterAlignedTopAppBar(
            title = { Text(collection?.title ?: "Плейлист", maxLines = 1, overflow = TextOverflow.Ellipsis) },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
                }
            }
        )
        when {
            collection == null -> EmptyBox("Плейлист не найден")
            vm.catalog == null -> LoadingBox()
            else -> {
                val videos = vm.videosOf(collection)
                val missing = vm.missingCount(collection)
                if (missing > 0) {
                    // Видео могли удалить с диска: молча показывать меньше
                    // записей, чем в списке, значило бы прятать расхождение.
                    Notice("Видео удалено с диска: $missing", isError = false, onDismiss = null)
                }
                VideoGrid(
                    items = videos,
                    onOpen = onOpenVideo,
                    favorites = userData.favorites.toSet(),
                    onToggleFavorite = vm::toggleFavorite,
                    onDelete = { v -> vm.removeVideo(collection.id, v.id) },
                    emptyText = "В этом плейлисте пока нет видео"
                )
            }
        }
    }
}

/** Строка плейлиста: превью, название, число видео и меню действий. */
@Composable
private fun CollectionRow(
    collection: VideoCollection,
    count: Int,
    thumb: String?,
    onClick: () -> Unit,
    onRename: (() -> Unit)?,
    onDelete: (() -> Unit)?
) {
    val colors = LtTheme.colors
    val sizes = LtTheme.sizes
    var menuOpen by remember { mutableStateOf(false) }
    val interactionSource = remember { MutableInteractionSource() }
    val focused by interactionSource.collectIsFocusedAsState()
    val isWatchLater = collection.id == VideoCollection.WATCH_LATER_ID

    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(sizes.cornerRadius))
            .tvFocusBorder(focused, colors.brandRed)
            .clickable(
                interactionSource = interactionSource,
                indication = LocalIndication.current,
                onClick = onClick
            )
            .padding(8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            Modifier
                .size(width = 96.dp, height = 54.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(colors.thumbPlaceholder),
            contentAlignment = Alignment.Center
        ) {
            if (thumb != null) {
                AsyncThumb(thumb, Modifier.fillMaxSize())
            } else {
                Icon(
                    if (isWatchLater) Icons.Filled.WatchLater
                    else Icons.AutoMirrored.Filled.PlaylistPlay,
                    contentDescription = null,
                    tint = colors.textSecondary
                )
            }
        }
        Column(
            Modifier
                .weight(1f)
                .padding(horizontal = 12.dp)
        ) {
            Text(
                collection.title,
                color = colors.textPrimary,
                fontSize = sizes.titleSize,
                fontWeight = FontWeight.Medium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Text(
                if (count == 0) "Пусто" else "Видео: $count",
                color = colors.textSecondary,
                fontSize = sizes.metaSize
            )
        }
        if (onRename != null || onDelete != null) {
            Box {
                IconButton(onClick = { menuOpen = true }) {
                    Icon(Icons.Filled.MoreVert, contentDescription = "Ещё", tint = colors.textSecondary)
                }
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                    onRename?.let {
                        DropdownMenuItem(
                            text = { Text("Переименовать") },
                            leadingIcon = { Icon(Icons.Filled.Edit, contentDescription = null) },
                            onClick = { menuOpen = false; it() }
                        )
                    }
                    onDelete?.let {
                        DropdownMenuItem(
                            text = { Text("Удалить") },
                            leadingIcon = { Icon(Icons.Filled.Delete, contentDescription = null) },
                            onClick = { menuOpen = false; it() }
                        )
                    }
                }
            }
        }
    }
}

/** Диалог ввода названия: используется и при создании, и при переименовании. */
@Composable
internal fun TitleDialog(
    title: String,
    initial: String,
    confirmLabel: String,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit
) {
    var text by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            OutlinedTextField(
                value = text,
                onValueChange = {
                    // Обрезаем на вводе: лимит совпадает с серверным, и лучше
                    // не дать напечатать лишнее, чем отказать после нажатия.
                    if (it.length <= VideoCollection.TITLE_LIMIT) text = it
                },
                label = { Text("Название") },
                singleLine = true,
                supportingText = { Text("${text.length}/${VideoCollection.TITLE_LIMIT}") }
            )
        },
        confirmButton = {
            TextButton(
                onClick = { onConfirm(text) },
                enabled = text.isNotBlank()
            ) { Text(confirmLabel) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Отмена") } }
    )
}

/** Строка-уведомление в цветах темы. */
@Composable
internal fun Notice(text: String, isError: Boolean, onDismiss: (() -> Unit)?) {
    val colors = LtTheme.colors
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(if (isError) Color(0x33FF5252) else Color(0x3300C853))
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text,
            color = colors.textPrimary,
            fontSize = 13.sp,
            modifier = Modifier.weight(1f)
        )
        if (onDismiss != null) {
            // На палец приходилось около 20dp. Высоту строки-уведомления
            // растягивать не хочется, поэтому область нажатия добирается
            // heightIn, а не отступами.
            Text(
                "Скрыть",
                color = colors.textSecondary,
                fontSize = LtType.xs,
                modifier = Modifier
                    .clip(CircleShape)
                    .clickable(onClick = onDismiss)
                    .defaultMinSize(minHeight = LtTap.min)
                    .wrapContentHeight(Alignment.CenterVertically)
                    .padding(horizontal = LtSpace.x3)
            )
        }
    }
}
