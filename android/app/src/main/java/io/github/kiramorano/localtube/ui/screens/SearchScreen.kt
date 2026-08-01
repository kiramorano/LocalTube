package io.github.kiramorano.localtube.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.ui.components.ErrorBox
import io.github.kiramorano.localtube.ui.components.LoadingBox
import io.github.kiramorano.localtube.ui.components.VideoGrid
import io.github.kiramorano.localtube.vm.SearchViewModel

@Composable
fun SearchScreen(
    onOpenVideo: (String) -> Unit,
    vm: SearchViewModel = viewModel()
) {
    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = vm.query,
            onValueChange = { vm.onQuery(it) },
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            placeholder = { Text("Поиск по названию или автору") },
            singleLine = true
        )
        when {
            vm.loading -> LoadingBox()
            vm.error != null -> ErrorBox(vm.error!!) { vm.onQuery(vm.query) }
            vm.results != null -> VideoGrid(vm.results!!, onOpenVideo)
            else -> EmptyBox("Введите запрос для поиска")
        }
    }
}
