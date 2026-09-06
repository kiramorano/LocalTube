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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Sort
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.Catalog
import io.github.kiramorano.localtube.data.CatalogSort
import io.github.kiramorano.localtube.data.VideoItem
import io.github.kiramorano.localtube.ui.components.AuthorsGrid
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.ui.components.PlaylistsGrid
import io.github.kiramorano.localtube.ui.components.SectionHeader
import io.github.kiramorano.localtube.ui.components.ShelfDivider
import io.github.kiramorano.localtube.ui.components.VideoCard
import io.github.kiramorano.localtube.ui.components.VideoGrid
import io.github.kiramorano.localtube.ui.components.VideoShelf
import io.github.kiramorano.localtube.ui.components.tvFocusBorder
import io.github.kiramorano.localtube.ui.theme.LtRadius
import io.github.kiramorano.localtube.ui.theme.LtSpace
import io.github.kiramorano.localtube.ui.theme.LtTap
import io.github.kiramorano.localtube.ui.theme.LtTheme
import io.github.kiramorano.localtube.ui.theme.LtType
import io.github.kiramorano.localtube.vm.HomeViewModel

/** Разделы каталога: те же чипы, что в веб-версии над сеткой. */
private val tabs = listOf("Все", "Видео", "Shorts", "Каналы", "Плейлисты", "Мои видео")

@Composable
fun HomeScreen(
    onOpenVideo: (String) -> Unit,
    onOpenShorts: (String) -> Unit,
    onOpenPlaylist: (String) -> Unit,
    onOpenChannel: (String) -> Unit,
    vm: HomeViewModel = viewModel()
) {
    val colors = LtTheme.colors
    val userData by vm.userData.collectAsStateWithLifecycle()
    val sort by vm.settings.sortFlow.collectAsStateWithLifecycle()
    val libraryVersion by vm.libraryVersion.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var sortMenu by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.load() }
    // Каталог перечитывается после завершения загрузки.
    LaunchedEffect(libraryVersion) { if (libraryVersion > 0) vm.load(force = true) }

    Column(
        Modifier
            .fillMaxSize()
            .background(colors.background)
    ) {
        // Строка чипов и сортировки: в вебе она тоже над сеткой.
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            LazyRow(
                Modifier.weight(1f),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(tabs.size) { index ->
                    Chip(
                        text = tabs[index],
                        active = tab == index,
                        onClick = { tab = index }
                    )
                }
            }
            Box {
                IconButton(onClick = { sortMenu = true }) {
                    Icon(Icons.AutoMirrored.Filled.Sort, "Сортировка", tint = colors.iconInactive)
                }
                DropdownMenu(expanded = sortMenu, onDismissRequest = { sortMenu = false }) {
                    CatalogSort.entries.forEach { option ->
                        DropdownMenuItem(
                            text = { Text(option.label + if (option == sort) "  ✓" else "") },
                            onClick = { sortMenu = false; vm.setSort(option) }
                        )
                    }
                }
            }
            IconButton(onClick = { vm.load(force = true) }) {
                Icon(Icons.Filled.Refresh, "Обновить", tint = colors.iconInactive)
            }
        }

        val catalog = vm.catalog
        if (catalog == null) {
            LoadingBox()
            return@Column
        }

        val visible = vm.visible(catalog, userData.hiddenChannels, sort)
        val favorites = userData.favorites.toSet()

        when (tab) {
            // «Все» повторяет главную веб-версии: сначала свои видео, затем
            // полка Shorts, затем общая сетка и чипы плейлистов.
            0 -> HomeAll(
                catalog = visible,
                favorites = favorites,
                onOpenVideo = onOpenVideo,
                onOpenShorts = onOpenShorts,
                onOpenPlaylist = onOpenPlaylist,
                onOpenChannel = onOpenChannel,
                onShowAllShorts = { tab = 2 },
                vm = vm
            )
            1 -> VideoGrid(
                items = visible.videos,
                onOpen = onOpenVideo,
                favorites = favorites,
                onToggleFavorite = vm::toggleFavorite,
                onOpenChannel = onOpenChannel,
                onHideChannel = { author -> vm.setChannelHidden(author, true) },
                onDelete = vm::delete,
                emptyText = "Видео пока нет"
            )
            2 -> VideoGrid(
                items = visible.shorts,
                onOpen = onOpenShorts,
                short = true,
                favorites = favorites,
                onToggleFavorite = vm::toggleFavorite,
                onOpenChannel = onOpenChannel,
                onHideChannel = { author -> vm.setChannelHidden(author, true) },
                onDelete = vm::delete,
                emptyText = "Shorts пока нет"
            )
            3 -> AuthorsGrid(authors = visible.authors, onOpen = onOpenChannel)
            4 -> PlaylistsGrid(playlists = visible.playlists, onOpen = onOpenPlaylist)
            else -> VideoGrid(
                items = visible.userVideos,
                onOpen = onOpenVideo,
                favorites = favorites,
                onToggleFavorite = vm::toggleFavorite,
                onDelete = vm::delete,
                emptyText = "Свои видео добавляются в разделе «Мои видео»"
            )
        }
    }
}

/**
 * Главная в раскладке ПК-версии: разделы идут друг за другом в одном скролле,
 * как в templates/index.html. Раньше на «Все» была просто сетка из всего
 * подряд, без полки Shorts и без раздела своих видео.
 */
@Composable
private fun HomeAll(
    catalog: Catalog,
    favorites: Set<String>,
    onOpenVideo: (String) -> Unit,
    onOpenShorts: (String) -> Unit,
    onOpenPlaylist: (String) -> Unit,
    onOpenChannel: (String) -> Unit,
    onShowAllShorts: () -> Unit,
    vm: HomeViewModel
) {
    val sizes = LtTheme.sizes
    if (catalog.videos.isEmpty() && catalog.shorts.isEmpty() &&
        catalog.userVideos.isEmpty() && catalog.playlists.isEmpty()
    ) {
        EmptyBox("Здесь пока нет видео. Скачанные и добавленные вручную появятся тут.")
        return
    }

    LazyVerticalGrid(
        columns = GridCells.Adaptive(sizes.videoCardMinWidth),
        contentPadding = PaddingValues(sizes.gridGap),
        horizontalArrangement = Arrangement.spacedBy(sizes.gridGap),
        verticalArrangement = Arrangement.spacedBy(sizes.gridGap),
        modifier = Modifier.fillMaxSize()
    ) {
        if (catalog.userVideos.isNotEmpty()) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                SectionHeader("📹 Мои видео")
            }
            items(catalog.userVideos, key = { "user:${it.id}" }) { v ->
                VideoCard(
                    v = v,
                    onClick = { onOpenVideo(v.id) },
                    isFavorite = favorites.contains(v.id),
                    onToggleFavorite = { vm.toggleFavorite(v.id) },
                    onDelete = { vm.delete(v) }
                )
            }
        }

        if (catalog.shorts.isNotEmpty()) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Column {
                    ShelfDivider()
                    SectionHeader(
                        "📱 Shorts",
                        action = "Показать все →",
                        onAction = onShowAllShorts
                    )
                    VideoShelf(
                        items = catalog.shorts,
                        onOpen = onOpenShorts,
                        short = true,
                        favorites = favorites,
                        onToggleFavorite = vm::toggleFavorite
                    )
                    ShelfDivider()
                }
            }
        }

        items(catalog.videos, key = { "v:${it.id}" }) { v ->
            VideoCard(
                v = v,
                onClick = { onOpenVideo(v.id) },
                isFavorite = favorites.contains(v.id),
                onToggleFavorite = { vm.toggleFavorite(v.id) },
                onOpenChannel = { onOpenChannel(v.author) },
                onHideChannel = { vm.setChannelHidden(v.author, true) },
                onDelete = { vm.delete(v) }
            )
        }

        if (catalog.playlists.isNotEmpty()) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Column {
                    SectionHeader("Плейлисты")
                    LazyRow(
                        contentPadding = PaddingValues(horizontal = 0.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        items(catalog.playlists, key = { it.id }) { p ->
                            Chip(
                                text = "${p.title} · ${p.videoCount} видео",
                                active = false,
                                onClick = { onOpenPlaylist(p.id) }
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * Чип фильтра: .chip из веб-версии, включая инверсию цвета у активного.
 *
 * Пилюля остаётся невысокой (иначе ряд фильтров занимает половину экрана), а
 * область нажатия добирается до 48dp внешней обёрткой. Раньше нажималось ровно
 * то, что нарисовано, — около 36dp.
 */
@Composable
fun Chip(text: String, active: Boolean, onClick: () -> Unit) {
    val colors = LtTheme.colors
    val interactionSource = remember { MutableInteractionSource() }
    val focused by interactionSource.collectIsFocusedAsState()
    Box(
        Modifier
            .heightIn(min = LtTap.min)
            .clip(RoundedCornerShape(LtRadius.pill))
            .clickable(
                interactionSource = interactionSource,
                indication = LocalIndication.current,
                onClick = onClick
            ),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text,
            color = if (active) colors.background else colors.textPrimary,
            fontSize = LtType.md,
            fontWeight = if (active) FontWeight.Medium else FontWeight.Normal,
            modifier = Modifier
                .clip(RoundedCornerShape(LtRadius.pill))
                .tvFocusBorder(focused, colors.brandRed)
                .background(if (active) colors.textPrimary else colors.buttonBg)
                .padding(horizontal = 14.dp, vertical = LtSpace.x2)
        )
    }
}
