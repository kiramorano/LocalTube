@echo off
title LocalTube – Установка всех зависимостей
echo ============================================================
echo   Установка компонентов для LocalTube NEO
echo ============================================================
echo.

:: 1. Обновление pip
echo [1/6] Обновление pip...
python -m pip install --upgrade pip
if %errorlevel% neq 0 echo Ошибка при обновлении pip & goto :pause_exit
echo.

:: 2. Установка Python-пакетов (flask, yt-dlp, requests)
echo [2/6] Установка Flask, yt-dlp, requests...
pip install --upgrade flask yt-dlp requests
if %errorlevel% neq 0 echo Ошибка при установке пакетов & goto :pause_exit
echo.

:: 3. Установка Deno (нужен для решения JS-задач YouTube)
echo [3/6] Установка Deno...
where deno >nul 2>nul
if %errorlevel% equ 0 (
    echo Deno уже установлен: & deno --version
) else (
    echo Deno не найден. Пытаемся установить...
    where winget >nul 2>nul
    if %errorlevel% equ 0 (
        echo Установка через winget...
        winget install DenoLand.Deno --silent --accept-package-agreements
        if %errorlevel% equ 0 ( echo Deno успешно установлен. ) else ( echo Не удалось установить Deno через winget. )
    ) else (
        echo winget не доступен. Пытаемся через PowerShell...
        powershell -Command "irm https://deno.land/install.ps1 | iex"
        if %errorlevel% equ 0 ( echo Deno установлен через PowerShell. ) else ( echo Ошибка установки Deno. Установите вручную: https://deno.com/ )
    )
)
echo.

:: 4. Установка ffmpeg (для создания превью)
echo [4/6] Установка ffmpeg (требуется для генерации превью)...
where ffmpeg >nul 2>nul
if %errorlevel% equ 0 (
    echo ffmpeg уже установлен.
) else (
    where winget >nul 2>nul
    if %errorlevel% equ 0 (
        echo Установка ffmpeg через winget...
        winget install Gyan.FFmpeg --silent --accept-package-agreements
        if %errorlevel% equ 0 ( echo ffmpeg установлен. ) else ( echo Не удалось установить ffmpeg. Установите вручную.)
    ) else (
        echo winget не доступен, установите ffmpeg вручную с https://ffmpeg.org/download.html
    )
)
echo.

:: 5. Проверка файла cookies.txt
echo [5/6] Проверка cookies.txt...
if not exist "cookies.txt" (
    echo ВНИМАНИЕ: файл cookies.txt не найден.
    echo Для скачивания видео в высоком качестве и обхода возрастных ограничений
    echo экспортируйте cookies из браузера (расширение "Get cookies.txt") и поместите в папку проекта.
    echo Создаю пустой файл-заглушку cookies.txt...
    echo # Place your cookies here > cookies.txt
) else (
    echo cookies.txt найден.
)
echo.

:: 6. Финальная информация
echo [6/6] Проверка установленных версий:
echo.
python --version
echo.
deno --version 2>nul || echo Deno не установлен или не добавлен в PATH.
echo.
yt-dlp --version
echo.
ffmpeg -version 2>nul | findstr "ffmpeg version" || echo ffmpeg не найден в PATH.

echo.
echo ============================================================
echo Установка завершена.
echo Рекомендации:
echo   - Если Deno не установился автоматически, скачайте с https://deno.com/
echo   - Для ffmpeg: добавьте папку с ffmpeg.exe в переменную PATH.
echo   - Перезапустите командную строку, затем запустите python app.py
echo ============================================================
:pause_exit
pause