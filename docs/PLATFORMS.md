# Платформы и артефакты релизов

LocalTube состоит из двух частей: серверного приложения на Python/Flask и автономного Android-клиента.

## Desktop и сервер

Приложение на Python/Flask. Интерфейс отдаётся локально через `app.py`, для обработки медиа нужен `ffmpeg` в `PATH`.

Публикация тега вида `v*` запускает workflow сборки релиза. К GitHub Release прикрепляются пакеты PyInstaller (`onedir`) для пяти целей:

| Артефакт | Платформа сборки |
|---|---|
| `LocalTube-windows-x64.zip` | windows-2022 |
| `LocalTube-windows-x86.zip` | windows-2022 |
| `LocalTube-linux-x64.tar.gz` | ubuntu-22.04 |
| `LocalTube-macos-x64.tar.gz` | macos-13 (Intel) |
| `LocalTube-macos-arm64.tar.gz` | macos-14 (Apple Silicon) |

Плюс автоматически создаваемые GitHub архивы исходного кода (ZIP и TAR.GZ).

Как запустить: распакуйте архив, убедитесь что `ffmpeg` доступен в `PATH`, затем запустите `LocalTube.exe` на Windows или `./LocalTube/LocalTube` на Linux и macOS. В пакет входят шаблоны Flask, статические файлы, конфигурация по умолчанию и данные времени выполнения `yt-dlp`. Медиафайлы и рабочие файлы создаются рядом с данными приложения.

Сборки macOS не подписаны и не нотаризованы, поэтому при первом запуске Gatekeeper их заблокирует. Обойти можно через «Системные настройки → Конфиденциальность и безопасность → Всё равно открыть».

## Android

Начиная с `v3.0.0` выпускается автономное приложение. Сервер ему не нужен: `yt-dlp` и `FFmpeg` встроены в APK через `youtubedl-android`, видео скачиваются прямо на устройство.

| Артефакт | Для кого |
|---|---|
| `app-arm64-v8a-release.apk` | большинство современных телефонов |
| `app-universal-release.apk` | универсальный, если предыдущий не установился |

Реализация: Kotlin, Jetpack Compose, Material 3, плеер на Media3/ExoPlayer. Минимальная версия Android — 7.0 (API 24), целевая — API 35. Собирается для `arm64-v8a` и `armeabi-v7a` через ABI splits; product flavors в проекте нет.

Сборка из исходников требует JDK 17 и Android SDK 35:

```bash
cd android
./gradlew assembleRelease
```

Если рядом лежит `android/app/keystore.jks`, применяется подпись release с паролями из переменных окружения `LT_STORE_PASSWORD`, `LT_KEY_ALIAS`, `LT_KEY_PASSWORD`. Без keystore APK собирается неподписанным.

## Что не собирается

Приложения для iOS и пакеты для Android TV не выпускаются. Для Android TV нужна отдельная навигация под пульт (D-pad) и лончер-баннер, для iOS — платная учётная запись разработчика и решения по распространению.
