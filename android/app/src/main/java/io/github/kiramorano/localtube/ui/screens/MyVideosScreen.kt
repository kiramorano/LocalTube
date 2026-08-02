package io.github.kiramorano.localtube.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.kiramorano.localtube.data.VideoItem
import io.github.kiramorano.localtube.ui.components.AsyncThumb
import io.github.kiramorano.localtube.ui.components.EmptyBox
import io.github.kiramorano.localtube.vm.MyVideosViewModel

@Composable
fun MyVideosScreen(
    onOpenVideo: (String) -> Unit,
    vm: MyVideosViewModel = viewModel()
) {
    LaunchedEffect(Unit) { vm.load() }
    val videoPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { vm.setVideo(it) }
    }
    var editing by remember { mutableStateOf<VideoItem?>(null) }

    Column(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxWidth().padding(12.dp)) {
            Text("Мои видео", style = MaterialTheme.typography.titleLarge)
            if (vm.videoUri != null) {
                UploadForm(vm)
            } else {
                FilledTonalButton(onClick = { videoPicker.launch(arrayOf("video/*")) }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.Add, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Добавить видео")
                }
            }
        }
        if (vm.videos.isEmpty()) {
            EmptyBox("Вы ещё не добавили видео")
        } else {
            LazyColumn(Modifier.weight(1f)) {
                items(vm.videos, key = { it.id }) { v ->
                    MyVideoRow(v, onOpen = { onOpenVideo(v.id) }, onDelete = { vm.delete(v.id) }, onEdit = { editing = v })
                }
            }
        }
    }

    editing?.let { v ->
        EditDialog(
            initialTitle = v.title,
            initialDesc = v.description,
            onDismiss = { editing = null },
            onSave = { t, d ->
                vm.edit(v.id, t, d)
                editing = null
            }
        )
    }
}

@Composable
private fun UploadForm(vm: MyVideosViewModel) {
    Column(Modifier.fillMaxWidth()) {
        OutlinedTextField(
            value = vm.title,
            onValueChange = { vm.title = it },
            label = { Text("Название") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = vm.author,
            onValueChange = { vm.author = it },
            label = { Text("Автор") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = vm.description,
            onValueChange = { vm.description = it },
            label = { Text("Описание") },
            minLines = 2,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(8.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Button(onClick = { vm.upload() }, enabled = !vm.uploading, modifier = Modifier.weight(1f)) {
                if (vm.uploading) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                } else {
                    Text("Сохранить")
                }
            }
            Spacer(Modifier.width(8.dp))
            TextButton(onClick = { vm.cancelUpload() }) { Text("Отмена") }
        }
        vm.status?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable
private fun MyVideoRow(v: VideoItem, onOpen: () -> Unit, onDelete: () -> Unit, onEdit: () -> Unit) {
    Card(
        onClick = onOpen,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)
    ) {
        Row(Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            AsyncThumb(v.thumb, Modifier.size(96.dp, 54.dp))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(v.title, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(v.author, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = onEdit) {
                Icon(Icons.Filled.Edit, contentDescription = "Изменить")
            }
            IconButton(onClick = onDelete) {
                Icon(Icons.Filled.Delete, contentDescription = "Удалить")
            }
        }
    }
}

@Composable
private fun EditDialog(initialTitle: String, initialDesc: String, onDismiss: () -> Unit, onSave: (String, String) -> Unit) {
    var title by remember { mutableStateOf(initialTitle) }
    var desc by remember { mutableStateOf(initialDesc) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Изменить видео") },
        text = {
            Column {
                OutlinedTextField(value = title, onValueChange = { title = it }, label = { Text("Название") }, singleLine = true)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(value = desc, onValueChange = { desc = it }, label = { Text("Описание") }, minLines = 2)
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(title, desc) }) { Text("Сохранить") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Отмена") }
        }
    )
}
