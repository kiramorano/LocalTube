package io.github.kiramorano.localtube.data

import android.app.Application
import java.io.File

/** Контейнер зависимостей: один экземпляр на приложение. */
class Repository(app: Application) {
    val settings = Settings(app)
    val library = Library(app, resolveStorage(app, settings))
    val userData = UserDataStore(app)
    val downloads = DownloadManager(app, library, settings)
    val media = MediaProcessor(app, library)
    val subtitles = SubtitleManager(app, library, settings)
    val channels = ChannelSync(app, library, settings, downloads)
    val lan = LanSharing(app, library, userData, settings)

    companion object {
        /**
         * Корень библиотеки: карта памяти, если она выбрана в настройках и
         * доступна. Проверяем доступность каждый запуск — карту могли вынуть,
         * и тогда молча возвращаемся во внутреннюю память вместо падения на
         * каждой файловой операции.
         */
        private fun resolveStorage(app: Application, settings: Settings): File? {
            if (!settings.externalStorage) return null
            // Первый элемент — внутренняя память, поэтому берём со второго:
            // именно там лежат съёмные носители.
            val external = runCatching {
                app.getExternalFilesDirs(null).drop(1).firstOrNull { dir ->
                    dir != null && (dir.isDirectory || dir.mkdirs()) && dir.canWrite()
                }
            }.getOrNull()
            return external
        }
    }
}
