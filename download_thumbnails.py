#!/usr/bin/env python3
"""
download_thumbnails.py – создаёт превью (thumbnail) для всех видео, у которых его нет.
Требуется ffmpeg (установите отдельно или укажите путь в переменной FFMPEG_PATH).
Использование:
    python download_thumbnails.py [--force] [--ffmpeg PATH]
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

# Добавляем путь к проекту для импорта utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import safe_name

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

# ========== ПОИСК ВСЕХ ВИДЕО ==========
def find_videos_without_thumbnail(video_dir, force=False):
    """Возвращает список путей к видеофайлам, у которых нет превью."""
    result = []
    for author in os.listdir(video_dir):
        author_path = os.path.join(video_dir, author)
        if not os.path.isdir(author_path):
            continue
        for vfolder in os.listdir(author_path):
            vfolder_path = os.path.join(author_path, vfolder)
            if not os.path.isdir(vfolder_path):
                continue
            # Ищем видеофайл
            video_file = None
            for f in os.listdir(vfolder_path):
                if f.lower().endswith(('.mp4', '.mkv', '.webm', '.avi', '.mov')):
                    video_file = os.path.join(vfolder_path, f)
                    break
            if not video_file:
                continue
            # Проверяем наличие превью
            has_thumb = any(f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) for f in os.listdir(vfolder_path))
            if force or not has_thumb:
                result.append(video_file)
    return result

# ========== ПОЛУЧЕНИЕ ПРЕВЬЮ ИЗ JSON ==========
def get_thumbnail_from_json(video_path):
    """Ищет рядом .info.json и извлекает URL лучшей превью."""
    base = os.path.splitext(video_path)[0]
    json_path = base + '.info.json'
    if not os.path.exists(json_path):
        # Попробуем найти любой .json в папке
        folder = os.path.dirname(video_path)
        for f in os.listdir(folder):
            if f.endswith('.info.json'):
                json_path = os.path.join(folder, f)
                break
        else:
            return None
    try:
        with open(json_path, 'r', encoding='utf-8') as jf:
            meta = json.load(jf)
        thumbnails = meta.get('thumbnails', [])
        if not thumbnails:
            return None
        # Выбираем превью с наибольшим разрешением
        best = max(thumbnails, key=lambda t: t.get('width', 0) * t.get('height', 0))
        return best.get('url')
    except:
        return None

# ========== СКАЧИВАНИЕ ПРЕВЬЮ ПО URL ==========
def download_thumbnail_from_url(url, output_path):
    """Скачивает изображение по URL и сохраняет."""
    try:
        import requests
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            ext = '.jpg'
            if 'png' in resp.headers.get('content-type', ''):
                ext = '.png'
            elif 'webp' in resp.headers.get('content-type', ''):
                ext = '.webp'
            out_file = output_path + ext
            with open(out_file, 'wb') as f:
                f.write(resp.content)
            return out_file
    except Exception as e:
        print(f"    Ошибка скачивания: {e}")
    return None

# ========== ИЗВЛЕЧЕНИЕ КАДРА ЧЕРЕЗ FFMPEG ==========
def extract_thumbnail_ffmpeg(video_path, output_path, ffmpeg_path='ffmpeg'):
    """Извлекает кадр на 1-й секунде видео."""
    # Выходной файл будет .jpg
    out_file = output_path + '.jpg'
    cmd = [ffmpeg_path, '-i', video_path, '-ss', '00:00:01', '-vframes', '1', '-q:v', '2', out_file, '-y']
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        if os.path.exists(out_file):
            return out_file
    except:
        pass
    return None

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def main():
    parser = argparse.ArgumentParser(description="Генерация превью для видео")
    parser.add_argument("--force", action="store_true", help="Перезаписать существующие превью")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="Путь к ffmpeg (по умолчанию ffmpeg)")
    args = parser.parse_args()

    config = load_config()
    video_dir = os.path.join(os.path.dirname(__file__), config["video_dir"])
    if not os.path.isdir(video_dir):
        print(f"Папка с видео не найдена: {video_dir}")
        return

    videos = find_videos_without_thumbnail(video_dir, args.force)
    print(f"Найдено видео без превью: {len(videos)}")
    success = 0
    for vpath in videos:
        print(f"\nОбработка: {vpath}")
        # Определяем базовое имя для превью (без расширения)
        base_name = os.path.splitext(vpath)[0]
        # Сначала пробуем взять из JSON
        thumb_url = get_thumbnail_from_json(vpath)
        if thumb_url:
            print("  Превью найдено в метаданных, скачиваю...")
            result = download_thumbnail_from_url(thumb_url, base_name)
            if result:
                print(f"  ✓ Превью сохранено: {result}")
                success += 1
                continue
        # Если не вышло – через ffmpeg
        print("  Превью из метаданных не получено, извлекаю кадр через ffmpeg...")
        result = extract_thumbnail_ffmpeg(vpath, base_name, args.ffmpeg)
        if result:
            print(f"  ✓ Кадр сохранён: {result}")
            success += 1
        else:
            print("  ✗ Не удалось создать превью")

    print(f"\nГотово. Успешно создано превью: {success} из {len(videos)}")

if __name__ == "__main__":
    main()