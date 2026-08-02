package io.github.kiramorano.localtube.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import io.github.kiramorano.localtube.ui.screens.DownloadsScreen
import io.github.kiramorano.localtube.ui.screens.HomeScreen
import io.github.kiramorano.localtube.ui.screens.MyVideosScreen
import io.github.kiramorano.localtube.ui.screens.PlayerScreen
import io.github.kiramorano.localtube.ui.screens.PlaylistScreen
import io.github.kiramorano.localtube.ui.screens.SearchScreen
import io.github.kiramorano.localtube.ui.screens.SettingsScreen
import io.github.kiramorano.localtube.ui.screens.ShortsScreen

@Composable
fun AppRoot() {
    val navController = rememberNavController()
    val backStack by navController.currentBackStackEntryAsState()
    val route = backStack?.destination?.route
    val showBar = route != "player/{videoId}" &&
        route != "shorts/{videoId}" &&
        route != "playlist/{playlistId}"

    Scaffold(
        bottomBar = {
            if (showBar) {
                NavigationBar {
                    NavigationBarItem(
                        selected = route == "home",
                        onClick = {
                            navController.navigate("home") {
                                popUpTo("home") { inclusive = true }
                                launchSingleTop = true
                            }
                        },
                        icon = { Icon(Icons.Filled.Home, contentDescription = null) },
                        label = { Text("Главная") }
                    )
                    NavigationBarItem(
                        selected = route == "search",
                        onClick = { navController.navigate("search") { popUpTo("home"); launchSingleTop = true } },
                        icon = { Icon(Icons.Filled.Search, contentDescription = null) },
                        label = { Text("Поиск") }
                    )
                    NavigationBarItem(
                        selected = route == "downloads",
                        onClick = { navController.navigate("downloads") { popUpTo("home"); launchSingleTop = true } },
                        icon = { Icon(Icons.AutoMirrored.Filled.List, contentDescription = null) },
                        label = { Text("Загрузки") }
                    )
                    NavigationBarItem(
                        selected = route == "myvideos",
                        onClick = { navController.navigate("myvideos") { popUpTo("home"); launchSingleTop = true } },
                        icon = { Icon(Icons.AutoMirrored.Filled.Send, contentDescription = null) },
                        label = { Text("Моё") }
                    )
                    NavigationBarItem(
                        selected = route == "settings",
                        onClick = { navController.navigate("settings") { popUpTo("home"); launchSingleTop = true } },
                        icon = { Icon(Icons.Filled.Settings, contentDescription = null) },
                        label = { Text("Настройки") }
                    )
                }
            }
        }
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = "home",
            modifier = Modifier.padding(padding)
        ) {
            composable("home") {
                HomeScreen(
                    onOpenVideo = { id -> navController.navigate("player/$id") },
                    onOpenShorts = { id -> navController.navigate("shorts/$id") },
                    onOpenPlaylist = { id -> navController.navigate("playlist/$id") }
                )
            }
            composable("search") {
                SearchScreen(onOpenVideo = { id -> navController.navigate("player/$id") })
            }
            composable("downloads") {
                DownloadsScreen()
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
                PlayerScreen(videoId = id, onBack = { navController.popBackStack() })
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
                PlaylistScreen(playlistId = id, onBack = { navController.popBackStack() }, onOpenVideo = { vid -> navController.navigate("player/$vid") })
            }
        }
    }
}
