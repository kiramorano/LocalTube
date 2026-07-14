import os
import json
import shutil
import hashlib
import time
import subprocess

USER_VIDEOS_ROOT = "uservideos"

def get_user_videos_dir():
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), USER_VIDEOS_ROOT)
    os.makedirs(base_dir, exist_ok=True)
    return base_dir

def get_user_folder(username):
    safe_username = "".join(c for c in username if c.isalnum() or c in (' ', '_', '-')).strip() or "guest"
    folder = os.path.join(get_user_videos_dir(), safe_username)
    os.makedirs(folder, exist_ok=True)
    return folder

def generate_video_id(username):
    raw = f"{username}_{time.time()}_{os.urandom(4).hex()}"
    return hashlib.md5(raw.encode()).hexdigest()[:11]

def get_video_info(video_dir):
    info_path = os.path.join(video_dir, "info.json")
    if not os.path.exists(info_path):
        return None
    try:
        with open(info_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None

def get_all_user_videos():
    base_dir = get_user_videos_dir()
    all_videos = []
    for user_folder in os.listdir(base_dir):
        user_path = os.path.join(base_dir, user_folder)
        if not os.path.isdir(user_path):
            continue
        for video_dir_name in os.listdir(user_path):
            video_dir = os.path.join(user_path, video_dir_name)
            if not os.path.isdir(video_dir):
                continue
            info = get_video_info(video_dir)
            if info is None:
                continue
            video_file = None
            for ext in ['.mp4', '.mkv', '.webm', '.avi', '.mov']:
                candidate = os.path.join(video_dir, f"video{ext}")
                if os.path.exists(candidate):
                    video_file = candidate
                    break
            if not video_file:
                continue
            info['video_path'] = video_file
            info['thumb_path'] = os.path.join(video_dir, "thumbnail.jpg") if os.path.exists(os.path.join(video_dir, "thumbnail.jpg")) else None
            info['folder'] = video_dir_name
            info['user_folder'] = user_folder
            all_videos.append(info)
    return all_videos

def get_video_by_id(video_id):
    all_vids = get_all_user_videos()
    for v in all_vids:
        if v.get('id') == video_id:
            return v
    return None

def ensure_unique_title(user_folder, desired_title):
    existing = set()
    for d in os.listdir(user_folder):
        info = get_video_info(os.path.join(user_folder, d))
        if info and 'title' in info:
            existing.add(info['title'])
    if desired_title not in existing:
        return desired_title
    c = 1
    while f"{desired_title} ({c})" in existing:
        c += 1
    return f"{desired_title} ({c})"

def extract_thumbnail(video_path, output_path):
    if not os.path.exists(video_path):
        return False
    cmd = ['ffmpeg', '-i', video_path, '-ss', '00:00:01', '-vframes', '1', '-q:v', '2', output_path, '-y']
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return os.path.exists(output_path)
    except:
        return False

def add_user_video(source_path, title, description, username, custom_thumbnail_path=None):
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Исходный файл не найден: {source_path}")

    user_folder = get_user_folder(username)
    video_id = generate_video_id(username)
    video_dir = os.path.join(user_folder, video_id)
    os.makedirs(video_dir, exist_ok=True)

    _, ext = os.path.splitext(source_path)
    if not ext:
        ext = '.mp4'
    target_video = os.path.join(video_dir, f"video{ext}")
    shutil.move(source_path, target_video)

    thumb_path = os.path.join(video_dir, "thumbnail.jpg")
    if custom_thumbnail_path and os.path.isfile(custom_thumbnail_path):
        shutil.copy2(custom_thumbnail_path, thumb_path)
    else:
        extract_thumbnail(target_video, thumb_path)

    if not title:
        title = "Без названия"
    title = ensure_unique_title(user_folder, title)

    info = {
        "id": video_id,
        "title": title,
        "description": description.strip() if description else "Видео не имеет описания",
        "author": username,
        "source": "user",
        "added_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "folder": video_id
    }
    with open(os.path.join(video_dir, "info.json"), 'w', encoding='utf-8') as f:
        json.dump(info, f, indent=2, ensure_ascii=False)

    info['video_path'] = target_video
    info['thumb_path'] = thumb_path if os.path.exists(thumb_path) else None
    return info

def edit_user_video(video_id, new_title, new_description, username, new_thumbnail_path=None):
    video_info = get_video_by_id(video_id)
    if not video_info or video_info.get('author') != username:
        return None
    video_dir = os.path.join(get_user_folder(username), video_info['folder'])
    info_path = os.path.join(video_dir, "info.json")
    with open(info_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if new_title:
        data['title'] = ensure_unique_title(get_user_folder(username), new_title)
    if new_description is not None:
        data['description'] = new_description.strip() if new_description else "Видео не имеет описания"

    if new_thumbnail_path and os.path.isfile(new_thumbnail_path):
        shutil.copy2(new_thumbnail_path, os.path.join(video_dir, "thumbnail.jpg"))

    with open(info_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    video_info.update(data)
    video_info['thumb_path'] = os.path.join(video_dir, "thumbnail.jpg") if os.path.exists(os.path.join(video_dir, "thumbnail.jpg")) else None
    return video_info

def delete_user_video(video_id, username):
    video_info = get_video_by_id(video_id)
    if not video_info or video_info.get('author') != username:
        return False
    video_dir = os.path.join(get_user_folder(username), video_info['folder'])
    if os.path.exists(video_dir):
        shutil.rmtree(video_dir)
        return True
    return False