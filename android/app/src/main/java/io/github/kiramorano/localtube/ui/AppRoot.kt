package io.github.kiramorano.localtube.ui

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import io.github.kiramorano.localtube.ui.screens.ChannelScreen
import io.github.kiramorano.localtube.ui.screens.DownloadsScreen
import io.github.kiramorano.localtube.ui.screens.HistoryScreen
import io.github.kiramorano.localtube.ui.screens.HomeScreen
import io.github.kiramorano.localtube.ui.screens.MyVideosScreen
import io.github.kiramorano.localtube.ui.screens.PlayerScreen
import io.github.kiramorano.localtube.ui.screens.PlaylistScreen
import io.github.kiramorano.localtube.ui.screens.SearchScreen
import io.github.kiramorano.localtube.ui.screens.SettingsScreen
import io.github.kiramorano.localtube.ui.screens.ShortsScreen

private data class Destination(
    val route: String,
    val label: String,
    val icon: ImageVector
)

private val destinations = listOf(
    Destination("home", "Главная", Icons.Filled.Home),
    Destination("search", "Поиск", Icons.Filled.Search),
    Destination("favorites", "Избранное", Icons.Filled.Star),
    Destination("history", "История", Icons.Filled.History),
    Destination("downloads", "Загрузки", Icons.Filled.Download),
    Destination("myvideos", "Моё", Icons.Filled.VideoLibrary),
    Destination("settings", "Настройки", Icons.Filled.Settings)
)

/** Экраны на весь экран: без панели навигации. */
private val fullScreenRoutes = setOf(
    "player/{videoId}", "shorts/{videoId}", "playlist/{playlistId}", "channel/{author}"
)

@Composable
fun AppRoot(
    isTv: Boolean = false,
    sharedUrl: String? = null,
    onSharedUrlHandled: () -> Unit = {}
) {
    val navController = rememberNavController()
    val backStack by navController.currentBackStackEntryAsState()
    val route = backStack?.destination?.route
    val showNav = route !in fullScreenRoutes

    // Ссылка из «Поделиться» открывает экран загрузок.
    LaunchedEffect(sharedUrl) {
        if (!sharedUrl.isNullOrBlank()) {
            navController.navigate("downloads") { launchSingleTop = true }
        }
    }

    val configuration = LocalConfiguration.current
    // На телевизоре и планшете боковая панель: на широком экране нижняя панель
    // отрезает содержимое и до неё далеко тянуться пультом.
    val useRail = isTv || configuration.screenWidthDp >= 600

    if (useRail) {
        Row(Modifier.fillMaxSize()) {
            if (showNav) {
                NavigationRail {
                    destinations.forEach { d ->
                        NavigationRailItem(
                            selected = route == d.route,
                            onClick = { navController.navigateTab(d.route) },
                            icon = { Icon(d.icon, contentDescription = d.label) },
                            label = { Text(d.label) }
                        )
                    }
                }
            }
            AppNavHost(navController, Modifier.fillMaxSize(), sharedUrl)
        }
    } else {
        Scaffold(
            bottomBar = {
                if (showNav) {
                    NavigationBar {
                        // На телефоне семь пунктов не поместятся: часть разделов
                        // доступна с главной, в панели оставляем основные.
                        destinations.filter { it.route in phoneTabs }.forEach { d ->
                            NavigationBarItem(
                                selected = route == d.route,
                                onClick = { navController.navigateTab(d.route) },
                                icon = { Icon(d.icon, contentDescription = d.label) },
                                label = { Text(d.label) }
                            )
                        }
                    }
                }
            }
        ) { padding ->
            AppNavHost(navController, Modifier.padding(padding), sharedUrl)
        }
    }

    LaunchedEffect(route) {
        if (route == "downloads" && !sharedUrl.isNullOrBlank()) onSharedUrlHandled()
    }
}

private val phoneTabs = setOf("home", "search", "downloads", "myvideos", "settings")

private fun NavHostController.navigateTab(route: String) {
    navigate(route) {
        popUpTo(graph.startDestinationId) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}

@Composable
private fun AppNavHost(
    navController: NavHostController,
    modifier: Modifier,
    sharedUrl: String? = null
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
                onOpenPlaylist = { id -> navController.navigate("playlist/$id") },
                onOpenChannel = { name -> navController.navigate("channel/${name.encode()}") }
            )
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
            DownloadsScreen(initialUrl = sharedUrl)
        }
        composable("myvideos") {
            MyVideosScreen(onOpenVideo = { id -> navController.navigate("player/$id") })
        }
        composable("settings") {
            SettingsScreen()
        }
        composable(
            "player/{videoId}",
            arguments = listOf(navArgument("videoId") { type = NavType.StringType })
        ) { entry ->
            val id = entry.arguments?.getString("videoId").orEmpty()
            PlayerScreen(
                videoId = id,
                onBack = { navController.popBackStack() },
                onOpenVideo = { next ->
                    navController.navigate("player/$next") { launchSingleTop = true }
                },
                onOpenChannel = { name -> navController.navigate("channel/${name.encode()}") }
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
                playlistId = id,
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

/** Имя канала может содержать слэши и пробелы, поэтому кодируем его в маршруте. */
private fun String.encode(): String = java.net.URLEncoder.encode(this, "UTF-8")

private fun String.decode(): String =
    runCatching { java.net.URLDecoder.decode(this, "UTF-8") }.getOrDefault(this)
