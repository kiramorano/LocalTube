@echo off
title LocalTube NEO
echo ==========================================
echo   Запуск LocalTube NEO
echo ==========================================
echo.

cd /d "%~dp0"

echo Запуск LocalTube...
echo Откройте в браузере: http://127.0.0.1:80
python app.py

pause