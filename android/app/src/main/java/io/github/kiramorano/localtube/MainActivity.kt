package io.github.kiramorano.localtube

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import io.github.kiramorano.localtube.ui.AppRoot
import io.github.kiramorano.localtube.ui.theme.LocalTubeTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val dark = LocalTubeApp.from(this).repository.settings.darkTheme
            LocalTubeTheme(darkTheme = dark) {
                AppRoot()
            }
        }
    }
}
