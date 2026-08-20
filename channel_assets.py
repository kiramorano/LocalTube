#!/usr/bin/env python3
"""
channel_assets.py – автоматическое скачивание аватарки, шапки (баннера)
и описания канала с YouTube.
Вызывается автоматически после скачивания видео и при открытии страницы канала,
если данные ещё не скачаны.
"""

import os
import sys
import json
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import safe_name, write_json_atomic, read_json, JsonWriteError
from logger import logger

try:
    import yt_dlp
    import requests
except ImportError:
    yt_dlp = None
    requests = None

COOKIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")

CHANNEL_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "avas")
BANNERS_DIR = os.path.join(CHANNEL_ASSETS_DIR, "banners")
META_DIR = os.path.join(CHANNEL_ASSETS_DIR, "meta")

_fetch_lock = threading.Lock()
# Отдельный лок на запись метаданных: read-modify-write из разных потоков
# (фоновая догрузка ассетов и ручная синхронизация) иначе теряет поля.
_meta_write_lock = threading.RLock()
_fetching = set()


def _ensure_dirs():
    os.makedirs(BANNERS_DIR, exist_ok=True)
    os.makedirs(META_DIR, exist_ok=True)


def get_channel_url(video_info):
    """Извлекает URL канала из метаданных видео (channel_url/uploader_url/channel_id)."""
    if not isinstance(video_info, dict):
        return None
    url = video_info.get('channel_url') or video_info.get('uploader_url')
    if url and 'youtube.com' in url:
        return url
    channel_id = video_info.get('channel_id') or video_info.get('uploader_id')
    if channel_id:
        return f"https://www.youtube.com/channel/{channel_id}"
    return None


def _ydl_opts(flat):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': flat,
        'socket_timeout': 20,
        'retries': 2,
        # Без этого канал не извлекается, если cookies принадлежат другому аккаунту:
        # "Playlists that require authentication may not extract correctly..."
        'extractor_args': {'youtubetab': {'skip': ['authcheck']}},
    }
    if os.path.exists(COOKIES_PATH):
        opts['cookiefile'] = COOKIES_PATH
    return opts


def _pick_largest(thumbnails):
    """Возвращает URL самой большой картинки из списка thumbnails."""
    if not isinstance(thumbnails, list) or not thumbnails:
        return None
    best, best_size = None, 0
    for t in thumbnails:
        if not isinstance(t, dict) or not t.get('url'):
            continue
        size = (t.get('width') or 0) * (t.get('height') or 0)
        if size > best_size:
            best, best_size = t['url'], size
    if best:
        return best
    first = thumbnails[0]
    return first.get('url') if isinstance(first, dict) else None


def fetch_channel_info(channel_url, raise_on_error=False):
    """Получает данные канала: аватар, баннер, описание, число подписчиков."""
    if yt_dlp is None:
        if raise_on_error:
            raise RuntimeError('yt-dlp недоступен')
        return None

    result = {}
    # Быстрый запрос: аватар, описание, подписчики
    try:
        with yt_dlp.YoutubeDL(_ydl_opts(True)) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            if not info:
                raise RuntimeError('YouTube не вернул данные канала')
            avatar = info.get('avatar')
            result['avatar'] = _pick_largest(info.get('thumbnails')) or (avatar if isinstance(avatar, str) else None)
            result['description'] = info.get('description') or ''
            result['subscribers'] = info.get('channel_follower_count') or info.get('subscriber_count')
            result['channel_id'] = info.get('channel_id') or info.get('id') or info.get('uploader_id')
            result['country'] = info.get('channel_country') or info.get('country') or ''
            result['joined_date'] = info.get('channel_joined') or info.get('channel_created') or info.get('upload_date') or ''
    except Exception as e:
        logger.warning(f"channel_assets: ошибка получения данных канала: {e}")
        if raise_on_error:
            raise RuntimeError(str(e)) from e
        return None

    # Баннер необязателен: метаданные считаются успешными даже если запрос баннера не удался.
    try:
        opts = _ydl_opts(False)
        opts['playlist_items'] = '1'
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            if info:
                banner = info.get('banner') or info.get('banner_image_url')
                banners = info.get('banners')
                if isinstance(banners, list) and banners:
                    banner = _pick_largest(banners) or banner
                if banner:
                    result['banner'] = banner
    except Exception as e:
        logger.warning(f"channel_assets: ошибка получения баннера: {e}")

    return result


def _download_image(url, base_path):
    """Скачивает картинку по URL в файл base_path + правильное расширение."""
    if not url or requests is None:
        return None
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get('content-type', '')
        ext = '.jpg'
        if 'png' in content_type:
            ext = '.png'
        elif 'webp' in content_type:
            ext = '.webp'
        if '.png' in url:
            ext = '.png'
        elif '.webp' in url:
            ext = '.webp'
        final_path = base_path + ext
        with open(final_path, 'wb') as f:
            f.write(resp.content)
        return os.path.basename(final_path)
    except Exception as e:
        logger.warning(f"channel_assets: ошибка скачивания {url}: {e}")
        return None


def save_channel_assets(author, channel_info):
    """Сохраняет аватар, баннер и описание канала в локальные файлы."""
    if not channel_info:
        return
    _ensure_dirs()
    safe = safe_name(author)
    if channel_info.get('avatar'):
        _download_image(channel_info['avatar'], os.path.join(CHANNEL_ASSETS_DIR, safe))
    if channel_info.get('banner'):
        _download_image(channel_info['banner'], os.path.join(BANNERS_DIR, safe))
    meta = {
        'description': channel_info.get('description', ''),
        'subscribers': channel_info.get('subscribers'),
        'channel_id': channel_info.get('channel_id'),
        'country': channel_info.get('country', ''),
        'joined_date': channel_info.get('joined_date', ''),
        'updated_at': time.time(),
    }
    # Лок вокруг read-modify-write: синхронизация канала может идти из
    # нескольких потоков, а файл один.
    with _meta_write_lock:
        try:
            # Сохраняем поля синхронизации: этот вызов перезаписывает файл
            # целиком, а диагностика живёт в том же JSON.
            existing = load_channel_meta(author)
            for key in list(existing):
                if key.startswith('sync_') or key.startswith('last_sync_'):
                    meta[key] = existing[key]
            write_json_atomic(os.path.join(META_DIR, safe + '.json'), meta)
        except JsonWriteError as e:
            logger.warning(f"channel_assets: ошибка сохранения описания: {e}")


def load_channel_meta(author):
    """Читает сохранённые данные канала (описание, подписчики).

    При повреждении основного файла берёт данные из .bak, иначе одна неудачная
    запись стоила бы описания и числа подписчиков.
    """
    data = read_json(_meta_path(author), default={})
    return data if isinstance(data, dict) else {}


def _meta_path(author):
    _ensure_dirs()
    return os.path.join(META_DIR, safe_name(author) + '.json')


def update_sync_status(author, status, error='', started_at=None, finished_at=None, success=None):
    """Обновляет только диагностические поля синхронизации канала."""
    path = _meta_path(author)
    # Лок обязателен: read-modify-write из нескольких потоков иначе теряет
    # изменения (последний записавший затирает чужие поля).
    with _meta_write_lock:
        meta = load_channel_meta(author)
        meta['sync_status'] = str(status or '')
        # Ошибку приводим к строке: исключение или любой объект иначе сорвёт
        # json.dump и статус вообще не сохранится.
        meta['sync_error'] = '' if error in (None, '') else str(error)
        if started_at is not None:
            meta['last_sync_started_at'] = started_at
        if finished_at is not None:
            meta['last_sync_finished_at'] = finished_at
        if success is not None:
            meta['last_sync_success'] = bool(success)
        try:
            write_json_atomic(path, meta)
        except JsonWriteError as e:
            logger.warning(f"channel_assets: ошибка записи статуса: {e}")
        return meta


def get_sync_status(author):
    meta = load_channel_meta(author)
    status = meta.get('sync_status', 'never' if not meta else 'unknown')
    error = meta.get('sync_error', '')
    with _fetch_lock:
        in_progress = author in _fetching
    # 'checking' без живого потока означает, что процесс перезапустили посреди проверки.
    # Иначе кнопка обновления осталась бы заблокированной навсегда.
    if status == 'checking' and not in_progress:
        status = 'interrupted'
        error = error or 'Проверка была прервана (сервер перезапущен). Запустите её заново.'
    return {
        'status': status,
        'error': error,
        'started_at': meta.get('last_sync_started_at'),
        'finished_at': meta.get('last_sync_finished_at'),
        'success': meta.get('last_sync_success'),
        'updated_at': meta.get('updated_at'),
        'in_progress': in_progress,
    }


def _save_sync_result(author, channel_info, started_at):
    save_channel_assets(author, channel_info)
    update_sync_status(author, 'success', started_at=started_at, finished_at=time.time(), success=True)


def sync_channel(author, channel_url=None):
    """Синхронизирует канал и сохраняет диагностический результат."""
    if not channel_url:
        channel_url = _find_channel_url_from_videos(author)
    if not channel_url:
        raise RuntimeError('URL канала не найден в локальных метаданных видео')
    with _fetch_lock:
        if author in _fetching:
            return False
        _fetching.add(author)
    started_at = time.time()
    update_sync_status(author, 'checking', error='', started_at=started_at, success=None)
    try:
        channel_info = fetch_channel_info(channel_url, raise_on_error=True)
        _save_sync_result(author, channel_info, started_at)
        logger.info(f"channel_assets: данные канала «{author}» синхронизированы")
        return True
    except Exception as e:
        error = str(e)
        update_sync_status(author, 'error', error=error, started_at=started_at, finished_at=time.time(), success=False)
        logger.warning(f"channel_assets: ошибка синхронизации «{author}»: {error}")
        return False
    finally:
        with _fetch_lock:
            _fetching.discard(author)


def get_banner_url(author):
    """Возвращает локальный URL баннера канала или None."""
    safe = safe_name(author)
    if not os.path.isdir(BANNERS_DIR):
        return None
    try:
        for f in os.listdir(BANNERS_DIR):
            name, ext = os.path.splitext(f)
            if name == safe and ext.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                return f"/channel_banner/{f}"
    except Exception:
        pass
    return None


def format_subscribers(n):
    """Форматирует число подписчиков: 1.2 млн / 340 тыс."""
    if not n:
        return None
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if n >= 1000000:
        return f"{n / 1000000:.1f} млн".replace('.', ',')
    if n >= 1000:
        return f"{n / 1000:.1f} тыс".replace('.', ',')
    return str(n)


def _find_channel_url_from_videos(author):
    """Ищет channel_url в .info.json любого видео автора (папка videos/<author>/...)."""
    video_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'videos')
    author_path = os.path.join(video_dir, safe_name(author))
    if not os.path.isdir(author_path):
        return None
    for sub in os.listdir(author_path):
        sub_path = os.path.join(author_path, sub)
        if not os.path.isdir(sub_path):
            continue
        try:
            for f in os.listdir(sub_path):
                if f.endswith('.info.json') or f == 'info.json':
                    with open(os.path.join(sub_path, f), 'r', encoding='utf-8') as jf:
                        meta = json.load(jf)
                    url = get_channel_url(meta)
                    if url:
                        return url
                    break
        except Exception:
            continue
    return None


def fetch_and_save(author, video_info):
    """Точка вызова после скачивания видео: получает и сохраняет данные канала."""
    try:
        channel_url = get_channel_url(video_info)
        if not channel_url:
            return
        sync_channel(author, channel_url)
    except Exception as e:
        logger.warning(f"channel_assets: fetch_and_save: {e}")


AUTO_RETRY_COOLDOWN = 600  # 10 минут между автоматическими повторами после ошибки


def try_fetch_if_missing(author):
    """Если баннера или описания канала ещё нет — фоном подтягивает их с YouTube."""
    try:
        meta = load_channel_meta(author)
        if meta and get_banner_url(author):
            return
        # После неудачи не дёргаем YouTube на каждом открытии страницы: сетевые таймауты
        # надолго блокируют кнопку обновления. Ручная синхронизация игнорирует задержку.
        if meta.get('sync_status') == 'error':
            last_attempt = meta.get('last_sync_finished_at') or 0
            if time.time() - last_attempt < AUTO_RETRY_COOLDOWN:
                return
        sync_channel(author)
    except Exception as e:
        logger.warning(f"channel_assets: try_fetch_if_missing: {e}")
