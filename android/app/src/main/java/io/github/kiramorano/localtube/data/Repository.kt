package io.github.kiramorano.localtube.data

import android.app.Application

class Repository(app: Application) {
    val settings = Settings(app)
    val library = Library(app)
    val downloads = DownloadManager(app, library, settings)
}
