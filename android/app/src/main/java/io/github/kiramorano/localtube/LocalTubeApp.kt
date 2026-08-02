package io.github.kiramorano.localtube

import android.app.Application
import android.util.Log
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import io.github.kiramorano.localtube.data.Engine
import io.github.kiramorano.localtube.data.Repository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class LocalTubeApp : Application() {
    lateinit var repository: Repository
        private set

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()
        repository = Repository(this)
        try {
            YoutubeDL.getInstance().init(this)
            FFmpeg.getInstance().init(this)
        } catch (e: YoutubeDLException) {
            Log.e("LocalTube", "failed to initialize youtubedl-android", e)
        }
        appScope.launch {
            try {
                val ctx = this@LocalTubeApp
                Engine.ensureYtDlpFresh(ctx, Engine.appVersion(ctx))
            } catch (e: Exception) {
                Log.e("LocalTube", "yt-dlp update failed", e)
            }
        }
    }

    companion object {
        @JvmStatic
        fun from(context: android.content.Context): LocalTubeApp =
            context.applicationContext as LocalTubeApp
    }
}
