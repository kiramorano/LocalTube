# LocalTube Android

Автономное приложение: сервер LocalTube ему не нужен. `yt-dlp` и `FFmpeg` встроены в APK через [youtubedl-android](https://github.com/JunkFood02/youtubedl-android), видео скачиваются и хранятся прямо на устройстве во внутренней памяти приложения.

## Возможности

- Каталог с вкладками: Видео, Shorts, Каналы, Плейлисты, Моё
- Поиск по локальной библиотеке
- Загрузка по ссылке: запрос доступных форматов, выбор качества, очередь с прогрессом в уведомлении и отменой
- Плеер на Media3/ExoPlayer с локальными субтитрами и полосой рекомендаций
- Вертикальная лента Shorts
- Свои видео: добавление, правка, удаление
- Импорт `cookies.txt` через системный файловый выбор
- Обновление `yt-dlp` из приложения

## Стек

Kotlin 2.0.21, Jetpack Compose (Material 3), Media3 1.5.1, OkHttp, Coil. `minSdk 24` (Android 7.0), `targetSdk 35`.

## Сборка

Нужны JDK 17 и Android SDK 35. Gradle wrapper в комплекте.

```bash
./gradlew assembleDebug      # отладочная
./gradlew assembleRelease    # релизная
```

APK появятся в `app/build/outputs/apk/`. Собираются варианты для `arm64-v8a`, `armeabi-v7a` и универсальный (ABI splits, product flavors в проекте нет).

Подпись: если рядом лежит `app/keystore.jks`, применяется конфигурация release с паролями из переменных окружения `LT_STORE_PASSWORD`, `LT_KEY_ALIAS`, `LT_KEY_PASSWORD`. Без keystore APK собирается неподписанным — такой можно установить только с разрешением на установку из неизвестных источников.

Готовые сборки — во вкладке [Releases](https://github.com/kiramorano/LocalTube/releases).
