package io.github.kiramorano.localtube

import android.app.Application
import android.util.Log
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import io.github.kiramorano.localtube.data.Repository

class LocalTubeApp : Application() {
    lateinit var repository: Repository
        private set

    override fun onCreate() {
        super.onCreate()
        repository = Repository(this)
        try {
            YoutubeDL.getInstance().init(this)
            FFmpeg.getInstance().init(this)
        } catch (e: YoutubeDLException) {
            Log.e("LocalTube", "failed to initialize youtubedl-android", e)
        }
    }

    companion object {
        @JvmStatic
        fun from(context: android.content.Context): LocalTubeApp =
            context.applicationContext as LocalTubeApp
    }
}
