package io.github.kiramorano.localtube

import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.kiramorano.localtube.ui.AppRoot
import io.github.kiramorano.localtube.ui.theme.LocalTubeTheme

class MainActivity : ComponentActivity() {

    private var sharedUrl by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sharedUrl = extractSharedUrl(intent)

        val settings = LocalTubeApp.from(this).repository.settings
        val isTv = isTelevision()

        setContent {
            // Тема читается из StateFlow: раньше значение брали один раз, и
            // переключатель в настройках срабатывал лишь после перезапуска.
            val theme by settings.themeFlow.collectAsStateWithLifecycle()
            LocalTubeTheme(theme = theme, isTv = isTv) {
                AppRoot(
                    isTv = isTv,
                    sharedUrl = sharedUrl,
                    onSharedUrlHandled = { sharedUrl = null }
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        extractSharedUrl(intent)?.let { sharedUrl = it }
    }

    /** Ссылка, отправленная в приложение через «Поделиться». */
    private fun extractSharedUrl(intent: Intent?): String? {
        if (intent?.action != Intent.ACTION_SEND) return null
        val text = intent.getStringExtra(Intent.EXTRA_TEXT) ?: return null
        return Regex("""https?://\S+""").find(text)?.value
    }

    private fun isTelevision(): Boolean {
        if (packageManager.hasSystemFeature(PackageManager.FEATURE_LEANBACK)) return true
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP &&
            packageManager.hasSystemFeature("android.software.leanback_only")
        ) return true
        val uiMode = resources.configuration.uiMode and Configuration.UI_MODE_TYPE_MASK
        return uiMode == Configuration.UI_MODE_TYPE_TELEVISION
    }
}
