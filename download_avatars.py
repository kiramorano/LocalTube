#!/usr/bin/env python3
"""
download_avatars.py – скачивает аватарки для всех авторов видео.
Поддерживает несколько методов получения URL аватарки.
Использование:
    python download_avatars.py [--force] [--author Имя]
"""

import os
import sys
import json
import argparse
import requests
import re
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
from utils import safe_name, cookiefile_for_ydl, apply_cookie_updates
from channel_assets import pick_avatar

try:
    import yt_dlp
except ImportError:
    # sys.exit на импорте убивал бы весь сервер: модуль вызывается из
    # приложения, а не только как отдельный скрипт. Без yt-dlp работать нечем,
    # поэтому main() сообщит об этом и завершится сам.
    yt_dlp = None

# ========== ЗАГРУЗКА КОНФИГА ==========
def load_config():
    # avatars_dir обязан совпадать с app.py: здесь стояло "avatars", и без
    # config.json аватарки скачивались в папку, в которую веб не смотрит,
    # поэтому на страницах каналов не появлялись картинки.
    default = {"video_dir": "videos", "avatars_dir": "avas"}
    config_file = paths.data_path("config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                for k in default:
                    if k not in cfg:
                        cfg[k] = default[k]
                return cfg
        # Голый except глотал KeyboardInterrupt/SystemExit. Битый конфиг —
        # не повод падать, возвращаем значения по умолчанию.
        except (OSError, ValueError) as e:
            print(f"[warn] не удалось прочитать {config_file}: {e}")
    return default

# ========== ПОИСК ВСЕХ АВТОРОВ ПО ПАПКАМ ==========
def find_all_authors(video_dir):
    if not os.path.isdir(video_dir):
        print(f"Папка с видео не найдена: {video_dir}")
        return []
    authors = []
    for item in os.listdir(video_dir):
        item_path = os.path.join(video_dir, item)
        if os.path.isdir(item_path) and item not in ('.', '..'):
            authors.append(item)
    return authors

# ========== МЕТОД 1: ИЗ МЕТАДАННЫХ JSON ==========
def get_avatar_from_json(author_name, video_dir):
    """Пытается найти channel_id из JSON любого видео автора, затем через yt-dlp получить аватарку."""
    author_path = os.path.join(video_dir, author_name)
    if not os.path.isdir(author_path):
        return None
    # Ищем любой .json в подпапках
    for sub in os.listdir(author_path):
        sub_path = os.path.join(author_path, sub)
        if os.path.isdir(sub_path):
            for f in os.listdir(sub_path):
                if f.endswith('.info.json'):
                    json_path = os.path.join(sub_path, f)
                    try:
                        with open(json_path, 'r', encoding='utf-8') as jf:
                            meta = json.load(jf)
                        channel_id = meta.get('channel_id') or meta.get('uploader_id')
                        if channel_id:
                            channel_url = f"https://www.youtube.com/channel/{channel_id}"
                            return _fetch_avatar_from_channel_url(channel_url, author_name)
                        # Пробуем uploader_url
                        uploader_url = meta.get('uploader_url')
                        if uploader_url and 'youtube.com' in uploader_url:
                            return _fetch_avatar_from_channel_url(uploader_url, author_name)
                    # Битый .info.json — причина перейти к следующему файлу, а
                    # не прекращать обход. AttributeError ловим потому, что
                    # json.load может вернуть список или строку, и тогда
                    # meta.get не существует.
                    except (OSError, ValueError, AttributeError) as e:
                        print(f"[warn] не удалось прочитать {json_path}: {e}")
    return None

# ========== МЕТОД 2: ПОИСК КАНАЛА ПО ИМЕНИ ==========
def get_avatar_by_search(author_name):
    """Ищет канал по имени через yt-dlp и возвращает URL аватарки."""
    print(f"  Поиск канала для: {author_name}")
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'default_search': 'ytsearch',
    }
    cookies_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    # Поток, а не путь: иначе yt-dlp перезапишет cookies.txt при close().
    cookies_stream = cookiefile_for_ydl(cookies_path)
    if cookies_stream is not None:
        ydl_opts['cookiefile'] = cookies_stream

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Ищем видео этого автора, чтобы получить channel_url
            search_query = f"ytsearch1:{author_name}"
            info = ydl.extract_info(search_query, download=False)
            if info and 'entries' in info and len(info['entries']) > 0:
                first = info['entries'][0]
                channel_url = first.get('channel_url') or first.get('uploader_url')
                if channel_url:
                    return _fetch_avatar_from_channel_url(channel_url, author_name)
        apply_cookie_updates(ydl_opts)
    except Exception as e:
        print(f"  Ошибка поиска: {e}")
    return None

# ========== МЕТОД 3: ПРЯМОЙ ПАРСИНГ СТРАНИЦЫ КАНАЛА ==========
def get_avatar_by_scraping(author_name):
    """Пытается найти аватарку через requests + парсинг HTML (резервный метод)."""
    print(f"  Парсинг страницы канала для: {author_name}")
    # Пытаемся найти канал по имени через YouTube search (через requests)
    search_url = f"https://www.youtube.com/results?search_query={author_name.replace(' ', '+')}&sp=EgIQAVAU"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        resp = requests.get(search_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        # Ищем ссылку на канал: /channel/UC...
        channel_match = re.search(r'/channel/(UC[A-Za-z0-9_-]{22})', resp.text)
        if not channel_match:
            return None
        channel_id = channel_match.group(1)
        channel_url = f"https://www.youtube.com/channel/{channel_id}"
        return _fetch_avatar_from_channel_url(channel_url, author_name)
    except Exception as e:
        print(f"  Ошибка парсинга: {e}")
        return None

# ========== ВСПОМОГАТЕЛЬНАЯ: ПОЛУЧЕНИЕ АВАТАРКИ ПО URL КАНАЛА ==========
def _fetch_avatar_from_channel_url(channel_url, author_name):
    """Извлекает URL аватарки, используя yt-dlp."""
    print(f"    Запрос аватарки по URL: {channel_url}")
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
    }
    cookies_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    # Поток, а не путь: иначе yt-dlp перезапишет cookies.txt при close().
    cookies_stream = cookiefile_for_ydl(cookies_path)
    if cookies_stream is not None:
        ydl_opts['cookiefile'] = cookies_stream

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            # Аватарка и шапка канала лежат в общем списке thumbnails. Здесь
            # выбиралась «самая большая картинка», а шапка 2560x424 крупнее
            # аватарки 900x900 — в avas/ попадала широкая полоса вместо
            # круглой аватарки. Логика общая с channel_assets, чтобы дефект не
            # разъезжался по двум копиям.
            thumbnails = info.get('thumbnails') or info.get('avatar') or []
            best = pick_avatar(thumbnails)
            if best:
                return best
            # Альтернативное поле
            avatar_url = info.get('avatar_thumbnail_url') or info.get('thumbnail')
            if avatar_url:
                return avatar_url
        apply_cookie_updates(ydl_opts)
    except Exception as e:
        print(f"    Ошибка yt-dlp: {e}")
    return None

# ========== СКАЧИВАНИЕ ФАЙЛА ==========
def download_file(url, save_path):
    """Скачивает файл по URL и сохраняет с правильным расширением."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            content_type = resp.headers.get('content-type', '')
            ext = '.jpg'
            if 'png' in content_type:
                ext = '.png'
            elif 'webp' in content_type:
                ext = '.webp'
            # Уточняем по URL
            if '.png' in url:
                ext = '.png'
            elif '.webp' in url:
                ext = '.webp'
            final_path = save_path + ext
            with open(final_path, 'wb') as f:
                f.write(resp.content)
            return True
    except Exception as e:
        print(f"    Ошибка скачивания: {e}")
    return False

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def main(argv=None):
    """Точка входа. argv передаётся явно, чтобы функцию можно было вызвать из
    приложения: без параметра argparse читал бы sys.argv сервера и завершал
    процесс через sys.exit при незнакомом ключе."""
    parser = argparse.ArgumentParser(description="Скачивание аватарок для авторов видео")
    parser.add_argument("--author", help="Только для указанного автора")
    parser.add_argument("--force", action="store_true", help="Перезаписать существующие")
    args = parser.parse_args(argv)

    if yt_dlp is None:
        print("Ошибка: установите yt-dlp: pip install yt-dlp")
        return

    config = load_config()
    video_dir = paths.user_path(config["video_dir"])
    avatars_dir = paths.user_path(config["avatars_dir"])
    os.makedirs(avatars_dir, exist_ok=True)

    # Список авторов
    if args.author:
        authors = [args.author]
    else:
        authors = find_all_authors(video_dir)
        if not authors:
            print("Нет ни одного автора в папке videos.")
            return

    print(f"Найдено авторов: {len(authors)}")
    success = 0
    for author in authors:
        safe_author = safe_name(author)
        # Проверяем, есть ли уже аватарка
        existing = None
        for ext in ['.jpg', '.jpeg', '.png', '.webp']:
            cand = os.path.join(avatars_dir, f"{safe_author}{ext}")
            if os.path.exists(cand):
                existing = cand
                break
        if existing and not args.force:
            print(f"[✓] {author}: аватарка уже есть ({os.path.basename(existing)})")
            success += 1
            continue

        print(f"[→] {author}: поиск аватарки...")
        avatar_url = None
        # Метод 1: из JSON
        avatar_url = get_avatar_from_json(author, video_dir)
        if avatar_url:
            print(f"    Найдена через JSON")
        else:
            # Метод 2: поиск через yt-dlp
            avatar_url = get_avatar_by_search(author)
            if avatar_url:
                print(f"    Найдена через поиск")
            else:
                # Метод 3: парсинг страницы
                avatar_url = get_avatar_by_scraping(author)
                if avatar_url:
                    print(f"    Найдена через парсинг")
        if avatar_url:
            save_path = os.path.join(avatars_dir, safe_author)
            if download_file(avatar_url, save_path):
                print(f"[✔] {author}: аватарка сохранена")
                success += 1
            else:
                print(f"[✗] {author}: не удалось сохранить")
        else:
            print(f"[✗] {author}: аватарка не найдена ни одним методом")

    print(f"\nГотово. Успешно: {success} из {len(authors)}")

if __name__ == "__main__":
    main()