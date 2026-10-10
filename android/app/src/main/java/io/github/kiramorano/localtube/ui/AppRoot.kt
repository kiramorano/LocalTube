package io.github.kiramorano.localtube.ui

import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.PlayCircle
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material.icons.outlined.VideoLibrary
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import io.github.kiramorano.localtube.ui.components.LtHeader
import io.github.kiramorano.localtube.ui.components.LtSidebar
import io.github.kiramorano.localtube.ui.components.tvFocusBorder
import io.github.kiramorano.localtube.ui.screens.ChannelScreen
import io.github.kiramorano.localtube.ui.screens.CollectionDetailScreen
import io.github.kiramorano.localtube.ui.screens.CollectionsScreen
import io.github.kiramorano.localtube.ui.screens.DownloadsScreen
import io.github.kiramorano.localtube.ui.screens.HistoryScreen
import io.github.kiramorano.localtube.ui.screens.HomeScreen
import io.github.kiramorano.localtube.ui.screens.MyVideosScreen
import io.github.kiramorano.localtube.ui.screens.PlayerScreen
import io.github.kiramorano.localtube.ui.screens.PlaylistScreen
import io.github.kiramorano.localtube.ui.screens.SearchScreen
import io.github.kiramorano.localtube.ui.screens.SettingsScreen
import io.github.kiramorano.localtube.ui.screens.ShortsScreen
import io.github.kiramorano.localtube.ui.screens.SubtitlesScreen
import io.github.kiramorano.localtube.data.ImportResult
import io.github.kiramorano.localtube.ui.theme.LtBreakpoints
import io.github.kiramorano.localtube.ui.theme.LtTheme
import io.github.kiramorano.localtube.vm.HomeViewModel
import kotlinx.coroutines.launch

/** Экраны на весь экран: без шапки и меню. */
internal val fullScreenRoutes = setOf(
    "player/{videoId}?collection={collectionId}",
    "shorts/{videoId}",
    "playlist/{playlistId}",
    "channel/{author}"
)

/**
 * Пункт нижней панели.
 *
 * Иконок две: заливная для выбранного пункта и контурная для остальных. Так
 * выбранный раздел виден и без опоры на цвет — полезно и при слабом зрении, и
 * на солнце, где полутон между textPrimary и textSecondary неразличим.
 */
internal data class BottomTab(
    val route: String,
    val label: String,
    val icon: ImageVector,
    val iconOutlined: ImageVector,
    /**
     * Вложенные разделы, для которых пункт считается выбранным. Без этого на
     * `collections`, `history` и `search` не подсвечивался ни один пункт, и
     * панель выглядела так, будто приложение вообще нигде не находится.
     */
    val childRoutes: Set<String> = emptySet()
) {
    fun matches(current: String?): Boolean =
        current == route || current in childRoutes
}

/** Быстрый доступ снизу на телефоне: как и в мобильном YouTube. */
internal val bottomTabs = listOf(
    BottomTab("home", "Главная", Icons.Filled.Home, Icons.Outlined.Home),
    BottomTab("shorts_feed", "Shorts", Icons.Filled.PlayCircle, Icons.Outlined.PlayCircle),
    BottomTab(
        "favorites", "Избранное", Icons.Filled.Star, Icons.Outlined.StarBorder,
        // История и избранное — обе «мои отметки»: в сайдбаре они рядом, и
        // логично держать пункт подсвеченным на обоих экранах.
        childRoutes = setOf("history")
    ),
    BottomTab("downloads", "Очередь", Icons.Filled.Download, Icons.Outlined.Download),
    BottomTab(
        "myvideos", "Моё", Icons.Filled.VideoLibrary, Icons.Outlined.VideoLibrary,
        // Плейлисты и их содержимое — часть «моего»: без этого переход в
        // плейлист гасил подсветку целиком.
        childRoutes = setOf("collections", "collection/{collectionId}")
    )
)

@Composable
fun AppRoot(
    isTv: Boolean = false,
    sharedUrl: String? = null,
    onSharedUrlHandled: () -> Unit = {}
) {
    val colors = LtTheme.colors
    val navController = rememberNavController()
    val backStack by navController.currentBackStackEntryAsState()
    val route = backStack?.destination?.route
    val showChrome = route !in fullScreenRoutes

    val configuration = LocalConfiguration.current
    // Постоянный сайдбар там, где хватает ширины: планшет, ТВ, ландшафт.
    // Порог общий с расчётом compact в MainActivity: раньше сайдбар включался
    // от 720dp, а карточки укрупнялись уже с 600dp, и на 7-дюймовом планшете
    // раскладка была ни телефонной, ни планшетной.
    val permanentSidebar = LtBreakpoints.hasPermanentSidebar(configuration.screenWidthDp, isTv)
    var drawerOpen by remember { mutableStateOf(false) }

    /**
     * Ссылка из «Поделиться» держится здесь до того, как её увидит экран
     * загрузок. Раньше AppRoot сбрасывал её сразу после navigate(), и до
     * DownloadsScreen доезжал уже null — поле оставалось пустым.
     */
    var pendingUrl by remember { mutableStateOf<String?>(null) }

    // Данные для меню: список каналов и скрытые каналы, как в вебе. Модель
    // общая с экранами: раньше сайдбар держал свой экземпляр и запускал
    // отдельное сканирование библиотеки.
    val homeVm: HomeViewModel = viewModel()
    val userData by homeVm.userData.collectAsStateWithLifecycle()
    // Имя для шапки: раньше там всегда стояло «Гость», а настройки его не знали.
    val userName by homeVm.settings.userNameFlow.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { homeVm.load() }
    val authors = homeVm.catalog?.authors
        ?.filterNot { userData.hiddenChannels.contains(it.name) }
        .orEmpty()

    // Импорт канала из боковой панели: выбор tar.gz и диалог результата.
    val scope = rememberCoroutineScope()
    var importResult by remember { mutableStateOf<ImportResult?>(null) }
    var importResultDialog by remember { mutableStateOf(false) }
    val importPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            scope.launch {
                importResult = homeVm.importChannel(uri)
                importResultDialog = true
            }
        }
    }

    LaunchedEffect(sharedUrl) {
        if (!sharedUrl.isNullOrBlank()) {
            pendingUrl = sharedUrl
            navController.navigate("downloads") { launchSingleTop = true }
            onSharedUrlHandled()
        }
    }

    fun go(target: String) {
        drawerOpen = false
        navController.navigate(target) {
            popUpTo(navController.graph.startDestinationId) { saveState = true }
            launchSingleTop = true
            restoreState = true
        }
    }

    Box(
        Modifier
            .fillMaxSize()
            .background(colors.background)
            // Отступ под overscan применяем один раз ко всему каркасу, чтобы
            // на ТВ ни шапка, ни меню не упирались в обрезанный край. Плеер и
            // Shorts занимают весь экран: у них рамки быть не должно.
            .padding(if (showChrome) LtTheme.sizes.screenPadding else 0.dp)
    ) {
        Row(Modifier.fillMaxSize()) {
            if (permanentSidebar && showChrome) {
                Column(Modifier.statusBarsPadding()) {
                    LtSidebar(
                        currentRoute = route,
                        authors = authors,
                        hiddenChannels = userData.hiddenChannels,
                        onNavigate = ::go,
                        onOpenChannel = { name ->
                            navController.navigate("channel/${name.encode()}")
                        },
                        onUnhideChannel = { name -> homeVm.setChannelHidden(name, false) },
                        onImportClick = { importPicker.launch(arrayOf("application/gzip", "application/gzip-compressed", "application/x-gzip")) },
                        onDonateClick = {},
                        onDonateUnavailable = { go("settings") }
                    )
                }
            }
            Column(Modifier.fillMaxSize()) {
                if (showChrome) {
                    Column(Modifier.statusBarsPadding()) {
                        LtHeader(
                            // На узком экране меню выдвижное, на широком уже открыто.
                            onMenuClick = if (permanentSidebar) null else {
                                { drawerOpen = true }
                            },
                            onSearchClick = { go("search") },
                            onSettingsClick = { go("settings") },
                            onLogoClick = { go("home") },
                            userName = userName
                        )
                    }
                }
                Box(Modifier.weight(1f)) {
                    AppNavHost(
                        navController = navController,
                        modifier = Modifier.fillMaxSize(),
                        pendingUrl = pendingUrl,
                        onPendingUrlConsumed = { pendingUrl = null }
                    )
                }
                if (showChrome && !permanentSidebar) {
                    BottomBar(currentRoute = route, onNavigate = ::go)
                }
            }
        }

        // Выдвижное меню поверх содержимого, как .sidebar-drawer в вебе.
        if (!permanentSidebar) {
            if (drawerOpen) {
                BackHandler { drawerOpen = false }
                Box(
                    Modifier
                        .fillMaxSize()
                        .background(Color(0x99000000))
                        .clickable { drawerOpen = false }
                )
            }
            AnimatedVisibility(
                visible = drawerOpen,
                enter = slideInHorizontally(initialOffsetX = { -it }),
                exit = slideOutHorizontally(targetOffsetX = { -it })
            ) {
                Box(Modifier.statusBarsPadding()) {
                    LtSidebar(
                        currentRoute = route,
                        authors = authors,
                        hiddenChannels = userData.hiddenChannels,
                        onNavigate = ::go,
                        onOpenChannel = { name ->
                            drawerOpen = false
                            navController.navigate("channel/${name.encode()}")
                        },
                        onUnhideChannel = { name -> homeVm.setChannelHidden(name, false) },
                        onImportClick = { importPicker.launch(arrayOf("application/gzip", "application/gzip-compressed", "application/x-gzip")) },
                        onDonateClick = { drawerOpen = false },
                        onDonateUnavailable = { go("settings") }
                    )
                }
            }
        }

        // Диалог результата импорта: какие каналы добавлены и сколько видео.
        // Должен быть за пределами if (!permanentSidebar), чтобы показываться
        // на планшетах и ТВ, где сайдбар постоянный. Раньше он лежал внутри
        // условия и импорт на больших экранах проходил в тишину.
        if (importResultDialog && importResult != null) {
            AlertDialog(
                onDismissRequest = { importResultDialog = false; importResult = null },
                title = {
                    Text(if (importResult?.error != null) "Ошибка импорта" else "Импорт завершён")
                },
                text = {
                    Column {
                        importResult?.error?.let { error ->
                            Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                        } ?: run {
                            Text(
                                "Импортировано каналов: ${importResult!!.channels.size}",
                                style = MaterialTheme.typography.bodySmall
                            )
                            Text(
                                "Видеофайлов: ${importResult!!.imported}",
                                style = MaterialTheme.typography.bodySmall
                            )
                            importResult!!.channels.forEach { ch ->
                                Text("  • $ch", style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                },
                confirmButton = {
                    TextButton(onClick = { importResultDialog = false; importResult = null }) { Text("ОК") }
                }
            )
        }
    }
}

/**
 * Нижняя панель в цветах веб-версии.
 *
 * Собрана на `NavigationBar`, а не на самописном `Row` из `Column`-ов, как было
 * раньше. Причины по порядку значимости:
 *
 * 1. Область нажатия. У прежней вёрстки на палец приходилось около 42dp
 *    (иконка 24dp плюс `vertical = 2.dp`), причём 6dp внешнего отступа лежали
 *    вне `clickable` и не нажимались. `NavigationBarItem` держит 48dp,
 *    как требует Material.
 * 2. Заметность выбранного пункта. Отличием служил только цвет текста и
 *    иконки — на глаз почти незаметно. Появилась пилюля-подложка, а иконка
 *    выбранного пункта стала заливной против контурной у остальных: два
 *    независимых признака вместо полутона одного.
 * 3. Доступность. `NavigationBarItem` сам сообщает роль вкладки и её
 *    состояние; у `Column` с `clickable` скринридер объявлял просто «кнопка».
 *
 * Панель показывается только на телефоне (см. `permanentSidebar`), поэтому
 * подсветка фокуса для пульта здесь не нужна.
 */
@Composable
private fun BottomBar(currentRoute: String?, onNavigate: (String) -> Unit) {
    val colors = LtTheme.colors
    Column {
        // Тонкая линия сверху, как border-top у .lt-bottom-nav в вебе: без неё
        // панель сливается с содержимым при прокрутке.
        Box(
            Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(colors.border)
        )
        NavigationBar(
            containerColor = colors.background,
            // Material подмешивает в фон оттенок primary тем сильнее, чем выше
            // elevation. Здесь primary — красный бренда, и панель уходила в
            // розоватый вместо цвета темы.
            tonalElevation = 0.dp
        ) {
            bottomTabs.forEach { tab ->
                val selected = tab.matches(currentRoute)
                NavigationBarItem(
                    selected = selected,
                    onClick = { onNavigate(tab.route) },
                    icon = {
                        Icon(
                            if (selected) tab.icon else tab.iconOutlined,
                            contentDescription = null
                        )
                    },
                    label = {
                        Text(
                            tab.label,
                            maxLines = 1,
                            // «Избранное» — самая длинная подпись: на узком
                            // экране пятая часть ширины её не вмещает, и без
                            // обрезки текст рвался бы посреди буквы.
                            overflow = TextOverflow.Ellipsis
                        )
                    },
                    colors = NavigationBarItemDefaults.colors(
                        selectedIconColor = colors.textPrimary,
                        selectedTextColor = colors.textPrimary,
                        unselectedIconColor = colors.textSecondary,
                        unselectedTextColor = colors.textSecondary,
                        indicatorColor = colors.buttonHover
                    )
                )
            }
        }
    }
}

@Composable
private fun AppNavHost(
    navController: NavHostController,
    modifier: Modifier,
    pendingUrl: String? = null,
    onPendingUrlConsumed: () -> Unit = {}
) {
    NavHost(
        navController = navController,
        startDestination = "home",
        modifier = modifier
    ) {
        composable("home") {
            HomeScreen(
                onOpenVideo = { id -> navController.navigate("player/$id") },
                onOpenShorts = { id -> navController.navigate("shorts/$id") },
                onOpenPlaylist = { id -> navController.navigate("playlist/${id.encode()}") },
                onOpenChannel = { name -> navController.navigate("channel/${name.encode()}") }
            )
        }
        // Отдельный маршрут для ленты Shorts: в вебе клик по «Shorts» в меню
        // открывает случайный непросмотренный ролик.
        composable("shorts_feed") {
            ShortsScreen(startId = "", onBack = { navController.popBackStack() })
        }
        composable("search") {
            SearchScreen(onOpenVideo = { id -> navController.navigate("player/$id") })
        }
        composable("favorites") {
            HistoryScreen(
                mode = HistoryScreen.Mode.FAVORITES,
                onOpenVideo = { id -> navController.navigate("player/$id") }
            )
        }
        composable("history") {
            HistoryScreen(
                mode = HistoryScreen.Mode.HISTORY,
                onOpenVideo = { id -> navController.navigate("player/$id") }
            )
        }
        composable("downloads") {
            DownloadsScreen(
                initialUrl = pendingUrl,
                onInitialUrlConsumed = onPendingUrlConsumed
            )
        }
        composable("myvideos") {
            MyVideosScreen(onOpenVideo = { id -> navController.navigate("player/$id") })
        }
        composable("collections") {
            CollectionsScreen(
                onOpenCollection = { id -> navController.navigate("collection/$id") }
            )
        }
        composable(
            "subtitles/{videoId}",
            arguments = listOf(navArgument("videoId") { type = NavType.StringType })
        ) { entry ->
            SubtitlesScreen(
                videoId = entry.arguments?.getString("videoId").orEmpty(),
                onBack = { navController.popBackStack() }
            )
        }
        composable(
            "collection/{collectionId}",
            arguments = listOf(navArgument("collectionId") { type = NavType.StringType })
        ) { entry ->
            val id = entry.arguments?.getString("collectionId").orEmpty()
            CollectionDetailScreen(
                collectionId = id,
                onBack = { navController.popBackStack() },
                // Плеер получает id плейлиста: после конца видео он ведёт по
                // списку, как ?collection=<id> на ПК.
                onOpenVideo = { vid -> navController.navigate("player/$vid?collection=$id") }
            )
        }
        composable("settings") {
            SettingsScreen()
        }
        composable(
            // collection необязателен: тот же маршрут открывается и с плейлистом,
            // и без него, как /video/<id>[?collection=<id>] на ПК.
            "player/{videoId}?collection={collectionId}",
            arguments = listOf(
                navArgument("videoId") { type = NavType.StringType },
                navArgument("collectionId") {
                    type = NavType.StringType
                    defaultValue = ""
                }
            )
        ) { entry ->
            val id = entry.arguments?.getString("videoId").orEmpty()
            val collectionId = entry.arguments?.getString("collectionId").orEmpty()
            PlayerScreen(
                videoId = id,
                collectionId = collectionId,
                onBack = { navController.popBackStack() },
                onOpenVideo = { next ->
                    val suffix = if (collectionId.isBlank()) "" else "?collection=$collectionId"
                    navController.navigate("player/$next$suffix") { launchSingleTop = true }
                },
                onOpenChannel = { name -> navController.navigate("channel/${name.encode()}") },
                onOpenSubtitles = { navController.navigate("subtitles/$id") }
            )
        }
        composable(
            "shorts/{videoId}",
            arguments = listOf(navArgument("videoId") { type = NavType.StringType })
        ) { entry ->
            val id = entry.arguments?.getString("videoId").orEmpty()
            ShortsScreen(startId = id, onBack = { navController.popBackStack() })
        }
        composable(
            "playlist/{playlistId}",
            arguments = listOf(navArgument("playlistId") { type = NavType.StringType })
        ) { entry ->
            val id = entry.arguments?.getString("playlistId").orEmpty()
            PlaylistScreen(
                playlistId = id.decode(),
                onBack = { navController.popBackStack() },
                onOpenVideo = { vid -> navController.navigate("player/$vid") }
            )
        }
        composable(
            "channel/{author}",
            arguments = listOf(navArgument("author") { type = NavType.StringType })
        ) { entry ->
            val name = entry.arguments?.getString("author").orEmpty()
            ChannelScreen(
                author = name.decode(),
                onBack = { navController.popBackStack() },
                onOpenVideo = { id -> navController.navigate("player/$id") },
                onOpenShorts = { id -> navController.navigate("shorts/$id") }
            )
        }
    }
}

/** Имя канала может содержать слэши и пробелы, поэтому кодируем его. */
private fun String.encode(): String = java.net.URLEncoder.encode(this, "UTF-8")

private fun String.decode(): String =
    runCatching { java.net.URLDecoder.decode(this, "UTF-8") }.getOrDefault(this)
