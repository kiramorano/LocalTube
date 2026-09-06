package io.github.kiramorano.localtube

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalConfiguration
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.kiramorano.localtube.ui.AppRoot
import io.github.kiramorano.localtube.ui.theme.LocalTubeTheme
import io.github.kiramorano.localtube.ui.theme.LtBreakpoints

class MainActivity : ComponentActivity() {

    private var sharedUrl by mutableStateOf<String?>(null)

    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sharedUrl = extractSharedUrl(intent)

        val settings = LocalTubeApp.from(this).repository.settings
        val isTv = isTelevision()
        requestNotificationPermission(isTv)

        setContent {
            // Тема читается из StateFlow: раньше значение брали один раз, и
            // переключатель в настройках срабатывал лишь после перезапуска.
            val theme by settings.themeFlow.collectAsStateWithLifecycle()
            // Узкий экран: карточки и отступы уменьшаются, иначе на телефоне
            // в сетку влезает одна колонка. Порог общий с AppRoot, чтобы
            // раскладка не расходилась сама с собой на планшете.
            val compact = LtBreakpoints.isCompact(LocalConfiguration.current.screenWidthDp)
            LocalTubeTheme(theme = theme, isTv = isTv, compact = compact) {
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

    /**
     * Разрешение на уведомления о загрузках. Без запроса на Android 13+ оно
     * считается отклонённым, и переключатель уведомлений в настройках ничего
     * не давал: notify() молча ничего не делал.
     */
    private fun requestNotificationPermission(isTv: Boolean) {
        if (isTv) return
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            runCatching { notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS) }
        }
    }

    /** Ссылка, отправленная в приложение через «Поделиться». */
    private fun extractSharedUrl(intent: Intent?): String? {
        if (intent?.action != Intent.ACTION_SEND) return null
        val text = intent.getStringExtra(Intent.EXTRA_TEXT) ?: return null
        return Regex("""https?://\S+""").find(text)?.value
    }

    private fun isTelevision(): Boolean {
        if (packageManager.hasSystemFeature(PackageManager.FEATURE_LEANBACK)) return true
        if (packageManager.hasSystemFeature("android.software.leanback_only")) return true
        val uiMode = resources.configuration.uiMode and Configuration.UI_MODE_TYPE_MASK
        return uiMode == Configuration.UI_MODE_TYPE_TELEVISION
    }
}
