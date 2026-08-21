package io.github.kiramorano.localtube.data

import android.app.Application

/** Контейнер зависимостей: один экземпляр на приложение. */
class Repository(app: Application) {
    val settings = Settings(app)
    val library = Library(app)
    val userData = UserDataStore(app)
    val downloads = DownloadManager(app, library, settings)
}
