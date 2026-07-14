import os
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('ALL_PROXY', None)
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)
os.environ.pop('all_proxy', None)

import json
import threading
import shutil
import hashlib
import random
import sys
import time
import requests
import subprocess
import mimetypes
import re
import signal
import traceback
from urllib.parse import quote
from flask import Flask, render_template, send_from_directory, request, jsonify, send_file, abort
from datetime import datetime
from PIL import Image
import io

from downloader import get_format_choices, get_playlist_info, is_playlist_url
from download_lib import download_media, download_single_sync
from utils import safe_name, is_shorts_video
from user_videos import (
    add_user_video, edit_user_video, delete_user_video,
    get_all_user_videos, USER_VIDEOS_ROOT
)
from subtitles import (
    get_subtitles_dir, get_available_subtitles, download_youtube_subtitles,
    upload_subtitle_file, delete_subtitle
)
from logger import logger

from po_manager import get_po_method, get_video_info, get_formats, get_playlist_info as get_playlist_info_new, shutdown_extractor, get_extractor, get_po_args

import yt_dlp

app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
COOKIES_PATH = os.path.join(SCRIPT_DIR, "cookies.txt")

def load_config():
    default = {
        "video_dir": "videos", "avatars_dir": "avas", "thumbnails_dir": "thumbnails",
        "playlists_dir": "playlists", "subtitles_dir": "subtitles"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
                for k in default:
                    if k not in cfg:
                        cfg[k] = default[k]
                return cfg
        except:
            return default
    return default

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

config = load_config()
BASE_VIDEO_DIR = os.path.join(SCRIPT_DIR, config["video_dir"])
AVATARS_DIR = os.path.join(SCRIPT_DIR, config["avatars_dir"])
THUMBNAILS_DIR = os.path.join(SCRIPT_DIR, config["thumbnails_dir"])
PLAYLISTS_DIR = os.path.join(SCRIPT_DIR, config["playlists_dir"])
SUBTITLES_DIR = os.path.join(SCRIPT_DIR, config["subtitles_dir"])
os.makedirs(BASE_VIDEO_DIR, exist_ok=True)
os.makedirs(AVATARS_DIR, exist_ok=True)
os.makedirs(THUMBNAILS_DIR, exist_ok=True)
os.makedirs(PLAYLISTS_DIR, exist_ok=True)
os.makedirs(SUBTITLES_DIR, exist_ok=True)

# Папка для кэша ресайзнутых изображений
CACHE_DIR = os.path.join(SCRIPT_DIR, 'static', 'images', 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)

QUEUE_FILE = os.path.join(SCRIPT_DIR, "queue.json")
if not os.path.exists(QUEUE_FILE):
    try:
        with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)
        logger.info("Создан файл очереди queue.json")
    except Exception as e:
        logger.warning(f"Не удалось создать queue.json: {e}")

progress_data = {"percent": 0, "status": "idle", "message": ""}
VIDEO_MAP = {}
PLAYLIST_MAP = {}
USER_VIDEO_MAP = {}

def find_file(folder, exts):
    try:
        for f in os.listdir(folder):
            if any(f.lower().endswith(e) for e in exts):
                return f
    except:
        return None

def get_avatar_url(author):
    safe = safe_name(author)
    if os.path.exists(AVATARS_DIR):
        for f in os.listdir(AVATARS_DIR):
            name, ext = os.path.splitext(f)
            if name == safe and ext.lower() in ('.jpg','.jpeg','.png','.webp'):
                return f"/avatars/{f}"
    return None

@app.route('/avatars/<filename>')
def avatars(filename):
    return send_from_directory(AVATARS_DIR, filename)

def build_video_map():
    VIDEO_MAP.clear()
    logger.info("Сканирование YouTube видео...")
    if not os.path.exists(BASE_VIDEO_DIR):
        return 0
    total = 0
    for author in os.listdir(BASE_VIDEO_DIR):
        author_path = os.path.join(BASE_VIDEO_DIR, author)
        if not os.path.isdir(author_path) or author == os.path.basename(AVATARS_DIR):
            continue
        for vfolder in os.listdir(author_path):
            vpath = os.path.join(author_path, vfolder)
            if not os.path.isdir(vpath):
                continue
            video_file = find_file(vpath, ['.mp4','.mkv','.webm','.avi'])
            if not video_file:
                continue
            meta_file = find_file(vpath, ['info.json'])
            if not meta_file:
                meta_file = find_file(vpath, ['.info.json'])
            meta = {}
            if meta_file:
                json_path = os.path.join(vpath, meta_file)
                try:
                    with open(json_path, 'r', encoding='utf-8') as jf:
                        meta = json.load(jf)
                except:
                    meta = {}
            try:
                youtube_id = meta.get('id', '')
                vid = youtube_id if youtube_id else vfolder
                title = meta.get('title', f"Видео {vfolder}")
                size = round(os.path.getsize(os.path.join(vpath, video_file))/(1024*1024),1) if video_file else 0
                is_short = is_shorts_video(meta) if meta else False
                VIDEO_MAP[vid] = {
                    "author": author,
                    "folder": vfolder,
                    "is_short": is_short,
                    "filename": video_file,
                    "title": title,
                    "size_mb": size,
                    "source": "youtube",
                    "youtube_id": youtube_id
                }
                total += 1
            except Exception as e:
                logger.error(f"Ошибка обработки {vpath}: {e}")
                continue
    logger.info(f"Найдено YouTube видео: {total}")
    return total

def build_user_video_map():
    USER_VIDEO_MAP.clear()
    logger.info("Сканирование пользовательских видео...")
    all_user = get_all_user_videos()
    for v in all_user:
        vid = v.get('id')
        if not vid:
            continue
        USER_VIDEO_MAP[vid] = {
            "id": vid,
            "title": v.get('title', 'Без названия'),
            "author": v.get('author', 'Unknown'),
            "size_mb": round(os.path.getsize(v['video_path']) / (1024*1024), 1) if os.path.exists(v['video_path']) else 0,
            "thumb": v.get('thumb_path'),
            "description": v.get('description', ''),
            "added_at": v.get('added_at', ''),
            "source": "user",
            "folder": v.get('folder'),
            "video_path": v['video_path']
        }
    logger.info(f"Найдено пользовательских видео: {len(USER_VIDEO_MAP)}")

@app.route('/usermedia/<path:filename>')
def usermedia(filename):
    base = os.path.join(SCRIPT_DIR, USER_VIDEOS_ROOT)
    return send_from_directory(base, filename)

@app.route('/subtitles/<video_id>/<lang>.<ext>')
def serve_subtitle(video_id, lang, ext):
    if ext not in ('vtt', 'srt'):
        return "Invalid extension", 400
    source = request.args.get('source', 'youtube')
    if source not in ('youtube', 'user'):
        return "Invalid source", 400
    folder = os.path.join(SUBTITLES_DIR, source, video_id)
    file_path = os.path.join(folder, f"{lang}.{ext}")
    if os.path.exists(file_path):
        return send_from_directory(folder, f"{lang}.{ext}")
    return "Not found", 404

def build_playlist_map():
    PLAYLIST_MAP.clear()
    if not os.path.exists(PLAYLISTS_DIR):
        return
    for playlist_folder in os.listdir(PLAYLISTS_DIR):
        folder_path = os.path.join(PLAYLISTS_DIR, playlist_folder)
        if not os.path.isdir(folder_path):
            continue
        meta_file = os.path.join(folder_path, 'playlist.json')
        if not os.path.exists(meta_file):
            continue
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            playlist_id = hashlib.md5(playlist_folder.encode()).hexdigest()[:11]
            thumb = data.get('thumbnail', '')
            if thumb and not thumb.startswith('/'):
                thumb = '/' + thumb
            PLAYLIST_MAP[playlist_id] = {
                'id': playlist_id,
                'title': data.get('title', playlist_folder),
                'uploader': data.get('uploader', 'Unknown'),
                'thumbnail': thumb,
                'video_count': data.get('video_count', 0),
                'videos': data.get('videos', []),
                'folder': playlist_folder
            }
        except Exception as e:
            logger.error(f"Ошибка загрузки плейлиста {playlist_folder}: {e}")

@app.route('/')
def index():
    build_video_map()
    build_user_video_map()
    build_playlist_map()
    video_items = list(VIDEO_MAP.items())
    all_videos = []
    shorts = []
    authors_set = set()
    for vid, v in video_items:
        thumb = find_file(os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"]), ['.jpg','.png','.webp'])
        item = {
            "author": v["author"], "folder": v["folder"], "filename": v["filename"],
            "thumb": thumb, "title": v["title"], "is_short": v["is_short"],
            "size_mb": v["size_mb"], "id": vid, "author_avatar": get_avatar_url(v["author"]),
            "source": "youtube"
        }
        if v["is_short"]:
            shorts.append(item)
        else:
            all_videos.append(item)
        authors_set.add(v["author"])
    user_videos_list = []
    for vid, uv in USER_VIDEO_MAP.items():
        user_videos_list.append({
            "id": vid,
            "title": uv["title"],
            "author": uv["author"],
            "size_mb": uv["size_mb"],
            "thumb": uv["thumb"] if uv["thumb"] and os.path.exists(uv["thumb"]) else None,
            "source": "user",
            "video_path": uv["video_path"],
            "folder": uv.get("folder"),
            "author_avatar": get_avatar_url(uv["author"])
        })
    random.shuffle(all_videos)
    authors = [{"name": a, "avatar": get_avatar_url(a)} for a in sorted(authors_set)]
    playlists = list(PLAYLIST_MAP.values())
    return render_template("index.html", all_videos=all_videos, shorts=shorts, authors=authors, playlists=playlists, user_videos=user_videos_list)

# ------------------ ПРЕВЬЮ ------------------
def generate_thumbnail(video_path, output_path):
    cmd = ['ffmpeg', '-i', video_path, '-ss', '00:00:01', '-vframes', '1', '-q:v', '2', output_path, '-y']
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return os.path.exists(output_path)
    except:
        return False

@app.route('/api/thumbnail/<vid_id>')
def api_thumbnail(vid_id):
    if vid_id in VIDEO_MAP:
        v = VIDEO_MAP[vid_id]
        video_dir = os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"])
        thumb_file = find_file(video_dir, ['.jpg','.png','.webp'])
        if thumb_file:
            return send_from_directory(video_dir, thumb_file)
        video_file = find_file(video_dir, ['.mp4','.mkv','.webm','.avi'])
        if not video_file:
            return jsonify({"error": "Video not found"}), 404
        video_path = os.path.join(video_dir, video_file)
        thumb_path = os.path.join(video_dir, 'thumbnail.jpg')
        if generate_thumbnail(video_path, thumb_path):
            return send_file(thumb_path, mimetype='image/jpeg')
        else:
            return jsonify({"error": "Failed to generate thumbnail"}), 500
    build_user_video_map()
    if vid_id in USER_VIDEO_MAP:
        uv = USER_VIDEO_MAP[vid_id]
        thumb_path = uv.get('thumb')
        if thumb_path and os.path.exists(thumb_path):
            return send_file(thumb_path)
        video_path = uv.get('video_path')
        if video_path and os.path.exists(video_path):
            thumb_dir = os.path.dirname(video_path)
            thumb_path = os.path.join(thumb_dir, 'thumbnail.jpg')
            if generate_thumbnail(video_path, thumb_path):
                return send_file(thumb_path, mimetype='image/jpeg')
        return jsonify({"error": "No thumbnail"}), 404
    return jsonify({"error": "Video not found"}), 404

# ------------------ НОВЫЕ МАРШРУТЫ ДЛЯ YOUTUBE ------------------
@app.route('/api/video/info', methods=['POST'])
def api_video_info():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        info = get_video_info(url)
        if not info:
            return jsonify({"error": "Failed to fetch video info"}), 500

        if 'entries' in info:
            playlist_info = get_playlist_info_new(url)
            return jsonify({
                "is_playlist": True,
                "title": playlist_info.get('title'),
                "count": playlist_info.get('count', 0),
                "videos": playlist_info.get('videos', [])
            })

        formats = get_formats(url)
        response = {
            "is_playlist": False,
            "id": info.get('id'),
            "title": info.get('title'),
            "author": info.get('uploader'),
            "thumbnail": info.get('thumbnail'),
            "duration": info.get('duration'),
            "view_count": info.get('view_count'),
            "description": info.get('description'),
            "formats": formats,
        }
        return jsonify(response)

    except Exception as e:
        logger.error(f"Ошибка получения информации: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/video/download', methods=['POST'])
def api_video_download():
    data = request.get_json()
    url = data.get('url')
    format_id = data.get('format_id')
    if not url:
        return jsonify({"error": "No URL"}), 400

    try:
        info = get_video_info(url)
        if not info:
            return jsonify({"error": "Cannot fetch video info"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    title = info.get('title', 'video')
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
    if not safe_title:
        safe_title = hashlib.md5(title.encode()).hexdigest()[:10]

    author_folder = safe_name(info.get('uploader', 'Unknown'))
    video_id = info.get('id') or hashlib.md5(title.encode()).hexdigest()[:11]
    video_folder = video_id + (" #shorts" if is_shorts_video(info) else "")
    output_dir = os.path.join(BASE_VIDEO_DIR, author_folder, video_folder)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'video.mp4')
    filename = 'video.mp4'
    try:
        with open(os.path.join(output_dir, 'info.json'), 'w', encoding='utf-8') as f:
            json.dump(info, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Не удалось сохранить info.json: {e}")

    progress_data['percent'] = 0
    progress_data['status'] = 'starting'
    progress_data['message'] = 'Подготовка...'

    def download_thread():
        try:
            from po_manager import download_video
            def progress_hook(d):
                if d['status'] == 'downloading':
                    progress_data['status'] = 'downloading'
                    p_str = d.get('_percent_str', '0%').replace('%', '').strip()
                    try:
                        progress_data['percent'] = float(p_str)
                    except ValueError:
                        pass
                    progress_data['message'] = f"Загрузка: {d.get('_percent_str', '0%')}"
                elif d['status'] == 'finished':
                    progress_data['percent'] = 100
                    progress_data['message'] = "Скачивание завершено"
                    progress_data['status'] = 'finished'
                    build_video_map()
                elif d['status'] == 'error':
                    progress_data['status'] = 'error'
                    progress_data['message'] = d.get('error', 'Ошибка скачивания')
            success = download_video(url, output_path, format_id, progress_hook)
            if not success:
                progress_data['status'] = 'error'
                progress_data['message'] = 'Ошибка скачивания'
        except Exception as e:
            logger.error(f"Ошибка в потоке скачивания: {e}")
            progress_data['status'] = 'error'
            progress_data['message'] = str(e)

    threading.Thread(target=download_thread, daemon=True).start()
    return jsonify({"status": "started", "filename": filename, "progress_url": "/progress"})

# ================== ПРЯМОЕ СКАЧИВАНИЕ С ВЫБОРОМ КАЧЕСТВА ==================

@app.route('/api/direct_formats', methods=['POST'])
def direct_formats():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({"error": "No URL"}), 400

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
            'socket_timeout': 30,
        }
        
        po_args = get_po_args()
        if po_args:
            ydl_opts.update(po_args)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info or 'formats' not in info:
            logger.warning("Форматы не найдены или видео недоступно")
            return jsonify({"error": "Видео недоступно или форматы не найдены"}), 500

        formats = []
        seen_resolutions = set()

        for f in info.get('formats', []):
            if not f.get('url'):
                continue
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            height = f.get('height', 0)
            format_id = f.get('format_id')
            ext = f.get('ext', 'mp4')
            filesize = f.get('filesize') or f.get('filesize_approx')

            if vcodec != 'none' and acodec != 'none' and height > 0:
                res_key = f"{height}p"
                if res_key not in seen_resolutions:
                    seen_resolutions.add(res_key)
                    formats.append({
                        'format_id': format_id,
                        'resolution': res_key,
                        'ext': ext,
                        'codec': f"{vcodec.split('.')[0]}+{acodec.split('.')[0]}",
                        'filesize': filesize,
                        'height': height
                    })

        if not formats:
            video_formats = []
            audio_formats = []
            for f in info.get('formats', []):
                if not f.get('url'):
                    continue
                vcodec = f.get('vcodec', 'none')
                acodec = f.get('acodec', 'none')
                height = f.get('height', 0)
                if vcodec != 'none' and height > 0:
                    video_formats.append({
                        'format_id': f['format_id'],
                        'resolution': f"{height}p",
                        'ext': f.get('ext', 'mp4'),
                        'codec': vcodec.split('.')[0],
                        'filesize': f.get('filesize') or f.get('filesize_approx'),
                        'height': height
                    })
                elif acodec != 'none':
                    audio_formats.append({
                        'format_id': f['format_id'],
                        'resolution': f"{f.get('tbr', 0)}k",
                        'ext': f.get('ext', 'm4a'),
                        'codec': acodec.split('.')[0],
                        'filesize': f.get('filesize') or f.get('filesize_approx')
                    })

            video_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
            formats.extend(video_formats[:10])
            if audio_formats:
                formats.extend(audio_formats[:3])

        formats.sort(key=lambda x: x.get('height', 0), reverse=True)
        formats.insert(0, {'format_id': None, 'resolution': 'Авто (лучшее)', 'ext': 'mp4', 'codec': 'best', 'filesize': None, 'height': 0})

        logger.info(f"Найдено доступных форматов: {len(formats)}")
        return jsonify({"formats": formats})
    except Exception as e:
        logger.error(f"Ошибка в direct_formats: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/direct_download', methods=['POST'])
def direct_download():
    data = request.get_json()
    url = data.get('url')
    format_id = data.get('format_id')
    if not url:
        return jsonify({"error": "No URL"}), 400

    logger.info(f"📥 direct_download: url={url}, format_id={format_id}")

    try:
        ydl_opts_info = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
            'socket_timeout': 30,
        }
        po_args = get_po_args()
        if po_args:
            ydl_opts_info.update(po_args)

        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return jsonify({"error": "Видео удалено, приватно или недоступно"}), 404

        channel = info.get('uploader', 'Unknown')
        title = info.get('title', 'video')
        video_id = info.get('id')
        if not video_id:
            import re
            match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})(?:[&?]|$)', url)
            video_id = match.group(1) if match else None
        if not video_id:
            video_id = hashlib.md5(title.encode()).hexdigest()[:11]

        author_folder = safe_name(channel)
        video_folder = video_id
        if is_shorts_video(info):
            video_folder += " #shorts"
        output_dir = os.path.join(BASE_VIDEO_DIR, author_folder, video_folder)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, 'video.mp4')

        info_path = os.path.join(output_dir, 'info.json')
        with open(info_path, 'w', encoding='utf-8') as f:
            json.dump(info, f, indent=2, ensure_ascii=False)

        if not format_id:
            format_str = 'bestvideo+bestaudio/best'
        else:
            if '+' not in format_id:
                format_str = f"{format_id}+bestaudio/best"
            else:
                format_str = format_id

        logger.info(f"📥 Используем формат для загрузки: {format_str}")

        ydl_opts_download = {
            'format': format_str,
            'merge_output_format': 'mp4',
            'outtmpl': output_path,
            'quiet': False,
            'no_warnings': True,
            'ignoreerrors': True,
            'socket_timeout': 30,
            'retries': 5,
            'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
        }
        if po_args:
            ydl_opts_download.update(po_args)

        with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
            ydl.download([url])

        build_video_map()

        resolution = "неизвестно"
        if format_id:
            available = {f['format_id']: f for f in info.get('formats', [])}
            if format_id in available:
                h = available[format_id].get('height')
                if h:
                    resolution = f"{h}p"

        return jsonify({
            "status": "success",
            "filename": os.path.basename(output_path),
            "title": title,
            "url": f"/media/{author_folder}/{video_folder}/video.mp4",
            "resolution": resolution,
            "selected_format": format_str
        })

    except Exception as e:
        logger.error(f"❌ Ошибка в direct_download: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

# ================== ФОНЫ ДЛЯ ТЕМ (УЛУЧШЕННЫЙ РЕСАЙЗ С КЭШИРОВАНИЕМ) ==================
@app.route('/static/images/themes/<theme>/<filename>')
def get_resized_theme_image(theme, filename):
    """Возвращает ресайзнутое изображение под размер экрана с кэшированием."""
    folder = os.path.join(SCRIPT_DIR, 'static', 'images', 'themes', theme)
    filepath = os.path.join(folder, filename)
    if not os.path.exists(filepath):
        abort(404)
    
    # Получаем размеры из запроса
    width = request.args.get('w', 1920, type=int)
    height = request.args.get('h', 1080, type=int)
    
    # Ограничиваем максимальный размер
    max_size = 3840
    width = min(width, max_size)
    height = min(height, max_size)
    
    # Генерируем ключ кэша на основе размера и хеша файла
    try:
        with open(filepath, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()[:8]
    except:
        file_hash = hashlib.md5(filename.encode()).hexdigest()[:8]
    
    cache_key = f"{file_hash}_{width}x{height}.webp"
    cache_path = os.path.join(CACHE_DIR, cache_key)
    
    # Если есть в кэше — отдаём сразу
    if os.path.exists(cache_path):
        return send_file(cache_path, mimetype='image/webp', max_age=86400)
    
    try:
        with Image.open(filepath) as img:
            # Конвертируем в RGB
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            # Вычисляем пропорции
            img_ratio = img.width / img.height
            target_ratio = width / height
            
            if img_ratio > target_ratio:
                new_height = height
                new_width = int(height * img_ratio)
            else:
                new_width = width
                new_height = int(width / img_ratio)
            
            # Ресайзим с LANCZOS (наилучшее качество)
            img = img.resize((new_width, new_height), Image.LANCZOS)
            
            # Центрируем и обрезаем
            left = (new_width - width) // 2
            top = (new_height - height) // 2
            right = left + width
            bottom = top + height
            img = img.crop((left, top, right, bottom))
            
            # Сохраняем в кэш как WebP с высоким качеством
            img.save(cache_path, format='WEBP', quality=95, optimize=True, method=6)
            
            return send_file(cache_path, mimetype='image/webp', max_age=86400)
    except Exception as e:
        logger.error(f"Ошибка обработки изображения: {e}")
        # Если ошибка — отдаём оригинал
        return send_file(filepath)

@app.route('/api/theme-backgrounds/<theme>')
def get_theme_backgrounds(theme):
    """Возвращает список изображений для указанной темы."""
    folder = os.path.join(SCRIPT_DIR, 'static', 'images', 'themes', theme)
    if not os.path.isdir(folder):
        return jsonify([])
    images = [f for f in os.listdir(folder) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    return jsonify(images)

# ------------------ ПЕРЕНАПРАВЛЕНИЕ СТАРЫХ МАРШРУТОВ ------------------
@app.route('/api/playlist/info', methods=['POST'])
def api_playlist_info_redirect():
    return api_video_info()

@app.route('/api/formats', methods=['POST'])
def api_formats_redirect():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({"error": "No URL"}), 400
    try:
        info = get_video_info(url)
        if not info:
            return jsonify({"error": "Failed to fetch video info"}), 500
        formats = get_formats(url)
        old_formats = []
        for f in formats:
            old_formats.append({
                'type': 'video' if f.get('vcodec') != 'none' else 'audio',
                'format_id': f.get('format_id'),
                'resolution': f.get('resolution'),
                'codec': f.get('vcodec') or f.get('acodec'),
                'size_mb': round(f.get('filesize', 0) / (1024*1024), 1) if f.get('filesize') else None,
                'note': f.get('ext'),
            })
        old_formats.insert(0, {'type': 'auto', 'format_id': None, 'resolution': 'Авто (рекомендуемое)', 'codec': 'best', 'size_mb': None})
        return jsonify({"formats": old_formats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ------------------ СТАРЫЕ МАРШРУТЫ (ОСТАВЛЯЕМ ДЛЯ СОВМЕСТИМОСТИ) ------------------
@app.route('/download', methods=['POST'])
def download_old():
    data = request.json
    urls = data.get('urls')
    fmt = data.get('format_id')
    if not urls:
        return jsonify({"error": "No URLs"}), 400
    if isinstance(urls, str):
        urls = [urls]

    is_real_playlist = len(urls) == 1 and is_playlist_url(urls[0])

    progress_data['percent'] = 0
    progress_data['status'] = 'starting'
    progress_data['message'] = 'Подготовка...'

    def run():
        success = download_media(urls, fmt, is_real_playlist, progress_data)
        if not success and progress_data['status'] != 'error':
            progress_data['status'] = 'error'
            progress_data['message'] = 'Ошибка при скачивании'
        else:
            if is_real_playlist:
                build_playlist_map()
            else:
                build_video_map()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "started"})

@app.route('/progress')
def progress():
    return jsonify(progress_data)

def _safe_resolve(base_dir, relative_path):
    base = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base, relative_path))
    if target == base or target.startswith(base + os.sep):
        return target
    return None

@app.route('/media/<path:filename>')
def media(filename):
    filepath = _safe_resolve(BASE_VIDEO_DIR, filename)
    if not filepath or not os.path.isfile(filepath):
        abort(404)
    ext = os.path.splitext(filename)[1].lower()
    mime_type_map = {
        '.mp4': 'video/mp4',
        '.mkv': 'video/x-matroska',
        '.webm': 'video/webm',
        '.avi': 'video/x-msvideo',
        '.mov': 'video/quicktime',
        '.wmv': 'video/x-ms-wmv',
        '.flv': 'video/x-flv',
    }
    mime_type = mime_type_map.get(ext, 'video/mp4')
    response = send_file(filepath, mimetype=mime_type, conditional=True)
    response.headers['Accept-Ranges'] = 'bytes'
    return response

@app.route('/api/refresh', methods=['POST'])
def refresh():
    total = build_video_map()
    build_user_video_map()
    build_playlist_map()
    return jsonify({"status": "ok", "total": total})

@app.route('/watch/<vid_id>')
def watch(vid_id):
    if not VIDEO_MAP:
        build_video_map()
    if vid_id in VIDEO_MAP:
        v = VIDEO_MAP[vid_id]
        author = v["author"]
        folder = v["folder"]
        video_dir = os.path.join(BASE_VIDEO_DIR, author, folder)
        video_file = find_file(video_dir, ['.mp4','.mkv','.webm','.avi'])
        if not video_file:
            build_video_map()
            video_file = find_file(video_dir, ['.mp4','.mkv','.webm','.avi'])
        if not video_file:
            return "Видеофайл не найден на диске", 404
        ext = os.path.splitext(video_file)[1].lower()
        mime_type = {
            '.mp4': 'video/mp4',
            '.mkv': 'video/x-matroska',
            '.webm': 'video/webm',
            '.avi': 'video/x-msvideo',
        }.get(ext, 'video/mp4')
        encoded_author = quote(author)
        encoded_folder = quote(folder)
        encoded_filename = quote(video_file)
        video_url = f"/media/{encoded_author}/{encoded_folder}/{encoded_filename}"
        meta_file = find_file(video_dir, ['info.json'])
        if not meta_file:
            meta_file = find_file(video_dir, ['.info.json'])
        meta = {}
        if meta_file:
            try:
                with open(os.path.join(video_dir, meta_file), 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            except:
                pass
        shorts_feed = []
        recommended = []
        if v["is_short"]:
            for vid2, v2 in VIDEO_MAP.items():
                if v2["is_short"]:
                    shorts_feed.append({
                        'id': vid2, 'url': f"{v2['author']}/{v2['folder']}/{v2['filename']}",
                        'title': v2['title'], 'author': v2['author'], 'size_mb': v2['size_mb']
                    })
            cur = next((x for x in shorts_feed if x['id'] == vid_id), None)
            if cur:
                shorts_feed.remove(cur)
                shorts_feed.insert(0, cur)
        else:
            for vid2, v2 in VIDEO_MAP.items():
                if not v2["is_short"] and vid2 != vid_id:
                    recommended.append({
                        'id': vid2, 'title': v2['title'], 'author': v2['author'], 'folder': v2['folder'],
                        'thumb': find_file(os.path.join(BASE_VIDEO_DIR, v2['author'], v2['folder']), ['.jpg','.png','.webp'])
                    })
            build_user_video_map()
            for vid2, uv2 in USER_VIDEO_MAP.items():
                if vid2 != vid_id:
                    recommended.append({
                        'id': vid2,
                        'title': uv2['title'],
                        'author': uv2['author'],
                        'folder': uv2['folder'],
                        'thumb': uv2['thumb'] if uv2['thumb'] and os.path.exists(uv2['thumb']) else None
                    })
            random.shuffle(recommended)
        return render_template("video.html",
            author=author, folder=folder, video_url=video_url, meta=meta, is_short=v["is_short"],
            shorts_feed=shorts_feed, recommended_videos=recommended,
            file_size_mb=v["size_mb"], author_avatar=get_avatar_url(author),
            video_id=vid_id, video_source='youtube', youtube_id=v.get('youtube_id', ''),
            mime_type=mime_type
        )
    build_user_video_map()
    if vid_id in USER_VIDEO_MAP:
        uv = USER_VIDEO_MAP[vid_id]
        video_filename = os.path.basename(uv['video_path'])
        ext = os.path.splitext(video_filename)[1].lower()
        mime_type = {
            '.mp4': 'video/mp4',
            '.mkv': 'video/x-matroska',
            '.webm': 'video/webm',
            '.avi': 'video/x-msvideo',
        }.get(ext, 'video/mp4')
        encoded_author = quote(uv['author'])
        encoded_folder = quote(uv['folder'])
        encoded_filename = quote(video_filename)
        video_url = f"/usermedia/{encoded_author}/{encoded_folder}/{encoded_filename}"
        meta = {
            'id': uv['id'],
            'title': uv['title'],
            'uploader': uv['author'],
            'description': uv.get('description', ''),
            'duration': None,
            'source': 'user'
        }
        recommended = []
        for vid2, v2 in VIDEO_MAP.items():
            if not v2["is_short"]:
                recommended.append({
                    'id': vid2,
                    'title': v2['title'],
                    'author': v2['author'],
                    'folder': v2['folder'],
                    'thumb': find_file(os.path.join(BASE_VIDEO_DIR, v2['author'], v2['folder']), ['.jpg','.png','.webp'])
                })
        for vid2, uv2 in USER_VIDEO_MAP.items():
            if vid2 != vid_id:
                recommended.append({
                    'id': vid2,
                    'title': uv2['title'],
                    'author': uv2['author'],
                    'folder': uv2['folder'],
                    'thumb': uv2['thumb'] if uv2['thumb'] and os.path.exists(uv2['thumb']) else None
                })
        random.shuffle(recommended)
        return render_template("video.html",
            author=uv['author'], folder=uv['folder'], video_url=video_url, meta=meta, is_short=False,
            shorts_feed=[], recommended_videos=recommended,
            file_size_mb=uv['size_mb'], author_avatar=get_avatar_url(uv['author']),
            video_id=vid_id, video_source='user', youtube_id='',
            mime_type=mime_type
        )
    return "Видео не найдено", 404

@app.route('/playlist/<playlist_id>')
def playlist_view(playlist_id):
    if not PLAYLIST_MAP:
        build_playlist_map()
    if playlist_id not in PLAYLIST_MAP:
        return "Плейлист не найден", 404
    pl = PLAYLIST_MAP[playlist_id]
    videos_for_template = []
    for v in pl['videos']:
        video_path = v.get('video_path', '')
        if not video_path:
            continue
        parts = video_path.split('/')
        if len(parts) >= 3:
            author = parts[-3]
            folder = parts[-2]
        else:
            author = pl['uploader']
            folder = "unknown"
        vid_id = hashlib.md5(video_path.encode()).hexdigest()[:11]
        thumb = find_file(os.path.join(BASE_VIDEO_DIR, author, folder), ['.jpg','.png','.webp'])
        videos_for_template.append({
            'id': vid_id,
            'title': v['title'],
            'author': author,
            'duration': v.get('duration'),
            'thumb': thumb,
            'video_path': video_path
        })
    return render_template('playlist.html', playlist=pl, videos=videos_for_template)

# ------------------ СУБТИТРЫ ------------------
@app.route('/api/subtitles/<video_id>', methods=['GET'])
def api_get_subtitles(video_id):
    video_source = request.args.get('source', 'youtube')
    subs = get_available_subtitles(video_id, video_source)
    return jsonify({"subtitles": subs})

@app.route('/api/subtitles/download/<video_id>', methods=['POST'])
def api_download_subtitles(video_id):
    data = request.get_json()
    lang = data.get('lang', 'ru')
    video_source = data.get('source', 'youtube')
    if video_source == 'youtube':
        video_info = None
        for vid, v in VIDEO_MAP.items():
            if vid == video_id:
                video_info = v
                break
        if not video_info:
            return jsonify({"error": "Видео не найдено"}), 404
        youtube_id = video_info.get('youtube_id')
        if not youtube_id:
            meta_file = find_file(os.path.join(BASE_VIDEO_DIR, video_info['author'], video_info['folder']), ['info.json'])
            if not meta_file:
                meta_file = find_file(os.path.join(BASE_VIDEO_DIR, video_info['author'], video_info['folder']), ['.info.json'])
            if meta_file:
                try:
                    with open(os.path.join(BASE_VIDEO_DIR, video_info['author'], video_info['folder'], meta_file), 'r') as f:
                        meta_data = json.load(f)
                        youtube_id = meta_data.get('id')
                except:
                    pass
        if not youtube_id:
            return jsonify({"error": "Не удалось определить YouTube ID"}), 400
        video_url = f"https://youtu.be/{youtube_id}"
        success = download_youtube_subtitles(video_url, video_id, lang)
        if success:
            return jsonify({"status": "ok"})
        else:
            return jsonify({"error": "Не удалось скачать субтитры"}), 500
    else:
        return jsonify({"error": "Для пользовательских видео субтитры можно только загрузить вручную"}), 400

@app.route('/api/subtitles/upload/<video_id>', methods=['POST'])
def api_upload_subtitles(video_id):
    video_source = request.form.get('source', 'youtube')
    lang = request.form.get('lang', 'ru')
    file = request.files.get('file')
    if not file:
        return jsonify({"error": "Файл не загружен"}), 400
    success = upload_subtitle_file(video_id, video_source, file, lang)
    if success:
        return jsonify({"status": "ok"})
    else:
        return jsonify({"error": "Не удалось загрузить файл"}), 500

@app.route('/api/subtitles/<video_id>/<lang>', methods=['DELETE'])
def api_delete_subtitle(video_id, lang):
    video_source = request.args.get('source', 'youtube')
    success = delete_subtitle(video_id, video_source, lang)
    if success:
        return jsonify({"status": "ok"})
    else:
        return jsonify({"error": "Субтитры не найдены"}), 404

@app.route('/api/subtitles/download_all', methods=['POST'])
def api_download_all_subtitles():
    data = request.get_json() or {}
    lang = data.get('lang', 'ru')
    build_video_map()
    count = 0
    for vid, v in VIDEO_MAP.items():
        subs = get_available_subtitles(vid, 'youtube')
        existing = any(s['lang'] == lang for s in subs)
        if not existing:
            youtube_id = v.get('youtube_id')
            if not youtube_id:
                meta_file = find_file(os.path.join(BASE_VIDEO_DIR, v['author'], v['folder']), ['info.json'])
                if not meta_file:
                    meta_file = find_file(os.path.join(BASE_VIDEO_DIR, v['author'], v['folder']), ['.info.json'])
                if meta_file:
                    try:
                        with open(os.path.join(BASE_VIDEO_DIR, v['author'], v['folder'], meta_file), 'r') as f:
                            meta_data = json.load(f)
                            youtube_id = meta_data.get('id')
                    except:
                        pass
            if youtube_id:
                video_url = f"https://youtu.be/{youtube_id}"
                if download_youtube_subtitles(video_url, vid, lang):
                    count += 1
    return jsonify({"status": "ok", "downloaded": count, "total": len(VIDEO_MAP)})

# ------------------ ПОЛЬЗОВАТЕЛЬСКИЕ ВИДЕО ------------------
@app.route('/upload')
def upload_page():
    return render_template('upload.html')

@app.route('/api/user_video/upload', methods=['POST'])
def api_upload_user_video():
    username = request.form.get('username', 'Гость')
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    video_file = request.files.get('video_file')
    thumbnail_file = request.files.get('thumbnail_file')
    if not video_file:
        return jsonify({"error": "Видеофайл не загружен"}), 400

    import tempfile
    fd, temp_video_path = tempfile.mkstemp(suffix=".mp4", dir=SCRIPT_DIR)
    os.close(fd)
    temp_thumb_path = None
    try:
        video_file.save(temp_video_path)
        if thumbnail_file:
            fd, temp_thumb_path = tempfile.mkstemp(suffix=".jpg", dir=SCRIPT_DIR)
            os.close(fd)
            thumbnail_file.save(temp_thumb_path)

        result = add_user_video(
            source_path=temp_video_path,
            title=title,
            description=description,
            username=username,
            custom_thumbnail_path=temp_thumb_path
        )
    except Exception as e:
        logger.error(f"Ошибка загрузки пользовательского видео: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(temp_video_path):
            os.unlink(temp_video_path)
        if temp_thumb_path and os.path.exists(temp_thumb_path):
            os.unlink(temp_thumb_path)

    if not result:
        return jsonify({"error": "Не удалось добавить видео"}), 500

    build_user_video_map()
    return jsonify({"status": "ok", "video_id": result['id']})

@app.route('/edit/<video_id>')
def edit_page(video_id):
    build_user_video_map()
    if video_id not in USER_VIDEO_MAP:
        return "Видео не найдено", 404
    v = USER_VIDEO_MAP[video_id]
    return render_template('edit.html', video=v)

@app.route('/api/user_video/edit/<video_id>', methods=['POST'])
def api_edit_user_video(video_id):
    data = request.form
    username = data.get('username')
    new_title = data.get('title', '').strip()
    new_description = data.get('description', '').strip()
    thumbnail_file = request.files.get('thumbnail_file')
    if not username:
        return jsonify({"error": "Username required"}), 400
    temp_thumb = None
    if thumbnail_file:
        import tempfile
        fd, temp_thumb = tempfile.mkstemp(suffix=".jpg", dir=SCRIPT_DIR)
        os.close(fd)
        thumbnail_file.save(temp_thumb)
    try:
        result = edit_user_video(
            video_id=video_id,
            new_title=new_title,
            new_description=new_description,
            username=username,
            new_thumbnail_path=temp_thumb
        )
    except Exception as e:
        if temp_thumb and os.path.exists(temp_thumb):
            os.unlink(temp_thumb)
        logger.error(f"Ошибка редактирования видео: {e}")
        return jsonify({"error": str(e)}), 500
    if temp_thumb and os.path.exists(temp_thumb):
        os.unlink(temp_thumb)
    if not result:
        return jsonify({"error": "Видео не найдено или вы не являетесь владельцем"}), 404
    build_user_video_map()
    return jsonify({"status": "ok"})

@app.route('/api/user_video/delete/<video_id>', methods=['DELETE'])
def api_delete_user_video(video_id):
    data = request.get_json() or {}
    username = data.get('username')
    if not username:
        return jsonify({"error": "Username required"}), 400
    success = delete_user_video(video_id, username)
    if not success:
        return jsonify({"error": "Видео не найдено или вы не являетесь владельцем"}), 404
    build_user_video_map()
    return jsonify({"status": "ok"})

@app.route('/api/user_video/info/<video_id>', methods=['GET'])
def api_user_video_info(video_id):
    build_user_video_map()
    if video_id not in USER_VIDEO_MAP:
        return jsonify({"error": "Not found"}), 404
    return jsonify(USER_VIDEO_MAP[video_id])

# ------------------ ОСТАЛЬНЫЕ МАРШРУТЫ ------------------
@app.route('/api/upload_avatar', methods=['POST'])
def upload_avatar():
    author = request.form.get('author')
    file = request.files.get('avatar')
    if not author or not file:
        return jsonify({"error": "Missing data"}), 400
    safe_author = safe_name(author)
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.jpg','.jpeg','.png','.webp'):
        return jsonify({"error": "Unsupported format"}), 400
    filename = f"{safe_author}{ext}"
    file.save(os.path.join(AVATARS_DIR, filename))
    return jsonify({"status": "ok", "url": f"/avatars/{filename}"})

@app.route('/api/delete_avatar', methods=['POST'])
def delete_avatar():
    author = request.json.get('author')
    if not author:
        return jsonify({"error": "No author"}), 400
    safe = safe_name(author)
    for f in os.listdir(AVATARS_DIR):
        name, ext = os.path.splitext(f)
        if name == safe and ext.lower() in ('.jpg','.jpeg','.png','.webp'):
            os.remove(os.path.join(AVATARS_DIR, f))
            return jsonify({"status": "ok"})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/delete/<vid_id>', methods=['DELETE'])
def delete_video(vid_id):
    if vid_id in VIDEO_MAP:
        author = VIDEO_MAP[vid_id]['author']
        folder = VIDEO_MAP[vid_id]['folder']
        target = _safe_resolve(BASE_VIDEO_DIR, os.path.join(author, folder))
        if target and os.path.exists(target):
            shutil.rmtree(target)
            author_dir = os.path.join(BASE_VIDEO_DIR, author)
            try:
                if os.path.isdir(author_dir) and not os.listdir(author_dir):
                    os.rmdir(author_dir)
            except OSError as e:
                logger.warning(f"Не удалось удалить папку автора {author_dir}: {e}")
            del VIDEO_MAP[vid_id]
            return jsonify({"status": "deleted"})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/config', methods=['GET', 'POST'])
def config_api():
    global BASE_VIDEO_DIR, AVATARS_DIR, THUMBNAILS_DIR, PLAYLISTS_DIR, SUBTITLES_DIR, config
    if request.method == 'GET':
        return jsonify(config)
    data = request.json or {}
    allowed_keys = {"video_dir", "avatars_dir", "thumbnails_dir", "playlists_dir", "subtitles_dir"}
    for key, value in data.items():
        if key not in allowed_keys:
            return jsonify({"error": f"Недопустимый ключ конфигурации: {key}"}), 400
        if not isinstance(value, str) or not value.strip():
            return jsonify({"error": f"Некорректное значение для {key}"}), 400
        if os.path.isabs(value) or '..' in value.replace('\\', '/').split('/'):
            return jsonify({"error": f"Путь для {key} должен быть относительным и без '..'"}), 400
    config.update(data)
    save_config(config)
    BASE_VIDEO_DIR = os.path.join(SCRIPT_DIR, config["video_dir"])
    AVATARS_DIR = os.path.join(SCRIPT_DIR, config["avatars_dir"])
    THUMBNAILS_DIR = os.path.join(SCRIPT_DIR, config["thumbnails_dir"])
    PLAYLISTS_DIR = os.path.join(SCRIPT_DIR, config["playlists_dir"])
    SUBTITLES_DIR = os.path.join(SCRIPT_DIR, config["subtitles_dir"])
    os.makedirs(BASE_VIDEO_DIR, exist_ok=True)
    os.makedirs(AVATARS_DIR, exist_ok=True)
    os.makedirs(THUMBNAILS_DIR, exist_ok=True)
    os.makedirs(PLAYLISTS_DIR, exist_ok=True)
    os.makedirs(SUBTITLES_DIR, exist_ok=True)
    build_video_map()
    build_user_video_map()
    build_playlist_map()
    return jsonify({"status": "ok"})

@app.route('/api/restart', methods=['POST'])
def restart():
    def _restart():
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Thread(target=_restart).start()
    return jsonify({"status": "restarting"})

# ------------------ АВАТАРКИ ------------------
def fetch_avatar_url_for_author(author_name):
    author_path = os.path.join(BASE_VIDEO_DIR, author_name)
    if not os.path.isdir(author_path):
        return None
    for sub in os.listdir(author_path):
        sub_path = os.path.join(author_path, sub)
        if os.path.isdir(sub_path):
            for f in os.listdir(sub_path):
                if f.endswith('.info.json') or f.endswith('info.json'):
                    json_path = os.path.join(sub_path, f)
                    try:
                        with open(json_path, 'r', encoding='utf-8') as jf:
                            meta = json.load(jf)
                        channel_id = meta.get('channel_id') or meta.get('uploader_id')
                        if channel_id:
                            channel_url = f"https://www.youtube.com/channel/{channel_id}"
                            return _extract_avatar_from_channel_url(channel_url)
                        uploader_url = meta.get('uploader_url')
                        if uploader_url and 'youtube.com' in uploader_url:
                            return _extract_avatar_from_channel_url(uploader_url)
                    except:
                        pass
    return _search_avatar_by_name(author_name)

def _extract_avatar_from_channel_url(channel_url):
    import yt_dlp
    from po_manager import get_po_args
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
    }
    cookies_path = os.path.join(SCRIPT_DIR, "cookies.txt")
    if os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path
    
    po_args = get_po_args()
    if po_args:
        ydl_opts.update(po_args)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            if info.get('avatar_thumbnail_url'):
                return info['avatar_thumbnail_url']
            thumbnails = info.get('thumbnails', [])
            best = None
            for t in thumbnails:
                url = t.get('url')
                if not url: continue
                w = t.get('width', 0)
                h = t.get('height', 0)
                if w > 0 and h > 0 and (w / h) > 1.2: continue
                size = w * h
                if size > (best.get('size', 0) if best else 0):
                    best = {'url': url, 'size': size}
            if best:
                return best['url']
            if thumbnails:
                return thumbnails[0].get('url')
    except Exception as e:
        logger.error(f"Ошибка извлечения аватарки: {e}")
    return None

def _search_avatar_by_name(author_name):
    import yt_dlp
    from po_manager import get_po_args
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'default_search': 'ytsearch',
    }
    cookies_path = os.path.join(SCRIPT_DIR, "cookies.txt")
    if os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path
    
    po_args = get_po_args()
    if po_args:
        ydl_opts.update(po_args)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"ytsearch1:{author_name}"
            info = ydl.extract_info(search_query, download=False)
            if info and 'entries' in info and len(info['entries']) > 0:
                first = info['entries'][0]
                channel_url = first.get('channel_url') or first.get('uploader_url')
                if channel_url:
                    return _extract_avatar_from_channel_url(channel_url)
    except Exception as e:
        logger.error(f"Ошибка поиска канала: {e}")
    return None

def download_avatar_for_author(author_name, force=False):
    safe_author = safe_name(author_name)
    for ext in ['.jpg', '.jpeg', '.png', '.webp']:
        candidate = os.path.join(AVATARS_DIR, f"{safe_author}{ext}")
        if os.path.exists(candidate):
            if not force:
                return True
            else:
                os.remove(candidate)
                break
    url = None
    for attempt in range(3):
        try:
            url = fetch_avatar_url_for_author(author_name)
            if url:
                break
        except Exception as e:
            logger.warning(f"Попытка {attempt+1} для {author_name} не удалась: {e}")
            time.sleep(2)
    if not url:
        logger.info(f"Аватарка для {author_name} не найдена")
        return False
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            content_type = resp.headers.get('content-type', '')
            ext = '.jpg'
            if 'png' in content_type: ext = '.png'
            elif 'webp' in content_type: ext = '.webp'
            if '.png' in url: ext = '.png'
            elif '.webp' in url: ext = '.webp'
            save_path = os.path.join(AVATARS_DIR, f"{safe_author}{ext}")
            with open(save_path, 'wb') as f:
                f.write(resp.content)
            return True
    except Exception as e:
        logger.error(f"Ошибка скачивания аватарки для {author_name}: {e}")
    return False

def update_all_avatars(force=False):
    logger.info("Обновление аватарок авторов...")
    authors = set()
    for vid, v in VIDEO_MAP.items():
        authors.add(v['author'])
    if not authors:
        logger.info("Нет авторов для обновления аватарок.")
        return
    success = 0
    for author in authors:
        try:
            if download_avatar_for_author(author, force):
                success += 1
                logger.info(f"  ✓ {author}")
            else:
                logger.info(f"  ✗ {author}")
        except Exception as e:
            logger.error(f"  ✗ {author}: ошибка — {e}")
        time.sleep(0.5)
    logger.info(f"Аватарки обновлены: {success}/{len(authors)}")
    build_video_map()

@app.route('/api/avatars/download_all', methods=['POST'])
def api_download_all_avatars():
    def run():
        update_all_avatars(force=True)
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "started", "message": "Обновление аватарок запущено"})

@app.route('/api/thumbnails/generate', methods=['POST'])
def api_generate_thumbnails():
    script_path = os.path.join(SCRIPT_DIR, "download_thumbnails.py")
    if not os.path.exists(script_path):
        return jsonify({"status": "error", "message": "download_thumbnails.py не найден"})
    force = request.json.get('force', False)
    ffmpeg_path = request.json.get('ffmpeg', 'ffmpeg')
    def run():
        cmd = [sys.executable, script_path]
        if force: cmd.append("--force")
        if ffmpeg_path != 'ffmpeg': cmd.extend(["--ffmpeg", ffmpeg_path])
        subprocess.run(cmd, capture_output=True)
        build_video_map()
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "started", "message": "Генерация превью запущена"})

# ================== ОЧЕРЕДЬ ЗАГРУЗОК ==================
queue_tasks = []
queue_lock = threading.Lock()
queue_processing = False
queue_processor_thread = None

class QueueTask:
    def __init__(self, task_id, urls, format_id, title, merge_format='mp4'):
        self.id = task_id
        self.urls = urls if isinstance(urls, list) else [urls]
        self.format_id = format_id
        self.title = title
        self.merge_format = merge_format
        self.status = "waiting"
        self.progress = 0
        self.added_at = datetime.now().isoformat()

def save_queue():
    with queue_lock:
        tasks_data = []
        for t in queue_tasks:
            tasks_data.append({
                "id": t.id,
                "urls": t.urls,
                "format_id": t.format_id,
                "title": t.title,
                "merge_format": t.merge_format,
                "status": t.status,
                "progress": t.progress,
                "added_at": t.added_at
            })
    try:
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Ошибка сохранения очереди: {e}")

def load_queue():
    global queue_tasks
    if not os.path.exists(QUEUE_FILE):
        return
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            tasks_data = json.load(f)
        with queue_lock:
            queue_tasks = []
            for td in tasks_data:
                task = QueueTask(td["id"], td["urls"], td["format_id"], td["title"], td.get("merge_format", "mp4"))
                if td["status"] in ("downloading", "paused"):
                    task.status = "waiting"
                else:
                    task.status = td["status"]
                task.progress = td.get("progress", 0)
                task.added_at = td["added_at"]
                queue_tasks.append(task)
    except Exception as e:
        logger.error(f"Ошибка загрузки очереди: {e}")

def start_queue_processor():
    global queue_processing, queue_processor_thread
    if queue_processing:
        return
    with queue_lock:
        pending = any(t.status == "waiting" for t in queue_tasks)
    if not pending:
        return
    queue_processing = True
    queue_processor_thread = threading.Thread(target=_process_queue, daemon=True)
    queue_processor_thread.start()

def _process_queue():
    global queue_processing, queue_tasks
    while queue_processing:
        with queue_lock:
            current_task = None
            for t in queue_tasks:
                if t.status == "waiting":
                    current_task = t
                    t.status = "downloading"
                    break
        if current_task is None:
            break
        save_queue()

        def progress_callback(percent, message):
            with queue_lock:
                current_task.progress = percent
            save_queue()

        try:
            success = download_single_sync(current_task.urls, current_task.format_id, progress_callback, merge_format=current_task.merge_format)
            if success:
                current_task.status = "completed"
                current_task.progress = 100
                def update_cache():
                    time.sleep(2)
                    build_video_map()
                threading.Thread(target=update_cache, daemon=True).start()
            else:
                current_task.status = "error"
        except Exception as e:
            logger.error(f"Ошибка выполнения задачи {current_task.id}: {e}")
            current_task.status = "error"
        save_queue()
        time.sleep(1)
    queue_processing = False

@app.route('/api/queue/list', methods=['GET'])
def api_queue_list():
    with queue_lock:
        tasks = []
        for t in queue_tasks:
            tasks.append({
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "progress": t.progress,
                "added_at": t.added_at,
                "urls": t.urls
            })
    return jsonify({"tasks": tasks})

@app.route('/api/queue/add', methods=['POST'])
def api_queue_add():
    data = request.json
    urls = data.get('urls')
    format_id = data.get('format_id')
    if format_id == '':
        format_id = None
    title = data.get('title', '')
    merge_format = data.get('merge_format', 'mp4')
    if not urls:
        return jsonify({"error": "No URLs"}), 400
    if isinstance(urls, str):
        urls = [urls]
    task_id = hashlib.md5(f"{time.time()}_{random.randint(0,100000)}".encode()).hexdigest()[:8]
    task = QueueTask(task_id, urls, format_id, title or (urls[0] if len(urls) == 1 else f"Плейлист ({len(urls)} видео)"), merge_format)
    with queue_lock:
        queue_tasks.append(task)
    save_queue()
    start_queue_processor()
    return jsonify({"task_id": task_id})

@app.route('/api/queue/remove/<task_id>', methods=['DELETE'])
def api_queue_remove(task_id):
    with queue_lock:
        global queue_tasks
        queue_tasks = [t for t in queue_tasks if t.id != task_id]
    save_queue()
    return jsonify({"status": "ok"})

@app.route('/api/queue/pause', methods=['POST'])
def api_queue_pause():
    global queue_processing
    queue_processing = False
    return jsonify({"status": "paused"})

@app.route('/api/queue/resume', methods=['POST'])
def api_queue_resume():
    start_queue_processor()
    return jsonify({"status": "resumed"})

@app.route('/api/queue/clear', methods=['POST'])
def api_queue_clear():
    with queue_lock:
        global queue_tasks
        queue_tasks = []
    save_queue()
    return jsonify({"status": "ok"})

load_queue()
with queue_lock:
    has_pending = any(t.status == "waiting" for t in queue_tasks)
if has_pending:
    start_queue_processor()

# ========== ОБРАБОТЧИКИ СИГНАЛОВ ==========
def signal_handler(sig, frame):
    logger.info("Получен сигнал завершения, сервер останавливается...")
    shutdown_extractor()
    for handler in logger.handlers:
        handler.flush()
        handler.close()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ========== ТОЧКА ВХОДА ==========
if __name__ == '__main__':
    print("[APP] 🚀 Запуск LocalTube NEO...")
    print("[APP] 🔄 Инициализация метода обхода (Seal)...")
    get_extractor()
    port = int(os.environ.get('PORT', '8000'))
    logger.info(f"🚀 LocalTube NEO запущен: http://127.0.0.1:{port}")
    logger.info(f"🔑 Метод обхода: {get_po_method()}")
    try:
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("Сервер остановлен пользователем (Ctrl+C)")
    finally:
        logger.info("Завершение работы сервера")
        shutdown_extractor()
        for handler in logger.handlers:
            handler.flush()
            handler.close()