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
import re
import signal
import traceback
from urllib.parse import quote
from flask import Flask, render_template, send_from_directory, request, jsonify, send_file, abort
from datetime import datetime

from downloader import get_format_choices, get_playlist_info, is_playlist_url
from download_lib import download_media, download_single_sync, DownloadCancelledByUser
from utils import safe_name, is_shorts_video, write_json_atomic, read_json, JsonWriteError
from user_videos import add_user_video, edit_user_video, delete_user_video, get_all_user_videos, USER_VIDEOS_ROOT
from logger import logger
from po_manager import get_po_method, get_video_info, get_formats, get_playlist_info as get_playlist_info_new, shutdown_extractor, get_extractor, get_po_args
import yt_dlp

# Импорт наших новых модулей (Blueprints)
import custom_quality
import audio_language
import channel_assets
import auth_options
import userdata

app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['TEMPLATES_AUTO_RELOAD'] = True

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
COOKIES_PATH = os.path.join(SCRIPT_DIR, "cookies.txt")

def load_config():
    default = {
        "video_dir": "videos", "avatars_dir": "avas", "thumbnails_dir": "thumbnails",
        "playlists_dir": "playlists", "subtitles_dir": "subtitles"
    }
    # read_json подхватит .bak, если config.json повреждён: иначе одна неудачная
    # запись сбросила бы пути к библиотеке на значения по умолчанию.
    cfg = read_json(CONFIG_FILE, default=None)
    if not isinstance(cfg, dict):
        return default
    for k in default:
        cfg.setdefault(k, default[k])
    return cfg

def save_config(cfg):
    """Сохраняет config.json атомарно, с копией предыдущей версии."""
    write_json_atomic(CONFIG_FILE, cfg)

config = load_config()
BASE_VIDEO_DIR = os.path.join(SCRIPT_DIR, config["video_dir"])
AVATARS_DIR = os.path.join(SCRIPT_DIR, config["avatars_dir"])
THUMBNAILS_DIR = os.path.join(SCRIPT_DIR, config["thumbnails_dir"])
PLAYLISTS_DIR = os.path.join(SCRIPT_DIR, config["playlists_dir"])
SUBTITLES_DIR = os.path.join(SCRIPT_DIR, config["subtitles_dir"])

for d in [BASE_VIDEO_DIR, AVATARS_DIR, THUMBNAILS_DIR, PLAYLISTS_DIR, SUBTITLES_DIR]:
    os.makedirs(d, exist_ok=True)

CACHE_DIR = os.path.join(SCRIPT_DIR, 'static', 'images', 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)

QUEUE_FILE = os.path.join(SCRIPT_DIR, "queue.json")
if not os.path.exists(QUEUE_FILE):
    try:
        # backup=False: файла ещё нет, копировать нечего.
        write_json_atomic(QUEUE_FILE, {'paused': False, 'tasks': []}, backup=False)
    except JsonWriteError as e:
        logger.warning(f"Не удалось создать queue.json: {e}")

progress_data = {"percent": 0, "status": "idle", "message": ""}
VIDEO_MAP = {}
PLAYLIST_MAP = {}
USER_VIDEO_MAP = {}

queue_tasks = []
queue_lock = threading.Lock()
queue_processing = False
queue_paused = False
# id задач, для которых запрошена отмена. Загрузчик проверяет это множество на каждом хуке.
queue_cancel_requests = set()
PRIORITY_HIGH, PRIORITY_NORMAL, PRIORITY_LOW = 'high', 'normal', 'low'
PRIORITY_ORDER = {PRIORITY_HIGH: 0, PRIORITY_NORMAL: 1, PRIORITY_LOW: 2}

class QueueTask:
    def __init__(self, task_id, urls, format_id, title, merge_format='mp4', priority=PRIORITY_NORMAL):
        self.id = task_id
        self.priority = priority if priority in PRIORITY_ORDER else PRIORITY_NORMAL
        self.urls = urls if isinstance(urls, list) else [urls]
        self.format_id = format_id
        self.title = title
        self.merge_format = merge_format
        self.status = "waiting"
        self.progress = 0
        self.message = ""
        self.error = ""
        self.current_url = ""
        self.current_index = 0
        self.total_urls = len(self.urls)
        self.speed = ""
        self.eta = ""
        self.attempts = 0
        self.added_at = datetime.now().isoformat()

    @classmethod
    def from_dict(cls, data):
        task = cls(data.get('id', ''), data.get('urls', []), data.get('format_id'), data.get('title', 'Видео'), data.get('merge_format', 'mp4'), data.get('priority', PRIORITY_NORMAL))
        task.status = data.get('status', 'waiting')
        task.progress = data.get('progress', 0)
        task.message = data.get('message', '')
        task.error = data.get('error', '')
        task.current_url = data.get('current_url', '')
        task.current_index = data.get('current_index', 0)
        task.total_urls = data.get('total_urls', len(task.urls))
        task.speed = data.get('speed', '')
        task.eta = data.get('eta', '')
        task.attempts = data.get('attempts', 0)
        task.added_at = data.get('added_at', task.added_at)
        if task.status == 'downloading':
            task.status = 'waiting'
            task.progress = 0
            task.message = 'Восстановлено после перезапуска'
        return task

    def to_dict(self):
        return {
            'id': self.id, 'title': self.title, 'urls': self.urls,
            'format_id': self.format_id, 'merge_format': self.merge_format,
            'status': self.status, 'progress': self.progress,
            'message': self.message, 'error': self.error,
            'current_url': self.current_url, 'current_index': self.current_index,
            'total_urls': self.total_urls, 'speed': self.speed, 'eta': self.eta,
            'attempts': self.attempts, 'priority': self.priority,
            'added_at': self.added_at
        }


def save_queue():
    try:
        # Запись под тем же локом: раньше сериализация шла под локом, а сама
        # запись — вне, и два потока могли писать в файл одновременно.
        with queue_lock:
            data = {'paused': queue_paused, 'tasks': [task.to_dict() for task in queue_tasks]}
            write_json_atomic(QUEUE_FILE, data)
    except Exception as e:
        logger.warning(f"Не удалось сохранить очередь: {e}")


def load_queue():
    global queue_tasks, queue_paused
    try:
        # read_json подхватит .bak, если основной файл повреждён.
        data = read_json(QUEUE_FILE, default=None)
        if data is None:
            return
        # Старый формат: список задач. Новый: {'paused': bool, 'tasks': [...]}
        if isinstance(data, dict):
            queue_paused = bool(data.get('paused', False))
            data = data.get('tasks', [])
        if isinstance(data, list):
            queue_tasks = [QueueTask.from_dict(item) for item in data if isinstance(item, dict)]
    except Exception as e:
        logger.warning(f"Не удалось загрузить очередь: {e}")


def normalize_video_metadata(meta):
    meta = meta if isinstance(meta, dict) else {}
    return {
        'duration': meta.get('duration') or 0,
        'upload_date': meta.get('upload_date') or meta.get('release_date') or '',
        'description': meta.get('description') or '',
        'channel_url': meta.get('channel_url') or meta.get('uploader_url') or '',
        'channel_id': meta.get('channel_id') or meta.get('uploader_id') or '',
        'country': meta.get('channel_country') or meta.get('country') or '',
        'channel_created': meta.get('channel_created') or meta.get('channel_joined') or '',
        'storyboards': meta.get('storyboards') or meta.get('storyboard_spec') or meta.get('storyboard') or {}
    }

load_queue()


@app.template_filter('human_date')
def human_date(value):
    """20260812 -> 12.08.2026; ISO-даты и мусор возвращаем как есть."""
    text = str(value or '').strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[6:8]}.{text[4:6]}.{text[0:4]}"
    if len(text) >= 10 and text[4] == '-' and text[7] == '-':
        return f"{text[8:10]}.{text[5:7]}.{text[0:4]}"
    return text


@app.template_filter('human_duration')
def human_duration(value):
    """Секунды -> 7:05 или 1:02:03."""
    try:
        total = int(float(value or 0))
    except (TypeError, ValueError):
        return ''
    if total <= 0:
        return ''
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def find_main_video_file(folder):
    for ext in ['.mp4', '.mkv', '.webm', '.avi', '.mov']:
        if os.path.exists(os.path.join(folder, f"video{ext}")): return f"video{ext}"
    try:
        for f in os.listdir(folder):
            if any(f.lower().endswith(e) for e in ['.mp4', '.mkv', '.webm', '.avi']): return f
    except: pass
    return None

def find_file(folder, exts):
    try:
        for f in os.listdir(folder):
            if any(f.lower().endswith(e) for e in exts): return f
    except: pass
    return None

# Кэш карты аватарок: раньше каталог листался на каждое видео в выдаче,
# то есть 500 раз на один поиск.
_avatar_cache = {'mtime': None, 'map': {}}
_avatar_cache_lock = threading.Lock()


def get_avatar_url(author):
    safe = safe_name(author)
    try:
        mtime = os.stat(AVATARS_DIR).st_mtime
    except OSError:
        return None
    with _avatar_cache_lock:
        if _avatar_cache['mtime'] != mtime:
            fresh = {}
            try:
                for f in os.listdir(AVATARS_DIR):
                    name, ext = os.path.splitext(f)
                    if ext.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                        fresh.setdefault(name, f"/avatars/{f}")
            except OSError:
                return None
            _avatar_cache['map'] = fresh
            _avatar_cache['mtime'] = mtime
        return _avatar_cache['map'].get(safe)

# Кэш разобранных папок видео: путь -> (отпечаток содержимого, готовая запись).
# Полное пересканирование читало info.json каждого видео при каждом вызове, а
# build_video_map() вызывается на каждом поиске и после каждой задачи очереди.
_scan_cache = {}
_scan_cache_lock = threading.Lock()

# Момент последней сборки карты. Обработчики часто сканируют библиотеку по
# несколько раз за один запрос (поиск — и видео, и пользовательские видео),
# поэтому короткое окно позволяет переиспользовать уже собранную карту.
_map_built_at = 0.0
MAP_FRESH_WINDOW = 2.0


def _cheap_fingerprint(vdir_entry, video_file, meta_file):
    """Дешёвый признак изменений папки видео.

    Полный scandir на каждую папку обходится дорого, поэтому проверяем только
    то, что реально меняется: mtime самой папки (ловит добавление и удаление
    файлов) плюс размер и mtime видеофайла и info.json — их правят на месте,
    и mtime папки при этом не меняется.
    """
    try:
        parts = [int(vdir_entry.stat().st_mtime)]
    except OSError:
        return None
    for name in (video_file, meta_file):
        if not name:
            parts.append(None)
            continue
        try:
            st = os.stat(os.path.join(vdir_entry.path, name))
        except OSError:
            return None
        parts.append((st.st_size, int(st.st_mtime)))
    return tuple(parts)


def _parse_video_folder(author, vfolder, vpath, names, video_file):
    """Собирает запись о видео, читая info.json с диска."""
    if not video_file:
        return None

    meta_file = next((n for n in names if n.lower().endswith(('info.json', '.info.json'))), None)
    meta = {}
    if meta_file:
        try:
            # utf-8-sig: файл мог быть сохранён с BOM (например, вручную из
            # редактора или PowerShell) — обычный utf-8 на таком падает.
            with open(os.path.join(vpath, meta_file), 'r', encoding='utf-8-sig') as jf:
                meta = json.load(jf)
        except Exception as e:
            # Раньше ошибка молча проглатывалась и видео теряло название и дату.
            logger.warning(f"Не удалось прочитать метаданные {os.path.join(vpath, meta_file)}: {e}")

    try:
        size_bytes = os.path.getsize(os.path.join(vpath, video_file))
    except OSError:
        size_bytes = 0

    # Имя превью запоминаем здесь: иначе каждая выдача заново листала папку.
    thumb_file = next((n for n in names if n.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))), None)

    youtube_id = meta.get('id', '') if isinstance(meta, dict) else ''
    record = {
        "author": author, "folder": vfolder,
        "is_short": is_shorts_video(meta) if meta else False,
        "filename": video_file, "title": (meta.get('title') if isinstance(meta, dict) else None) or f"Видео {vfolder}",
        "size_mb": round(size_bytes / (1024 * 1024), 1),
        "source": "youtube", "youtube_id": youtube_id, "thumb_file": thumb_file,
    }
    record.update(normalize_video_metadata(meta))
    return youtube_id or vfolder, record, meta_file


def build_video_map():
    new_video_map = {}
    if not os.path.exists(BASE_VIDEO_DIR):
        return 0
    total = 0
    avatars_name = os.path.basename(AVATARS_DIR)
    seen_paths = set()

    try:
        author_entries = list(os.scandir(BASE_VIDEO_DIR))
    except OSError as e:
        logger.error(f"Не удалось прочитать каталог видео: {e}")
        return 0

    for author_entry in author_entries:
        if not author_entry.is_dir() or author_entry.name == avatars_name:
            continue
        author = author_entry.name
        try:
            video_entries = list(os.scandir(author_entry.path))
        except OSError as e:
            logger.warning(f"Не удалось прочитать каталог канала {author}: {e}")
            continue

        for vdir in video_entries:
            if not vdir.is_dir():
                continue
            vpath = vdir.path
            seen_paths.add(vpath)

            with _scan_cache_lock:
                cached = _scan_cache.get(vpath)

            # Быстрый путь: папка не менялась — не открываем её вообще.
            if cached:
                fingerprint = _cheap_fingerprint(vdir, cached[1], cached[2])
                if fingerprint is not None and fingerprint == cached[0]:
                    new_video_map[cached[3]] = cached[4]
                    total += 1
                    continue

            try:
                names = [e.name for e in os.scandir(vpath) if e.is_file()]
            except OSError as e:
                logger.warning(f"Не удалось прочитать папку видео {vpath}: {e}")
                continue

            video_file = None
            for ext in ('.mp4', '.mkv', '.webm', '.avi', '.mov'):
                if f"video{ext}" in names:
                    video_file = f"video{ext}"
                    break
            if not video_file:
                video_file = next((n for n in names if n.lower().endswith(('.mp4', '.mkv', '.webm', '.avi'))), None)
            if not video_file:
                continue

            try:
                parsed = _parse_video_folder(author, vdir.name, vpath, names, video_file)
            except Exception as e:
                logger.error(f"Ошибка обработки {vpath}: {e}")
                continue
            if not parsed:
                continue
            vid, record, meta_file = parsed
            fingerprint = _cheap_fingerprint(vdir, video_file, meta_file)
            if fingerprint is not None:
                with _scan_cache_lock:
                    _scan_cache[vpath] = (fingerprint, video_file, meta_file, vid, record)
            new_video_map[vid] = record
            total += 1

    # Забываем удалённые папки, иначе кэш растёт бесконечно.
    with _scan_cache_lock:
        for stale in set(_scan_cache) - seen_paths:
            del _scan_cache[stale]

    global VIDEO_MAP, _map_built_at
    VIDEO_MAP = new_video_map
    _map_built_at = time.time()
    return total


def invalidate_scan_cache():
    """Сбрасывает кэш сканирования (после удаления или правки видео)."""
    global _map_built_at
    with _scan_cache_lock:
        _scan_cache.clear()
        _map_built_at = 0.0


def ensure_video_map(max_age=MAP_FRESH_WINDOW):
    """Пересканирует библиотеку, только если карта успела устареть."""
    if VIDEO_MAP and (time.time() - _map_built_at) < max_age:
        return len(VIDEO_MAP)
    return build_video_map()

def build_user_video_map():
    new_user_map = {}
    for v in get_all_user_videos():
        vid = v.get('id')
        if not vid: continue
        new_user_map[vid] = {
            "id": vid, "title": v.get('title', 'Без названия'), "author": v.get('author', 'Unknown'),
            "size_mb": round(os.path.getsize(v['video_path']) / (1024*1024), 1) if os.path.exists(v['video_path']) else 0,
            "thumb": v.get('thumb_path'), "description": v.get('description', ''), "added_at": v.get('added_at', ''),
            "source": "user", "folder": v.get('folder'), "video_path": v['video_path']
        }
    global USER_VIDEO_MAP
    USER_VIDEO_MAP = new_user_map

def build_playlist_map():
    new_playlist_map = {}
    if not os.path.exists(PLAYLISTS_DIR): return
    for playlist_folder in os.listdir(PLAYLISTS_DIR):
        folder_path = os.path.join(PLAYLISTS_DIR, playlist_folder)
        if not os.path.isdir(folder_path): continue
        meta_file = os.path.join(folder_path, 'playlist.json')
        if not os.path.exists(meta_file): continue
        try:
            with open(meta_file, 'r', encoding='utf-8') as f: data = json.load(f)
            playlist_id = hashlib.md5(playlist_folder.encode()).hexdigest()[:11]
            thumb = data.get('thumbnail', '')
            if thumb and not thumb.startswith('/'): thumb = '/' + thumb
            new_playlist_map[playlist_id] = {'id': playlist_id, 'title': data.get('title', playlist_folder), 'uploader': data.get('uploader', 'Unknown'), 'thumbnail': thumb, 'video_count': data.get('video_count', 0), 'videos': data.get('videos', []), 'folder': playlist_folder}
        except: pass
    global PLAYLIST_MAP
    PLAYLIST_MAP = new_playlist_map

# ===== ИНИЦИАЛИЗАЦИЯ И РЕГИСТРАЦИЯ БЛЮПРИНТОВ =====
custom_quality.init(BASE_VIDEO_DIR, logger, lambda: VIDEO_MAP, lambda: USER_VIDEO_MAP, build_video_map, build_user_video_map)
audio_language.init(BASE_VIDEO_DIR, SUBTITLES_DIR, logger, lambda: VIDEO_MAP, lambda: USER_VIDEO_MAP, build_video_map)

app.register_blueprint(custom_quality.bp)
app.register_blueprint(audio_language.bp)
# ==================================================

@app.route('/usermedia/<path:filename>')
def usermedia(filename):
    return send_from_directory(os.path.join(SCRIPT_DIR, USER_VIDEOS_ROOT), filename)

@app.route('/media/<path:filename>')
def media(filename):
    return send_from_directory(BASE_VIDEO_DIR, filename)

@app.route('/avatars/<filename>')
def serve_avatars(filename):
    return send_from_directory(AVATARS_DIR, filename)

@app.route('/channel_banner/<filename>')
def serve_channel_banner(filename):
    return send_from_directory(channel_assets.BANNERS_DIR, filename)

@app.route('/')
def index():
    ensure_video_map()
    build_user_video_map()
    build_playlist_map()
    
    # Фильтруем скрытые каналы на сервере: клиентская фильтрация оставалась
    # обходимой и заставляла страницу прятать уже отрисованные карточки.
    hidden_authors = hidden_channels_set()

    all_videos, shorts, authors_set = [], [], set()
    for vid, v in VIDEO_MAP.items():
        if v["author"] in hidden_authors: continue
        # Имя превью берём из кэша сканирования, на диск идём только при его отсутствии.
        thumb = v.get("thumb_file")
        if thumb is None and "thumb_file" not in v:
            thumb = find_file(os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"]), ['.jpg','.png','.webp'])
        item = {"author": v["author"], "folder": v["folder"], "filename": v["filename"], "thumb": thumb, "title": v["title"], "is_short": v["is_short"], "size_mb": v["size_mb"], "duration": v.get("duration", 0), "upload_date": v.get("upload_date", ""), "id": vid, "author_avatar": get_avatar_url(v["author"]), "source": "youtube"}
        if v["is_short"]: shorts.append(item)
        else: all_videos.append(item)
        authors_set.add(v["author"])
        
    user_videos_list = [{"id": vid, "title": uv["title"], "author": uv["author"], "size_mb": uv["size_mb"], "thumb": uv["thumb"] if uv["thumb"] and os.path.exists(uv["thumb"]) else None, "source": "user", "video_path": uv["video_path"], "folder": uv.get("folder"), "author_avatar": get_avatar_url(uv["author"])} for vid, uv in USER_VIDEO_MAP.items()]
    random.shuffle(all_videos)
    authors = [{"name": a, "avatar": get_avatar_url(a)} for a in sorted(authors_set)]
    
    # Отдаём пользовательские данные вместе со страницей: без этого избранное
    # и список скрытых каналов появлялись с задержкой после загрузки.
    user_state = userdata.get_all()

    return render_template("index.html", all_videos=all_videos, shorts=shorts, authors=authors, playlists=list(PLAYLIST_MAP.values()), user_videos=user_videos_list, hidden_channels=sorted(hidden_authors), favorites=user_state['favorites'], watch_history=user_state['history'])

@app.route('/settings')
def settings_page():
    return render_template('settings.html')

@app.route('/channel/<author>')
def channel(author):
    ensure_video_map()
    build_playlist_map()

    author_videos = []
    channel_url = ''
    for vid, v in VIDEO_MAP.items():
        if v["author"] != author:
            continue
        if not channel_url:
            channel_url = v.get('channel_url', '')
        author_videos.append({
            "id": vid,
            "title": v.get("title", v["folder"]),
            "author": v["author"],
            "size_mb": v.get("size_mb", 0),
            "thumb": find_file(os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"]), ['.jpg', '.png', '.webp']),
            "folder": v["folder"],
            "duration": v.get("duration", 0),
            "upload_date": v.get("upload_date", ""),
            "is_short": v.get("is_short", False),
            "author_avatar": get_avatar_url(v["author"])
        })

    author_videos.sort(key=lambda v: (v.get('upload_date') or '', v.get('title') or ''), reverse=True)

    author_playlists = []
    for playlist in PLAYLIST_MAP.values():
        if playlist.get("uploader") == author or any(video.get("author") == author for video in playlist.get("videos", [])):
            author_playlists.append({
                "id": playlist.get("id"),
                "title": playlist.get("title", ""),
                "thumbnail": playlist.get("thumbnail"),
                "video_count": playlist.get("video_count", 0)
            })

    authors_list = [{"name": name, "avatar": get_avatar_url(name)} for name in sorted({video["author"] for video in VIDEO_MAP.values()})]
    author_avatar_url = get_avatar_url(author)
    banner_url = channel_assets.get_banner_url(author)
    channel_meta = channel_assets.load_channel_meta(author)
    if not banner_url or not channel_meta:
        threading.Thread(target=channel_assets.try_fetch_if_missing, args=(author,), daemon=True).start()

    return render_template(
        "channel.html",
        author=author,
        author_avatar=author_avatar_url,
        banner_url=banner_url,
        videos=author_videos,
        playlists=author_playlists,
        authors=authors_list,
        # Состояние кнопки «Скрыть канал» приходит сразу, иначе надпись мигает.
        is_hidden=author in hidden_channels_set(),
        total_videos=len(author_videos),
        total_shorts=sum(1 for video in author_videos if video['is_short']),
        channel_url=channel_url,
        description=channel_meta.get('description', ''),
        subscribers=channel_assets.format_subscribers(channel_meta.get('subscribers')),
        country=channel_meta.get('country', ''),
        joined_date=channel_meta.get('joined_date', ''),
        sync_status=channel_assets.get_sync_status(author)
    )


@app.route('/api/channel/<author>/sync-status')
def api_channel_sync_status(author):
    ensure_video_map()
    status = channel_assets.get_sync_status(author)
    status['author'] = author
    status['channel_url'] = next((v.get('channel_url') for v in VIDEO_MAP.values() if v.get('author') == author and v.get('channel_url')), '')
    return jsonify(status)


@app.route('/api/channel/<author>/sync', methods=['POST'])
def api_channel_sync(author):
    build_video_map()
    channel_url = next((v.get('channel_url') for v in VIDEO_MAP.values() if v.get('author') == author and v.get('channel_url')), '')
    if not channel_url:
        channel_url = channel_assets._find_channel_url_from_videos(author)
    if not channel_url:
        return jsonify({'error': 'URL канала не найден в локальных метаданных видео'}), 404
    with channel_assets._fetch_lock:
        if author in channel_assets._fetching:
            return jsonify({'status': 'checking', 'message': 'Синхронизация уже выполняется'})
    threading.Thread(target=channel_assets.sync_channel, args=(author, channel_url), daemon=True).start()
    return jsonify({'status': 'checking', 'message': 'Проверка канала запущена'})


@app.route('/api/thumbnail/<vid_id>')
def api_thumbnail(vid_id):
    if vid_id not in VIDEO_MAP: build_video_map()
    if vid_id in VIDEO_MAP:
        v = VIDEO_MAP[vid_id]
        thumb_path = os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"], "thumbnail.jpg")
        if os.path.exists(thumb_path):
            return send_file(thumb_path)
    return send_file(os.path.join(SCRIPT_DIR, "static", "images", "lazy_placeholder.gif"))

@app.route('/watch/<vid_id>')
def watch(vid_id):
    ensure_video_map()
    build_user_video_map()
    
    meta = {}
    video_url = None
    author_avatar = None
    is_short = False
    
    if vid_id in USER_VIDEO_MAP:
        v = USER_VIDEO_MAP[vid_id]
        meta = {"title": v["title"], "author": v["author"], "description": v["description"], "id": v["id"], "source": "user", "uploader": v["author"]}
        rel_path = os.path.relpath(v["video_path"], start=os.path.join(SCRIPT_DIR, USER_VIDEOS_ROOT)).replace('\\', '/')
        video_url = f"/usermedia/{rel_path}"
        author_avatar = get_avatar_url(v["author"])
    elif vid_id in VIDEO_MAP:
        v = VIDEO_MAP[vid_id]
        folder_path = os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"])
        video_url = f"/media/{quote(v['author'])}/{quote(v['folder'])}/{quote(v['filename'])}"
        author_avatar = get_avatar_url(v["author"])
        is_short = v["is_short"]
        
        info_file = find_file(folder_path, ['info.json', '.info.json'])
        if info_file:
            try:
                with open(os.path.join(folder_path, info_file), 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            except: pass
        if not meta:
            meta = {"title": v["title"], "uploader": v["author"], "id": vid_id}
            
    if not video_url:
        abort(404)
        
    mime_type = "video/mp4"
    if video_url.endswith('.webm'): mime_type = "video/webm"
    elif video_url.endswith('.mkv'): mime_type = "video/x-matroska"

    # Рекомендации: скрытые каналы исключаем до перемешивания, иначе они
    # занимали места в выдаче и клиент прятал их уже постфактум.
    hidden_authors = hidden_channels_set()
    recommended_videos = []
    all_combined = [v for v in VIDEO_MAP.values() if v["author"] not in hidden_authors]
    random.shuffle(all_combined)
    for rv in all_combined[:15]:
        if rv.get("youtube_id", rv["folder"]) != vid_id:
            # Имя превью уже известно из сканирования библиотеки.
            thumb = rv.get("thumb_file")
            if thumb is None and "thumb_file" not in rv:
                thumb = find_file(os.path.join(BASE_VIDEO_DIR, rv["author"], rv["folder"]), ['.jpg','.png','.webp'])
            recommended_videos.append({
                "id": rv.get("youtube_id", rv["folder"]),
                "title": rv["title"], "author": rv["author"],
                "folder": rv["folder"], "thumb": thumb
            })

    # Если Shorts, отдаем всю ленту Shorts
    shorts_feed = []
    if is_short:
        # Скрытые каналы раньше попадали в ленту Shorts: она собиралась на
        # сервере, а клиентская фильтрация до неё не доходила.
        hidden = hidden_channels_set()
        for sid, sv in VIDEO_MAP.items():
            # Текущее видео оставляем даже если его канал скрыт: пользователь
            # открыл его намеренно.
            if sv["author"] in hidden and sid != vid_id: continue
            if sv["is_short"]:
                shorts_feed.append({
                    "id": sid, "title": sv["title"], "author": sv["author"], 
                    "size_mb": sv["size_mb"], "url": f"{sv['author']}/{sv['folder']}/{sv['filename']}"
                })
        random.shuffle(shorts_feed)
        # Перемещаем текущее видео на первое место
        shorts_feed.sort(key=lambda x: x["id"] == vid_id, reverse=True)

    return render_template("video.html", 
                           video_url=video_url, 
                           meta=meta, 
                           author=meta.get('uploader', 'Unknown'),
                           folder=vid_id,
                           video_id=vid_id,
                           mime_type=mime_type, 
                           author_avatar=author_avatar,
                           file_size_mb=round(os.path.getsize(v["video_path"]) / (1024 * 1024), 1) if vid_id in USER_VIDEO_MAP and os.path.exists(v["video_path"]) else round(os.path.getsize(os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"], v["filename"])) / (1024 * 1024), 1) if vid_id in VIDEO_MAP and os.path.exists(os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"], v["filename"])) else 0,
                           recommended_videos=recommended_videos,
                           is_short=is_short,
                           shorts_feed=shorts_feed,
                           video_source=meta.get('source', 'youtube'),
                           publish_date=meta.get('upload_date') or meta.get('upload_date'))

# ================= API: СКАЧИВАНИЕ =================
@app.route('/api/formats', methods=['POST'])
def api_formats():
    url = request.json.get('url')
    if not url: return jsonify({'error': 'URL не указан'})
    formats = get_format_choices(url)
    if not formats:
        formats = [{'type': 'auto', 'format_id': None, 'resolution': 'Авто (рекомендуемое)', 'codec': 'best', 'size_mb': None}]
    return jsonify({'formats': formats, 'video_id': url})

@app.route('/api/direct_formats', methods=['POST'])
def api_direct_formats():
    url = request.json.get('url')
    if not url: return jsonify({'error': 'URL не указан'})
    formats = get_format_choices(url)
    return jsonify({'formats': formats})

@app.route('/api/direct_download', methods=['POST'])
def api_direct_download():
    data = request.json
    url = data.get('url')
    video_format = data.get('format_id')
    audio_format = data.get('audio_format_id')

    if not url: return jsonify({'error': 'URL не указан'})

    final_format = video_format
    if video_format and audio_format:
        final_format = f"{video_format}+{audio_format}"

    success = download_single_sync([url], final_format, lambda p, m: None, merge_format='mp4')
    if success:
        build_video_map()
        return jsonify({'status': 'ok', 'title': 'Загрузка завершена'})
    else:
        return jsonify({'error': 'Ошибка загрузки'})

# ================= API: COOKIES =================
@app.route('/api/cookies', methods=['GET', 'DELETE'])
def api_cookies():
    if request.method == 'GET':
        if not os.path.exists(COOKIES_PATH):
            return jsonify({'exists': False, 'size': 0})
        mtime = os.path.getmtime(COOKIES_PATH)
        return jsonify({'exists': True, 'size': os.path.getsize(COOKIES_PATH), 'modified': mtime})
    elif request.method == 'DELETE':
        if os.path.exists(COOKIES_PATH):
            os.remove(COOKIES_PATH)
            return jsonify({'status': 'deleted'})
        return jsonify({'status': 'not_found'})

@app.route('/api/cookies/status', methods=['GET'])
def api_cookies_status():
    return jsonify({
        'exists': os.path.exists(COOKIES_PATH),
        'size': os.path.getsize(COOKIES_PATH) if os.path.exists(COOKIES_PATH) else 0,
        'modified': os.path.getmtime(COOKIES_PATH) if os.path.exists(COOKIES_PATH) else 0
    })

@app.route('/api/cookies/import', methods=['POST'])
def api_cookies_import():
    try:
        if request.content_type == 'application/json':
            data = request.json
            text = data.get('text', '')
            if not text:
                return jsonify({'error': 'Нет данных cookies'})
            lines = text.strip().split('\n')
            cookies_count = 0
            if lines and "Netscape" in lines[0]:
                netscape_content = text
                try:
                    import http.cookiejar
                    import io
                    cookie_jar = http.cookiejar.MozillaCookieJar()
                    cookie_jar.load(io.StringIO(netscape_content), ignore_discard=True, ignore_expires=True)
                    cookies_count = len(list(cookie_jar))
                except Exception:
                    cookies_count = len([l for l in lines if l.strip() and not l.startswith('#')])
                with open(COOKIES_PATH, 'w', encoding='utf-8') as f:
                    f.write(text)
            else:
                try:
                    import json as json_module
                    data_cookies = json_module.loads(text)
                    if isinstance(data_cookies, list):
                        netscape_lines = ['# Netscape HTTP Cookie File']
                        for c in data_cookies:
                            netscape_lines.append(f"{c.get('domain', '')}\t{'TRUE' if c.get('domain','').startswith('.') else 'FALSE'}\t{c.get('path', '/')}\t{'TRUE' if c.get('secure') else 'FALSE'}\t{c.get('expires', 0)}\t{c.get('name', '')}\t{c.get('value', '')}")
                        with open(COOKIES_PATH, 'w', encoding='utf-8') as f:
                            f.write('\n'.join(netscape_lines))
                        cookies_count = len(data_cookies)
                    else:
                        return jsonify({'error': 'Неверный формат JSON'})
                except Exception as e:
                    return jsonify({'error': f'Ошибка парсинга: {str(e)}'})
        elif 'file' in request.files:
            file = request.files['file']
            if not file:
                return jsonify({'error': 'Файл не загружен'})
            content = file.read().decode('utf-8')
            cookies_count = len([l for l in content.strip().split('\n') if l.strip() and not l.startswith('#')])
            with open(COOKIES_PATH, 'w', encoding='utf-8') as f:
                f.write(content)
        else:
            return jsonify({'error': 'Нет данных для импорта'})
        return jsonify({'status': 'ok', 'cookies_count': cookies_count})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/cookies/from-browser', methods=['POST'])
def api_cookies_from_browser():
    browser = (request.json or {}).get('browser', '')
    if not browser:
        return jsonify({'error': 'Не указан браузер'}), 400
    result = auth_options.import_cookies_from_browser(browser)
    if result.get('error'):
        return jsonify({'error': result['error']}), 400
    return jsonify({'status': 'ok', 'cookies_count': result['count'], 'browser': result['browser']})

@app.route('/api/playlist/info', methods=['POST'])
def api_playlist_info():
    url = request.json.get('url')
    if not url: return jsonify({'error': 'URL не указан'})
    try:
        info = get_playlist_info(url)
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/channel/<author>/remaining', methods=['POST'])
def api_channel_remaining(author):
    build_video_map()
    channel_urls = [v.get('channel_url') for v in VIDEO_MAP.values() if v.get('author') == author and v.get('channel_url')]
    channel_url = next((url for url in channel_urls if url), '')
    if not channel_url:
        return jsonify({'error': 'Не удалось определить ссылку на канал'}), 404
    try:
        options = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extract_flat': True,
            'ignoreerrors': True,
            'socket_timeout': 30,
            'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
            # Иначе канал не извлекается, если cookies от другого аккаунта.
            'extractor_args': {'youtubetab': {'skip': ['authcheck']}},
        }
        po_args = get_po_args()
        if po_args:
            options.update(po_args)
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(channel_url, download=False)
        entries = info.get('entries', []) if isinstance(info, dict) else []
        local_ids = set(VIDEO_MAP.keys())
        remaining = []
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            video_id = entry.get('id', '')
            url = entry.get('webpage_url') or entry.get('url')
            if video_id and not str(url).startswith('http'):
                url = f"https://www.youtube.com/watch?v={video_id}"
            if not url or not video_id or video_id in local_ids or video_id in seen:
                continue
            seen.add(video_id)
            remaining.append({'id': video_id, 'url': url, 'title': entry.get('title', 'Видео')})
        return jsonify({'title': info.get('title', author), 'videos': remaining, 'count': len(remaining)})
    except Exception as e:
        logger.warning(f"Не удалось получить видео канала {author}: {e}")
        return jsonify({'error': str(e)}), 502

# ================= ОЧЕРЕДЬ =================
# Плагины getpot_bgutil для PO Token (создаются при первом запуске)
try:
    auth_options.ensure_plugins()
except Exception as e:
    logger.warning(f"Не удалось установить плагины PO Token: {e}")

_queue_worker_started = False

def ensure_queue_worker():
    """Запускает фоновый обработчик очереди (только один раз)."""
    global _queue_worker_started
    if not _queue_worker_started:
        _queue_worker_started = True
        threading.Thread(target=process_queue, daemon=True).start()

def process_queue():
    global queue_processing, queue_paused
    queue_processing = True
    while True:
        if queue_paused:
            time.sleep(2)
            continue
            
        task_to_process = None
        with queue_lock:
            # Сначала высокий приоритет, внутри одного приоритета — порядок добавления.
            waiting = [t for t in queue_tasks if t.status == "waiting"]
            if waiting:
                task = min(waiting, key=lambda t: PRIORITY_ORDER.get(t.priority, 1))
                task_to_process = task
                task.status = "downloading"
                task.progress = 0
                task.message = "Подготовка загрузки..."
                task.error = ""
                task.current_url = task.urls[0] if task.urls else ""
                task.current_index = 1 if task.urls else 0
                task.total_urls = len(task.urls)
                task.speed = ""
                task.eta = ""
                task.attempts += 1
                queue_cancel_requests.discard(task.id)
        if task_to_process:
            save_queue()

        if not task_to_process:

            time.sleep(2)
            continue
            
        def update_progress(percent, message):
            with queue_lock:
                task_to_process.progress = max(0, min(100, percent or 0))
                if message:
                    task_to_process.message = message
                    match = re.match(r'\[(\d+)/(\d+)\]\s+', message)
                    if match:
                        task_to_process.current_index = int(match.group(1))
                        task_to_process.total_urls = int(match.group(2))
                    speed_match = re.search(r'·\s*([^·]+?)\s*·\s*ETA\s*(.+)$', message)
                    if speed_match:
                        task_to_process.speed = speed_match.group(1).strip()
                        task_to_process.eta = speed_match.group(2).strip()
            save_queue()
            
        def is_cancelled():
            with queue_lock:
                return task_to_process.id in queue_cancel_requests

        try:
            success = download_single_sync(
                task_to_process.urls, 
                task_to_process.format_id, 
                update_progress, 
                task_to_process.merge_format,
                should_cancel=is_cancelled
            )
            with queue_lock:
                task_to_process.status = "completed" if success else "error"
                task_to_process.progress = 100 if success else 0
                task_to_process.message = "Готово" if success else "Ошибка скачивания"
                task_to_process.error = "" if success else task_to_process.message
            save_queue()
        except DownloadCancelledByUser:
            with queue_lock:
                queue_cancel_requests.discard(task_to_process.id)
                task_to_process.status = "cancelled"
                task_to_process.progress = 0
                task_to_process.message = "Отменено пользователем"
                task_to_process.error = ""
                task_to_process.speed = ""
                task_to_process.eta = ""
            save_queue()
        except Exception as e:
            logger.error(f"Queue error: {e}")
            with queue_lock:
                queue_cancel_requests.discard(task_to_process.id)
                task_to_process.status = "error"
                task_to_process.error = str(e)
                task_to_process.message = f"Ошибка: {e}"
            save_queue()

                
        build_video_map()
        time.sleep(1)

@app.route('/api/queue/add', methods=['POST'])
def api_queue_add():
    ensure_queue_worker()
    data = request.json
    urls = data.get('urls', [])
    format_id = data.get('format_id')
    title = data.get('title', 'Видео')
    merge_format = data.get('merge_format', 'mp4')
    
    if not urls: return jsonify({'error': 'Нет ссылок'})
    
    priority = data.get('priority', PRIORITY_NORMAL)
    task_id = hashlib.md5(f"{time.time()}{urls[0]}".encode()).hexdigest()[:8]
    task = QueueTask(task_id, urls, format_id, title, merge_format, priority)
    
    with queue_lock:
        queue_tasks.append(task)
    save_queue()
    return jsonify({'status': 'ok', 'task_id': task_id})

@app.route('/api/queue/list', methods=['GET'])
def api_queue_list():
    with queue_lock:
        tasks = [{
            'id': t.id, 'title': t.title, 'urls': t.urls,
            'status': t.status, 'progress': t.progress, 'message': t.message,
            'error': t.error, 'added_at': t.added_at,
            'current_url': t.current_url, 'current_index': t.current_index,
            'total_urls': t.total_urls, 'speed': t.speed, 'eta': t.eta,
            'attempts': t.attempts, 'priority': t.priority,
            'cancelling': t.id in queue_cancel_requests and t.status == 'downloading'
        } for t in queue_tasks]
    return jsonify({'tasks': tasks, 'paused': queue_paused})

@app.route('/api/queue/remove/<task_id>', methods=['DELETE'])
def api_queue_remove(task_id):
    global queue_tasks
    with queue_lock:
        # Удаление активной задачи равносильно отмене: иначе загрузчик продолжил бы
        # писать файлы для задачи, которой уже нет в очереди.
        active = any(t.id == task_id and t.status == 'downloading' for t in queue_tasks)
        if active:
            queue_cancel_requests.add(task_id)
        queue_tasks = [t for t in queue_tasks if t.id != task_id]
    save_queue()
    return jsonify({'status': 'ok', 'cancelled_active': active})


@app.route('/api/queue/cancel/<task_id>', methods=['POST'])
def api_queue_cancel(task_id):
    """Отменяет задачу. Активная загрузка прерывается, temp-файлы удаляются."""
    with queue_lock:
        task = next((t for t in queue_tasks if t.id == task_id), None)
        if not task:
            return jsonify({'error': 'Задача не найдена'}), 404
        if task.status in ('completed', 'error', 'cancelled'):
            return jsonify({'error': 'Задача уже завершена'}), 409
        was_downloading = task.status == 'downloading'
        if was_downloading:
            # Воркер увидит запрос на следующем хуке прогресса и остановится сам.
            queue_cancel_requests.add(task_id)
            task.message = 'Отмена загрузки...'
        else:
            task.status = 'cancelled'
            task.progress = 0
            task.message = 'Отменено пользователем'
            task.error = ''
    save_queue()
    return jsonify({'status': 'ok', 'was_downloading': was_downloading})


@app.route('/api/queue/priority/<task_id>', methods=['POST'])
def api_queue_priority(task_id):
    """Меняет приоритет ожидающей задачи."""
    priority = (request.json or {}).get('priority', PRIORITY_NORMAL)
    if priority not in PRIORITY_ORDER:
        return jsonify({'error': 'Неизвестный приоритет'}), 400
    with queue_lock:
        task = next((t for t in queue_tasks if t.id == task_id), None)
        if not task:
            return jsonify({'error': 'Задача не найдена'}), 404
        task.priority = priority
    save_queue()
    return jsonify({'status': 'ok', 'priority': priority})

@app.route('/api/queue/retry/<task_id>', methods=['POST'])
def api_queue_retry(task_id):
    found = False
    with queue_lock:
        for t in queue_tasks:
            if t.id == task_id:
                queue_cancel_requests.discard(task_id)
                t.status = 'waiting'
                t.progress = 0
                t.error = ''
                t.message = 'Повторная попытка ожидает запуска'
                found = True
                break
    if not found:
        return jsonify({'error': 'Задача не найдена'}), 404
    save_queue()
    ensure_queue_worker()
    return jsonify({'status': 'ok'})

@app.route('/api/queue/pause', methods=['POST'])
def api_queue_pause():
    global queue_paused
    queue_paused = True
    save_queue()
    return jsonify({'status': 'ok', 'paused': True})

@app.route('/api/queue/resume', methods=['POST'])
def api_queue_resume():
    global queue_paused
    queue_paused = False
    save_queue()
    ensure_queue_worker()
    return jsonify({'status': 'ok', 'paused': False})

@app.route('/api/queue/clear', methods=['POST'])
def api_queue_clear():
    global queue_tasks
    with queue_lock:
        queue_tasks = [t for t in queue_tasks if t.status not in ('completed', 'error', 'cancelled')]
    save_queue()
    return jsonify({'status': 'ok'})

# ================= ПОЛЬЗОВАТЕЛЬСКИЕ ВИДЕО =================
@app.route('/upload')
def upload_page():
    return render_template('upload.html')

@app.route('/edit/<vid_id>')
def edit_page(vid_id):
    return render_template('edit.html', vid_id=vid_id)

@app.route('/api/user_video/upload', methods=['POST'])
def api_user_upload():
    try:
        username = request.form.get('username', 'Гость')
        title = request.form.get('title', 'Без названия')
        desc = request.form.get('description', '')
        v_file = request.files.get('video_file')
        t_file = request.files.get('thumbnail_file')
        
        if not v_file: return jsonify({'error': 'Файл видео обязателен'}), 400
        
        tmp_v = os.path.join(SCRIPT_DIR, "temp_video" + os.path.splitext(v_file.filename)[1])
        v_file.save(tmp_v)
        
        tmp_t = None
        if t_file:
            tmp_t = os.path.join(SCRIPT_DIR, "temp_thumb" + os.path.splitext(t_file.filename)[1])
            t_file.save(tmp_t)
            
        info = add_user_video(tmp_v, title, desc, username, tmp_t)
        
        if os.path.exists(tmp_v): os.remove(tmp_v)
        if tmp_t and os.path.exists(tmp_t): os.remove(tmp_t)
        
        build_user_video_map()
        return jsonify({'status': 'ok', 'id': info['id']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/user_video/edit/<vid_id>', methods=['POST'])
def api_user_edit(vid_id):
    try:
        username = request.form.get('username')
        title = request.form.get('title')
        desc = request.form.get('description')
        t_file = request.files.get('thumbnail_file')
        
        tmp_t = None
        if t_file:
            tmp_t = os.path.join(SCRIPT_DIR, "temp_thumb2" + os.path.splitext(t_file.filename)[1])
            t_file.save(tmp_t)
            
        info = edit_user_video(vid_id, title, desc, username, tmp_t)
        if tmp_t and os.path.exists(tmp_t): os.remove(tmp_t)
        
        if info:
            build_user_video_map()
            return jsonify({'status': 'ok'})
        return jsonify({'error': 'Не найдено или нет прав'}), 403
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/user_video/delete/<vid_id>', methods=['POST'])
def api_user_delete(vid_id):
    username = request.json.get('username')
    if delete_user_video(vid_id, username):
        build_user_video_map()
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Не найдено'}), 403

@app.route('/api/user_video/info/<vid_id>')
def api_user_info(vid_id):
    build_user_video_map()
    if vid_id in USER_VIDEO_MAP:
        return jsonify(USER_VIDEO_MAP[vid_id])
    return jsonify({'error': 'Not found'}), 404

# ================= АВТОРИЗАЦИЯ YOUTUBE (СПОСОБЫ ЗАГРУЗКИ) =================
@app.route('/api/auth/options', methods=['GET'])
def api_auth_options_get():
    return jsonify(auth_options.get_options())

@app.route('/api/auth/options', methods=['POST'])
def api_auth_options_save():
    data = request.json or {}
    result = auth_options.save_options(data)
    if isinstance(result, dict) and result.get('error'):
        return jsonify({'error': result['error']}), 400
    return jsonify({'status': 'ok'})

@app.route('/api/auth/ensure', methods=['POST'])
def api_auth_ensure():
    ok = auth_options.ensure_plugins()
    return jsonify({'status': 'ok' if ok else 'error', 'plugins_dir': os.path.isdir(auth_options.PLUGINS_DIR)})

@app.route('/api/auth/status')
def api_auth_status():
    return jsonify(auth_options.status())

# ================= УТИЛИТЫ (Аватарки и Превью) =================
@app.route('/api/avatars/download_all', methods=['POST'])
def api_download_all_avatars():
    def run_script():
        subprocess.run([sys.executable, 'download_avatars.py'], cwd=SCRIPT_DIR)
    threading.Thread(target=run_script, daemon=True).start()
    return jsonify({'status': 'started'})

@app.route('/api/thumbnails/generate', methods=['POST'])
def api_generate_thumbnails():
    force = request.json.get('force', False)
    def run_script():
        cmd = [sys.executable, 'download_thumbnails.py']
        if force: cmd.append('--force')
        subprocess.run(cmd, cwd=SCRIPT_DIR)
    threading.Thread(target=run_script, daemon=True).start()
    return jsonify({'status': 'started'})

@app.route('/api/theme-backgrounds/<theme>')
def api_theme_backgrounds(theme):
    theme_dir = os.path.join(SCRIPT_DIR, 'static', 'images', 'themes', theme)
    if not os.path.exists(theme_dir): return jsonify([])
    images = [f for f in os.listdir(theme_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    return jsonify(images)

@app.route('/api/frutiger/backgrounds')
def api_frutiger_backgrounds():
    theme_dir = os.path.join(SCRIPT_DIR, 'static', 'images', 'themes', 'frutiger-aero')
    if not os.path.exists(theme_dir):
        return jsonify({'status': 'error', 'message': 'Directory not found'}), 404
    images = [f for f in os.listdir(theme_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    if not images:
        return jsonify({'status': 'error', 'message': 'No images found'}), 404
    import random
    selected = random.sample(images, min(2, len(images)))
    urls = ['/static/images/themes/frutiger-aero/' + quote(img) for img in selected]
    return jsonify({'status': 'ok', 'urls': urls})


# ================= API: КАТАЛОГ (JSON) =================
def _user_media_url(path):
    try:
        rel = os.path.relpath(path, start=os.path.join(SCRIPT_DIR, USER_VIDEOS_ROOT)).replace('\\', '/')
        return f"/usermedia/{rel}"
    except Exception:
        return None

def _video_item(vid, v):
    # Имя превью уже известно из сканирования; на диск ходим только если его нет.
    thumb = v.get("thumb_file")
    if thumb is None and "thumb_file" not in v:
        thumb = find_file(os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"]), ['.jpg', '.png', '.webp'])
    return {
        "id": vid, "author": v["author"], "title": v["title"],
        "is_short": v["is_short"], "size_mb": v["size_mb"], "duration": v.get("duration", 0), "upload_date": v.get("upload_date", ""), "source": "youtube",
        "video_url": f"/media/{quote(v['author'])}/{quote(v['folder'])}/{quote(v['filename'])}",
        "thumb": f"/media/{quote(v['author'])}/{quote(v['folder'])}/{quote(thumb)}" if thumb else None,
        "author_avatar": get_avatar_url(v["author"]),
    }

def hidden_channels_set():
    """Скрытые каналы для серверной фильтрации подборок.

    Скрытие раньше работало только в браузере, поэтому любой другой клиент
    (и сам JSON API) продолжал получать видео скрытых каналов.
    """
    try:
        return set(userdata.get_all().get('hidden_channels', []))
    except Exception as e:
        # Подборки важнее фильтра: при сбое чтения показываем всё.
        logger.warning(f"Не удалось получить список скрытых каналов: {e}")
        return set()


@app.route('/api/catalog')
def api_catalog():
    ensure_video_map()
    build_user_video_map()
    build_playlist_map()

    # include_hidden=1 нужен странице настроек, чтобы показать сами скрытые каналы.
    hidden = set() if request.args.get('include_hidden') == '1' else hidden_channels_set()

    videos, shorts = [], []
    for vid, v in VIDEO_MAP.items():
        if v["author"] in hidden: continue
        item = _video_item(vid, v)
        if v["is_short"]: shorts.append(item)
        else: videos.append(item)

    authors = [{"name": a, "avatar": get_avatar_url(a)}
               for a in sorted({v["author"] for v in VIDEO_MAP.values()} - hidden)]

    user_videos = [{
        "id": uv["id"], "title": uv["title"], "author": uv["author"],
        "size_mb": uv["size_mb"], "source": "user", "author_avatar": get_avatar_url(uv["author"]),
        "thumb": _user_media_url(uv["thumb"]) if uv.get("thumb") else None,
        "video_url": _user_media_url(uv["video_path"]),
    } for uv in USER_VIDEO_MAP.values()]

    playlists = [{
        "id": p["id"], "title": p["title"], "uploader": p["uploader"],
        "thumbnail": p["thumbnail"], "video_count": p["video_count"],
    } for p in PLAYLIST_MAP.values()]

    random.shuffle(videos)
    return jsonify({
        "videos": videos, "shorts": shorts,
        "authors": authors, "playlists": playlists, "user_videos": user_videos,
    })

@app.route('/api/video/<vid_id>')
def api_video(vid_id):
    ensure_video_map()
    build_user_video_map()

    meta = {}
    video_url = None
    author_avatar = None
    is_short = False
    source = "youtube"
    thumb = None

    if vid_id in USER_VIDEO_MAP:
        uv = USER_VIDEO_MAP[vid_id]
        meta = {"title": uv["title"], "author": uv["author"], "description": uv.get("description", ""), "id": uv["id"], "source": "user"}
        video_url = _user_media_url(uv["video_path"])
        author_avatar = get_avatar_url(uv["author"])
        thumb = _user_media_url(uv["thumb"]) if uv.get("thumb") else None
        source = "user"
    elif vid_id in VIDEO_MAP:
        v = VIDEO_MAP[vid_id]
        folder_path = os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"])
        video_url = f"/media/{quote(v['author'])}/{quote(v['folder'])}/{quote(v['filename'])}"
        author_avatar = get_avatar_url(v["author"])
        is_short = v["is_short"]
        thumb_file = find_file(folder_path, ['.jpg', '.png', '.webp'])
        if thumb_file:
            thumb = f"/media/{quote(v['author'])}/{quote(v['folder'])}/{quote(thumb_file)}"
        info_file = find_file(folder_path, ['info.json', '.info.json'])
        if info_file:
            try:
                with open(os.path.join(folder_path, info_file), 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            except: pass
        if not meta:
            meta = {"title": v["title"], "uploader": v["author"], "id": vid_id}

    if not video_url:
        return jsonify({"error": "Not found"}), 404

    mime_type = "video/mp4"
    if video_url.endswith('.webm'): mime_type = "video/webm"
    elif video_url.endswith('.mkv'): mime_type = "video/x-matroska"

    full_path = os.path.join(SCRIPT_DIR, video_url.lstrip('/'))
    file_size_mb = round(os.path.getsize(full_path) / (1024 * 1024), 1) if os.path.exists(full_path) else 0

    recommended = []
    all_combined = list(VIDEO_MAP.values())
    random.shuffle(all_combined)
    for rv in all_combined[:15]:
        if rv.get("youtube_id", rv["folder"]) != vid_id:
            recommended.append(_video_item(rv.get("youtube_id", rv["folder"]), rv))

    return jsonify({
        "id": vid_id,
        "title": meta.get("title", "Без названия"),
        "author": meta.get("uploader", meta.get("author", "Unknown")),
        "description": meta.get("description", ""),
        "video_url": video_url,
        "mime_type": mime_type,
        "is_short": is_short,
        "thumb": thumb,
        "author_avatar": author_avatar,
        "file_size_mb": file_size_mb,
        "source": source,
        "recommended": recommended,
    })

# ================= ПОЛЬЗОВАТЕЛЬСКИЕ ДАННЫЕ =================
# Избранное, история и скрытые каналы раньше жили в localStorage: пропадали
# при чистке браузера и не были видны с других устройств.

@app.route('/api/userdata', methods=['GET'])
def api_userdata_get():
    return jsonify(userdata.get_all())


@app.route('/api/userdata/favorite/<vid_id>', methods=['POST'])
def api_userdata_favorite(vid_id):
    # Клиент может прислать желаемое состояние (active). Без него — переключение,
    # но тогда запрос, отправленный до загрузки данных, сделает обратное.
    desired = (request.json or {}).get('active') if request.is_json else None
    try:
        active, items = userdata.toggle_favorite(vid_id, desired)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok', 'active': active, 'favorites': items})


@app.route('/api/userdata/hidden-channel', methods=['POST'])
def api_userdata_hidden_channel():
    payload = request.json or {}
    author = payload.get('author', '')
    try:
        hidden, items = userdata.toggle_hidden_channel(author, payload.get('hidden'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok', 'hidden': hidden, 'hidden_channels': items})


@app.route('/api/userdata/watched/<vid_id>', methods=['POST'])
def api_userdata_watched(vid_id):
    try:
        history = userdata.mark_watched(vid_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok', 'history': history})


@app.route('/api/userdata/clear/<section>', methods=['POST'])
def api_userdata_clear(section):
    try:
        userdata.clear(section)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok', **userdata.get_all()})


@app.route('/api/userdata/migrate', methods=['POST'])
def api_userdata_migrate():
    """Разовый перенос данных из localStorage. Ничего не удаляет.

    При ошибке отвечает 500: клиент стирает localStorage только после успеха,
    поэтому мнимый успех означал бы потерю данных.
    """
    try:
        added, state = userdata.merge_from_client(request.json or {})
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok', 'added': added, **state})


@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').lower().strip()
    if not q:
        return jsonify({"results": []})
    ensure_video_map()
    build_user_video_map()

    hidden = set() if request.args.get('include_hidden') == '1' else hidden_channels_set()

    results = []
    for vid, v in VIDEO_MAP.items():
        if v["author"] in hidden: continue
        if q in v["title"].lower() or q in v["author"].lower():
            results.append(_video_item(vid, v))
    for uv in USER_VIDEO_MAP.values():
        if q in uv["title"].lower() or q in uv["author"].lower():
            results.append({
                "id": uv["id"], "author": uv["author"], "title": uv["title"],
                "is_short": False, "size_mb": uv["size_mb"], "source": "user",
                "video_url": _user_media_url(uv["video_path"]),
                "thumb": _user_media_url(uv["thumb"]) if uv.get("thumb") else None,
                "author_avatar": get_avatar_url(uv["author"]),
            })
    return jsonify({"results": results})


# ================= ЗАПУСК СЕРВЕРА =================
if __name__ == '__main__':
    # Запускаем фоновый поток для очереди
    ensure_queue_worker()
    
    print("==================================================")
    print("LocalTube starting...")
    print("Open in browser: http://127.0.0.1:5000")
    print("==================================================")
    
    # Отключаем логи Werkzeug для чистоты консоли
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    app.run(host='0.0.0.0', port=5000, debug=False)