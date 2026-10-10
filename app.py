import os
# Пути к данным и ресурсам: в собранной версии они разные, и знать об этом нужно
# раньше всех остальных импортов — logger сразу открывает файл лога.
import paths
# Прокси нельзя просто стирать: если доступ к YouTube идёт через него (xray,
# VPN-клиенты), yt-dlp пойдёт напрямую и получит ConnectionResetError(10054)
# на «Unable to download API page». Достаточно исключить из прокси localhost,
# иначе запросы к bgutil-серверу на 127.0.0.1 уходили бы наружу.
from proxy_setup import apply_proxy_environment

apply_proxy_environment()

import json
import threading
import hashlib
import random
import socket
import uuid
import sys
import time
import requests
import subprocess
import re
from urllib.parse import quote, urlparse
from flask import Flask, render_template, send_from_directory, request, jsonify, send_file, abort
import jinja2
from datetime import datetime

from downloader import get_format_choices, get_playlist_info, is_playlist_url
import download_lib
from download_lib import download_media, download_single_sync, DownloadCancelledByUser
from utils import (safe_name, is_shorts_video, write_json_atomic, read_json,
                   JsonWriteError, cookiefile_for_ydl, apply_cookie_updates,
                   write_text_atomic,
                   sanitize_netscape_cookies as utils_sanitize_cookies)
from user_videos import add_user_video, edit_user_video, delete_user_video, get_all_user_videos, USER_VIDEOS_ROOT
from logger import logger
from po_manager import get_po_method, get_video_info, get_formats, get_playlist_info as get_playlist_info_new, shutdown_extractor, get_extractor, get_po_args, apply_po_args
import yt_dlp

# Импорт наших новых модулей (Blueprints)
import custom_quality
import audio_language
import channel_assets
# Нужен как модуль, а не только его функции: apply_storage_paths меняет
# user_videos.USER_VIDEOS_ROOT, когда пользователь задаёт другую папку.
import user_videos
import auth_options
import userdata
# Языки аудиодорожек и субтитров: настройки читает и загрузчик, поэтому они
# лежат в отдельном модуле, а не в app.py.
import download_prefs
# Перевод интерфейса: русский и английский.
import i18n
# Доступ из локальной сети: сервер слушает 0.0.0.0, поэтому его видит каждое
# устройство в сети, а проверок прав в проекте не было ни одной.
import access

# Пути к шаблонам и статике задаются явно: Flask ищет их рядом с модулем, а в
# собранной версии модуль лежит внутри архива, откуда каталогов не видно —
# интерфейс отдавался бы как TemplateNotFound на каждой странице.
app = Flask(__name__,
            static_folder=paths.resource_path('static'),
            template_folder=paths.resource_path('templates'))
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['TEMPLATES_AUTO_RELOAD'] = True


@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(413)
@app.errorhandler(500)
def handle_error_as_json(error):
    """Ошибки на /api/... отдаём в JSON.

    По умолчанию Flask возвращает HTML-страницу, и клиентский res.json() падал
    с SyntaxError вместо показа причины: в интерфейсе это выглядело как «ничего
    не произошло». На обычных страницах поведение оставляем прежним.
    """
    code = getattr(error, 'code', 500)
    if not request.path.startswith('/api/'):
        return error
    message = getattr(error, 'description', None) or 'Внутренняя ошибка сервера'
    if code == 413:
        # Размер известен из конфига, и без него сообщение бесполезно.
        limit_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
        message = f'Файл слишком большой. Максимум — {limit_mb} МБ.'
    if code == 500:
        logger.error(f"Необработанная ошибка на {request.path}: {error}")
    return jsonify({'error': message}), code

# Каталог данных: настройки, cookies, очередь, библиотека. В собранной версии он
# отделён от каталога программы, поэтому SCRIPT_DIR больше не «корень проекта», а
# именно место для записи. Шаблоны и статика берутся из paths.resource_dir().
SCRIPT_DIR = paths.ensure_data_dir()
CONFIG_FILE = paths.data_path("config.json")
COOKIES_PATH = paths.data_path("cookies.txt")

# ================= ДОСТУП ИЗ ЛОКАЛЬНОЙ СЕТИ =================
# Гостю разрешён только просмотр, и разрешения перечислены явно: всё, что не
# в списке, закрыто. Обратный порядок (перечислять запрещённое) означал бы, что
# каждый новый маршрут открыт всей сети, пока про него не вспомнят.
GUEST_ENDPOINTS = frozenset({
    # Страницы просмотра.
    'index',
    'watch',
    'channel',
    'static',
    # Файлы: видео, превью, аватарки, баннеры.
    'media',
    'usermedia',
    'serve_avatars',
    'serve_channel_banner',
    'api_thumbnail',
    # Данные для показа библиотеки.
    'api_catalog',
    'api_search',
    'api_video',
    'api_theme_backgrounds',
    # Субтитры и список готовых качеств: только чтение уже скачанных файлов.
    'audio_language.serve_subtitle',
    'audio_language.api_get_subtitles',
    'quality.api_get_qualities',
    # Язык интерфейса: свойство устройства, а не библиотеки владельца. Гость
    # тоже должен иметь возможность читать страницы на своём языке.
    'api_i18n_dictionary',
    'api_language_save',
    # Раздел «Сеть»: ping нужен автопоиску, unlock — вход по PIN.
    'api_network_ping',
    'api_network_unlock',
    'api_network_lock',
})


def request_is_owner():
    """Владелец ли тот, кто прислал текущий запрос.

    Владелец — это либо сама машина (127.0.0.1), либо устройство, впущенное по
    PIN: у него в cookie лежит ключ. Cookie, а не заголовок, потому что права
    нужны и обычным страницам, а не только запросам из JS.
    """
    if access.is_owner_address(request.remote_addr):
        return True
    return access.is_valid_token(request.cookies.get(access.TOKEN_COOKIE))


@app.before_request
def check_access():
    """Пускает гостей только на маршруты просмотра."""
    if request_is_owner():
        return None

    # Тумблер выключен: сервер отвечает только владельцу.
    if not access.is_network_enabled():
        return _access_denied('Доступ из локальной сети выключен владельцем.')

    if request.endpoint in GUEST_ENDPOINTS:
        return None

    return _access_denied('Это действие доступно только владельцу. '
                          'Введите PIN на его компьютере в настройках.')


def _access_denied(message):
    if request.path.startswith('/api/'):
        return jsonify({'error': message, 'guest': True}), 403
    return message, 403

DEFAULT_DIRS = {
    "video_dir": "videos", "avatars_dir": "avas", "thumbnails_dir": "thumbnails",
    "playlists_dir": "playlists", "subtitles_dir": "subtitles",
    # Раньше эти три пути были зашиты в channel_assets.py и user_videos.py,
    # поэтому настроить их было нельзя вовсе.
    "banners_dir": os.path.join("avas", "banners"),
    "meta_dir": os.path.join("avas", "meta"),
    "uservideos_dir": "uservideos",
}

def load_config():
    default = dict(DEFAULT_DIRS)
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

def resolve_dir(value):
    """Абсолютный путь к папке хранения.

    Относительные значения считаются от каталога данных, абсолютные (D:/видео)
    возвращаются как есть.
    """
    return paths.user_path(value)

def apply_storage_paths(cfg=None):
    """Применяет пути из конфига к работающему приложению.

    app.py читал config.json один раз при импорте, поэтому смена папки в
    настройках не действовала до перезапуска, тогда как download_lib читает
    конфиг на каждую загрузку. Новые видео уходили в новую папку, а библиотека
    продолжала показывать старую, и это выглядело как пропажа загрузок.

    Пути раздаются и в модули, которые держат собственные копии: блюпринты
    получают их через init() при импорте, channel_assets и user_videos хранят
    в своих константах.
    """
    global config, BASE_VIDEO_DIR, AVATARS_DIR, THUMBNAILS_DIR, PLAYLISTS_DIR
    global SUBTITLES_DIR, USER_VIDEOS_ROOT

    config = cfg if isinstance(cfg, dict) else load_config()
    BASE_VIDEO_DIR = resolve_dir(config["video_dir"])
    AVATARS_DIR = resolve_dir(config["avatars_dir"])
    THUMBNAILS_DIR = resolve_dir(config["thumbnails_dir"])
    PLAYLISTS_DIR = resolve_dir(config["playlists_dir"])
    SUBTITLES_DIR = resolve_dir(config["subtitles_dir"])
    USER_VIDEOS_ROOT = resolve_dir(config["uservideos_dir"])

    channel_assets.set_asset_dirs(
        avatars=AVATARS_DIR,
        banners=resolve_dir(config["banners_dir"]),
        meta=resolve_dir(config["meta_dir"]),
    )
    user_videos.USER_VIDEOS_ROOT = USER_VIDEOS_ROOT

    for d in (BASE_VIDEO_DIR, AVATARS_DIR, THUMBNAILS_DIR, PLAYLISTS_DIR,
              SUBTITLES_DIR, USER_VIDEOS_ROOT):
        os.makedirs(d, exist_ok=True)

    # Кэш сканирования ключуется абсолютным путём папки видео и хранит отметку
    # свежести карты. После смены папки в настройках записи старой папки
    # оставались валидными по своему ключу, а _map_built_at был свежим, поэтому
    # ensure_video_map возвращал прежнюю библиотеку: пользователь менял папку и
    # видел старый список, пока не истечёт окно свежести.
    # invalidate_scan_cache определена ниже, но вызывается только в рантайме.
    invalidate_scan_cache()

config = load_config()
BASE_VIDEO_DIR = resolve_dir(config["video_dir"])
AVATARS_DIR = resolve_dir(config["avatars_dir"])
THUMBNAILS_DIR = resolve_dir(config["thumbnails_dir"])
PLAYLISTS_DIR = resolve_dir(config["playlists_dir"])
SUBTITLES_DIR = resolve_dir(config["subtitles_dir"])
USER_VIDEOS_ROOT = resolve_dir(config["uservideos_dir"])

for d in [BASE_VIDEO_DIR, AVATARS_DIR, THUMBNAILS_DIR, PLAYLISTS_DIR, SUBTITLES_DIR]:
    os.makedirs(d, exist_ok=True)

# Кэш обработанных картинок раньше писался в static/images/cache, то есть внутрь
# ресурсов. В собранной версии этот каталог только для чтения, а в onefile ещё и
# удаляется при выходе, поэтому кэш переехал в каталог данных.
CACHE_DIR = paths.data_path('cache', 'images')
os.makedirs(CACHE_DIR, exist_ok=True)

QUEUE_FILE = paths.data_path("queue.json")
if not os.path.exists(QUEUE_FILE):
    try:
        # backup=False: файла ещё нет, копировать нечего.
        write_json_atomic(QUEUE_FILE, {'paused': False, 'tasks': []}, backup=False)
    except JsonWriteError as e:
        logger.warning(f"Не удалось создать queue.json: {e}")

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

# Задача больше не будет выполняться сама: её можно повторить, удалить, очистить.
# «partial» — частичный успех: часть видео скачана, часть нет. Отдельный статус
# нужен, чтобы такая задача попадала в фильтр ошибок и в массовый повтор.
FINISHED_STATUSES = ('completed', 'error', 'cancelled', 'partial')
# Статусы, которые можно повторить.
RETRYABLE_STATUSES = ('error', 'cancelled', 'partial')


def _new_task_id_locked():
    """Уникальный id задачи. Вызывать, держа queue_lock.

    Раньше id считался как md5(time.time() + url)[:8]: разрешение таймера на
    Windows грубое, поэтому два быстрых добавления одной ссылки давали
    одинаковый id, а он используется как ключ во всех операциях очереди.

    Снимок существующих id и добавление задачи должны идти под одним локом:
    иначе два одновременных запроса получали один и тот же свободный id, и
    отмена одной задачи отменяла обе.
    """
    existing = {task.id for task in queue_tasks}
    while True:
        candidate = uuid.uuid4().hex[:8]
        if candidate not in existing and candidate not in queue_cancel_requests:
            return candidate

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
            # Скорость и ETA относились к прерванной загрузке: без сброса
            # интерфейс показывал их у задачи, которая ещё даже не началась.
            task.speed = ''
            task.eta = ''
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
    """Сохраняет очередь на диск. Возвращает текст ошибки или '' при успехе.

    Раньше сбой записи (нет места, нет прав, файл занят) только писался в лог,
    а эндпоинты всё равно отвечали {'status': 'ok'}: пользователь видел
    подтверждение, а после перезапуска изменения исчезали.
    """
    try:
        # Запись под тем же локом: раньше сериализация шла под локом, а сама
        # запись — вне, и два потока могли писать в файл одновременно.
        with queue_lock:
            data = {'paused': queue_paused, 'tasks': [task.to_dict() for task in queue_tasks]}
            write_json_atomic(QUEUE_FILE, data)
            global _last_progress_save
            _last_progress_save = time.monotonic()
        return ''
    except Exception as e:
        logger.warning(f"Не удалось сохранить очередь: {e}")
        return str(e) or e.__class__.__name__


# Прогресс приходит от yt-dlp примерно раз в секунду на каждую загрузку, а
# write_json_atomic пишет временный файл, копию .bak и делает fsync. Сохранять
# на каждый тик — это постоянная запись на диск ради данных, которые устаревают
# через секунду. Раз в PROGRESS_SAVE_INTERVAL достаточно: при перезапуске
# теряется только процент, а сама задача и её статус остаются.
PROGRESS_SAVE_INTERVAL = 5.0
_last_progress_save = 0.0


def save_queue_progress():
    """Сохраняет очередь, но не чаще раза в PROGRESS_SAVE_INTERVAL секунд."""
    if time.monotonic() - _last_progress_save < PROGRESS_SAVE_INTERVAL:
        return ''
    return save_queue()


def save_queue_or_error(payload=None, status=200):
    """Готовит ответ эндпоинта очереди с учётом результата записи на диск.

    При сбое отдаёт 500 и текст причины: молчаливое «ok» приводило к тому, что
    задача пропадала после перезапуска без каких-либо признаков проблемы.
    """
    error = save_queue()
    if error:
        return jsonify({'error': f'Очередь не сохранена на диск: {error}'}), 500
    body = {'status': 'ok'}
    if payload:
        body.update(payload)
    return jsonify(body), status


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


def source_from_metadata(meta):
    """Платформа ролика по данным yt-dlp, не по имени папки.

    yt-dlp возвращает extractor_key=TikTok и tiktok.com в webpage_url. Поле
    source нужно для интерфейса и субтитров; незнакомые экстракторы оставляем
    совместимыми с прежней библиотекой как YouTube.
    """
    meta = meta if isinstance(meta, dict) else {}
    extractor = str(meta.get('extractor_key') or meta.get('ie_key') or '').lower()
    webpage = str(meta.get('webpage_url') or meta.get('original_url') or '').lower()
    return 'tiktok' if extractor.startswith('tiktok') or 'tiktok.com' in webpage else 'youtube'


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


def current_lang():
    """Выбранный язык интерфейса.

    Берётся из cookie: страницы собирает сервер, и к моменту работы клиентского
    кода разметка уже отдана — выбор через localStorage давал бы вспышку
    русского текста при каждом заходе.
    """
    return i18n.normalize_lang(request.cookies.get(i18n.LANG_COOKIE))


@app.template_filter('t')
@jinja2.pass_context
def translate_filter(ctx, text):
    """Фильтр перевода для шаблонов: {{ 'Настройки'|t }}.

    Ключ — сама русская строка, поэтому пропуск в словаре оставляет строку
    русской, а не пустой.

    pass_context здесь не ради самого контекста, а чтобы Jinja не сворачивала
    вызов при компиляции: аргумент постоянный, и без этого результат первого
    рендера запекался в шаблон. Страница, впервые открытая на русском, потом не
    переводилась никогда — язык менялся только после перезапуска сервера.
    """
    return i18n.translate(text, current_lang())


def _t(text):
    """Перевод строки для ответов сервера: текст ошибки виден пользователю."""
    return i18n.translate(text, current_lang())


@app.after_request
def vary_by_language(response):
    """Помечает ответы зависящими от cookie: иначе браузер отдаёт старый язык.

    Страницы, открытые до переключения языка, браузер брал из кэша и показывал
    их на прежнем языке до принудительного обновления. Vary: Cookie говорит, что
    ответ зависит от cookie (в котором лежит язык), и кэш перестаёт их смешивать.
    """
    response.headers.add('Vary', 'Cookie')
    return response


@app.context_processor
def inject_lang():
    """Отдаёт язык каждому шаблону: он нужен атрибуту lang у <html>.

    Вместе с языком отдаём и словарь для клиентского кода. Отдельным запросом
    (/api/i18n/<lang>) он приходил позже первой отрисовки: шапка успевала
    нарисовать русское «Гость» на английской странице. Русскому языку словарь не
    нужен — это язык исходных строк, и в ответ он не попадает.
    """
    lang = current_lang()
    return {
        'ui_lang': lang,
        'ui_languages': i18n.languages_for_ui(),
        'ui_strings': i18n.load_dictionary(lang),
    }


@app.template_filter('human_date')
def human_date(value):
    """20260812 -> 12.08.2026; ISO-даты и мусор возвращаем как есть."""
    text = str(value or '').strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[6:8]}.{text[4:6]}.{text[0:4]}"
    if len(text) >= 10 and text[4] == '-' and text[7] == '-':
        return f"{text[8:10]}.{text[5:7]}.{text[0:4]}"
    return text


def safe_channel_links(links):
    """Оставляет только внешние ссылки канала с безопасной схемой.

    Метаданные лежат в JSON на диске, и `javascript:` в href выполнился бы на
    странице пользователя. Фильтруем здесь, а не в шаблоне: шаблон экранирует
    текст, но схему URL не проверяет.
    """
    result = []
    if not isinstance(links, list):
        return result
    for link in links:
        if not isinstance(link, dict):
            continue
        url = str(link.get('url') or '').strip()
        if not url.lower().startswith(('http://', 'https://')):
            continue
        result.append({'title': str(link.get('title') or url), 'url': url})
    return result


@app.template_filter('compact_count')
def compact_count(value):
    """9000000 -> 9 млн. Полное число просмотров канала нечитаемо."""
    try:
        number = int(float(value or 0))
    except (TypeError, ValueError):
        return ''
    if number <= 0:
        return ''
    for limit, suffix in ((1_000_000_000, 'млрд'), (1_000_000, 'млн'), (1_000, 'тыс')):
        if number >= limit:
            scaled = number / limit
            # Без дробной части у круглых значений: «9 млн» вместо «9,0 млн».
            text = f"{scaled:.0f}" if scaled >= 10 or scaled == int(scaled) else f"{scaled:.1f}"
            return f"{text.replace('.', ',')} {suffix}"
    return str(number)


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


# OSError вместо голого except: голый перехватывал KeyboardInterrupt, поэтому
# Ctrl+C во время сканирования библиотеки не останавливал сервер.
def find_main_video_file(folder):
    for ext in ['.mp4', '.mkv', '.webm', '.avi', '.mov']:
        if os.path.exists(os.path.join(folder, f"video{ext}")): return f"video{ext}"
    try:
        for f in os.listdir(folder):
            if any(f.lower().endswith(e) for e in ['.mp4', '.mkv', '.webm', '.avi']): return f
    except OSError:
        pass
    return None

def find_file(folder, exts):
    try:
        for f in os.listdir(folder):
            if any(f.lower().endswith(e) for e in exts): return f
    except OSError:
        pass
    return None


def read_video_info(folder_path):
    """Читает info.json видео. Пустой dict, если файла нет или он битый.

    Один helper на два маршрута (/watch и /api/video): раньше это был
    скопированный блок, и в обеих копиях был голый except и encoding='utf-8'
    вместо utf-8-sig — файл с BOM не читался, метаданные молча терялись.
    """
    info_file = find_file(folder_path, ['info.json', '.info.json'])
    if not info_file:
        return {}
    filepath = os.path.join(folder_path, info_file)
    try:
        if os.path.getsize(filepath) == 0:
            return {}
    except OSError:
        return {}
    for enc in ('utf-8-sig', 'utf-8', 'cp1251', 'latin-1'):
        try:
            with open(filepath, 'r', encoding=enc) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            continue
        except UnicodeDecodeError:
            continue
    # Если JSON не читается — пробуем извлечь метаданные через ffmpeg
    video_file = find_file(folder_path, ['.mp4', '.webm', '.mkv'])
    if video_file:
        try:
            cmd = [paths.ffmpeg_path(), '-i', os.path.join(folder_path, video_file)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 or 'Duration' in result.stderr:
                return {'title': os.path.splitext(video_file)[0], 'source': 'ffmpeg'}
        except Exception:
            pass
    logger.warning(f"Не удалось прочитать {info_file}: файл повреждён или пуст")
    return {}

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
    source = source_from_metadata(meta)
    record = {
        "author": author, "folder": vfolder,
        "is_short": is_shorts_video(meta) if meta else False,
        "filename": video_file, "title": (meta.get('title') if isinstance(meta, dict) else None) or f"Видео {vfolder}",
        "size_mb": round(size_bytes / (1024 * 1024), 1),
        "source": source, "youtube_id": youtube_id, "thumb_file": thumb_file,
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
            # utf-8-sig: файл, записанный с BOM, иначе не читается.
            with open(meta_file, 'r', encoding='utf-8-sig') as f: data = json.load(f)
            playlist_id = hashlib.md5(playlist_folder.encode()).hexdigest()[:11]
            thumb = data.get('thumbnail', '')
            if thumb and not thumb.startswith('/'): thumb = '/' + thumb
            new_playlist_map[playlist_id] = {'id': playlist_id, 'title': data.get('title', playlist_folder), 'uploader': data.get('uploader', 'Unknown'), 'thumbnail': thumb, 'video_count': data.get('video_count', 0), 'videos': data.get('videos', []), 'folder': playlist_folder}
        except (OSError, ValueError) as e:
            # Не голый except: он глотал KeyboardInterrupt и прятал причину, по
            # которой плейлист не появлялся в списке.
            logger.warning(f"Плейлист {playlist_folder} пропущен: {e}")
    global PLAYLIST_MAP
    PLAYLIST_MAP = new_playlist_map

# ===== ИНИЦИАЛИЗАЦИЯ И РЕГИСТРАЦИЯ БЛЮПРИНТОВ =====
custom_quality.init(BASE_VIDEO_DIR, logger, lambda: VIDEO_MAP, lambda: USER_VIDEO_MAP, build_video_map, build_user_video_map, USER_VIDEOS_ROOT)
audio_language.init(BASE_VIDEO_DIR, SUBTITLES_DIR, logger, lambda: VIDEO_MAP, lambda: USER_VIDEO_MAP, build_video_map)

app.register_blueprint(custom_quality.bp)
app.register_blueprint(audio_language.bp)
# ==================================================

@app.route('/usermedia/<path:filename>')
def usermedia(filename):
    # USER_VIDEOS_ROOT уже абсолютный (resolve_dir): повторный join с каталогом
    # данных ломал бы свой путь, заданный в настройках.
    return send_from_directory(USER_VIDEOS_ROOT, filename)

@app.route('/media/<path:filename>')
def media(filename):
    # Первый сегмент пути — имя автора. Гостю файлы скрытого канала не отдаём:
    # путь /media/<автор>/<папка>/<файл> угадывается по названию, и без этой
    # проверки скрытое видео забиралось бы мимо страниц и каталога.
    author = filename.replace('\\', '/').split('/')[0]
    if hidden_from_guest(author):
        abort(404)
    return send_from_directory(BASE_VIDEO_DIR, filename)

@app.route('/avatars/<filename>')
def serve_avatars(filename):
    if _hidden_asset_for_guest(filename):
        abort(404)
    return send_from_directory(AVATARS_DIR, filename)

@app.route('/channel_banner/<filename>')
def serve_channel_banner(filename):
    if _hidden_asset_for_guest(filename):
        abort(404)
    return send_from_directory(channel_assets.BANNERS_DIR, filename)


def _hidden_asset_for_guest(filename):
    """Аватарка или баннер скрытого канала.

    Файлы называются по safe_name(автор), поэтому сравниваем имя без
    расширения с safe_name каждого скрытого канала.
    """
    hidden = guest_hidden_authors()
    if not hidden:
        return False
    name = os.path.splitext(os.path.basename(filename))[0]
    return any(safe_name(author) == name for author in hidden)

# Разделы главной -> отмечаемый пункт нижней навигации. Разделы «all», «shorts»
# и прочие живут только в браузере (filterNav), поэтому таблица нужна, чтобы
# отметка стояла верно сразу в разметке при переходе по /?nav=...
NAV_SECTIONS = {
    'all': 'home',
    'shorts': 'shorts',
    'favorites': 'favorites',
    'history': 'history',
    'queue': 'queue',
}


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
        item = {"author": v["author"], "folder": v["folder"], "filename": v["filename"], "thumb": thumb, "title": v["title"], "is_short": v["is_short"], "size_mb": v["size_mb"], "duration": v.get("duration", 0), "upload_date": v.get("upload_date", ""), "id": vid, "author_avatar": get_avatar_url(v["author"]), "source": v.get("source", "youtube")}
        if v["is_short"]: shorts.append(item)
        else: all_videos.append(item)
        authors_set.add(v["author"])
        
    user_videos_list = [{"id": vid, "title": uv["title"], "author": uv["author"], "size_mb": uv["size_mb"], "thumb": uv["thumb"] if uv["thumb"] and os.path.exists(uv["thumb"]) else None, "source": "user", "video_path": uv["video_path"], "folder": uv.get("folder"), "author_avatar": get_avatar_url(uv["author"])} for vid, uv in USER_VIDEO_MAP.items()]
    random.shuffle(all_videos)
    authors = [{"name": a, "avatar": get_avatar_url(a)} for a in sorted(authors_set)]
    
    # Отдаём пользовательские данные вместе со страницей: без этого избранное
    # и список скрытых каналов появлялись с задержкой после загрузки.
    # Гостю личные данные владельца не показываем: они приезжают прямо в
    # разметке, поэтому фильтровать надо здесь, а не в браузере. Своё избранное
    # гость ведёт в localStorage своего устройства.
    is_owner = request_is_owner()
    user_state = userdata.get_all() if is_owner else userdata.empty_state()

    # Отметка раздела в нижней навигации. Разделы главной переключаются в
    # браузере без перезагрузки, но при переходе по ссылке /?nav=queue отметка
    # должна стоять верно уже в разметке: иначе до выполнения скрипта подсвечена
    # «Главная». Значения совпадают с data-nav-target в _mobile_nav.html.
    nav_active = NAV_SECTIONS.get(request.args.get('nav', 'all'), 'home')

    return render_template("index.html", all_videos=all_videos, shorts=shorts, authors=authors, playlists=list(PLAYLIST_MAP.values()), user_videos=user_videos_list, hidden_channels=sorted(hidden_authors) if is_owner else [], favorites=user_state['favorites'], watch_history=user_state['history'], is_owner=is_owner, nav_active=nav_active)

@app.route('/settings')
def settings_page():
    return render_template('settings.html', nav_active='settings')

@app.route('/channel/<author>')
def channel(author):
    # Гостю скрытый канал не существует: страница канала обходила фильтр,
    # достаточно было знать имя автора.
    if hidden_from_guest(author):
        abort(404)

    ensure_video_map()
    build_playlist_map()

    author_videos = []
    channel_url = ''
    for vid, v in VIDEO_MAP.items():
        if v["author"] != author:
            continue
        if not channel_url:
            channel_url = v.get('channel_url', '')
        # Имя превью берём из кэша сканирования, как на главной. Здесь стоял
        # безусловный find_file, то есть os.listdir на каждое видео канала: у
        # автора с сотней видео страница делала сотню обходов папок, хотя
        # build_video_map уже сохранил имя файла превью в thumb_file.
        thumb = v.get("thumb_file")
        if thumb is None and "thumb_file" not in v:
            thumb = find_file(os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"]),
                              ['.jpg', '.png', '.webp'])
        author_videos.append({
            "id": vid,
            "title": v.get("title", v["folder"]),
            "author": v["author"],
            "size_mb": v.get("size_mb", 0),
            "thumb": thumb,
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

    is_owner = request_is_owner()
    hidden_authors = guest_hidden_authors()
    authors_list = [{"name": name, "avatar": get_avatar_url(name)}
                    for name in sorted({video["author"] for video in VIDEO_MAP.values()}
                                       - hidden_authors)]
    author_avatar_url = get_avatar_url(author)
    banner_url = channel_assets.get_banner_url(author)
    channel_meta = channel_assets.load_channel_meta(author)
    # Догрузка идёт в YouTube и пишет файлы на диск. Запускаем её только для
    # владельца: чужой запрос не должен приводить к записи и сетевым походам.
    if is_owner and (not banner_url or not channel_meta):
        threading.Thread(target=channel_assets.try_fetch_if_missing, args=(author,), daemon=True).start()

    return render_template(
        "channel.html",
        author=author,
        author_avatar=author_avatar_url,
        banner_url=banner_url,
        videos=author_videos,
        playlists=author_playlists,
        authors=authors_list,
        is_owner=is_owner,
        # Состояние кнопки «Скрыть канал» приходит сразу, иначе надпись мигает.
        is_hidden=author in hidden_channels_set(),
        total_videos=len(author_videos),
        total_shorts=sum(1 for video in author_videos if video['is_short']),
        channel_url=channel_url,
        description=channel_meta.get('description', ''),
        subscribers=channel_assets.format_subscribers(channel_meta.get('subscribers')),
        country=channel_meta.get('country', ''),
        joined_date=channel_meta.get('joined_date', ''),
        # Данные с YouTube для вкладки «О канале»: раньше там было только число
        # скачанных файлов, и понять размер самого канала было невозможно.
        channel_handle=channel_meta.get('handle', ''),
        remote_channel_url=channel_meta.get('channel_url', '') or channel_url,
        remote_video_count=channel_meta.get('video_count'),
        channel_views=channel_meta.get('view_count'),
        channel_verified=bool(channel_meta.get('verified')),
        channel_tags=channel_meta.get('tags') or [],
        channel_links=safe_channel_links(channel_meta.get('links')),
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
    # Проверка «уже синхронизируется» и запуск потока должны быть одной
    # операцией. Раньше лок отпускался до старта потока, и два одновременных
    # запроса успевали оба пройти проверку: sync_channel регистрируется в
    # _fetching уже внутри потока, поэтому второй запрос видел пустой набор и
    # поднимал вторую загрузку тех же метаданных канала. Побеждала та, что
    # финишировала последней, а её результат мог быть старее.
    with channel_assets._fetch_lock:
        if author in channel_assets._fetching:
            return jsonify({'status': 'checking', 'message': 'Синхронизация уже выполняется'})
        # Занимаем слот здесь же, под тем же локом. sync_channel вызывается с
        # already_claimed=True, чтобы не пытаться занять его повторно, но
        # освобождение по-прежнему остаётся за ним (finally в sync_channel).
        channel_assets._fetching.add(author)
    try:
        threading.Thread(
            target=channel_assets.sync_channel,
            args=(author, channel_url),
            kwargs={'already_claimed': True},
            daemon=True,
        ).start()
    except RuntimeError as e:
        # Поток не создался (например, исчерпаны ресурсы): слот надо отдать,
        # иначе канал навсегда останется в состоянии «синхронизируется».
        with channel_assets._fetch_lock:
            channel_assets._fetching.discard(author)
        logger.error(f"api_channel_sync: не удалось запустить поток для «{author}»: {e}")
        return jsonify({'error': 'Не удалось запустить синхронизацию'}), 500
    return jsonify({'status': 'checking', 'message': 'Проверка канала запущена'})


# Прозрачный GIF 1x1: отдаём вместо превью, когда файла нет. Раньше здесь
# отдавался static/images/lazy_placeholder.gif, которого в проекте нет вовсе:
# send_file на несуществующем пути поднимает NotFound, поэтому каждое видео без
# thumbnail.jpg приводило к 404 в консоли браузера, а предзагрузка превью на
# главной (preloadAllThumbnails) заваливала лог ошибками.
PLACEHOLDER_GIF = bytes.fromhex(
    '47494638396101000100800000000000ffffff21f90401000000'
    '002c00000000010001000002024401003b')


@app.route('/api/thumbnail/<vid_id>')
def api_thumbnail(vid_id):
    # ensure_video_map, а не build_video_map: раньше промах по id запускал полный
    # обход библиотеки на КАЖДЫЙ запрос. Главная предзагружает превью всех видео,
    # поэтому сто неизвестных id давали сто полных сканирований подряд, и страница
    # вставала. Здесь скан выполняется только если карта успела устареть.
    if vid_id not in VIDEO_MAP: ensure_video_map()
    # Гостю у скрытого канала — 404, а не заглушка: код 200 подтверждал бы, что
    # такое видео есть.
    if vid_id in VIDEO_MAP and hidden_from_guest(VIDEO_MAP[vid_id]["author"]):
        abort(404)
    if vid_id in VIDEO_MAP:
        v = VIDEO_MAP[vid_id]
        # Имя превью известно из сканирования: раньше здесь жёстко искался
        # thumbnail.jpg, поэтому видео с превью в .webp или .png (yt-dlp
        # сохраняет и такие) всегда отдавали заглушку.
        candidates = [v.get('thumb_file'), 'thumbnail.jpg', 'thumbnail.webp', 'thumbnail.png']
        folder = os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"])
        for name in candidates:
            if not name:
                continue
            thumb_path = os.path.join(folder, name)
            if os.path.exists(thumb_path):
                return send_file(thumb_path)
    response = app.response_class(PLACEHOLDER_GIF, mimetype='image/gif')
    # Заглушку кэшируем: без этого главная запрашивала её заново на каждый показ.
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response

@app.route('/watch/<vid_id>')
def watch(vid_id):
    ensure_video_map()
    build_user_video_map()

    # Видео могли открыть из своего плейлиста: тогда после конца ролика плеер
    # переходит к следующему по списку.
    # Плейлисты принадлежат владельцу: гостю их состав не показываем.
    collection_id = (request.args.get('collection') or '') if request_is_owner() else ''
    collection_order = collection_playback_order(collection_id)
    if not collection_order:
        collection_id = ''

    # Гостю страница видео скрытого канала недоступна: прямая ссылка обходила
    # фильтр каталога.
    if vid_id in VIDEO_MAP and hidden_from_guest(VIDEO_MAP[vid_id]["author"]):
        abort(404)
    
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
        
        meta = read_video_info(folder_path)
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
                           # Просмотр плейлиста по порядку: страница открыта с
                           # ?collection=<id>, дальше плеер сам ведёт по списку.
                           collection_id=collection_id,
                           collection_order=collection_order,
                           # Гостю из локальной сети кнопки владельца не нужны:
                           # эндпоинты для него всё равно закрыты.
                           is_owner=request_is_owner(),
                           publish_date=meta.get('upload_date') or meta.get('upload_date'))

# ================= API: СКАЧИВАНИЕ =================
@app.route('/api/formats', methods=['POST'])
def api_formats():
    # silent=True обязателен: request.json без Content-Type: application/json
    # поднимает 415 и отдаёт HTML-страницу, а клиент разбирает ответ как JSON
    # и падает на «Unexpected token '<'» вместо понятного сообщения.
    url = (request.get_json(silent=True) or {}).get('url')
    if not url: return jsonify({'error': 'URL не указан'}), 400
    formats = get_format_choices(url)
    if not formats:
        formats = [{'type': 'auto', 'format_id': None, 'resolution': 'Авто (рекомендуемое)', 'codec': 'best', 'size_mb': None}]
    return jsonify({'formats': formats, 'video_id': url})

@app.route('/api/direct_formats', methods=['POST'])
def api_direct_formats():
    """Отдаёт фактические параметры уже скачанного файла.

    Раньше сюда приходил локальный путь (/media/Author/id/video.mp4), а не
    ссылка на YouTube: get_format_choices отвечал «is not a valid URL», список
    получался пустым, и меню качества в плеере всегда показывало
    «Нет доступных форматов». Пересобрать файл в другом разрешении локально
    всё равно нельзя, поэтому показываем то, что есть.
    """
    data = request.get_json(silent=True) or {}
    video_id = data.get('video_id') or ''
    if not video_id:
        return jsonify({'error': 'video_id не указан'}), 400

    ensure_video_map()
    entry = VIDEO_MAP.get(video_id)
    if not entry:
        if video_id in USER_VIDEO_MAP:
            return jsonify({'formats': [{
                'type': 'local', 'format_id': None, 'resolution': 'Локальный файл',
                'codec': '', 'size_mb': None, 'local': True,
            }]})
        return jsonify({'error': 'Видео не найдено'}), 404

    # Разрешение и кодек в VIDEO_MAP не хранятся, поэтому читаем info.json.
    folder_path = os.path.join(BASE_VIDEO_DIR, entry['author'], entry['folder'])
    meta = {}
    info_file = find_file(folder_path, ['info.json', '.info.json'])
    if info_file:
        try:
            with open(os.path.join(folder_path, info_file), 'r', encoding='utf-8-sig') as f:
                meta = json.load(f)
        except Exception as e:
            logger.warning(f"Не удалось прочитать метаданные {folder_path}: {e}")
    if not isinstance(meta, dict):
        meta = {}

    height = meta.get('height')
    resolution = f"{height}p" if height else (meta.get('resolution') or 'Локальный файл')
    return jsonify({'formats': [{
        'type': 'local',
        'format_id': None,
        'resolution': resolution,
        'codec': meta.get('vcodec') or '',
        'width': meta.get('width'),
        'height': height,
        'fps': meta.get('fps'),
        'size_mb': entry.get('size_mb'),
        'local': True,
    }]})

@app.route('/api/direct_download', methods=['POST'])
def api_direct_download():
    data = request.get_json(silent=True) or {}
    url = data.get('url')
    video_format = data.get('format_id')
    audio_format = data.get('audio_format_id')

    if not url: return jsonify({'error': 'URL не указан'}), 400

    final_format = video_format
    if video_format and audio_format:
        # Fallback обязателен: если у видео нет одного из этих id (они уникальны
        # для конкретного видео), yt-dlp отказывался скачивать вообще.
        final_format = f"{video_format}+{audio_format}/best"

    result = download_single_sync([url], final_format, lambda p, m: None, merge_format='mp4')
    reason = getattr(result, 'last_error', '') or ''
    failed = getattr(result, 'failed', 0)
    if not result:
        # Код ответа обязателен: клиент, проверяющий res.ok, раньше считал
        # отказ (HTTP 200 с телом {'error': ...}) успешной загрузкой.
        return jsonify({'error': f'Ошибка загрузки: {reason}' if reason else 'Ошибка загрузки'}), 502
    build_video_map()
    if failed:
        return jsonify({
            'status': 'partial',
            'title': f'Скачано частично: {failed} из {getattr(result, "succeeded", 0) + failed} не удалось',
            'error': reason,
        })
    if getattr(result, 'skipped', 0):
        return jsonify({'status': 'ok', 'title': 'Видео уже было скачано'})
    return jsonify({'status': 'ok', 'title': 'Загрузка завершена'})

# ================= API: COOKIES =================
@app.route('/api/cookies', methods=['GET', 'DELETE'])
def api_cookies():
    if request.method == 'GET':
        # os.path.exists + getsize/getmtime — три отдельных обращения к диску.
        # Файл могли удалить или перезаписать между ними (импорт cookies идёт
        # через os.replace), и тогда getmtime падал с FileNotFoundError, отдавая
        # HTML-страницу 500 на JSON-запрос настроек.
        try:
            stat = os.stat(COOKIES_PATH)
        except FileNotFoundError:
            return jsonify({'exists': False, 'size': 0})
        except OSError as e:
            logger.error(f"api_cookies: не удалось прочитать {COOKIES_PATH}: {e}")
            return jsonify({'error': 'Не удалось прочитать файл cookies'}), 500
        return jsonify({'exists': True, 'size': stat.st_size, 'modified': stat.st_mtime})
    elif request.method == 'DELETE':
        # На Windows файл, открытый yt-dlp, удалить нельзя: получаем
        # PermissionError. Без обработки это тоже давало 500 вместо
        # объяснимого ответа. FileNotFoundError означает, что удалять уже
        # нечего, — для DELETE это успех по смыслу операции.
        try:
            os.remove(COOKIES_PATH)
        except FileNotFoundError:
            return jsonify({'status': 'not_found'})
        except OSError as e:
            logger.error(f"api_cookies: не удалось удалить {COOKIES_PATH}: {e}")
            return jsonify({'error': 'Файл cookies занят другим процессом'}), 500
        return jsonify({'status': 'deleted'})

@app.route('/api/cookies/status', methods=['GET'])
def api_cookies_status():
    # Один os.stat вместо четырёх обращений к диску: прежний вариант проверял
    # существование трижды и мог получить исчезнувший файл между проверками.
    try:
        stat = os.stat(COOKIES_PATH)
    except OSError:
        return jsonify({'exists': False, 'size': 0, 'modified': 0})
    return jsonify({'exists': True, 'size': stat.st_size, 'modified': stat.st_mtime})

# Реализация живёт в utils: тем же путём идёт импорт cookies из браузера
# (auth_options), которому нельзя импортировать app.
sanitize_netscape_cookies = utils_sanitize_cookies


class CookieImportError(Exception):
    """Импортированные cookies не годятся для записи."""


def _store_cookies(content, cookies_count):
    """Записывает cookies.txt атомарно, отвергая пустой результат.

    Раньше файл открывался на запись напрямую: обрыв записи оставлял огрызок,
    а импорт файла, из которого не удалось разобрать ни одной записи, молча
    затирал рабочие cookies заголовком без единой строки — авторизация
    пропадала, и причину в интерфейсе было не видно.
    """
    if not cookies_count:
        raise CookieImportError(
            'Ни одной cookie распознать не удалось, файл не заменён. '
            'Проверьте, что это экспорт в формате Netscape или JSON.')
    try:
        write_text_atomic(COOKIES_PATH, content)
    except OSError as e:
        raise CookieImportError(f'Не удалось сохранить cookies: {e}') from e


@app.route('/api/cookies/import', methods=['POST'])
def api_cookies_import():
    try:
        # Раньше здесь стояло request.content_type == 'application/json', а
        # браузеры присылают 'application/json; charset=utf-8': точное сравнение
        # не срабатывало, ветка JSON пропускалась, и вставка текста в настройках
        # отвечала «Нет данных для импорта».
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            data = payload
            text = data.get('text', '')
            if not text:
                return jsonify({'error': 'Нет данных cookies'}), 400
            stripped = text.strip()
            cookies_count = 0
            # Формат определяем по содержимому, а не по первой строке: файлы из
            # части расширений начинаются с '# HTTP Cookie File' без слова
            # Netscape, и такой файл уходил в разбор как JSON и отвергался.
            if not stripped.startswith(('[', '{')):
                # Битые записи выбрасываем: одна строка с переводом строки в
                # значении разрывала запись на две неполные, и yt-dlp отвергал
                # ВЕСЬ файл («does not look like a Netscape format cookies
                # file»), то есть авторизация терялась целиком.
                netscape_content, cookies_count = sanitize_netscape_cookies(text)
                # Через _store_cookies, а не open(...,'w') напрямую: прямая
                # запись обрывала файл на месте, поэтому сбой посреди неё
                # оставлял половину cookies, и она же затирала рабочий файл
                # пустым результатом, если распознать не удалось ничего.
                _store_cookies(netscape_content, cookies_count)
            else:
                try:
                    import json as json_module
                    data_cookies = json_module.loads(text)
                    if isinstance(data_cookies, list):
                        netscape_lines = ['# Netscape HTTP Cookie File']
                        for c in data_cookies:
                            domain = str(c.get('domain', ''))
                            # Табы и переводы строк внутри значения разрывают
                            # запись, и файл становится нечитаемым для yt-dlp.
                            def _clean(value):
                                return re.sub(r'[\t\r\n]+', ' ', str(value)).strip()

                            expires = c.get('expires', 0)
                            try:
                                expires = int(float(expires or 0))
                            except (TypeError, ValueError):
                                expires = 0
                            netscape_lines.append('\t'.join([
                                _clean(domain),
                                'TRUE' if domain.startswith('.') else 'FALSE',
                                _clean(c.get('path', '/')) or '/',
                                'TRUE' if c.get('secure') else 'FALSE',
                                str(expires),
                                _clean(c.get('name', '')),
                                _clean(c.get('value', '')),
                            ]))
                        content, cookies_count = sanitize_netscape_cookies(
                            '\n'.join(netscape_lines))
                        _store_cookies(content, cookies_count)
                    else:
                        return jsonify({'error': 'Неверный формат JSON'}), 400
                except CookieImportError as e:
                    return jsonify({'error': str(e)}), 400
                except Exception as e:
                    return jsonify({'error': f'Ошибка парсинга: {str(e)}'}), 400
        elif 'file' in request.files:
            file = request.files['file']
            if not file:
                return jsonify({'error': 'Файл не загружен'}), 400
            content = file.read().decode('utf-8', 'replace')
            # Файл из браузера тоже может содержать битые записи.
            content, cookies_count = sanitize_netscape_cookies(content)
            _store_cookies(content, cookies_count)
        else:
            return jsonify({'error': 'Нет данных для импорта'}), 400
        return jsonify({'status': 'ok', 'cookies_count': cookies_count})
    except CookieImportError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Импорт cookies не удался: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/cookies/browsers', methods=['GET'])
def api_cookies_browsers():
    """Браузеры для выбора при импорте cookies."""
    return jsonify({'browsers': auth_options.available_browsers()})

@app.route('/api/cookies/from-browser', methods=['POST'])
def api_cookies_from_browser():
    # get_json(silent=True), а не request.json: сама property поднимает 415 ещё
    # до `or {}`, поэтому запрос без заголовка получал HTML вместо JSON.
    browser = (request.get_json(silent=True) or {}).get('browser', '')
    if not browser:
        return jsonify({'error': 'Не указан браузер'}), 400
    result = auth_options.import_cookies_from_browser(browser)
    if result.get('error'):
        return jsonify({'error': result['error']}), 400
    return jsonify({'status': 'ok', 'cookies_count': result['count'], 'browser': result['browser']})

@app.route('/api/playlist/info', methods=['POST'])
def api_playlist_info():
    url = (request.get_json(silent=True) or {}).get('url')
    if not url: return jsonify({'error': 'URL не указан'}), 400
    try:
        info = get_playlist_info(url)
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 502

CHANNEL_TAB_SUFFIXES = ('/videos', '/shorts', '/streams')
# Ссылка из info.json может уже указывать на конкретный таб канала.
KNOWN_TAB_SUFFIXES = CHANNEL_TAB_SUFFIXES + ('/playlists', '/featured', '/community', '/live')
# Всё, что не ведёт на страницу видео, — служебная запись канала (таб, плейлист).
VIDEO_URL_MARKERS = ('watch?v=', '/shorts/', '/live/', 'youtu.be/')

_TIKTOK_HOSTS = {'tiktok.com', 'm.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'}
_YOUTUBE_HOSTS = {'youtube.com', 'm.youtube.com', 'music.youtube.com',
                  'youtu.be', 'youtube-nocookie.com'}


def _url_host(url):
    try:
        parsed = urlparse(str(url).strip())
    except (TypeError, ValueError):
        return '', None
    if parsed.scheme not in ('http', 'https'):
        return '', None
    return parsed.hostname.lower().removeprefix('www.') if parsed.hostname else '', parsed


def is_supported_download_url(url):
    """Принимает только ссылки YouTube и TikTok, а не произвольные HTTP URL."""
    host, parsed = _url_host(url)
    if host in _YOUTUBE_HOSTS:
        return True
    if host not in _TIKTOK_HOSTS or parsed is None:
        return False
    # Короткие vm/vt-ссылки раскрывает yt-dlp. На основном сайте нужен путь:
    # корень tiktok.com не является ни роликом, ни профилем.
    if host in {'vm.tiktok.com', 'vt.tiktok.com'}:
        return bool(parsed.path.strip('/'))
    parts = [part for part in parsed.path.split('/') if part]
    return (len(parts) >= 3 and parts[0].startswith('@') and parts[1] == 'video'
            and parts[2].isdigit()) or (len(parts) == 1 and parts[0].startswith('@')) \
        or (host == 'm.tiktok.com' and len(parts) >= 2 and parts[0] == 'v'
            and parts[1].removesuffix('.html').isdigit())


def is_tiktok_profile_url(url):
    """Профиль @user: его надо развернуть в список отдельных роликов."""
    host, parsed = _url_host(url)
    if host != 'tiktok.com' or parsed is None:
        return False
    parts = [part for part in parsed.path.split('/') if part]
    return len(parts) == 1 and parts[0].startswith('@') and len(parts[0]) > 1


def _entry_video_url(entry):
    """URL ролика из плоской записи yt-dlp или None для служебной записи."""
    if not isinstance(entry, dict) or entry.get('_type') == 'playlist':
        return None
    url = str(entry.get('webpage_url') or entry.get('url') or '')
    if url.startswith(('http://', 'https://')) and is_supported_download_url(url):
        return url
    return None


def expand_download_urls(url):
    """Раскрывает профиль TikTok в URL его роликов.

    YouTube-плейлисты обрабатывает существующий выборщик, а обычные ссылки и
    короткие TikTok URL остаются одной задачей — yt-dlp сам раскрывает redirect.
    """
    if not is_tiktok_profile_url(url):
        return [url]
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'ignoreerrors': 'only_download',
        'socket_timeout': 30,
        'retries': 2,
        'cookiefile': cookiefile_for_ydl(COOKIES_PATH),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    apply_cookie_updates(opts)
    entries = info.get('entries') if isinstance(info, dict) else None
    urls, seen = [], set()
    for entry in entries if isinstance(entries, list) else []:
        video_url = _entry_video_url(entry)
        if video_url and video_url not in seen:
            seen.add(video_url)
            urls.append(video_url)
    if not urls:
        raise RuntimeError('TikTok не вернул ролики профиля')
    return urls


def channel_tab_urls(channel_url):
    """Ссылки на табы канала.

    Корень канала отдаёт не видео, а список табов, поэтому обходим
    /videos, /shorts и /streams по отдельности.
    """
    base = str(channel_url or '').strip().rstrip('/')
    if not base:
        return []
    for suffix in KNOWN_TAB_SUFFIXES:
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    return [base + suffix for suffix in CHANNEL_TAB_SUFFIXES]


def channel_entry_video_url(entry):
    """Ссылка на видео из плоской записи канала или None, если это не видео."""
    if not isinstance(entry, dict):
        return None
    # Таб и плейлист сами по себе не видео: их извлекает YoutubeTab.
    if entry.get('_type') == 'playlist' or entry.get('ie_key') in ('YoutubeTab', 'YoutubePlaylist'):
        return None
    video_id = str(entry.get('id') or '')
    url = str(entry.get('webpage_url') or entry.get('url') or '')
    if url.startswith('http'):
        if is_supported_download_url(url):
            return url
        return url if any(marker in url for marker in VIDEO_URL_MARKERS) else None
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else None


def iter_channel_videos(info, depth=0):
    """Разворачивает вложенные плейлисты канала в плоский список записей."""
    if not isinstance(info, dict) or depth > 3:
        return
    entries = info.get('entries')
    if isinstance(entries, list):
        for entry in entries:
            yield from iter_channel_videos(entry, depth + 1)
        return
    if info.get('id') and channel_entry_video_url(info):
        yield info


@app.route('/api/channel/<author>/remaining', methods=['POST'])
def api_channel_remaining(author):
    build_video_map()
    channel_urls = [v.get('channel_url') for v in VIDEO_MAP.values() if v.get('author') == author and v.get('channel_url')]
    channel_url = next((url for url in channel_urls if url), '')
    if not channel_url:
        return jsonify({'error': 'Не удалось определить ссылку на канал'}), 404

    options = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        # 'in_playlist', а не True: с True корень YouTube-канала отдавал сами
        # табы. У TikTok это обычная лента профиля, но та же опция возвращает
        # плоские записи без загрузки.
        'extract_flat': 'in_playlist',
        # 'only_download', а не True: с True yt-dlp гасит ошибку извлечения и
        # возвращает None, из-за чего недоступный профиль выглядел пустым.
        'ignoreerrors': 'only_download',
        'socket_timeout': 30,
        # Поток, а не путь: иначе yt-dlp перезапишет cookies.txt при close().
        'cookiefile': cookiefile_for_ydl(COOKIES_PATH),
    }
    is_tiktok = is_tiktok_profile_url(channel_url)
    if not is_tiktok:
        # Только YouTube: иначе TikTok получает несуществующие extractor args.
        options['extractor_args'] = {'youtubetab': {'skip': ['authcheck']}}
        # apply_po_args, а не update: update затирал extractor_args целиком
        # вместе с youtubetab:skip=authcheck.
        apply_po_args(options)

    local_ids = set(VIDEO_MAP.keys())
    remaining, seen, errors = [], set(), []
    profile_urls = [channel_url] if is_tiktok else channel_tab_urls(channel_url)
    for tab_url in profile_urls:
        info = None
        last_exc = None
        # Обрыв сети повторяем: иначе один сбой SSL «съедал» все видео таба,
        # и список остальных видео молча выходил неполным.
        for attempt in range(1, download_lib.STREAM_RETRIES + 1):
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(tab_url, download=False)
                # yt-dlp при close() сохраняет cookies в поток через truncate(0)
                # без seek(0), из-за чего позиция остаётся в конце. Без
                # apply_cookie_updates повторная загрузка из того же потока
                # падает с «does not look like a Netscape format cookies file».
                apply_cookie_updates(options)
                if info is None:
                    raise RuntimeError('YouTube не вернул данные вкладки')
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                info = None
                if (attempt >= download_lib.STREAM_RETRIES
                        or not download_lib.is_transient_error(str(e))):
                    break
                time.sleep(download_lib.STREAM_RETRY_DELAY * attempt)
        if last_exc is not None:
            # Таба может не быть вовсе (канал без трансляций или без shorts) —
            # это не повод терять видео, собранные из остальных табов.
            errors.append(str(last_exc))
            logger.warning(f"Не удалось получить {tab_url}: {last_exc}")
            continue
        for entry in iter_channel_videos(info):
            video_id = str(entry.get('id') or '')
            url = channel_entry_video_url(entry)
            if not url or not video_id or video_id in local_ids or video_id in seen:
                continue
            seen.add(video_id)
            # duration нужна модалке выбора видео; при extract_flat её может
            # не быть, поэтому приводим к числу только когда значение пришло.
            raw_duration = entry.get('duration')
            try:
                duration = float(raw_duration) if raw_duration is not None else None
            except (TypeError, ValueError):
                duration = None
            remaining.append({
                'id': video_id,
                'url': url,
                'title': entry.get('title') or 'Видео',
                'duration': duration,
            })

    # Ошибку показываем только если не набралось ни одного видео: иначе
    # недоступный таб превращал успешный обход в 502.
    if not remaining and errors:
        return jsonify({'error': errors[0]}), 502
    return jsonify({'title': author, 'videos': remaining, 'count': len(remaining)})

# ================= ЭКСПОРТ/ИМПОРТ КАНАЛОВ =================
@app.route('/api/channel/<author>/export', methods=['POST'])
def api_channel_export(author):
    """Экспорт канала как tar.gz с перекодировкой видео в совместимые форматы (с потерями качества, CRF 23)."""
    author_path = os.path.join(BASE_VIDEO_DIR, safe_name(author))
    if not os.path.isdir(author_path):
        return jsonify({'error': 'Канал не найден'}), 404

    import tarfile
    import io
    import tempfile
    import shutil
    import glob as glob_mod
    ffmpeg_bin = paths.ffmpeg_path()
    try:
        subprocess.run([ffmpeg_bin, '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        has_ffmpeg = True
    except Exception:
        has_ffmpeg = False

    # Создаём временную директорию с пересжатыми видео
    tmp_dir = tempfile.mkdtemp(prefix='lt_export_')
    try:
        tmp_author_path = os.path.join(tmp_dir, safe_name(author))
        os.makedirs(tmp_author_path, exist_ok=True)
        for entry in os.listdir(author_path):
            src_entry = os.path.join(author_path, entry)
            dst_entry = os.path.join(tmp_author_path, entry)
            if os.path.isdir(src_entry):
                shutil.copytree(src_entry, dst_entry, dirs_exist_ok=True)
                # Перекодируем видео через ffmpeg для переноса между каналами:
                # CRF 23 — компромисс между размером и качеством (не без потерь).
                if has_ffmpeg:
                    for video_file in glob_mod.glob(os.path.join(dst_entry, '*.mp4')) + \
                                      glob_mod.glob(os.path.join(dst_entry, '*.webm')):
                        tmp_out = video_file + '.tmp.mp4'
                        cmd = [ffmpeg_bin, '-y', '-i', video_file,
                               '-c:v', 'libx264', '-crf', '23', '-preset', 'slow',
                               '-c:a', 'aac', '-b:a', '128k',
                               tmp_out]
                        try:
                            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
                            if os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0:
                                # .webm перекодируется в .mp4: удаляем оригинал
                                # и переименовываем .tmp.mp4 в .mp4, чтобы
                                # расширение соответствовало формату контейнера.
                                if video_file.lower().endswith('.webm'):
                                    os.remove(video_file)
                                    os.rename(tmp_out, os.path.splitext(video_file)[0] + '.mp4')
                                else:
                                    os.replace(tmp_out, video_file)
                            else:
                                if os.path.exists(tmp_out):
                                    os.remove(tmp_out)
                        except Exception as e:
                            logger.warning(f"Экспорт: не удалось сжать {video_file}: {e}")
                            if os.path.exists(tmp_out):
                                os.remove(tmp_out)
            elif os.path.isfile(src_entry):
                shutil.copy2(src_entry, dst_entry)

        # Упаковываем во временный tar.gz
        archive_path = os.path.join(tmp_dir, f'{safe_name(author)}.tar.gz')
        with tarfile.open(archive_path, 'w:gz', compresslevel=9) as tar:
            tar.add(tmp_author_path, arcname=safe_name(author))

        # Читаем в память, чтобы не зависеть от удаления временной директории
        with open(archive_path, 'rb') as f:
            archive_data = f.read()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return send_file(
            io.BytesIO(archive_data),
            as_attachment=True,
            download_name=f'{safe_name(author)}.tar.gz',
            mimetype='application/gzip'
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

@app.route('/api/channel/import', methods=['POST'])
def api_channel_import():
    """Импорт канала из tar.gz архива."""
    uploaded = request.files.get('archive')
    if not uploaded:
        return jsonify({'error': 'Файл архива не передан'}), 400
    import tarfile
    import io
    import tempfile
    import shutil
    tmp_dir = tempfile.mkdtemp(prefix='lt_import_')
    try:
        archive_data = uploaded.read()
        try:
            with tarfile.open(fileobj=io.BytesIO(archive_data), mode='r:gz') as tar:
                # filter='data' блокирует path traversal (../../etc/passwd) и
                # запись за пределы tmp_dir — обязательный аргумент в Python 3.12+.
                try:
                    tar.extractall(tmp_dir, filter='data')
                except TypeError:
                    # Python < 3.12: filter не поддерживается, fallback на ручную проверку.
                    tar.extractall(tmp_dir)
        except (tarfile.ReadError, tarfile.CompressionError):
            return jsonify({'error': 'Файл не является корректным tar.gz архивом'}), 400

        extracted_dirs = [d for d in os.listdir(tmp_dir) if os.path.isdir(os.path.join(tmp_dir, d))]
        if not extracted_dirs:
            return jsonify({'error': 'В архиве нет директории канала'}), 400

        imported_count = 0
        for ch_dir in extracted_dirs:
            # safe_name предотвращает path traversal через имя директории в архиве:
            # '..' и 'CON' сворачиваются в безопасные имена внутри BASE_VIDEO_DIR.
            safe_dir = safe_name(ch_dir)
            dst_path = os.path.join(BASE_VIDEO_DIR, safe_dir)
            # Очищаем старый метафайл канала, чтобы не было пересечения с данными
            # из META_DIR (описание, подписчики из другого канала).
            try:
                channel_assets.clear_channel_meta(safe_dir)
            except Exception:
                pass
            if os.path.exists(dst_path):
                shutil.rmtree(dst_path)
            shutil.copytree(os.path.join(tmp_dir, ch_dir), dst_path)
            # Гарантируем, что импортированные видео не считаются шортс:
            # is_short в info.json может быть True из-за duration <= 60.
            for root, _, files in os.walk(dst_path):
                for f in files:
                    if f == "info.json":
                        info_path = os.path.join(root, f)
                        try:
                            info = read_json(info_path)
                            if isinstance(info, dict):
                                info["is_short"] = False
                                # Гарантируем, что title и description не перекрываются
                                # полями из чужого info.json.
                                if not info.get('title'):
                                    info['title'] = f"Видео {os.path.basename(root)}"
                                write_json_atomic(info_path, info)
                        except Exception:
                            pass
                    if f.lower().endswith(('.mp4', '.webm', '.mp3', '.m4a')):
                        imported_count += 1

        invalidate_scan_cache()
        build_video_map()
        build_user_video_map()
        return jsonify({'imported': imported_count, 'channels': extracted_dirs})
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

# ================= ОЧЕРЕДЬ =================
# Плагины getpot_bgutil для PO Token (создаются при первом запуске)
try:
    auth_options.ensure_plugins()
except Exception as e:
    logger.warning(f"Не удалось установить плагины PO Token: {e}")

# Провайдер PO Token поднимается в фоне: без токена YouTube отдаёт HTTP 403
# на середине длинных видео. Ожидание сервера не должно задерживать старт.
def _start_po_provider():
    try:
        if auth_options.ensure_bgutil_server():
            logger.info("Провайдер PO Token готов")
        elif auth_options.get_options().get("po_token") == "bgutil:http":
            logger.warning("Провайдер PO Token не запустился: длинные видео могут падать с HTTP 403")
    except Exception as e:
        logger.warning(f"Не удалось запустить провайдер PO Token: {e}")


threading.Thread(target=_start_po_provider, daemon=True).start()

_queue_worker_started = False
_queue_worker_thread = None
_queue_worker_lock = threading.Lock()


def ensure_queue_worker():
    """Запускает фоновый обработчик очереди, если он ещё не работает.

    Проверяем именно живость потока, а не флаг: раньше упавший воркер навсегда
    оставлял флаг поднятым, и очередь замирала до перезапуска процесса, при
    этом /api/queue/add продолжал отвечать 200.
    """
    global _queue_worker_started, _queue_worker_thread
    # Лок вокруг check-then-set: без него два одновременных запроса могли
    # поднять двух воркеров и скачивать одну задачу дважды.
    with _queue_worker_lock:
        if _queue_worker_thread is not None and _queue_worker_thread.is_alive():
            return _queue_worker_thread
        _queue_worker_thread = threading.Thread(target=process_queue, daemon=True)
        _queue_worker_started = True
        _queue_worker_thread.start()
        return _queue_worker_thread

def process_queue():
    global queue_processing, queue_paused
    queue_processing = True
    while True:
        try:
            _process_queue_once()
        except Exception as e:
            # Последний рубеж: воркер один, и любое непойманное исключение
            # раньше останавливало очередь до перезапуска процесса.
            logger.error(f"Сбой цикла очереди: {e}")
            time.sleep(2)


def _process_queue_once():
        task_to_process = None
        with queue_lock:
            # Пауза читается под локом вместе с выбором задачи: раньше проверка
            # шла до лока, и задача, снятая с паузы прямо в этот момент, могла
            # уйти в загрузку уже после нажатия «Пауза».
            # Сначала высокий приоритет, внутри одного приоритета — порядок добавления.
            waiting = [] if queue_paused else [t for t in queue_tasks if t.status == "waiting"]
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
            return

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
            # С троттлингом: раньше здесь был save_queue() на каждый тик прогресса,
            # то есть запись queue.json с копией и fsync примерно раз в секунду на
            # каждую активную загрузку.
            save_queue_progress()
            
        def is_cancelled():
            with queue_lock:
                return task_to_process.id in queue_cancel_requests

        try:
            result = download_single_sync(
                task_to_process.urls, 
                task_to_process.format_id, 
                update_progress, 
                task_to_process.merge_format,
                should_cancel=is_cancelled
            )
            # DownloadOutcome ведёт себя как bool, но несёт разбивку по видео:
            # она нужна, чтобы не выдавать частичный провал за полный успех.
            # Заглушки в тестах возвращают обычный bool, поэтому getattr.
            success = bool(result)
            done = getattr(result, 'succeeded', 1 if success else 0)
            failed = getattr(result, 'failed', 0 if success else 1)
            with queue_lock:
                # Отмена, пришедшая на этапе склейки, раньше терялась: хуков
                # прогресса там уже нет, и задача помечалась как «Готово».
                if task_to_process.id in queue_cancel_requests:
                    queue_cancel_requests.discard(task_to_process.id)
                    task_to_process.status = "cancelled"
                    task_to_process.progress = 0
                    task_to_process.message = "Отменено пользователем"
                    task_to_process.error = ""
                    task_to_process.speed = ""
                    task_to_process.eta = ""
                else:
                    # Флаг снимаем и на успешном пути: иначе он оставался в
                    # queue_cancel_requests навсегда и мог отменить чужую задачу.
                    queue_cancel_requests.discard(task_to_process.id)
                    task_to_process.speed = ""
                    task_to_process.eta = ""
                    reason = getattr(result, 'last_error', '') or ''
                    skipped = getattr(result, 'skipped', 0)
                    if not success:
                        task_to_process.status = "error"
                        task_to_process.progress = 0
                        # Настоящая причина отказа вместо заглушки: yt-dlp с
                        # ignoreerrors не бросает исключение, поэтому раньше в
                        # очереди всегда стояло «Ошибка скачивания».
                        task_to_process.message = f"Ошибка: {reason}" if reason else "Ошибка скачивания"
                        task_to_process.error = task_to_process.message
                    elif failed:
                        # Частичный успех нельзя показывать как «Готово»:
                        # со статусом completed до задачи не доставали ни кнопка
                        # «Повторить», ни фильтр «С ошибками», ни массовый повтор.
                        task_to_process.status = "partial"
                        task_to_process.progress = 100
                        # Считаем от размера задачи, а не от числа обработанных
                        # ссылок: при остановке из-за сети задача прекращается на
                        # середине, и «3 из 27» скрывало 52 нетронутых видео.
                        planned = len(task_to_process.urls) or (done + failed)
                        untouched = max(0, planned - done - failed)
                        task_to_process.message = (
                            f"Готово, но {failed + untouched} из {planned} не скачано")
                        if reason:
                            task_to_process.message += f". Последняя ошибка: {reason}"
                        task_to_process.error = task_to_process.message
                    else:
                        task_to_process.status = "completed"
                        task_to_process.progress = 100
                        if skipped and skipped >= done:
                            task_to_process.message = f"Все {skipped} видео уже были скачаны"
                        elif skipped:
                            task_to_process.message = f"Готово ({skipped} уже было скачано)"
                        else:
                            task_to_process.message = "Готово"
                        task_to_process.error = ""
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

        # Пересканирование библиотеки не должно ронять воркер: раньше любая
        # ошибка файловой системы убивала единственный поток очереди, и
        # следующие задачи навсегда оставались в статусе waiting.
        try:
            build_video_map()
        except Exception as e:
            logger.error(f"Не удалось пересканировать библиотеку: {e}")
        time.sleep(1)

@app.route('/api/queue/add', methods=['POST'])
def api_queue_add():
    ensure_queue_worker()
    # silent=True: без него запрос без заголовка Content-Type получал HTML-страницу
    # 415, и клиент падал на разборе ответа как JSON.
    data = request.get_json(silent=True) or {}
    urls = data.get('urls') or []
    if not isinstance(urls, list):
        urls = [urls]
    # Отбрасываем мусор: пустая или чужая ссылка иначе уходила в загрузчик.
    urls = [str(u).strip() for u in urls if isinstance(u, (str, bytes)) and str(u).strip()]
    if not urls: return jsonify({'error': 'Нет ссылок'}), 400
    invalid = next((url for url in urls if not is_supported_download_url(url)), None)
    if invalid:
        return jsonify({'error': 'Поддерживаются ссылки YouTube и TikTok'}), 400
    try:
        expanded = []
        for url in urls:
            expanded.extend(expand_download_urls(url))
        urls = expanded
    except Exception as e:
        logger.warning(f"Не удалось получить ролики TikTok: {e}")
        return jsonify({'error': f'Не удалось получить ролики TikTok: {e}'}), 502
    if not urls:
        return jsonify({'error': 'Нет роликов для загрузки'}), 400
    format_id = data.get('format_id')
    title = data.get('title', 'Видео')
    merge_format = data.get('merge_format', 'mp4')

    # Код ответа обязателен: без него клиент, проверяющий res.ok, считал
    # отказ успешным добавлением.
    if not urls: return jsonify({'error': 'Нет ссылок'}), 400
    
    priority = data.get('priority', PRIORITY_NORMAL)

    with queue_lock:
        task_id = _new_task_id_locked()
        task = QueueTask(task_id, urls, format_id, title, merge_format, priority)
        queue_tasks.append(task)
    return save_queue_or_error({'task_id': task_id})

@app.route('/api/queue/list', methods=['GET'])
def api_queue_list():
    # Воркер поднимается и здесь: при запуске не через `python app.py`
    # (WSGI-хост, flask run) он раньше не существовал вообще, и восстановленные
    # после перезапуска задачи навсегда оставались в «Ожидание».
    ensure_queue_worker()
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
        # Читаем под тем же локом, что и задачи: иначе ответ мог сообщить о
        # снятой паузе, показав при этом список задач до её снятия.
        paused = queue_paused
    return jsonify({'tasks': tasks, 'paused': paused})

@app.route('/api/queue/remove/<task_id>', methods=['DELETE'])
def api_queue_remove(task_id):
    global queue_tasks
    with queue_lock:
        # Удаление активной задачи равносильно отмене: иначе загрузчик продолжил бы
        # писать файлы для задачи, которой уже нет в очереди.
        active = any(t.id == task_id and t.status == 'downloading' for t in queue_tasks)
        if active:
            queue_cancel_requests.add(task_id)
        else:
            # Неактивную задачу удаляем вместе с её флагом: иначе он оставался
            # в наборе навсегда и мог отменить новую задачу с тем же id.
            queue_cancel_requests.discard(task_id)
        queue_tasks = [t for t in queue_tasks if t.id != task_id]
    return save_queue_or_error({'cancelled_active': active})


@app.route('/api/queue/cancel/<task_id>', methods=['POST'])
def api_queue_cancel(task_id):
    """Отменяет задачу. Активная загрузка прерывается, temp-файлы удаляются."""
    with queue_lock:
        task = next((t for t in queue_tasks if t.id == task_id), None)
        if not task:
            return jsonify({'error': 'Задача не найдена'}), 404
        if task.status in FINISHED_STATUSES:
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
    return save_queue_or_error({'was_downloading': was_downloading})


@app.route('/api/queue/priority/<task_id>', methods=['POST'])
def api_queue_priority(task_id):
    """Меняет приоритет ожидающей задачи."""
    priority = (request.get_json(silent=True) or {}).get('priority', PRIORITY_NORMAL)
    if priority not in PRIORITY_ORDER:
        return jsonify({'error': 'Неизвестный приоритет'}), 400
    with queue_lock:
        task = next((t for t in queue_tasks if t.id == task_id), None)
        if not task:
            return jsonify({'error': 'Задача не найдена'}), 404
        task.priority = priority
    return save_queue_or_error({'priority': priority})

@app.route('/api/queue/retry/<task_id>', methods=['POST'])
def api_queue_retry(task_id):
    with queue_lock:
        task = next((t for t in queue_tasks if t.id == task_id), None)
        if not task:
            return jsonify({'error': 'Задача не найдена'}), 404
        # Активную загрузку перезапускать нельзя: снятие флага отмены делало
        # её неотменяемой, а статус waiting тут же перетирался воркером.
        if task.status == 'downloading':
            return jsonify({'error': 'Задача уже выполняется'}), 409
        queue_cancel_requests.discard(task_id)
        task.status = 'waiting'
        task.progress = 0
        task.error = ''
        task.message = 'Повторная попытка ожидает запуска'
        # Позицию и метрики прошлой попытки надо обнулить: иначе у ожидающей
        # задачи оставалось «Видео 11/79 · 1.50MiB/s», и это выглядело как
        # сохранённый прогресс, хотя загрузка начинается с первого видео.
        task.current_index = 0
        task.current_url = ''
        task.speed = ''
        task.eta = ''
    response = save_queue_or_error()
    ensure_queue_worker()
    return response

@app.route('/api/queue/pause', methods=['POST'])
def api_queue_pause():
    global queue_paused
    # Под локом: save_queue читает queue_paused под тем же локом, и без этого
    # запись флага могла попасть между чтением и записью файла — на диск уходило
    # старое значение, и после перезапуска пауза пропадала.
    with queue_lock:
        queue_paused = True
    return save_queue_or_error({'paused': True})

@app.route('/api/queue/resume', methods=['POST'])
def api_queue_resume():
    global queue_paused
    with queue_lock:
        queue_paused = False
    response = save_queue_or_error({'paused': False})
    ensure_queue_worker()
    return response

@app.route('/api/queue/clear', methods=['POST'])
def api_queue_clear():
    global queue_tasks
    with queue_lock:
        queue_tasks = [t for t in queue_tasks if t.status not in FINISHED_STATUSES]
        # Флаги отмены удалённых задач надо убрать вместе с ними: сюда попадают
        # id завершённых задач (отмена активной загрузки оставляет флаг, а
        # обработчик снимает его не на всех путях), и без чистки набор растёт на
        # весь срок работы процесса. Побочный эффект: _new_task_id_locked
        # исключает id из набора при выдаче новых, так что мусор постепенно
        # сужал пространство id.
        live_ids = {t.id for t in queue_tasks}
        queue_cancel_requests.intersection_update(live_ids)
    return save_queue_or_error()

# ================= ПОЛЬЗОВАТЕЛЬСКИЕ ВИДЕО =================
TEMP_UPLOAD_DIR = paths.data_path('uploads_tmp')


def _temp_upload_path(kind, filename):
    """Уникальный путь для временного файла загрузки.

    Расширение берётся из имени, присланного клиентом, поэтому его надо чистить:
    имя вида 'video.mp4/../../evil' уводило запись за пределы каталога, а
    os.path.splitext на нём даёт вовсе не то, что ожидается.
    """
    ext = os.path.splitext(filename or '')[1][:10]
    ext = re.sub(r'[^A-Za-z0-9.]', '', ext)
    if ext and not ext.startswith('.'):
        ext = '.' + ext
    os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)
    return os.path.join(TEMP_UPLOAD_DIR, f"{kind}_{uuid.uuid4().hex}{ext}")


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

    except Exception as e:
        logger.error(f"Загрузка своего видео не удалась: {e}")
        return jsonify({'error': str(e)}), 500

    # Имя временного файла уникально: раньше это был общий "temp_video.mp4" в
    # корне проекта, поэтому две одновременные загрузки писали в один файл и
    # первая получала чужое видео. Уборка вынесена в finally: при ошибке
    # add_user_video многогигабайтный temp_video оставался на диске навсегда.
    tmp_v = tmp_t = None
    try:
        tmp_v = _temp_upload_path("video", v_file.filename)
        v_file.save(tmp_v)

        if t_file:
            tmp_t = _temp_upload_path("thumb", t_file.filename)
            t_file.save(tmp_t)

        info = add_user_video(tmp_v, title, desc, username, tmp_t)
        build_user_video_map()
        return jsonify({'status': 'ok', 'id': info['id']})
    except Exception as e:
        logger.error(f"Загрузка своего видео не удалась: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        for path in (tmp_v, tmp_t):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as e:
                    logger.warning(f"Не удалось удалить временный файл {path}: {e}")

@app.route('/api/user_video/edit/<vid_id>', methods=['POST'])
def api_user_edit(vid_id):
    username = request.form.get('username')
    title = request.form.get('title')
    desc = request.form.get('description')
    t_file = request.files.get('thumbnail_file')

    tmp_t = None
    try:
        if t_file:
            tmp_t = _temp_upload_path("thumb", t_file.filename)
            t_file.save(tmp_t)

        info = edit_user_video(vid_id, title, desc, username, tmp_t)
        if info:
            build_user_video_map()
            return jsonify({'status': 'ok'})
        return jsonify({'error': 'Не найдено или нет прав'}), 403
    except Exception as e:
        logger.error(f"Правка своего видео не удалась: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        # finally: раньше удаление стояло после edit_user_video, и при ошибке
        # правки временный файл превью оставался в корне проекта.
        if tmp_t and os.path.exists(tmp_t):
            try:
                os.remove(tmp_t)
            except OSError as e:
                logger.warning(f"Не удалось удалить временный файл {tmp_t}: {e}")

@app.route('/api/user_video/delete/<vid_id>', methods=['POST'])
def api_user_delete(vid_id):
    username = (request.get_json(silent=True) or {}).get('username')
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
    # silent=True: запрос без Content-Type иначе получал HTML-страницу 415.
    data = request.get_json(silent=True) or {}
    result = auth_options.save_options(data)
    if isinstance(result, dict) and result.get('error'):
        return jsonify({'error': result['error']}), 400
    # Включение PO Token без этого требовало перезапуска приложения: настройка
    # сохранялась, но провайдер оставался незапущенным.
    threading.Thread(target=_start_po_provider, daemon=True).start()
    return jsonify({'status': 'ok'})

@app.route('/api/auth/ensure', methods=['POST'])
def api_auth_ensure():
    ok = auth_options.ensure_plugins()
    return jsonify({'status': 'ok' if ok else 'error', 'plugins_dir': os.path.isdir(auth_options.PLUGINS_DIR)})

@app.route('/api/auth/status')
def api_auth_status():
    return jsonify(auth_options.status())

# ================= ЯЗЫК ИНТЕРФЕЙСА =================
@app.route('/api/i18n/<lang>')
def api_i18n_dictionary(lang):
    """Словарь для строк, которые собирает клиентский код.

    Разметку переводит сервер, но часть подписей появляется уже в браузере
    (очередь загрузок, списки каналов), и для них нужен тот же словарь.
    """
    if lang not in i18n.LANGUAGES:
        return jsonify({'error': 'Неизвестный язык'}), 404
    return jsonify({'lang': lang, 'strings': i18n.load_dictionary(lang)})


@app.route('/api/language', methods=['POST'])
def api_language_save():
    """Сохраняет выбранный язык в cookie.

    Cookie, а не config.json: язык — свойство устройства, с которого смотрят.
    На телефоне гостя может быть удобен английский, хотя владелец сидит на
    русском, и общая настройка на сервере ломала бы обоим.
    """
    # silent=True: запрос без Content-Type иначе получал HTML-страницу 415.
    data = request.get_json(silent=True) or {}
    lang = data.get('lang')
    if lang not in i18n.LANGUAGES:
        return jsonify({'error': _t('Неизвестный язык')}), 400
    response = jsonify({'status': 'ok', 'lang': lang})
    response.set_cookie(i18n.LANG_COOKIE, lang, max_age=i18n.LANG_COOKIE_MAX_AGE,
                        samesite='Lax')
    return response

# ================= НАСТРОЙКИ ЗАГРУЗКИ (ЯЗЫКИ И СУБТИТРЫ) =================
@app.route('/api/download/prefs', methods=['GET'])
def api_download_prefs_get():
    """Языки аудиодорожек и субтитров плюс список языков для выпадающих полей.

    Список приходит с сервера, а не дублируется в шаблоне: две копии
    разъезжаются, и в настройках оказывался язык, которого код не знает.
    """
    data = download_prefs.get_prefs()
    data['languages'] = download_prefs.languages_for_ui()
    return jsonify(data)


@app.route('/api/download/prefs', methods=['POST'])
def api_download_prefs_save():
    # silent=True: запрос без Content-Type иначе получал HTML-страницу 415.
    data = request.get_json(silent=True) or {}
    result = download_prefs.save_prefs(data)
    if isinstance(result, dict) and result.get('error'):
        # Шаблон приходит с {value}: переводим текст, потом подставляем код
        # языка. Иначе строку с уже подставленным кодом не нашлось бы в словаре.
        message = _t(result['error']).format(value=result.get('value', ''))
        return jsonify({'error': message}), 400
    return jsonify({'status': 'ok'})

# ================= ХРАНЕНИЕ (ПУТИ К ПАПКАМ) =================
@app.route('/api/storage', methods=['GET'])
def api_storage_get():
    """Текущие пути хранения: как заданы в конфиге и куда разрешились."""
    cfg = load_config()
    data = {key: cfg[key] for key in DEFAULT_DIRS}
    # Относительное "videos" не объясняет, где лежат файлы: показываем и то,
    # во что путь разворачивается на самом деле.
    data['resolved'] = {key: resolve_dir(cfg[key]) for key in DEFAULT_DIRS}
    data['defaults'] = dict(DEFAULT_DIRS)
    return jsonify(data)

@app.route('/api/storage', methods=['POST'])
def api_storage_save():
    # silent=True: запрос без Content-Type иначе отдаёт HTML-страницу 415.
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify({'error': 'Нет данных для сохранения.'}), 400

    unknown = [key for key in data if key not in DEFAULT_DIRS]
    if unknown:
        # Опечатка в имени ключа иначе молча ничего бы не изменила.
        return jsonify({'error': 'Неизвестные настройки: ' + ', '.join(sorted(unknown))}), 400

    cfg = load_config()
    updates = {}
    for key, raw in data.items():
        value = (raw or '').strip() if isinstance(raw, str) else ''
        if not value:
            return jsonify({'error': f'Путь для «{key}» не может быть пустым.'}), 400
        target = resolve_dir(value)
        if os.path.exists(target) and not os.path.isdir(target):
            return jsonify({'error': f'По пути {target} лежит файл, а не папка.'}), 400
        # Проверяем доступность до записи в конфиг: иначе приложение осталось бы
        # с путём, по которому нельзя ничего создать.
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as e:
            return jsonify({'error': f'Не удалось создать папку {target}: {e}'}), 400
        updates[key] = value

    cfg.update(updates)
    try:
        save_config(cfg)
    except JsonWriteError as e:
        return jsonify({'error': f'Не удалось сохранить настройки: {e}'}), 500

    # Пути применяются на живом сервере: без этого веб продолжал бы показывать
    # старую папку, пока загрузчик уже писал бы в новую.
    apply_storage_paths(cfg)
    custom_quality.init(BASE_VIDEO_DIR, logger, lambda: VIDEO_MAP, lambda: USER_VIDEO_MAP, build_video_map, build_user_video_map, USER_VIDEOS_ROOT)
    audio_language.init(BASE_VIDEO_DIR, SUBTITLES_DIR, logger, lambda: VIDEO_MAP, lambda: USER_VIDEO_MAP, build_video_map)
    build_video_map()
    build_user_video_map()
    build_playlist_map()
    # Кэш аватарок сбрасывается по mtime каталога, а каталог сменился целиком:
    # без сброса в выдаче остались бы ссылки на файлы из старой папки.
    with _avatar_cache_lock:
        _avatar_cache['mtime'] = None
        _avatar_cache['map'] = {}

    result = {key: cfg[key] for key in DEFAULT_DIRS}
    result['resolved'] = {key: resolve_dir(cfg[key]) for key in DEFAULT_DIRS}
    return jsonify({'status': 'ok', **result})

# ================= УТИЛИТЫ (Аватарки и Превью) =================
# Обе задачи выполняются внутри процесса, а не через subprocess с sys.executable.
# В собранной версии sys.executable — это сам LocalTube.exe, поэтому такой вызов
# запускал бы второе приложение (второй сервер на том же порту), а не скрипт:
# скриптов рядом с exe нет вовсе.

@app.route('/api/avatars/download_all', methods=['POST'])
def api_download_all_avatars():
    def run_task():
        try:
            import download_avatars
            download_avatars.main([])
        except Exception as e:
            logger.error(f"Загрузка аватарок не завершилась: {e}")
    threading.Thread(target=run_task, daemon=True).start()
    return jsonify({'status': 'started'})

@app.route('/api/thumbnails/generate', methods=['POST'])
def api_generate_thumbnails():
    force = (request.get_json(silent=True) or {}).get('force', False)
    def run_task():
        try:
            import download_thumbnails
            download_thumbnails.main(['--force'] if force else [])
        except Exception as e:
            logger.error(f"Генерация превью не завершилась: {e}")
    threading.Thread(target=run_task, daemon=True).start()
    return jsonify({'status': 'started'})

# Темы, у которых есть свои обои. Список закрытый: имя темы попадало прямо в
# os.path.join, и хотя конвертер <theme> не пропускает '/', абсолютный путь
# ('C:\\Windows') или '..' в другой форме листали бы чужой каталог.
THEMES_WITH_BACKGROUNDS = ('frutiger-aero',)
BACKGROUND_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')


@app.route('/api/theme-backgrounds/<theme>')
def api_theme_backgrounds(theme):
    if theme not in THEMES_WITH_BACKGROUNDS:
        return jsonify([])
    theme_dir = os.path.join(SCRIPT_DIR, 'static', 'images', 'themes', theme)
    try:
        # Сортировка обязательна: os.listdir отдаёт порядок файловой системы, и
        # разные страницы получали список в разном порядке, поэтому переход
        # между страницами менял обои даже при неизменном наборе файлов.
        images = sorted(f for f in os.listdir(theme_dir)
                        if f.lower().endswith(BACKGROUND_EXTENSIONS))
    except OSError:
        # Папки может не быть (обои не скачаны) — это не ошибка, просто нет обоев.
        return jsonify([])
    return jsonify(images)


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
        "is_short": v["is_short"], "size_mb": v["size_mb"], "duration": v.get("duration", 0), "upload_date": v.get("upload_date", ""), "source": v.get("source", "youtube"),
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


def hidden_for_request():
    """Скрытые каналы с учётом того, кто спрашивает.

    include_hidden=1 нужен странице настроек владельца, чтобы показать сами
    скрытые каналы. Для гостя этот параметр игнорируется: иначе он был бы
    готовой лазейкой — достаточно дописать его к адресу.
    """
    if request_is_owner() and request.args.get('include_hidden') == '1':
        return set()
    return hidden_channels_set()


def guest_hidden_authors():
    """Каналы, недоступные текущему клиенту целиком.

    Для владельца — пустое множество: скрытие он включил сам и должен иметь
    доступ к своим видео. Для гостя скрытый канал пропадает полностью: и
    страница канала, и страница видео, и файлы на диске.
    """
    if request_is_owner():
        return set()
    return hidden_channels_set()


def hidden_from_guest(author):
    return bool(author) and author in guest_hidden_authors()


@app.route('/api/catalog')
def api_catalog():
    ensure_video_map()
    build_user_video_map()
    build_playlist_map()

    hidden = hidden_for_request()

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
    elif vid_id in VIDEO_MAP and not hidden_from_guest(VIDEO_MAP[vid_id]["author"]):
        v = VIDEO_MAP[vid_id]
        folder_path = os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"])
        video_url = f"/media/{quote(v['author'])}/{quote(v['folder'])}/{quote(v['filename'])}"
        author_avatar = get_avatar_url(v["author"])
        is_short = v["is_short"]
        source = v.get("source", "youtube")
        thumb_file = find_file(folder_path, ['.jpg', '.png', '.webp'])
        if thumb_file:
            thumb = f"/media/{quote(v['author'])}/{quote(v['folder'])}/{quote(thumb_file)}"
        meta = read_video_info(folder_path)
        if not meta:
            meta = {"title": v["title"], "uploader": v["author"], "id": vid_id}

    if not video_url:
        return jsonify({"error": "Not found"}), 404

    mime_type = "video/mp4"
    if video_url.endswith('.webm'): mime_type = "video/webm"
    elif video_url.endswith('.mkv'): mime_type = "video/x-matroska"

    # Размер берём по реальному пути на диске, а не по URL. Раньше здесь было
    # os.path.join(SCRIPT_DIR, video_url), то есть каталог проекта + «/media/…»:
    # такого пути не существует, плюс имена в URL percent-кодированы. Проверка
    # os.path.exists всегда была ложной, и размер файла всегда показывался 0.
    file_size_mb = 0
    if vid_id in USER_VIDEO_MAP:
        media_path = USER_VIDEO_MAP[vid_id]["video_path"]
    else:
        v = VIDEO_MAP[vid_id]
        media_path = os.path.join(BASE_VIDEO_DIR, v["author"], v["folder"], v["filename"])
    try:
        file_size_mb = round(os.path.getsize(media_path) / (1024 * 1024), 1)
    except OSError:
        # Файл могли удалить или переименовать между сканированием и запросом.
        pass

    recommended = []
    hidden = guest_hidden_authors()
    all_combined = [v for v in VIDEO_MAP.values() if v["author"] not in hidden]
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
    desired = (request.get_json(silent=True) or {}).get('active')
    try:
        active, items = userdata.toggle_favorite(vid_id, desired)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok', 'active': active, 'favorites': items})


@app.route('/api/userdata/hidden-channel', methods=['POST'])
def api_userdata_hidden_channel():
    payload = request.get_json(silent=True) or {}
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
        added, state = userdata.merge_from_client(request.get_json(silent=True) or {})
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok', 'added': added, **state})


# ================= СВОИ ПЛЕЙЛИСТЫ =================
# Это не плейлисты, скачанные с YouTube (те лежат папками в playlists/), а
# коллекции, которые пользователь собирает сам из уже скачанных видео.

def collection_playback_order(collection_id):
    """Порядок видео в плейлисте для последовательного просмотра.

    Нужен странице видео: она открывается с ?collection=<id>, и после конца
    ролика надо знать, что играть дальше. Неизвестный плейлист и отсутствующий
    параметр дают пустой список — обычный просмотр не меняется.
    """
    # Пустой id и неизвестный плейлист get_collection одинаково отдаёт как None,
    # поэтому отдельная проверка на пустое значение здесь не нужна.
    item = userdata.get_collection(collection_id)
    if not item:
        return []
    return list(item['videos'])


def _collection_summary(item):
    """Запись для списка: сайдбару нужно число видео, а не все идентификаторы."""
    return {
        'id': item['id'],
        'title': item['title'],
        'count': len(item['videos']),
        'videos': item['videos'],
        'built_in': item['id'] == userdata.WATCH_LATER_ID,
    }


@app.route('/api/collections', methods=['GET'])
def api_collections_list():
    data = userdata.get_all()
    return jsonify({'collections': [_collection_summary(c) for c in data['collections']]})


@app.route('/api/collections', methods=['POST'])
def api_collections_create():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'Нет данных.'}), 400
    try:
        item = userdata.create_collection(payload.get('title'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok', 'collection': _collection_summary(item)})


@app.route('/api/collections/<collection_id>', methods=['PATCH'])
def api_collections_rename(collection_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'Нет данных.'}), 400
    try:
        item = userdata.rename_collection(collection_id, payload.get('title'))
    except KeyError:
        return jsonify({'error': 'Плейлист не найден.'}), 404
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok', 'collection': _collection_summary(item)})


@app.route('/api/collections/<collection_id>', methods=['DELETE'])
def api_collections_delete(collection_id):
    try:
        userdata.delete_collection(collection_id)
    except KeyError:
        return jsonify({'error': 'Плейлист не найден.'}), 404
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok'})


def _resolve_collection_id(collection_id):
    """Подставляет встроенный список, создавая его при первом обращении.

    Кнопка «Смотреть позже» на странице видео иначе требовала бы, чтобы
    пользователь заранее создал список руками.
    """
    if collection_id == userdata.WATCH_LATER_ID:
        userdata.watch_later()
    return collection_id


@app.route('/api/collections/<collection_id>/videos', methods=['POST'])
def api_collections_add_video(collection_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'Нет данных.'}), 400
    try:
        item = userdata.add_to_collection(_resolve_collection_id(collection_id),
                                          payload.get('video_id'))
    except KeyError:
        return jsonify({'error': 'Плейлист не найден.'}), 404
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok', 'collection': _collection_summary(item)})


@app.route('/api/collections/<collection_id>/videos/<vid_id>', methods=['DELETE'])
def api_collections_remove_video(collection_id, vid_id):
    try:
        item = userdata.remove_from_collection(collection_id, vid_id)
    except KeyError:
        return jsonify({'error': 'Плейлист не найден.'}), 404
    except userdata.UserDataSaveError as e:
        return jsonify({'error': f'Не удалось сохранить: {e}'}), 500
    return jsonify({'status': 'ok', 'collection': _collection_summary(item)})


@app.route('/collection/<collection_id>')
def collection_page(collection_id):
    """Страница своего плейлиста."""
    item = userdata.get_collection(collection_id)
    if item is None:
        abort(404)

    if not VIDEO_MAP:
        build_video_map()
    if not USER_VIDEO_MAP:
        build_user_video_map()

    videos = []
    for vid in item['videos']:
        entry = VIDEO_MAP.get(vid) or USER_VIDEO_MAP.get(vid)
        # Видео могли удалить с диска: пропускаем, но плейлист не ломаем.
        if not entry:
            continue
        # Превью отдаёт /api/thumbnail/<id>: у него есть готовый фолбэк на
        # заглушку, поэтому собирать путь к файлу тут не нужно.
        videos.append({
            'id': vid,
            'title': entry.get('title', 'Без названия'),
            'author': entry.get('author', 'Unknown'),
            'size_mb': entry.get('size_mb', 0),
            'source': entry.get('source', 'youtube'),
            'folder': entry.get('folder'),
            'author_avatar': get_avatar_url(entry.get('author', '')),
        })

    missing = len(item['videos']) - len(videos)
    return render_template('collection.html', collection=item, videos=videos,
                           missing=missing, built_in_id=userdata.WATCH_LATER_ID)


@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').lower().strip()
    if not q:
        return jsonify({"results": []})
    ensure_video_map()
    build_user_video_map()

    hidden = hidden_for_request()

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


# ================= ЛОКАЛЬНАЯ СЕТЬ =================
# Свой сервер: адреса для гостей, QR, PIN, тумблер доступа.
# Чужие серверы: сохранённый список, проверка связи и поиск в своей подсети.

SERVER_PORT = access.DEFAULT_PORT

def set_server_port(port):
    """Меняет порт сервера и возвращает новое значение.

    Нужен тестам и настройкам: SERVER_PORT вынесен в отдельную функцию,
    чтобы QR-код и адреса в ответах API сразу менялись при смене порта.
    """
    global SERVER_PORT
    SERVER_PORT = int(port)
    return SERVER_PORT


@app.route('/api/network/ping')
def api_network_ping():
    """Отклик для автопоиска: «здесь LocalTube».

    Открыт гостям намеренно, иначе чужое устройство не смогло бы найти сервер.
    Поэтому в ответе только вывеска и число видео: ни PIN, ни путей, ни личных
    данных.
    """
    ensure_video_map()
    hidden = guest_hidden_authors()
    count = sum(1 for v in VIDEO_MAP.values() if v["author"] not in hidden)
    return jsonify({
        'app': 'LocalTube',
        'title': socket.gethostname(),
        'videos': count,
        'guest_allowed': access.is_network_enabled(),
    })


@app.route('/api/network/info')
def api_network_info():
    """Всё для раздела «Сеть»: адреса, PIN, состояние тумблера."""
    return jsonify({
        'port': SERVER_PORT,
        'addresses': access.local_addresses(SERVER_PORT),
        'pin': access.get_pin(),
        'enabled': access.is_network_enabled(),
        'servers': access.saved_servers(),
        'hidden_channels': sorted(hidden_channels_set()),
    })


@app.route('/api/network/qr')
def api_network_qr():
    """QR с адресом сервера: гостю проще навести камеру, чем набирать цифры."""
    url = request.args.get('url') or ''
    if not url:
        addresses = access.local_addresses(SERVER_PORT)
        url = addresses[0]['url'] if addresses else f'http://127.0.0.1:{SERVER_PORT}'
    if not access.normalize_server_url(url):
        return jsonify({'error': 'Непонятный адрес.'}), 400
    try:
        png = access.make_qr_png(url)
    except Exception as e:
        logger.error(f"Не удалось нарисовать QR: {e}")
        return jsonify({'error': 'Не удалось нарисовать QR-код.'}), 500
    response = app.response_class(png, mimetype='image/png')
    # Адрес меняется при смене сети, поэтому кэшируем ненадолго.
    response.headers['Cache-Control'] = 'private, max-age=60'
    return response


@app.route('/api/network/enabled', methods=['POST'])
def api_network_enabled():
    data = request.get_json(silent=True) or {}
    value = data.get('enabled')
    if not isinstance(value, bool):
        return jsonify({'error': 'Нужно поле enabled: true или false.'}), 400
    return jsonify({'enabled': access.set_network_enabled(value)})


@app.route('/api/network/pin/regenerate', methods=['POST'])
def api_network_pin_regenerate():
    """Новый PIN. Ранее впущенные устройства отключаются."""
    return jsonify({'pin': access.regenerate_pin()})


@app.route('/api/network/unlock', methods=['POST'])
def api_network_unlock():
    """Повышает устройство до владельца по PIN.

    Ключ уходит в cookie: права нужны и обычным страницам (настройки, загрузка),
    а не только запросам из JS.
    """
    data = request.get_json(silent=True) or {}
    # Окно попыток закрыто — говорим об этом прямо, иначе владелец, опечатавшийся
    # десять раз, видел бы «Неверный PIN» на верный PIN и не понимал причины.
    wait = access.pin_locked_for(request.remote_addr)
    if wait:
        logger.warning(f"Перебор PIN с адреса {request.remote_addr}: попытки исчерпаны")
        return jsonify({'error': f'Слишком много попыток. Подождите {wait} с.',
                        'retry_after': wait}), 429
    token = access.token_for_pin(str(data.get('pin') or ''), request.remote_addr)
    if not token:
        left = access.attempts_left(request.remote_addr)
        logger.warning(f"Неверный PIN с адреса {request.remote_addr}, осталось попыток: {left}")
        return jsonify({'error': 'Неверный PIN.', 'attempts_left': left}), 403
    response = jsonify({'ok': True})
    response.set_cookie(access.TOKEN_COOKIE, token, max_age=90 * 24 * 3600,
                        httponly=True, samesite='Lax')
    return response


@app.route('/api/network/lock', methods=['POST'])
def api_network_lock():
    """Возвращает устройству права гостя."""
    response = jsonify({'ok': True})
    response.delete_cookie(access.TOKEN_COOKIE)
    return response


@app.route('/api/network/servers', methods=['GET'])
def api_network_servers_list():
    return jsonify({'servers': access.saved_servers()})


@app.route('/api/network/servers', methods=['POST'])
def api_network_servers_add():
    data = request.get_json(silent=True) or {}
    try:
        item = access.add_server(data.get('url'), data.get('title'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'server': item, 'servers': access.saved_servers()})


@app.route('/api/network/servers', methods=['DELETE'])
def api_network_servers_remove():
    data = request.get_json(silent=True) or {}
    try:
        removed = access.remove_server(data.get('url'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'removed': removed, 'servers': access.saved_servers()})


@app.route('/api/network/check', methods=['POST'])
def api_network_check():
    """Проверка связи с чужим сервером."""
    data = request.get_json(silent=True) or {}
    url = data.get('url')
    if not access.normalize_server_url(url):
        return jsonify({'error': 'Непонятный адрес сервера.'}), 400
    # Недоступный сервер — обычный ответ, а не ошибка: интерфейсу нужно
    # показать «не отвечает», а не пятисотку.
    return jsonify(access.probe_server(url))


@app.route('/api/network/scan', methods=['POST'])
def api_network_scan():
    """Ищет другие LocalTube в своей подсети."""
    try:
        found = access.scan_network(SERVER_PORT)
    except Exception as e:
        logger.error(f"Поиск в сети не удался: {e}")
        return jsonify({'error': 'Не удалось просмотреть сеть.'}), 500
    return jsonify({'servers': found})


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