package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.ui.components.VideoGrid
import io.github.kiramorano.localtube.vm.SearchViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchScreen(
    onOpenVideo: (String) -> Unit,
    vm: SearchViewModel = viewModel()
) {
    LaunchedEffect(Unit) { vm.reload() }
    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = vm.query,
            onValueChange = vm::onQuery,
            placeholder = { Text("Поиск по каталогу") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(12.dp)
        )
        val results = vm.results
        when {
            vm.loading && results == null -> Text("Поиск...", modifier = Modifier.padding(16.dp))
            vm.query.isBlank() -> EmptyBox("Найдите видео по названию или каналу")
            results == null -> EmptyBox("Ничего не найдено")
            else -> VideoGrid(results, onOpenVideo)
        }
    }
}
