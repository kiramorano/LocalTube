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
from download_lib import download_media, download_single_sync
from utils import safe_name, is_shorts_video
from user_videos import add_user_video, edit_user_video, delete_user_video, get_all_user_videos, USER_VIDEOS_ROOT
from logger import logger
from po_manager import get_po_method, get_video_info, get_formats, get_playlist_info as get_playlist_info_new, shutdown_extractor, get_extractor, get_po_args
import yt_dlp

# Импорт наших новых модулей (Blueprints)
import custom_quality
import audio_language

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
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                for k in default:
                    if k not in cfg: cfg[k] = default[k]
                return cfg
        except: return default
    return default

def save_config(cfg):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

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
        with open(QUEUE_FILE, 'w', encoding='utf-8') as f: json.dump([], f)
    except Exception as e: logger.warning(f"Не удалось создать queue.json: {e}")

progress_data = {"percent": 0, "status": "idle", "message": ""}
VIDEO_MAP = {}
PLAYLIST_MAP = {}
USER_VIDEO_MAP = {}

queue_tasks = []
queue_lock = threading.Lock()
queue_processing = False
queue_paused = False

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

def get_avatar_url(author):
    safe = safe_name(author)
    if os.path.exists(AVATARS_DIR):
        for f in os.listdir(AVATARS_DIR):
            name, ext = os.path.splitext(f)
            if name == safe and ext.lower() in ('.jpg','.jpeg','.png','.webp'): return f"/avatars/{f}"
    return None

def build_video_map():
    new_video_map = {}
    if not os.path.exists(BASE_VIDEO_DIR): return 0
    total = 0
    for author in os.listdir(BASE_VIDEO_DIR):
        author_path = os.path.join(BASE_VIDEO_DIR, author)
        if not os.path.isdir(author_path) or author == os.path.basename(AVATARS_DIR): continue
        for vfolder in os.listdir(author_path):
            vpath = os.path.join(author_path, vfolder)
            if not os.path.isdir(vpath): continue
            video_file = find_main_video_file(vpath)
            if not video_file: continue
            meta_file = find_file(vpath, ['info.json', '.info.json'])
            meta = {}
            if meta_file:
                try:
                    with open(os.path.join(vpath, meta_file), 'r', encoding='utf-8') as jf: meta = json.load(jf)
                except: pass
            try:
                youtube_id = meta.get('id', '')
                vid = youtube_id if youtube_id else vfolder
                new_video_map[vid] = {
                    "author": author, "folder": vfolder, "is_short": is_shorts_video(meta) if meta else False,
                    "filename": video_file, "title": meta.get('title', f"Видео {vfolder}"),
                    "size_mb": round(os.path.getsize(os.path.join(vpath, video_file))/(1024*1024),1) if video_file else 0,
                    "source": "youtube", "youtube_id": youtube_id
                }
                total += 1
            except Exception as e:
                logger.error(f"Ошибка обработки {vpath}: {e}")
                continue
    global VIDEO_MAP
    VIDEO_MAP = new_video_map
    return total

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

@app.route('/')
def index():
    build_video_map()
    build_user_video_map()
    build_playlist_map()
    
    all_videos, shorts, authors_set = [], [], set()
    for vid, v in VIDEO_MAP.items():
        thumb = find_file(os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"]), ['.jpg','.png','.webp'])
        item = {"author": v["author"], "folder": v["folder"], "filename": v["filename"], "thumb": thumb, "title": v["title"], "is_short": v["is_short"], "size_mb": v["size_mb"], "id": vid, "author_avatar": get_avatar_url(v["author"]), "source": "youtube"}
        if v["is_short"]: shorts.append(item)
        else: all_videos.append(item)
        authors_set.add(v["author"])
        
    user_videos_list = [{"id": vid, "title": uv["title"], "author": uv["author"], "size_mb": uv["size_mb"], "thumb": uv["thumb"] if uv["thumb"] and os.path.exists(uv["thumb"]) else None, "source": "user", "video_path": uv["video_path"], "folder": uv.get("folder"), "author_avatar": get_avatar_url(uv["author"])} for vid, uv in USER_VIDEO_MAP.items()]
    random.shuffle(all_videos)
    authors = [{"name": a, "avatar": get_avatar_url(a)} for a in sorted(authors_set)]
    
    return render_template("index.html", all_videos=all_videos, shorts=shorts, authors=authors, playlists=list(PLAYLIST_MAP.values()), user_videos=user_videos_list)

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
    build_video_map()
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

    # Рекомендации
    recommended_videos = []
    all_combined = list(VIDEO_MAP.values())
    random.shuffle(all_combined)
    for rv in all_combined[:15]:
        if rv.get("youtube_id", rv["folder"]) != vid_id:
            thumb = find_file(os.path.join(BASE_VIDEO_DIR, rv["author"], rv["folder"]), ['.jpg','.png','.webp'])
            recommended_videos.append({
                "id": rv.get("youtube_id", rv["folder"]),
                "title": rv["title"], "author": rv["author"],
                "folder": rv["folder"], "thumb": thumb
            })

    # Если Shorts, отдаем всю ленту Shorts
    shorts_feed = []
    if is_short:
        for sid, sv in VIDEO_MAP.items():
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
                           mime_type=mime_type, 
                           author_avatar=author_avatar,
                           file_size_mb=round(os.path.getsize(os.path.join(SCRIPT_DIR, video_url.lstrip('/')))/(1024*1024),1) if os.path.exists(os.path.join(SCRIPT_DIR, video_url.lstrip('/'))) else 0,
                           recommended_videos=recommended_videos,
                           is_short=is_short,
                           shorts_feed=shorts_feed,
                           video_source=meta.get('source', 'youtube'))

# ================= API: СКАЧИВАНИЕ =================
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

@app.route('/api/playlist/info', methods=['POST'])
def api_playlist_info():
    url = request.json.get('url')
    if not url: return jsonify({'error': 'URL не указан'})
    try:
        info = get_playlist_info(url)
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)})

# ================= ОЧЕРЕДЬ =================
def process_queue():
    global queue_processing, queue_paused
    queue_processing = True
    while True:
        if queue_paused:
            time.sleep(2)
            continue
            
        task_to_process = None
        with queue_lock:
            for task in queue_tasks:
                if task.status == "waiting":
                    task_to_process = task
                    task.status = "downloading"
                    break
                    
        if not task_to_process:
            time.sleep(2)
            continue
            
        def update_progress(percent, message):
            task_to_process.progress = percent
            
        try:
            success = download_single_sync(
                task_to_process.urls, 
                task_to_process.format_id, 
                update_progress, 
                task_to_process.merge_format
            )
            with queue_lock:
                task_to_process.status = "completed" if success else "error"
                task_to_process.progress = 100 if success else 0
        except Exception as e:
            logger.error(f"Queue error: {e}")
            with queue_lock:
                task_to_process.status = "error"
                
        build_video_map()
        time.sleep(1)

@app.route('/api/queue/add', methods=['POST'])
def api_queue_add():
    data = request.json
    urls = data.get('urls', [])
    format_id = data.get('format_id')
    title = data.get('title', 'Видео')
    merge_format = data.get('merge_format', 'mp4')
    
    if not urls: return jsonify({'error': 'Нет ссылок'})
    
    task_id = hashlib.md5(f"{time.time()}{urls[0]}".encode()).hexdigest()[:8]
    task = QueueTask(task_id, urls, format_id, title, merge_format)
    
    with queue_lock:
        queue_tasks.append(task)
        
    return jsonify({'status': 'ok', 'task_id': task_id})

@app.route('/api/queue/list', methods=['GET'])
def api_queue_list():
    with queue_lock:
        tasks = [{
            'id': t.id, 'title': t.title, 'urls': t.urls,
            'status': t.status, 'progress': t.progress, 'added_at': t.added_at
        } for t in queue_tasks]
    return jsonify({'tasks': tasks, 'paused': queue_paused})

@app.route('/api/queue/remove/<task_id>', methods=['DELETE'])
def api_queue_remove(task_id):
    global queue_tasks
    with queue_lock:
        queue_tasks = [t for t in queue_tasks if t.id != task_id]
    return jsonify({'status': 'ok'})

@app.route('/api/queue/pause', methods=['POST'])
def api_queue_pause():
    global queue_paused
    queue_paused = True
    return jsonify({'status': 'ok'})

@app.route('/api/queue/resume', methods=['POST'])
def api_queue_resume():
    global queue_paused
    queue_paused = False
    return jsonify({'status': 'ok'})

@app.route('/api/queue/clear', methods=['POST'])
def api_queue_clear():
    global queue_tasks
    with queue_lock:
        queue_tasks = [t for t in queue_tasks if t.status in ('completed', 'error')]
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


# ================= API: КАТАЛОГ (JSON) =================
def _user_media_url(path):
    try:
        rel = os.path.relpath(path, start=os.path.join(SCRIPT_DIR, USER_VIDEOS_ROOT)).replace('\\', '/')
        return f"/usermedia/{rel}"
    except Exception:
        return None

def _video_item(vid, v):
    thumb = find_file(os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"]), ['.jpg', '.png', '.webp'])
    return {
        "id": vid, "author": v["author"], "title": v["title"],
        "is_short": v["is_short"], "size_mb": v["size_mb"], "source": "youtube",
        "video_url": f"/media/{quote(v['author'])}/{quote(v['folder'])}/{quote(v['filename'])}",
        "thumb": f"/media/{quote(v['author'])}/{quote(v['folder'])}/{quote(thumb)}" if thumb else None,
        "author_avatar": get_avatar_url(v["author"]),
    }

@app.route('/api/catalog')
def api_catalog():
    build_video_map()
    build_user_video_map()
    build_playlist_map()

    videos, shorts = [], []
    for vid, v in VIDEO_MAP.items():
        item = _video_item(vid, v)
        if v["is_short"]: shorts.append(item)
        else: videos.append(item)

    authors = [{"name": a, "avatar": get_avatar_url(a)} for a in sorted({v["author"] for v in VIDEO_MAP.values()})]

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
    build_video_map()
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

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').lower().strip()
    if not q:
        return jsonify({"results": []})
    build_video_map()
    build_user_video_map()

    results = []
    for vid, v in VIDEO_MAP.items():
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
    threading.Thread(target=process_queue, daemon=True).start()
    
    print("==================================================")
    print("🚀 LocalTube запускается...")
    print("🌐 Откройте в браузере: http://127.0.0.1:5000")
    print("==================================================")
    
    # Отключаем логи Werkzeug для чистоты консоли
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    app.run(host='0.0.0.0', port=5000, debug=False)