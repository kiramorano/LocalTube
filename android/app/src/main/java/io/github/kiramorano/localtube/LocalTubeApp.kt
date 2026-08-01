package io.github.kiramorano.localtube

import android.app.Application
import io.github.kiramorano.localtube.data.ServerManager

class LocalTubeApp : Application() {
    override fun onCreate() {
        super.onCreate()
        ServerManager.init(this)
    }
}
