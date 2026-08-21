package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.ui.components.VideoGrid
import io.github.kiramorano.localtube.vm.SearchViewModel

@Composable
fun SearchScreen(
    onOpenVideo: (String) -> Unit,
    vm: SearchViewModel = viewModel()
) {
    val userData by vm.userData.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.reload() }

    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = vm.query,
            onValueChange = vm::onQuery,
            label = { Text("Поиск по библиотеке") },
            leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
            singleLine = true,
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp)
        )
        val results = vm.results
        when {
            vm.loading -> LoadingBox()
            vm.query.isBlank() -> EmptyBox("Введите название видео или имя канала")
            // Пустой список — это именно «ничего не найдено», а не отсутствие запроса.
            results != null && results.isEmpty() -> EmptyBox("Ничего не найдено")
            results != null -> {
                Text(
                    "Найдено: ${results.size}",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 16.dp)
                )
                VideoGrid(
                    items = results,
                    onOpen = onOpenVideo,
                    favorites = userData.favorites.toSet()
                )
            }
            else -> EmptyBox("Введите название видео или имя канала")
        }
    }
}
