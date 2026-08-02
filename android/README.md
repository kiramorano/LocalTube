# LocalTube Android

Автономное Android-приложение LocalTube (начиная с v3.0.0). Не требует сервера: yt-dlp + FFmpeg встроены в APK.

Возможности:
- Скачивание видео по ссылке с выбором формата (в т.ч. видео+аудио, аудио).
- Автоматические субтитры.
- Плейлисты и Shorts.
- Свои видео (загрузка файла, редактирование, удаление).
- Офлайн-каталог: видео, каналы, поиск, рекомендации.
- Тёмная тема, уведомления о загрузках.

## Сборка

Сборка из папки без кириллицы в пути (например `C:\lt_android`). Кэш Gradle — в `GRADLE_USER_HOME`. Требуется JDK (Android Studio JBR) и Android SDK.

```bat
set JAVA_HOME=C:\Program Files\Android\Android Studio\jbr
set GRADLE_USER_HOME=C:\lt_gradle
gradlew :app:assembleRelease
```

Релизная подпись: `app/keystore.jks`, переменные окружения `LT_STORE_PASSWORD`, `LT_KEY_ALIAS`, `LT_KEY_PASSWORD`.
