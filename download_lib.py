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
import paths
from utils import (safe_name, is_shorts_video, cookiefile_for_ydl,
                   apply_cookie_updates, is_tiktok_url)
from logger import logger
from po_manager import get_po_args, apply_po_args
from download_prefs import (get_prefs as get_download_prefs, audio_format_selector,
                            apply_subtitle_opts)

try:
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled
except ImportError:
    logger.error("Ошибка: установите yt-dlp: pip install yt-dlp")
    sys.exit(1)

def load_config():
    default = {"video_dir": "videos"}
    config_file = paths.data_path("config.json")
    if os.path.exists(config_file):
        # Конкретные исключения вместо except: — голый except перехватывал и
        # KeyboardInterrupt с SystemExit, из-за чего Ctrl+C во время чтения
        # конфига молча игнорировался. Битый конфиг по-прежнему не должен ронять
        # загрузку, поэтому остаёмся на значениях по умолчанию, но с записью в лог.
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                if "video_dir" in cfg:
                    default["video_dir"] = cfg["video_dir"]
        except (OSError, ValueError) as e:
            logger.warning(f"load_config: не удалось прочитать {config_file}: {e}")
    return default

download_locks = {}
locks_mutex = threading.Lock()

def get_video_id(url):
    # TikTok использует 19-значный id; прежняя YouTube-регулярка брала от URL
    # хеш, поэтому повтор TikTok-видео попадал в другую папку и скачивался снова.
    match = re.search(r'/video/(\d+)(?:[/?#]|$)', url)
    if match:
        return match.group(1)
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})(?:[&?]|$)', url)
    return match.group(1) if match else hashlib.md5(url.encode()).hexdigest()[:11]

def get_output_path(base_dir, author, video_id, title):
    safe_author = safe_name(author)[:50]
    folder_name = video_id
    return os.path.join(base_dir, safe_author, folder_name)

COOKIES_PATH = paths.data_path("cookies.txt")

def get_ydl_opts(format_id, merge_format, progress_hook, temp_dir, url=None):
    os.makedirs(temp_dir, exist_ok=True)
    
    if format_id and '+' not in format_id and format_id.isdigit():
        actual_format = f"{format_id}+bestaudio/best"
    else:
        actual_format = format_id or 'bestvideo+bestaudio/best'

    # У TikTok видео и звук идут одним потоком, а id формата YouTube там не
    # существует: чужой селектор давал «Requested format is not available».
    # Выбор «Только звук» сохраняем: он работает и на едином потоке.
    if is_tiktok_url(url):
        actual_format = 'bestaudio/best' if 'bestaudio' == (format_id or '').split('/')[0] else 'best'

    # PO Token и player_client понимает только YouTube-экстрактор.
    po_args = {} if is_tiktok_url(url) else get_po_args()

    # Настройки читаем прямо здесь: сюда сходятся все загрузки, а протаскивать
    # языки через очередь (QueueTask, queue.json) значило бы, что задача,
    # добавленная до смены настроек, скачается по старым.
    prefs = get_download_prefs()
    actual_format = audio_format_selector(actual_format, prefs.get('audio_langs'))

    opts = {
        'format': actual_format,
        'outtmpl': os.path.join(temp_dir, 'video.%(ext)s'),
        'merge_output_format': merge_format or 'mp4',
        'writethumbnail': True,
        'writeinfojson': True,
        'quiet': False,
        'no_warnings': True,
        'ignoreerrors': True, # БАГФИКС: Защита от краша при загрузке
        # Ссылка вида watch?v=ID&list=PL... достаётся не видео-экстрактору, а
        # табличному, и без noplaylist качался весь плейлист: все видео писались
        # в один outtmpl внутри папки Unknown/<id плейлиста>, перезаписывая друг
        # друга. Очередь при этом показывала «1 из 1».
        'noplaylist': True,
        'socket_timeout': 30,
        'retries': 5,
        # Поток, а не путь: иначе yt-dlp перезапишет cookies.txt при close().
        'cookiefile': cookiefile_for_ydl(COOKIES_PATH),
        'progress_hooks': [progress_hook],
    }

    # Без ffmpeg_location postprocessor ищет ffmpeg только в PATH. В собранной
    # версии ffmpeg лежит внутри пакета, поэтому склейка видео с аудио падала
    # уже после скачивания: файлы есть, а результата нет.
    ffmpeg_dir = paths.ffmpeg_dir()
    if ffmpeg_dir:
        opts['ffmpeg_location'] = ffmpeg_dir

    if po_args:
        apply_po_args(opts, po_args)

    # Субтитры просим у yt-dlp вместе с видео: отдельный запрос к YouTube ради
    # тех же файлов — второй проход по сети и второй шанс получить отказ.
    apply_subtitle_opts(opts, prefs)

    return opts


# Имена файлов субтитров, которые оставляет yt-dlp: video.ru.vtt, video.pt-BR.vtt.
SUBTITLE_FILE_RE = re.compile(r'^video\.([A-Za-z0-9][A-Za-z0-9-]*)\.(vtt|srt)$')


def save_subtitles(temp_dir, video_id):
    """Переносит скачанные субтитры в папку субтитров. Возвращает их число.

    yt-dlp кладёт их рядом с видео во временный каталог, а тот удаляется в
    finally: без переноса файлы пропадали, и плеер их не находил — он читает
    subtitles/<источник>/<id>/<язык>.<vtt|srt>.
    """
    if not video_id:
        # Складывать некуда, но падать нельзя: видео уже скачано.
        return 0
    # Импорт внутри функции: subtitles.py читает config.json на каждый вызов, и
    # тесты подменяют его каталог через модуль.
    import subtitles as subtitles_module

    saved = 0
    try:
        names = sorted(os.listdir(temp_dir))
    except OSError as e:
        logger.warning(f"Не удалось прочитать временный каталог субтитров: {e}")
        return 0

    for name in names:
        match = SUBTITLE_FILE_RE.match(name)
        if not match:
            continue
        lang, ext = match.group(1), match.group(2)
        try:
            folder = subtitles_module.get_video_subtitle_folder(video_id, 'youtube')
            dst = os.path.join(folder, f"{lang}.{ext}")
            os.replace(os.path.join(temp_dir, name), dst)
            saved += 1
        except OSError as e:
            # Субтитры — не главный результат: видео уже на диске, поэтому
            # неудача переноса не должна отменять загрузку.
            logger.warning(f"Не удалось сохранить субтитры {name}: {e}")
    return saved


class DownloadCancelledByUser(Exception):
    """Пользователь отменил загрузку через очередь."""
    pass


# yt-dlp раскрашивает строки прогресса, если stdout — консоль. Свой хук
# вызывается уже после его собственного, поэтому в _percent_str приходит
# значение вида '\x1b[0;94m 45.3%\x1b[0m'.
ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

# Остатки отдельных потоков от yt-dlp: video.f401.mp4, video.f251.webm.
# Такой файл не является готовым видео, его нельзя принимать за результат.
FORMAT_FRAGMENT_RE = re.compile(r'\.f\d+\.[A-Za-z0-9]+$')

# Контейнеры готового результата. Аудио здесь тоже нужно: при выборе
# «Только звук» yt-dlp сохраняет одиночный поток в родном расширении
# (обычно .m4a), merge_output_format к нему не применяется. Раньше такой
# файл не считался результатом, и загрузка звука всегда падала с
# «Ошибка скачивания», хотя файл был скачан.
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.webm', '.avi', '.mov')
AUDIO_EXTENSIONS = ('.m4a', '.opus', '.mp3', '.ogg', '.aac', '.flac', '.wav')
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS + AUDIO_EXTENSIONS

# Сколько раз перезапускать загрузку видео целиком при обрыве потока.
STREAM_RETRIES = 3
# Базовая пауза между попытками (секунды), растёт линейно: 5, 10, ...
STREAM_RETRY_DELAY = 5

# Сколько видео подряд должны упасть по сети, чтобы признать её недоступной и
# остановить задачу. Иначе при лежащем интернете (или выключенном VPN) очередь
# перебирала бы все 79 ссылок по три попытки с паузами — это часы работы
# впустую, причём задача всё равно завершилась бы почти полным провалом.
NETWORK_FAILURE_STREAK = 3

# Признаки временного сбоя: сеть, прокси, троттлинг YouTube. Такие ошибки
# лечатся повтором, а «Video unavailable» — нет.
TRANSIENT_ERROR_MARKERS = (
    'unexpected_eof', 'eof occurred', 'ssl', 'timed out', 'timeout',
    'connection reset', 'connectionreset', '10054', '10053', '10060',
    'connection aborted', 'connection refused', 'remote end closed',
    'getaddrinfo', 'temporary failure in name resolution', 'unable to download api page',
    'http error 403', 'http error 429', 'http error 500', 'http error 502',
    'http error 503', 'http error 504', 'network is unreachable',
    'incomplete read', 'content too short', 'broken pipe',
    'the read operation timed out', 'unable to connect to proxy',
)

# Эти отказы окончательные: повтор только тратит время.
PERMANENT_ERROR_MARKERS = (
    'video unavailable', 'private video', 'members-only', 'members only',
    'this channel does not have', 'requested format is not available',
    'is not a valid url', 'unsupported url', 'has been removed',
    'account associated with this video has been terminated',
    'sign in to confirm your age', 'video is not available in your country',
    'this live event has ended', 'premieres in',
)


# Storyboard-форматы (раскадровка для полосы прокрутки) — не видео и не звук.
# Когда решатель JS-челленджа не сработал, yt-dlp выбрасывает все https-форматы
# и в info остаются только они, а сообщение об ошибке приходит невнятное:
# «Requested format is not available».
STORYBOARD_PROTOCOLS = ('mhtml',)

# Текст для этого случая: пользователю нужно знать, что дело не в его выборе
# качества, а в несработавшем решателе JS-челленджа yt-dlp.
NO_MEDIA_FORMATS_REASON = (
    'YouTube не отдал ни одного формата видео или звука '
    '(не сработал решатель JS-челленджа yt-dlp)')


def has_media_formats(formats):
    """Есть ли в списке хотя бы один скачиваемый поток видео или звука.

    Неизвестные кодеки (None) считаем пригодными: так yt-dlp помечает форматы,
    про которые просто нет данных, и отвергать их — значит ломать загрузку с
    сайтов, где кодек не определяется. Пустую строку 'none' он ставит осознанно.
    """
    for f in formats or []:
        if not isinstance(f, dict):
            continue
        # Раскадровка бывает и без пометок о кодеках, поэтому смотрим протокол.
        if f.get('protocol') in STORYBOARD_PROTOCOLS:
            continue
        if not f.get('url') and not f.get('fragments') and not f.get('manifest_url'):
            continue
        if f.get('vcodec') == 'none' and f.get('acodec') == 'none':
            continue
        return True
    return False


# Отказы, которые лечатся свежими cookies. Проверено замером: возрастное видео
# не отдаёт форматы ни одному клиенту YouTube без cookies (tv, tv_embedded,
# web_embedded, mweb, web_safari, android_vr, ios, web, tv_simply), поэтому
# подменой клиента такой отказ обойти нельзя. Зато сразу после экспорта из
# браузера то же видео отдаёт 27 форматов: YouTube периодически обновляет
# короткоживущие токены сессии, и файл перестаёт подтверждать вход.
AUTH_ERROR_MARKERS = (
    'sign in to confirm your age',
    "sign in to confirm you're not a bot",
    'sign in to confirm youre not a bot',
    'this video may be inappropriate for some users',
    'account cookies are no longer valid',
    'please sign in',
)


# Совет вместо сырого текста yt-dlp: ссылка на --cookies-from-browser
# пользователю интерфейса ничего не даёт, а обновить cookies он может кнопкой.
AUTH_ERROR_HINT = ('YouTube требует подтверждения входа, а cookies устарели. '
                   'Откройте настройки и нажмите «Экспортировать из браузера» '
                   '(для Chrome и Edge браузер нужно полностью закрыть).')


def is_auth_error(text):
    """Похож ли отказ на устаревшие cookies.

    Такие отказы не лечатся повтором запроса, но лечатся свежим экспортом из
    браузера, поэтому обрабатываются отдельно от временных сбоев.
    """
    low = strip_ansi(text or '').lower()
    if not low.strip():
        return False
    return any(marker in low for marker in AUTH_ERROR_MARKERS)


def explain_reason(text):
    """Заменяет отказ авторизации понятным советом.

    Остальные ошибки оставляем как есть: они уже осмысленные.
    """
    if is_auth_error(text):
        return AUTH_ERROR_HINT
    return text


def refresh_cookies_from_browser():
    """Обновляет cookies из браузера. Возвращает True, если получилось.

    Перебирает установленные браузеры: на Windows Chrome и Edge шифруют базу
    средствами системы и читаются только при полностью закрытом браузере,
    поэтому один отказ — не повод сдаваться. Ошибки не поднимаются наружу:
    неудачное обновление не должно ронять загрузку.
    """
    import auth_options

    try:
        browsers = [b['name'] for b in auth_options.available_browsers()
                    if b.get('installed')]
    except Exception as exc:                     # noqa: BLE001 - диагностика
        logger.warning(f'Не удалось получить список браузеров: {exc}')
        browsers = [None]
    if not browsers:
        browsers = [None]

    for name in browsers:
        try:
            result = auth_options.import_cookies_from_browser(name)
        except Exception as exc:                 # noqa: BLE001 - диагностика
            logger.warning(f'Обновление cookies из {name or "браузера"} '
                           f'не удалось: {exc}')
            continue
        if isinstance(result, dict) and result.get('status') == 'ok':
            logger.info(f'cookies обновлены из {result.get("browser") or name}: '
                        f'{result.get("count")} записей')
            return True
        reason = (result or {}).get('error') if isinstance(result, dict) else result
        logger.warning(f'Обновление cookies из {name or "браузера"} '
                       f'не удалось: {reason}')
    return False


def is_transient_error(text):
    """Похожа ли ошибка на временный сбой, который стоит повторить.

    Нужно, чтобы обрыв сети не отправлял видео сразу в отказ: при потере
    соединения очередь теряла десятки видео за один прогон, хотя достаточно
    было повторить попытку.
    """
    low = strip_ansi(text).lower()
    if not low.strip():
        return False
    # Окончательный отказ проверяем первым: в тексте могут быть оба признака.
    if any(marker in low for marker in PERMANENT_ERROR_MARKERS):
        return False
    return any(marker in low for marker in TRANSIENT_ERROR_MARKERS)

# Предел на один вызов ffmpeg (секунды). yt-dlp вызывает Popen.run без timeout,
# поэтому зависший ffmpeg блокировал единственный поток очереди навсегда:
# кооперативная отмена читается только из хуков прогресса, а на этапе склейки
# их уже нет. Ни «Отменить», ни «Удалить» в интерфейсе воркер не освобождали.
FFMPEG_TIMEOUT = 1800


def install_ffmpeg_timeout(timeout=None):
    """Ограничивает время работы ffmpeg, вызываемого yt-dlp.

    Патчим Popen.run в модуле постпроцессора: у него уже есть параметр timeout,
    yt-dlp просто его не передаёт. По истечении срока communicate_or_kill
    убивает процесс и поднимает исключение, поэтому загрузка завершается
    ошибкой вместо вечного зависания.
    """
    from yt_dlp.postprocessor import ffmpeg as ffmpeg_pp

    limit = FFMPEG_TIMEOUT if timeout is None else timeout
    # Берём незапатченный класс, иначе повторная установка наращивала цепочку
    # наследования на каждый вызов.
    base = getattr(ffmpeg_pp.Popen, '_localtube_base', ffmpeg_pp.Popen)
    original = base.run

    class _TimedPopen(base):
        _localtube_base = base

        @classmethod
        def run(cls, *args, timeout=None, **kwargs):
            # Свой timeout уважаем: yt-dlp сам задаёт его для check_version.
            return original(*args, timeout=limit if timeout is None else timeout, **kwargs)

    ffmpeg_pp.Popen = _TimedPopen
    return _TimedPopen


SHORTS_SUFFIX = ' #shorts'


def find_downloaded_media(output_dir):
    """Возвращает путь к уже скачанному медиафайлу видео или None.

    Проверяются оба варианта имени каталога: обычный «<id>» и «<id> #shorts».
    Признак Shorts зависит от метаданных и может отличаться между загрузками,
    поэтому поиск только по одному имени создавал вторую папку для того же
    видео — и одна из них пропадала из библиотеки (ключ VIDEO_MAP общий).
    """
    if not output_dir:
        return None
    base = output_dir[:-len(SHORTS_SUFFIX)] if output_dir.endswith(SHORTS_SUFFIX) else output_dir
    for candidate in (output_dir, base, base + SHORTS_SUFFIX):
        if not os.path.isdir(candidate):
            continue
        try:
            names = sorted(os.listdir(candidate))
        except OSError:
            continue
        for name in names:
            if not name.startswith('video.'):
                continue
            if not name.endswith(MEDIA_EXTENSIONS) or FORMAT_FRAGMENT_RE.search(name):
                continue
            path = os.path.join(candidate, name)
            # Пустышка от прерванной загрузки не считается результатом.
            try:
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    return path
            except OSError:
                continue
    return None


def _short_reason(text, limit=90):
    """Укорачивает текст ошибки yt-dlp для строки прогресса."""
    text = ' '.join(strip_ansi(text).split())
    # Префикс вида «[youtube] dQw4w9WgXcQ:» пользователю ничего не говорит.
    text = re.sub(r'^\[[^\]]+\]\s*', '', text)
    text = re.sub(r'^[0-9A-Za-z_-]{11}:\s*', '', text)
    return text[:limit].rstrip() + '…' if len(text) > limit else text


def _sleep_cancellable(seconds, should_cancel=None):
    """Пауза, прерываемая отменой: длинный sleep игнорировал бы стоп от пользователя."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if should_cancel and should_cancel():
            raise DownloadCancelledByUser('Загрузка отменена пользователем')
        time.sleep(0.2)


def strip_ansi(text):
    return ANSI_ESCAPE_RE.sub('', str(text or ''))


def _percent_from_hook(d):
    """Процент из хука yt-dlp.

    Считаем из байтов, а строку используем только как резерв: строковое поле
    приходит с ANSI-кодами, из-за которых float() падал и прогресс навсегда
    оставался нулевым.
    """
    downloaded = d.get('downloaded_bytes')
    total = d.get('total_bytes') or d.get('total_bytes_estimate')
    if downloaded is not None and total:
        try:
            return max(0.0, min(100.0, downloaded * 100.0 / total))
        except (TypeError, ZeroDivisionError):
            pass
    try:
        return float(strip_ansi(d.get('_percent_str', '0%')).replace('%', '').strip())
    except (TypeError, ValueError):
        return 0


class _ErrorCollector:
    """Логгер для yt-dlp, запоминающий текст ошибок.

    При ignoreerrors=True yt-dlp не бросает исключение, а пишет причину в
    stderr и продолжает. Без такого перехвата настоящая причина (403,
    недоступный формат, гео-блокировка) пропадала, а пользователь видел
    только «Ошибка скачивания».
    """

    # Технический шум, который не объясняет пользователю причину отказа.
    _NOISE = ('you have requested merging', 'ffmpeg is not installed')

    def __init__(self):
        self.errors = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        text = strip_ansi(msg).strip()
        if text.upper().startswith('ERROR:'):
            text = text[6:].strip()
        low = text.lower()
        if text and not any(noise in low for noise in self._NOISE):
            self.errors.append(text)

    def last_error(self):
        return self.errors[-1] if self.errors else ''


def download_single_video_impl(url, format_id, output_dir, progress_dict, progress_callback, merge_format,
                               should_cancel=None, error_sink=None):
    with locks_mutex:
        if download_locks.get(url):
            # Раньше здесь возвращался True, и задача очереди отчитывалась
            # «Готово», ничего не скачав: файл появлялся (или не появлялся)
            # благодаря чужой загрузке. Отказ честнее — вызывающий код
            # повторит попытку, когда лок освободится.
            logger.info(f"Видео {url} уже скачивается другим потоком.")
            if progress_dict is not None:
                progress_dict['status'] = 'busy'
                progress_dict['message'] = 'Это видео уже скачивается'
            return False
        download_locks[url] = True

    # temp_dir вычисляется до try: раньше он присваивался внутри, и падение на
    # этой строке приводило к UnboundLocalError уже из finally — исходная ошибка
    # подменялась, а ключ лока оставался навсегда, блокируя URL до перезапуска.
    temp_dir = None
    try:
        temp_dir = os.path.join(output_dir, "_tmp_" + hashlib.md5(str(url).encode()).hexdigest()[:6])
        last_callback_time = 0

        def internal_hook(d):
            nonlocal last_callback_time
            # DownloadCancelled — единственное исключение, которое yt-dlp не глотает
            # при ignoreerrors, поэтому отмену пробрасываем именно им.
            if should_cancel and should_cancel():
                raise DownloadCancelled('Загрузка отменена пользователем')
            if d['status'] == 'downloading':
                percent = _percent_from_hook(d)
                
                # Пустой словарь тоже надо заполнять, поэтому сравнение с None,
                # а не проверка на истинность.
                if progress_dict is not None:
                    progress_dict['percent'] = percent
                
                now = time.time()
                if now - last_callback_time > 1.0 or percent >= 100:
                    if progress_callback:
                        # strip_ansi обязателен: иначе escape-последовательности
                        # уезжали в интерфейс через speed и eta задачи.
                        speed = strip_ansi(d.get('_speed_str')).strip() or 'скорость неизвестна'
                        eta = strip_ansi(d.get('_eta_str')).strip() or 'ETA неизвестно'
                        progress_callback(percent, f"Загрузка: {percent:.1f}% · {speed} · ETA {eta}")
                    last_callback_time = now
            
            elif d['status'] == 'finished':
                if progress_callback:
                    progress_callback(100, "Склеивание и обработка...")

        if should_cancel and should_cancel():
            raise DownloadCancelledByUser('Загрузка отменена пользователем')

        opts = get_ydl_opts(format_id, merge_format, internal_hook, temp_dir, url)
        # Логгер перехватывает текст ошибки, который yt-dlp при ignoreerrors
        # просто печатает в stderr, не поднимая исключение.
        collector = _ErrorCollector()
        opts['logger'] = collector

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # YouTube обновляет короткоживущие токены при каждом запросе:
            # без сохранения авторизация протухает за считаные часы.
            apply_cookie_updates(opts)

        # Отказ авторизации бывает и на самой загрузке, а не только на
        # метаданных: обновляем cookies и пробуем ещё раз.
        if not info and is_auth_error(collector.last_error()):
            if refresh_cookies_from_browser():
                opts['cookiefile'] = cookiefile_for_ydl(COOKIES_PATH)
                collector = _ErrorCollector()
                opts['logger'] = collector
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    apply_cookie_updates(opts)

        # БАГФИКС: Проверка на None, если видео удалено
        if not info:
            reason = collector.last_error() or 'видео недоступно'
            logger.warning(f"Загрузка не выполнена ({url}): {reason}")
            if error_sink is not None:
                # Отказ авторизации заменяем советом: сырой текст yt-dlp
                # предлагает ключ командной строки, которого у пользователя нет.
                error_sink.append(explain_reason(reason))
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

        def _place(src_path, dst_path):
            """Переносит файл из временной папки на место назначения.

            os.replace перезаписывает существующий файл одним неделимым
            действием. Прежняя схема (os.remove, затем shutil.move) оставляла
            окно, в котором старого файла уже нет, а нового ещё нет: сбой между
            ними терял, например, info.json при повторной загрузке.
            """
            try:
                os.replace(src_path, dst_path)
            except OSError:
                # Разные диски: os.replace не работает через границу тома.
                shutil.move(src_path, dst_path + '.tmp')
                os.replace(dst_path + '.tmp', dst_path)

        # Сначала ищем именно склеенный файл. Остатки отдельных потоков
        # (video.f401.mp4, video.f251.webm) подходят под маску расширений, и
        # раньше обрыв одного потока выдавался за успех: аудиодорожка без видео
        # переносилась как video.webm, и функция возвращала True.
        media_files = [
            f for f in sorted(os.listdir(temp_dir))
            if f.endswith(MEDIA_EXTENSIONS) and not FORMAT_FRAGMENT_RE.search(f)
        ]
        # Видео важнее звука: если по какой-то причине в папке оказались оба,
        # переносим видео, а не аудиодорожку.
        video_files = [f for f in media_files if f.endswith(VIDEO_EXTENSIONS)]
        if video_files:
            media_files = video_files

        final_video = None
        for f in media_files:
            ext = os.path.splitext(f)[1]
            dst = os.path.join(output_dir, f"video{ext}")
            _place(os.path.join(temp_dir, f), dst)
            final_video = dst

        # Метаданные и превью без видеофайла бесполезны: каталог без video.*
        # не виден в библиотеке, но остаётся на диске мусором.
        if not final_video:
            reason = collector.last_error() or 'файл не получен'
            logger.warning(f"Медиафайл не получен, метаданные не сохраняем ({url}): {reason}")
            if error_sink is not None:
                error_sink.append(explain_reason(reason))
            return False

        for f in sorted(os.listdir(temp_dir)):
            src = os.path.join(temp_dir, f)
            if f.endswith('.json'):
                _place(src, os.path.join(output_dir, "info.json"))
            elif f.endswith(('.jpg', '.webp', '.png')):
                _place(src, os.path.join(output_dir, "thumbnail.jpg"))

        # Субтитры лежат в той же временной папке, а она удаляется в finally:
        # без переноса скачанные дорожки пропадали, и плеер их не находил.
        save_subtitles(temp_dir, (info or {}).get('id') or get_video_id(url))

        return True

    except (DownloadCancelled, DownloadCancelledByUser):
        logger.info(f"Загрузка отменена пользователем: {url}")
        if progress_dict is not None:
            progress_dict['status'] = 'cancelled'
            progress_dict['message'] = 'Отменено'
        # Частично скачанное видео не оставляем: temp-папка чистится в finally.
        raise DownloadCancelledByUser('Загрузка отменена пользователем')
    except Exception as e:
        logger.error(f"Ошибка download_lib: {e}")
        if progress_dict is not None:
            progress_dict['status'] = 'error'
            progress_dict['message'] = str(e)
        return False
    finally:
        # БАГФИКС: temp-папка теперь удаляется всегда — раньше при ошибке
        # загрузки на диске копились каталоги _tmp_*
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
            # Windows иногда держит файл (антивирус, ffmpeg), и rmtree с
            # ignore_errors молча провалится. Тогда каталог остаётся внутри
            # папки видео и при следующей попытке подсовывает старые обрывки.
            if os.path.isdir(temp_dir):
                logger.warning(f"Не удалось удалить временный каталог: {temp_dir}")
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

class DownloadOutcome(int):
    """Результат пакетной загрузки: булево «хоть что-то скачалось» + разбивка.

    Наследование от int сохраняет прежний контракт (`if download_single_sync(...)`),
    а поля succeeded/failed позволяют очереди отличить частичный провал от
    полного успеха: раньше 1 успех из 20 показывался как «Готово».
    """

    def __new__(cls, succeeded, failed, last_error='', skipped=0):
        obj = super().__new__(cls, 1 if succeeded > 0 else 0)
        obj.succeeded = succeeded
        obj.failed = failed
        # Текст последней ошибки нужен очереди, чтобы показать причину, а не
        # безликое «Ошибка скачивания».
        obj.last_error = last_error
        # Сколько видео пропущено как уже скачанные.
        obj.skipped = skipped
        return obj

    def __repr__(self):
        return (f"DownloadOutcome(succeeded={self.succeeded}, failed={self.failed}, "
                f"skipped={self.skipped}, last_error={self.last_error!r})")


def download_single_sync(urls, format_id, progress_callback, merge_format='mp4', should_cancel=None):
    """Скачивает список ссылок.

    Возвращает DownloadOutcome: в булевом контексте — «скачалось хотя бы одно
    видео», плюс поля succeeded и failed для отчёта в очереди.
    """
    if isinstance(urls, str): urls = [urls]

    # Ограничение на ffmpeg ставим здесь: зависшая склейка блокировала
    # единственный поток очереди навсегда, и остальные задачи не двигались.
    try:
        install_ffmpeg_timeout()
    except Exception as e:
        logger.warning(f"Не удалось ограничить время работы ffmpeg: {e}")

    config = load_config()
    base_dir = paths.user_path(config["video_dir"])
    
    total = len(urls)
    success_count = 0
    failed_count = 0
    skipped_count = 0
    last_error = ''
    # Счётчик подряд идущих сетевых отказов: см. NETWORK_FAILURE_STREAK.
    network_streak = 0

    for idx, url in enumerate(urls, 1):
        # Отмена прекращает всю задачу, а не только текущее видео из списка.
        if should_cancel and should_cancel():
            raise DownloadCancelledByUser('Загрузка отменена пользователем')
        output_dir = None
        try:
            # PO Token и player_client — YouTube-only: TikTok такие
            # extractor_args не понимает.
            po_args = {} if is_tiktok_url(url) else get_po_args()
            info_opts = {
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True, # БАГФИКС: Не крашить очередь из-за одного видео
                # Без noplaylist ссылка с &list= отдавала метаданные плейлиста:
                # uploader пустой (папка «Unknown»), id — идентификатор плейлиста.
                'noplaylist': True,
                # Без socket_timeout запрос метаданных висел бесконечно (по
                # умолчанию таймаута нет вовсе), намертво занимая единственный
                # поток очереди ещё до начала загрузки.
                'socket_timeout': 30,
                'retries': 2,
                'cookiefile': cookiefile_for_ydl(COOKIES_PATH),
            }
            if po_args: apply_po_args(info_opts, po_args)

            # Метаданные тоже повторяем: обрыв сети или прокси на этом шаге
            # раньше сразу отправлял видео в отказ, и за один прогон очередь
            # теряла десятки видео, хотя достаточно было повторить попытку.
            info = None
            info_errors = _ErrorCollector()
            # Обновление cookies делаем не больше одного раза на видео: чтение
            # профиля браузера занимает секунды, а повторять его по кругу
            # бессмысленно — если свежие cookies не помогли, не помогут и вторые.
            auth_retry_used = False
            attempt = 0
            # Жёсткий предел витков: attempt -= 1 не тратит попытку, и ошибка
            # в условии однократности превращала цикл в бесконечный.
            spins = 0
            max_spins = STREAM_RETRIES + 2
            while attempt < STREAM_RETRIES and spins < max_spins:
                spins += 1
                attempt += 1
                if should_cancel and should_cancel():
                    raise DownloadCancelledByUser('Загрузка отменена пользователем')
                info_errors = _ErrorCollector()
                info_opts['logger'] = info_errors
                with yt_dlp.YoutubeDL(info_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                apply_cookie_updates(info_opts)
                if info:
                    break
                reason = info_errors.last_error()
                # Устаревшие cookies: повтор без обновления смысла не имеет,
                # а после свежего экспорта то же видео отдаёт форматы. Попытку
                # не тратим: иначе видео, у которого попытки съели сетевые
                # сбои, уходило в отказ, хотя свежие cookies его спасали.
                if is_auth_error(reason) and not auth_retry_used:
                    auth_retry_used = True
                    progress_callback(((idx - 1) * 100) / total,
                                      f"[{idx}/{total}] Обновляю cookies "
                                      f"из браузера...")
                    if refresh_cookies_from_browser():
                        info_opts['cookiefile'] = cookiefile_for_ydl(COOKIES_PATH)
                        attempt -= 1
                        continue
                if attempt >= STREAM_RETRIES or not is_transient_error(reason):
                    break
                delay = STREAM_RETRY_DELAY * attempt
                logger.warning(
                    f"Метаданные не получены (попытка {attempt} из {STREAM_RETRIES}), "
                    f"повтор через {delay} с: {url}")
                progress_callback(((idx - 1) * 100) / total,
                                  f"[{idx}/{total}] Сеть недоступна, повтор "
                                  f"{attempt + 1} из {STREAM_RETRIES}...")
                _sleep_cancellable(delay, should_cancel)

            # БАГФИКС: Защита от AttributeError, если info == None
            if not info:
                reason = info_errors.last_error() or 'видео недоступно'
                logger.warning(f"Пропуск видео ({url}): {reason}")
                failed_count += 1
                # Отказ авторизации показываем советом: обновление cookies уже
                # пробовали автоматически, значит браузер не дал свежих.
                reason = explain_reason(reason)
                last_error = reason
                # Процент считаем от всей задачи, а не от одного видео: раньше
                # первое недоступное видео уводило прогресс сразу на 100%.
                progress_callback(idx * 100 / total,
                                  f"[{idx}/{total}] Ошибка: {_short_reason(reason)}")
                if is_transient_error(reason):
                    network_streak += 1
                    if network_streak >= NETWORK_FAILURE_STREAK and idx < total:
                        last_error = ('сеть недоступна, задача остановлена; '
                                      f'повторите позже (причина: {_short_reason(reason)})')
                        logger.warning(
                            f"Сеть недоступна ({network_streak} видео подряд), "
                            f"останавливаю задачу на {idx} из {total}")
                        progress_callback(idx * 100 / total,
                                          f"[{idx}/{total}] Сеть недоступна, задача остановлена")
                        break
                else:
                    network_streak = 0
                continue
            
            # Метаданные пришли, но без единого потока видео/звука: так
            # выглядит несработавший решатель JS-челленджа (yt-dlp выбрасывает
            # все https-форматы и оставляет только раскадровку). Дальше
            # загрузка всё равно упала бы с невнятным «Requested format is not
            # available», поэтому называем причину сразу.
            if 'formats' in info and not has_media_formats(info.get('formats')):
                logger.warning(f"Пропуск видео ({url}): {NO_MEDIA_FORMATS_REASON}")
                failed_count += 1
                last_error = NO_MEDIA_FORMATS_REASON
                network_streak = 0
                progress_callback(idx * 100 / total,
                                  f"[{idx}/{total}] Ошибка: {_short_reason(NO_MEDIA_FORMATS_REASON)}")
                continue

            author = info.get('uploader', 'Unknown')
            title = info.get('title', 'Video')
            video_id = info.get('id') or get_video_id(url)
            
            output_dir = get_output_path(base_dir, author, video_id, title)
            if is_shorts_video(info):
                output_dir += " #shorts"

            # Уже скачанное не качаем заново. Раньше повтор упавшей задачи из
            # 79 ссылок перекачивал и те видео, что успели сохраниться, а при
            # смене контейнера рядом появлялся второй файл (video.mp4 и
            # video.webm), и метаданные расходились с показываемым видео.
            existing = find_downloaded_media(output_dir)
            if existing:
                logger.info(f"Видео уже скачано, пропуск: {url} -> {existing}")
                success_count += 1
                skipped_count += 1
                # Сеть явно жива: метаданные пришли.
                network_streak = 0
                progress_callback(idx * 100 / total,
                                  f"[{idx}/{total}] Уже скачано, пропуск")
                continue

            os.makedirs(output_dir, exist_ok=True)

            def sub_cb(p, msg):
                overall = ((idx - 1) * 100 + p) / total
                progress_callback(overall, f"[{idx}/{total}] {msg}")

            # HTTP 403 на середине потока: ссылки googlevideo привязаны к сессии
            # и «прокисают» при массовой загрузке. Опция retries здесь не
            # помогает — она дёргает ту же мёртвую ссылку, поэтому повторяем
            # весь вызов, а он заново извлекает ссылки.
            res = False
            reasons = []
            for attempt in range(1, STREAM_RETRIES + 1):
                res = download_single_video_impl(url, format_id, output_dir, None, sub_cb, merge_format,
                                                 should_cancel=should_cancel, error_sink=reasons)
                if res:
                    break
                if attempt < STREAM_RETRIES:
                    if should_cancel and should_cancel():
                        raise DownloadCancelledByUser('Загрузка отменена пользователем')
                    delay = STREAM_RETRY_DELAY * attempt
                    logger.warning(
                        f"Попытка {attempt} из {STREAM_RETRIES} не удалась, повтор через {delay} с: {url}")
                    progress_callback(((idx - 1) * 100) / total,
                                      f"[{idx}/{total}] Повтор {attempt + 1} из {STREAM_RETRIES}...")
                    _sleep_cancellable(delay, should_cancel)
            if res:
                success_count += 1
                network_streak = 0
                try:
                    from channel_assets import fetch_and_save
                    threading.Thread(target=fetch_and_save, args=(author, info), daemon=True).start()
                except Exception as e:
                    logger.warning(f"Не удалось запустить скачивание шапки канала: {e}")
            else:
                failed_count += 1
                # Причина отказа теперь доходит до пользователя: раньше в очереди
                # всегда было одно и то же «Ошибка скачивания», а настоящий текст
                # (403, недоступный формат) оставался только в stdout процесса.
                reason = reasons[-1] if reasons else 'причина неизвестна'
                last_error = f"{title}: {reason}"
                progress_callback(idx * 100 / total,
                                  f"[{idx}/{total}] Ошибка: {_short_reason(reason)}")
                # Каталог после неудачи пуст: сеть могла оборваться (HTTP 403),
                # и без уборки на диске оставались папки без видеофайла.
                cleanup_empty_dir(output_dir)

        except DownloadCancelledByUser:
            # Отмену нельзя глотать вместе с обычными ошибками — иначе очередь
            # продолжит скачивать следующие видео задачи.
            cleanup_empty_dir(output_dir)
            raise
        except Exception as e:
            logger.error(f"Ошибка в цикле загрузки: {e}")
            failed_count += 1
            last_error = str(e)
            cleanup_empty_dir(output_dir)
            continue

    return DownloadOutcome(success_count, failed_count, last_error, skipped_count)


def cleanup_empty_dir(path):
    """Удаляет каталог видео, если после отмены в нём не осталось файлов."""
    try:
        if path and os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
    except Exception as e:
        logger.warning(f"Не удалось удалить пустой каталог {path}: {e}")
