# 🚀 Установка FFmpeg (обязательно)

Этот проект требует FFmpeg для склейки видео. Установите его одним из способов:

### Windows
1. Скачайте FFmpeg с официального сайта: https://ffmpeg.org/download.html
2. Распакуйте архив в папку `C:\ffmpeg`
3. Добавьте `C:\ffmpeg\bin` в переменную PATH (инструкция: https://www.ffmpeg.org/download.html#build-windows)

### Linux (Ubuntu/Debian)
```bash
sudo apt install ffmpeg -y
```

## Сборки и платформы

При публикации тега `v1.7` GitHub Actions создаёт настоящие desktop-пакеты для Windows x64 и Linux x64 и прикрепляет их к GitHub Release. Исходный код также доступен в автоматически созданных GitHub source archives. APK/Android TV APK не выпускаются: в репозитории нет Android/TV-проекта и нативного мобильнного рантайма для Python/Flask/FFmpeg.

��рлодробности установки и ограничений: [docs/PLATFORMS.md](docs/PLATFORMS.md).
