package io.github.kiramorano.localtube.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.vm.UploadViewModel

@Composable
fun UploadScreen(vm: UploadViewModel = viewModel()) {
    val videoPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { vm.setVideo(it) }
    }
    val thumbPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { vm.setThumb(it) }
    }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)
    ) {
        Text("Загрузка своего видео", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = vm.title,
            onValueChange = { vm.title = it },
            label = { Text("Название") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = vm.username,
            onValueChange = { vm.username = it },
            label = { Text("Автор") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = vm.description,
            onValueChange = { vm.description = it },
            label = { Text("Описание") },
            minLines = 3,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(16.dp))
        OutlinedButton(
            onClick = { videoPicker.launch(arrayOf("video/*")) },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text(vm.videoName ?: "Выбрать видеофайл")
        }
        if (vm.videoName != null) {
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = { thumbPicker.launch(arrayOf("image/*")) },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(vm.thumbName ?: "Выбрать обложку (необязательно)")
            }
        }
        Spacer(Modifier.height(16.dp))
        Button(
            onClick = { vm.upload() },
            enabled = vm.videoName != null && !vm.uploading,
            modifier = Modifier.fillMaxWidth()
        ) {
            if (vm.uploading) {
                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
            } else {
                Text("Загрузить на сервер")
            }
        }
        vm.status?.let {
            Spacer(Modifier.height(12.dp))
            Text(it, modifier = Modifier.align(Alignment.CenterHorizontally))
        }
    }
}
