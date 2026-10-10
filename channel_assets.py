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
import paths
from utils import (safe_name, write_json_atomic, read_json, JsonWriteError,
                   cookiefile_for_ydl, apply_cookie_updates, is_tiktok_url)
from logger import logger
# Страна, дата регистрации и внешние ссылки берутся со страницы /about: у
# yt-dlp этих полей для канала нет.
import channel_about

try:
    import yt_dlp
    import requests
except ImportError:
    yt_dlp = None
    requests = None

COOKIES_PATH = paths.data_path("cookies.txt")

CHANNEL_ASSETS_DIR = paths.data_path("avas")
BANNERS_DIR = os.path.join(CHANNEL_ASSETS_DIR, "banners")
META_DIR = os.path.join(CHANNEL_ASSETS_DIR, "meta")


def _configured_video_dir():
    """Каталог библиотеки из config.json.

    Модуль читает конфиг сам: он работает и как часть сервера, и как отдельный
    скрипт (download_avatars.py), где глобальных путей app.py ещё нет.
    """
    cfg = read_json(paths.data_path("config.json"), default=None)
    if isinstance(cfg, dict) and cfg.get("video_dir"):
        return cfg["video_dir"]
    return "videos"


def set_asset_dirs(avatars=None, banners=None, meta=None):
    """Задаёт каталоги ассетов канала из настроек приложения.

    Пути были зашиты здесь константами, поэтому раздел «Хранение» не мог ими
    управлять: аватарки переезжали вместе с настройкой, а шапки и метаданные
    оставались в старом avas/ и терялись из вида.
    """
    global CHANNEL_ASSETS_DIR, BANNERS_DIR, META_DIR
    if avatars:
        CHANNEL_ASSETS_DIR = avatars
    if banners:
        BANNERS_DIR = banners
    if meta:
        META_DIR = meta
    _ensure_dirs()

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
    if url and ('youtube.com' in url or 'tiktok.com' in url):
        return url
    channel_id = video_info.get('channel_id') or video_info.get('uploader_id')
    if channel_id:
        return f"https://www.youtube.com/channel/{channel_id}"
    return None


def _ydl_opts(flat, channel_url=None):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': flat,
        'socket_timeout': 20,
        'retries': 2,
    }
    # YouTubeTab — аргумент YouTube-экстрактора, TikTok его не понимает.
    if not is_tiktok_url(channel_url):
        opts['extractor_args'] = {'youtubetab': {'skip': ['authcheck']}}
    # Поток, а не путь: иначе yt-dlp перезапишет cookies.txt при close().
    stream = cookiefile_for_ydl(COOKIES_PATH)
    if stream is not None:
        opts['cookiefile'] = stream
    return opts


def _thumbs(thumbnails):
    """Только пригодные записи списка thumbnails."""
    if not isinstance(thumbnails, list):
        return []
    return [t for t in thumbnails if isinstance(t, dict) and t.get('url')]


def _is_banner(thumb):
    """Отличает шапку канала от аватарки.

    yt-dlp не помечает картинки типом: и аватарка, и баннер лежат в общем
    списке `thumbnails`. Опознаём по трём признакам, которые расставляет
    YouTube-экстрактор (`extractor/youtube/_tab.py`):

    * `id` = `banner_uncropped` у оригинала шапки;
    * `preference` = -10 у обрезанных вариантов шапки (у аватарки 1 или None);
    * широкое соотношение сторон — баннер всегда сильно шире, чем выше, тогда
      как аватарка квадратная.
    """
    thumb_id = str(thumb.get('id') or '')
    if 'banner' in thumb_id:
        return True
    if 'avatar' in thumb_id:
        return False
    preference = thumb.get('preference')
    if preference is not None and preference < 0:
        return True
    width, height = thumb.get('width') or 0, thumb.get('height') or 0
    return bool(width and height and width >= height * 2)


def _largest(thumbs):
    """URL картинки с наибольшей площадью; при равных — первая по порядку."""
    best, best_size = None, -1
    for t in thumbs:
        size = (t.get('width') or 0) * (t.get('height') or 0)
        if size > best_size:
            best, best_size = t['url'], size
    return best


def pick_avatar(thumbnails):
    """Выбирает URL аватарки канала из списка thumbnails.

    Раньше брали просто самую большую картинку, но баннер (2560x424) крупнее
    любой аватарки, и на страницу канала попадала шапка вместо круглой
    аватарки. Предпочитаем `avatar_uncropped`: это оригинал без обрезки,
    нужный для крупного круга на странице.
    """
    thumbs = [t for t in _thumbs(thumbnails) if not _is_banner(t)]
    if not thumbs:
        return None
    for t in thumbs:
        if 'avatar_uncropped' in str(t.get('id') or ''):
            return t['url']
    return _largest(thumbs)


def pick_banner(thumbnails):
    """Выбирает URL шапки канала из списка thumbnails.

    Полей `banner` и `banners` у yt-dlp нет: именно чтение их и приводило к
    тому, что шапки не скачивались никогда.

    Берём самый широкий *обрезанный* вариант, а не `banner_uncropped`:
    необрезанный исходник имеет пропорции 16:9 (например 4096x2304), и в полосе
    высотой 220px от него видна только центральная треть — лица и надписи с
    шапки уезжают за край. Обрезанные варианты YouTube отдаёт уже в пропорциях
    шапки (2560x424).
    """
    banners = [t for t in _thumbs(thumbnails) if _is_banner(t)]
    if not banners:
        return None
    cropped = [t for t in banners
               if 'uncropped' not in str(t.get('id') or '')
               and (t.get('width') or 0) and (t.get('height') or 0)]
    if cropped:
        # Самый широкий: шапка растягивается на всю ширину страницы.
        return max(cropped, key=lambda t: t['width'])['url']
    # Обрезанных вариантов нет — исходник лучше пустой шапки.
    for t in banners:
        if 'banner_uncropped' in str(t.get('id') or ''):
            return t['url']
    return _largest(banners)


def _count_videos(info):
    """Число видео на канале по ответу yt-dlp.

    `playlist_count` значит разное. Если yt-dlp вернул список вкладок канала
    («Видео», «Shorts»), то `playlist_count` — это число вкладок: у канала с
    миллионами подписчиков на странице появлялось «Видео на канале: 2».
    В этом случае складываем счётчики вкладок.
    """
    entries = info.get('entries')
    if isinstance(entries, list) and entries:
        tab_counts = [e.get('playlist_count') for e in entries
                      if isinstance(e, dict) and e.get('_type') == 'playlist'
                      and isinstance(e.get('playlist_count'), int)]
        if len(tab_counts) == len([e for e in entries if isinstance(e, dict)]):
            return sum(tab_counts)
    return info.get('playlist_count')


def _extract_channel(channel_url):
    """Один запрос метаданных канала к yt-dlp.

    Выделено отдельно, чтобы разбор ответа можно было проверять без сети.
    """
    opts = _ydl_opts(True, channel_url)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    apply_cookie_updates(opts)
    return info


def fetch_channel_info(channel_url, raise_on_error=False):
    """Получает данные канала: аватар, шапку, описание, число подписчиков.

    Один запрос вместо двух: за баннером ходили повторно с
    `extract_flat=False`, из-за чего YouTube отдавал полный список видео
    канала — секунды ожидания и лишний трафик ради одной картинки. Аватар и
    шапка приходят в том же ответе, в списке `thumbnails`.
    """
    if yt_dlp is None:
        if raise_on_error:
            raise RuntimeError('yt-dlp недоступен')
        return None

    try:
        info = _extract_channel(channel_url)
        if not info:
            raise RuntimeError('YouTube не вернул данные канала')
    except Exception as e:
        logger.warning(f"channel_assets: ошибка получения данных канала: {e}")
        if raise_on_error:
            raise RuntimeError(str(e)) from e
        return None

    thumbnails = info.get('thumbnails')
    avatar = info.get('avatar')
    tags = info.get('tags')
    result = {
        'avatar': pick_avatar(thumbnails) or (avatar if isinstance(avatar, str) else None),
        'banner': pick_banner(thumbnails),
        'description': info.get('description') or '',
        'subscribers': info.get('channel_follower_count') or info.get('subscriber_count'),
        'channel_id': info.get('channel_id') or info.get('id') or info.get('uploader_id'),
        # Ни одного из этих полей у yt-dlp нет для канала, но они появляются в
        # метаданных видео, откуда данные тоже могут прийти.
        'country': info.get('channel_country') or info.get('country') or '',
        'joined_date': info.get('channel_joined') or info.get('channel_created') or '',
        # Дополнительные данные для вкладки «О канале»: раньше там показывалось
        # только число локальных файлов.
        'handle': info.get('uploader_id') or '',
        'channel_url': info.get('channel_url') or info.get('uploader_url') or channel_url,
        'video_count': _count_videos(info),
        'view_count': info.get('view_count'),
        'verified': bool(info.get('channel_is_verified')),
        'tags': [str(t) for t in tags] if isinstance(tags, list) else [],
        'links': [],
    }

    # Страница /about дополняет то, чего у yt-dlp нет: страна, дата регистрации,
    # просмотры канала и внешние ссылки. Данные yt-dlp приоритетнее — разбор
    # HTML ломается при изменении вёрстки YouTube и не должен затирать то, что
    # пришло из поддерживаемого API. Ошибка здесь не фатальна: капча или
    # страница согласия не должны стоить нам аватара с шапкой.
    try:
        about = channel_about.fetch_about(result['channel_url'] or channel_url) or {}
    except Exception as e:
        logger.warning(f"channel_assets: страница «О канале» недоступна: {e}")
        about = {}
    for key in ('country', 'joined_date', 'description'):
        if not result.get(key) and about.get(key):
            result[key] = about[key]
    for key in ('subscribers', 'view_count', 'video_count'):
        if not result.get(key) and about.get(key):
            result[key] = about[key]
    if about.get('links'):
        result['links'] = about['links']
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


IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp')

# Версия схемы метаданных канала. Каналы, синхронизированные версией, которая не
# умела извлекать шапку, лежат на диске со статусом «success» и без баннера.
# Проверка «success — больше не трогаем» защищает от бесконечных повторов у
# каналов без шапки, но она же навсегда оставила бы старые записи неполными.
# Увеличение версии заставляет пересинхронизировать их один раз.
# 3 — добавлены страна, дата регистрации, просмотры и ссылки со страницы /about.
META_VERSION = 3


def _drop_stale_images(directory, safe, keep):
    """Удаляет прежние файлы картинки с другими расширениями.

    Имя файла зависит от content-type, поэтому обновление шапки с .jpg на .webp
    оставляло рядом два файла, а `get_banner_url` перебирает каталог и могла
    вернуть устаревший.
    """
    for ext in IMAGE_EXTS:
        path = os.path.join(directory, safe + ext)
        if os.path.basename(path) == keep:
            continue
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                logger.warning(f"channel_assets: не удалось удалить {path}: {e}")


def save_channel_assets(author, channel_info):
    """Сохраняет аватар, шапку и текстовые данные канала в локальные файлы."""
    if not channel_info:
        return
    _ensure_dirs()
    safe = safe_name(author)
    if channel_info.get('avatar'):
        saved = _download_image(channel_info['avatar'], os.path.join(CHANNEL_ASSETS_DIR, safe))
        if saved:
            _drop_stale_images(CHANNEL_ASSETS_DIR, safe, saved)
    if channel_info.get('banner'):
        saved = _download_image(channel_info['banner'], os.path.join(BANNERS_DIR, safe))
        if saved:
            _drop_stale_images(BANNERS_DIR, safe, saved)
    meta = {
        'description': channel_info.get('description', ''),
        'subscribers': channel_info.get('subscribers'),
        'channel_id': channel_info.get('channel_id'),
        'country': channel_info.get('country', ''),
        'joined_date': channel_info.get('joined_date', ''),
        'handle': channel_info.get('handle', ''),
        'channel_url': channel_info.get('channel_url', ''),
        'video_count': channel_info.get('video_count'),
        'view_count': channel_info.get('view_count'),
        'verified': bool(channel_info.get('verified')),
        'tags': channel_info.get('tags') or [],
        'links': channel_info.get('links') or [],
        'meta_version': META_VERSION,
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


def clear_channel_meta(author):
    """Удаляет сохранённый meta-файл канала, чтобы не было пересечения
    с данными при импорте канала с тем же именем."""
    # Путь считаем напрямую без _meta_path: очистка не должна создавать
    # директории (боковой эффект _ensure_dirs в _meta_path), только удалять
    # файлы по уже существующему пути.
    path = os.path.join(META_DIR, safe_name(author) + '.json')
    if os.path.exists(path):
        os.remove(path)
    # Очищаем и .bak
    bak = path + '.bak'
    if os.path.exists(bak):
        os.remove(bak)


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


def sync_channel(author, channel_url=None, already_claimed=False):
    """Синхронизирует канал и сохраняет диагностический результат.

    already_claimed=True означает, что вызывающий уже добавил author в _fetching
    под _fetch_lock. Это нужно, чтобы проверка «не синхронизируется ли уже» и
    захват слота были атомарными: при запуске в отдельном потоке слот иначе
    занимается только после старта потока, и два запроса успевают пройти
    проверку одновременно. Освобождение слота остаётся здесь в любом случае.
    """
    if not channel_url:
        channel_url = _find_channel_url_from_videos(author)
    if not channel_url:
        if already_claimed:
            with _fetch_lock:
                _fetching.discard(author)
        raise RuntimeError('URL канала не найден в локальных метаданных видео')
    if not already_claimed:
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
    # Каталог библиотеки настраиваемый, поэтому берётся из конфига, а не из
    # жёсткого 'videos' рядом с кодом: при своём пути канал не находился.
    video_dir = paths.user_path(_configured_video_dir())
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
        # У части каналов баннера нет вообще, и запрос за ним никогда не
        # добавит файл. Без этой проверки каждое открытие страницы запускало
        # новую синхронизацию: статус висел в checking, а кнопка «Скачать
        # остальные видео» отвечала, что канал ещё не синхронизирован.
        # Записи старой схемы пропускаем: они помечены «success», но собраны
        # кодом, который не умел находить шапку.
        if meta.get('sync_status') == 'success' \
                and meta.get('meta_version', 0) >= META_VERSION:
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
