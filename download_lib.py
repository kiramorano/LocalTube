#!/usr/bin/env python3
import os
import sys
import json
import threading
import time
import shutil
import re
import hashlib
import subprocess
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import safe_name, is_shorts_video
from logger import logger
from po_manager import get_po_args

try:
    import yt_dlp
except ImportError:
    logger.error("Ошибка: установите yt-dlp: pip install yt-dlp")
    sys.exit(1)

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

download_locks = {}
locks_mutex = threading.Lock()

def get_video_id(url):
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})(?:[&?]|$)', url)
    return match.group(1) if match else hashlib.md5(url.encode()).hexdigest()[:11]

def get_output_path(base_dir, author, video_id, title):
    safe_author = safe_name(author)[:50]
    folder_name = video_id
    return os.path.join(base_dir, safe_author, folder_name)

COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")

def get_ydl_opts(format_id, merge_format, progress_hook, temp_dir):
    os.makedirs(temp_dir, exist_ok=True)
    
    if format_id and '+' not in format_id and format_id.isdigit():
        actual_format = f"{format_id}+bestaudio/best"
    else:
        actual_format = format_id or 'bestvideo+bestaudio/best'

    po_args = get_po_args()

    opts = {
        'format': actual_format,
        'outtmpl': os.path.join(temp_dir, 'video.%(ext)s'),
        'merge_output_format': merge_format or 'mp4',
        'writethumbnail': True,
        'writeinfojson': True,
        'quiet': False,
        'no_warnings': True,
        'ignoreerrors': True, # БАГФИКС: Защита от краша при загрузке
        'socket_timeout': 30,
        'retries': 5,
        'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
        'progress_hooks': [progress_hook],
    }

    if po_args:
        if 'extractor_args' not in opts:
            opts['extractor_args'] = {}
        opts['extractor_args'].update(po_args.get('extractor_args', {}))

    return opts

def download_single_video_impl(url, format_id, output_dir, progress_dict, progress_callback, merge_format):
    with locks_mutex:
        if download_locks.get(url):
            logger.info(f"Видео {url} уже скачивается.")
            return True
        download_locks[url] = True

    try:
        temp_dir = os.path.join(output_dir, "_tmp_" + hashlib.md5(url.encode()).hexdigest()[:6])
        last_callback_time = 0

        def internal_hook(d):
            nonlocal last_callback_time
            if d['status'] == 'downloading':
                p = d.get('_percent_str', '0%').replace('%', '').strip()
                try:
                    percent = float(p)
                except:
                    percent = 0
                
                if progress_dict:
                    progress_dict['percent'] = percent
                
                now = time.time()
                if now - last_callback_time > 1.0 or percent >= 100:
                    if progress_callback:
                        progress_callback(percent, f"Загрузка: {percent}%")
                    last_callback_time = now
            
            elif d['status'] == 'finished':
                if progress_callback:
                    progress_callback(100, "Склеивание и обработка...")

        opts = get_ydl_opts(format_id, merge_format, internal_hook, temp_dir)
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # БАГФИКС: Проверка на None, если видео удалено
            if not info:
                logger.warning(f"Загрузка отменена: видео недоступно ({url})")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return False

        final_video = None
        for f in os.listdir(temp_dir):
            src = os.path.join(temp_dir, f)
            if f.endswith(('.mp4', '.mkv', '.webm', '.avi')):
                ext = os.path.splitext(f)[1]
                dst = os.path.join(output_dir, f"video{ext}")
                if os.path.exists(dst): os.remove(dst)
                shutil.move(src, dst)
                final_video = dst
            elif f.endswith('.json'):
                dst = os.path.join(output_dir, "info.json")
                # БАГФИКС: shutil.move падал, если info.json уже существовал (повторная загрузка)
                if os.path.exists(dst): os.remove(dst)
                shutil.move(src, dst)
            elif f.endswith(('.jpg', '.webp', '.png')):
                dst = os.path.join(output_dir, "thumbnail.jpg")
                if os.path.exists(dst): os.remove(dst)
                shutil.move(src, dst)

        return True if final_video else False

    except Exception as e:
        logger.error(f"Ошибка download_lib: {e}")
        if progress_dict:
            progress_dict['status'] = 'error'
            progress_dict['message'] = str(e)
        return False
    finally:
        # БАГФИКС: temp-папка теперь удаляется всегда — раньше при ошибке
        # загрузки на диске копились каталоги _tmp_*
        shutil.rmtree(temp_dir, ignore_errors=True)
        with locks_mutex:
            download_locks.pop(url, None)

def download_media(urls, format_id, is_playlist, progress_data):
    if not urls: return False

    def internal_cb(percent, message):
        progress_data['percent'] = percent
        progress_data['message'] = message
        progress_data['status'] = 'downloading'

    success = download_single_sync(urls, format_id, internal_cb)
    
    if success:
        progress_data['status'] = 'finished'
        progress_data['percent'] = 100
    else:
        progress_data['status'] = 'error'
    return success

def download_single_sync(urls, format_id, progress_callback, merge_format='mp4'):
    if isinstance(urls, str): urls = [urls]
    
    config = load_config()
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), config["video_dir"])
    
    total = len(urls)
    success_count = 0

    for idx, url in enumerate(urls, 1):
        try:
            po_args = get_po_args()
            info_opts = {
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True, # БАГФИКС: Не крашить очередь из-за одного видео
                'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
            }
            if po_args: info_opts.update(po_args)

            with yt_dlp.YoutubeDL(info_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            
            # БАГФИКС: Защита от AttributeError, если info == None
            if not info:
                logger.warning(f"Пропуск видео: недоступно ({url})")
                progress_callback(100, f"[{idx}/{total}] Ошибка: недоступно")
                continue
            
            author = info.get('uploader', 'Unknown')
            title = info.get('title', 'Video')
            video_id = info.get('id') or get_video_id(url)
            
            output_dir = get_output_path(base_dir, author, video_id, title)
            if is_shorts_video(info):
                output_dir += " #shorts"
            
            os.makedirs(output_dir, exist_ok=True)

            def sub_cb(p, msg):
                overall = ((idx - 1) * 100 + p) / total
                progress_callback(overall, f"[{idx}/{total}] {msg}")

            res = download_single_video_impl(url, format_id, output_dir, None, sub_cb, merge_format)
            if res: success_count += 1

        except Exception as e:
            logger.error(f"Ошибка в цикле загрузки: {e}")
            continue

    return success_count > 0 # Считаем успешным, если хотя бы 1 видео скачалось
