#!/usr/bin/env python3
"""
download_video.py – скачивает одно видео или плейлист с YouTube.
Использование:
    python download_video.py --url "https://..." [--format "137+140"] [--playlist]
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

# Добавляем текущую директорию для импорта utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import safe_name, is_shorts_video

try:
    import yt_dlp
except ImportError:
    print("Ошибка: установите yt-dlp: pip install yt-dlp")
    sys.exit(1)

# ========== ЗАГРУЗКА КОНФИГА ==========
def load_config():
    default = {"video_dir": "videos"}
    config_file = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                if "video_dir" in cfg:
                    default["video_dir"] = cfg["video_dir"]
        except:
            pass
    return default

# ========== ОСНОВНАЯ ФУНКЦИЯ СКАЧИВАНИЯ ==========
def download_media(url, format_id=None, is_playlist=False, callback_file=None):
    """
    Скачивает видео или плейлист.
    Если callback_file указан, записывает туда статус (для прогресса).
    """
    config = load_config()
    base_dir = os.path.join(os.path.dirname(__file__), config["video_dir"])
    cookies_path = os.path.join(os.path.dirname(__file__), "cookies.txt")

    ydl_opts = {
        'quiet': True,
        'no_warnings': False,
        'writethumbnail': True,
        'writeinfojson': True,
        'merge_output_format': 'mp4',
        'ignoreerrors': True,
        'progress_hooks': [lambda d: progress_hook(d, callback_file)] if callback_file else [],
    }

    # Добавляем cookies, если есть
    if os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path

    # Выбор формата
    if format_id:
        ydl_opts['format'] = format_id
    else:
        ydl_opts['format'] = 'bestvideo+bestaudio/best'

    # Для плейлиста: не нужно noplaylist, а нужно извлечь все видео
    if not is_playlist:
        ydl_opts['noplaylist'] = True

    def progress_hook(d, cb_file):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            percent = (downloaded / total * 100) if total else 0
            write_callback(cb_file, {"percent": percent, "status": "downloading"})
        elif d['status'] == 'finished':
            write_callback(cb_file, {"percent": 100, "status": "finished"})
        elif d['status'] == 'error':
            write_callback(cb_file, {"status": "error", "message": str(d.get('error', ''))})

    def write_callback(cb_file, data):
        if cb_file:
            try:
                with open(cb_file, 'w') as f:
                    json.dump(data, f)
            except:
                pass

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Получаем информацию
            info = ydl.extract_info(url, download=False)
            if is_playlist and 'entries' in info:
                # Скачиваем весь плейлист
                ydl.download([url])
            else:
                # Одиночное видео
                channel = info.get('channel') or info.get('uploader') or 'unknown'
                title = info.get('title', 'video')
                author_folder = safe_name(channel)
                video_folder = safe_name(title)
                if is_shorts_video(info):
                    video_folder += " #shorts"
                output_dir = os.path.join(base_dir, author_folder, video_folder)
                os.makedirs(output_dir, exist_ok=True)

                # Устанавливаем шаблон вывода
                ydl_opts['outtmpl'] = {'default': os.path.join(output_dir, '%(title)s.%(ext)s')}
                # Создаём новый YDL с обновлённым outtmpl
                with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                    ydl2.download([url])
            return True
    except Exception as e:
        if callback_file:
            write_callback(callback_file, {"status": "error", "message": str(e)})
        print(f"Ошибка: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Скачивание видео с YouTube")
    parser.add_argument("--url", required=True, help="Ссылка на видео или плейлист")
    parser.add_argument("--format", default=None, help="ID формата (опционально)")
    parser.add_argument("--playlist", action="store_true", help="Ссылка на плейлист")
    parser.add_argument("--callback", default=None, help="Файл для записи прогресса (JSON)")
    args = parser.parse_args()

    success = download_media(args.url, args.format, args.playlist, args.callback)
    sys.exit(0 if success else 1)