import os
import re
import time
import threading
import subprocess
from urllib.parse import quote

from flask import Blueprint, jsonify, request

import paths
from proc import NO_WINDOW as _NO_WINDOW

bp = Blueprint('quality', __name__)

CONVERSION_TASKS = {}
CONVERSION_LOCK = threading.Lock()

# Подписи качеств в порядке показа: от высокого к низкому. Порядок держится
# словарём, а не сортировкой на клиенте: '1080' > '720' как строки сравниваются
# посимвольно и дают 720p выше 1080p, а к числам эти ключи не сводятся
# ('enhance').
#
# Ключ подставляется в имя файла (video_<quality>.mp4), поэтому произвольная
# строка вида '../../../evil' уводила запись за пределы папки видео — значение
# проверяется по этому же набору. Заодно отсекается опечатка, которая раньше
# молча конвертировалась в 720p, но складывала результат в файл с неизвестным
# именем: интерфейс его потом не находил.
QUALITY_LABELS = {
    '2160': '2160p (4K UHD)',
    '1440': '1440p (2K QHD)',
    '1080': '1080p (FHD)',
    '720': '720p (HD)',
    '480': '480p (SD)',
    '360': '360p',
    '240': '240p',
    '144': 'Шакализатор (144p)',
    'enhance': 'Улучшайзер (Четкость+)',
    'enhance_2160': 'Улучшайзер (4K+Четкость)',
}

CONVERSION_QUALITIES = tuple(QUALITY_LABELS)


def _scale_preset(height, crf, preset='fast'):
    """Рецепт ffmpeg для обычного масштабирования в заданную высоту.

    scale=-2:<высота> сохраняет пропорции и держит ширину чётной: с -1 ffmpeg
    выдаёт нечётную ширину, а libx264 с yuv420p её не принимает и падает.
    Апскейл (например 480p → 2160p) идёт тем же путём: lanczos даёт заметно
    меньше ступенек на краях, чем билинейная фильтрация по умолчанию, поэтому
    crf для больших разрешений ниже — иначе растянутая картинка «плывёт».
    """
    return ['-vf', f'scale=-2:{height}:flags=lanczos,format=yuv420p',
            '-c:v', 'libx264', '-preset', preset, '-crf', str(crf),
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart']


# Рецепты ffmpeg без аудио-части: она зависит от дорожки исходника и добавляется
# при запуске. Набор ключей обязан совпадать с CONVERSION_QUALITIES: качество
# без рецепта раньше молча уходило в 720p.
FFMPEG_PRESETS = {
    '2160': _scale_preset(2160, 20, 'slow'),
    '1440': _scale_preset(1440, 19, 'slow'),
    '1080': _scale_preset(1080, 23),
    '720': _scale_preset(720, 23),
    '480': _scale_preset(480, 23),
    '360': _scale_preset(360, 24),
    '240': _scale_preset(240, 26),
    # 144p — «шакализатор»: жёсткое ограничение битрейта и масштабирование
    # ближайшим соседом дают ту самую крупную блочность.
    '144': ['-vf', 'scale=256:144:flags=neighbor,format=yuv420p',
            '-c:v', 'libx264', '-profile:v', 'baseline', '-level', '3.0',
            '-preset', 'ultrafast', '-b:v', '100k', '-maxrate', '150k',
            '-bufsize', '200k', '-g', '30', '-keyint_min', '30',
            '-sc_threshold', '0', '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart'],
    # «Улучшайзер»: резкость, контраст и подавление шума без смены разрешения.
    'enhance': ['-vf', 'unsharp=lx=5:ly=5:la=1.2:cx=5:cy=5:ca=0.8,'
                'eq=contrast=1.10:brightness=0.03:saturation=1.08,'
                'hqdn3d=luma_spatial=4.0:chroma_spatial=3.0:'
                'luma_tmp=6.0:chroma_tmp=4.5,format=yuv420p',
                '-c:v', 'libx264', '-preset', 'slow', '-crf', '16',
                '-tune', 'film', '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart'],
    'enhance_2160': ['-vf', 'scale=-2:2160:flags=lanczos,'
                     'unsharp=lx=5:ly=5:la=1.2:cx=5:cy=5:ca=0.8,'
                     'eq=contrast=1.10:brightness=0.03:saturation=1.08,'
                     'hqdn3d=luma_spatial=4.0:chroma_spatial=3.0:'
                     'luma_tmp=6.0:chroma_tmp=4.5,format=yuv420p',
                     '-c:v', 'libx264', '-preset', 'slow', '-crf', '16',
                     '-tune', 'film', '-pix_fmt', 'yuv420p',
                     '-movflags', '+faststart'],
}

# Качества, которым нужна тихая маленькая дорожка: у 144p битрейт видео ниже
# битрейта обычного аудио, и полноценный звук занимал бы больше самой картинки.
LOW_AUDIO_QUALITIES = ('144',)


# Контейнер результата всегда mp4, каким бы ни был исходник. Рецепты кодируют
# H.264 и AAC, а WebM их не принимает: ffmpeg отказывался с «Only VP8 or VP9 or
# AV1 video and Vorbis or Opus audio and WebVTT subtitles are supported in WebM».
# Расширение, взятое от исходника, делало пересборку webm- и mkv-файлов
# невозможной, а mp4 к тому же играет в любом браузере.
OUTPUT_EXT = '.mp4'


def output_name(quality):
    """Имя файла для пересобранного качества рядом с исходником."""
    return f"video_{quality}{OUTPUT_EXT}"


def build_audio_opts(quality, audio_codec):
    """Аудио-часть команды по кодеку исходной дорожки.

    `audio_codec=None` означает, что дорожки нет: пустой список, иначе ffmpeg
    отказывается («Stream map 'a' matches no streams»). Готовый AAC копируется
    без перекодирования — это и быстрее, и без потери качества.
    """
    if not audio_codec:
        return []
    if quality in LOW_AUDIO_QUALITIES:
        # У 144p битрейт видео ниже обычного аудио: полноценный звук занимал бы
        # больше самой картинки.
        return ["-c:a", "aac", "-b:a", "32k", "-ac", "1", "-ar", "22050"]
    if audio_codec.lower() in ('aac', 'mp4a'):
        return ["-c:a", "copy"]
    return ["-c:a", "aac", "-b:a", "192k"]


def build_command(input_path, quality, audio_opts, output_path):
    """Собирает вызов ffmpeg для пересборки в заданное качество.

    Рецепт берётся строго по ключу: quality уже проверен по
    CONVERSION_QUALITIES, а подстановка «по умолчанию» раньше писала картинку
    720p в файл с чужим именем — интерфейс показывал 360p, а на диске лежало
    720p.
    """
    return ([paths.ffmpeg_path(), '-y', '-hide_banner', '-loglevel', 'error',
             '-i', input_path]
            + FFMPEG_PRESETS[quality] + list(audio_opts) + [output_path])

# Терминальные значения прогресса: 100 — готово, -1 — ошибка.
TASK_DONE, TASK_FAILED = 100, -1

_BASE_VIDEO_DIR = ""
_USER_VIDEOS_ROOT = ""
_logger = None
_get_video_map = None
_get_user_video_map = None
_build_video_map = None
_build_user_video_map = None

def init(base_dir, logger_inst, get_v_map, get_uv_map, build_v_map, build_uv_map,
         user_videos_root=""):
    global _BASE_VIDEO_DIR, _USER_VIDEOS_ROOT, _logger, _get_video_map, _get_user_video_map, _build_video_map, _build_user_video_map
    _BASE_VIDEO_DIR = base_dir
    # Свои загрузки лежат в отдельном корне и отдаются через /usermedia: без
    # этого пути адрес пересобранного файла для них не построить.
    _USER_VIDEOS_ROOT = user_videos_root
    _logger = logger_inst
    _get_video_map = get_v_map
    _get_user_video_map = get_uv_map
    _build_video_map = build_v_map
    _build_user_video_map = build_uv_map


def _media_url(path):
    """Адрес, по которому плеер заберёт файл из библиотеки.

    Кодирование обязательно: имена авторов и папок содержат пробелы, кириллицу
    и знак «+», который в незакодированном виде браузер читает как пробел.
    """
    for root, prefix in ((_BASE_VIDEO_DIR, '/media/'),
                         (_USER_VIDEOS_ROOT, '/usermedia/')):
        if not root:
            continue
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            # Разные диски на Windows: относительного пути не существует.
            continue
        if rel.startswith('..'):
            continue
        return prefix + quote(rel.replace('\\', '/'))
    return None

def _check_ffmpeg():
    try:
        subprocess.run([paths.ffmpeg_path(), '-version'], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True, **_NO_WINDOW)
        return True
    except Exception:
        # Exception, а не голый except: голый перехватывал KeyboardInterrupt и
        # SystemExit, из-за чего Ctrl+C во время проверки не останавливал сервер.
        return False


def _remove_quietly(path):
    """Удаляет файл, не поднимая исключения: занятый файл — не повод падать."""
    try:
        if path and os.path.exists(path): os.remove(path)
    except OSError as e:
        if _logger: _logger.warning(f"Не удалось удалить {path}: {e}")

def get_video_dir_and_file(vid_id):
    v_map = _get_video_map()
    if not v_map:
        _build_video_map()
        v_map = _get_video_map()
    if v_map and vid_id in v_map:
        return os.path.join(_BASE_VIDEO_DIR, v_map[vid_id]['author'], v_map[vid_id]['folder']), v_map[vid_id]['filename']
        
    uv_map = _get_user_video_map()
    if not uv_map:
        _build_user_video_map()
        uv_map = _get_user_video_map()
    if uv_map and vid_id in uv_map:
        return os.path.dirname(uv_map[vid_id]['video_path']), os.path.basename(uv_map[vid_id]['video_path'])
    return None, None

@bp.route('/api/quality/<vid_id>', methods=['GET'])
def api_get_qualities(vid_id):
    vdir, vfile = get_video_dir_and_file(vid_id)
    if not vdir or not vfile: return jsonify({"error": "Video not found"}), 404
    qualities = {
        "original": {"label": "Оригинал", "available": True, "file": vfile},
    }
    for quality, label in QUALITY_LABELS.items():
        qualities[quality] = {"label": label, "available": False,
                              "file": output_name(quality)}
    # Порядок показа отдаём списком: Flask сортирует ключи JSON-объектов, а
    # сортировка строк ставит 1080p ниже 144p. Оригинал сверху — это возврат к
    # скачанному файлу.
    order = ["original"] + list(QUALITY_LABELS)
    for quality, item in qualities.items():
        path = os.path.join(vdir, item["file"])
        if quality != "original":
            item["available"] = os.path.exists(path)
        # Адрес для плеера: без него клиенту пришлось бы собирать путь из имени
        # автора и папки, а они содержат пробелы и кириллицу — без кодирования
        # приходил 404.
        item["url"] = _media_url(path) if item["available"] else None

    tasks = {}
    with CONVERSION_LOCK:
        for k, v in CONVERSION_TASKS.items():
            if k.startswith(vid_id + "_"): tasks[k.split("_", 1)[1]] = v
    return jsonify({"qualities": qualities, "order": order, "tasks": tasks})

@bp.route('/api/convert/<vid_id>', methods=['POST'])
def api_convert_video(vid_id):
    # get_json(silent=True): request.json без Content-Type поднимает 415 и
    # отдаёт HTML, на котором клиентский JSON.parse падает.
    quality = (request.get_json(silent=True) or {}).get('quality')
    if quality not in CONVERSION_QUALITIES:
        return jsonify({"error": "Неизвестное качество"}), 400
    vdir, vfile = get_video_dir_and_file(vid_id)
    if not vdir or not vfile: return jsonify({"error": "Not found"}), 404
    if not _check_ffmpeg(): return jsonify({"error": "ffmpeg не найден"}), 500

    task_key = f"{vid_id}_{quality}"
    with CONVERSION_LOCK:
        if task_key in CONVERSION_TASKS and CONVERSION_TASKS[task_key] not in (TASK_FAILED, TASK_DONE): return jsonify({"status": "already_running"})
        CONVERSION_TASKS[task_key] = 0

    def run_conversion():
        input_path = os.path.join(vdir, vfile)
        # Расширение результата не зависит от исходника: см. OUTPUT_EXT.
        output_path = os.path.join(vdir, output_name(quality))
        tmp_path = os.path.join(vdir, f"video_{quality}_tmp{OUTPUT_EXT}")
        log_path = os.path.join(vdir, f"video_{quality}_ffmpeg.log")

        # Уборка не должна ронять задачу: на Windows файл может быть занят
        # антивирусом или прошлым ffmpeg, и PermissionError убивал поток до
        # входа в основной try — прогресс навсегда замирал на нуле.
        for old in [tmp_path, output_path + ".tmp", log_path]:
            try:
                if os.path.exists(old): os.remove(old)
            except OSError as e:
                if _logger: _logger.warning(f"Не удалось удалить {old}: {e}")

        # duration нужен только для процента прогресса, поэтому любая неудача
        # здесь не критична. Но перехватываем конкретные ошибки: голый except
        # глотал KeyboardInterrupt, и Ctrl+C во время конвертации не работал.
        # ValueError — на случай нечислового вывода ffprobe (бывает 'N/A').
        probe_errors = (OSError, ValueError, subprocess.SubprocessError)
        duration = 1
        try:
            r = subprocess.run([paths.ffprobe_path(), '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30, **_NO_WINDOW)
            if r.stdout.strip(): duration = float(r.stdout.strip())
        except probe_errors:
            try:
                r = subprocess.run([paths.ffmpeg_path(), '-i', input_path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=15, **_NO_WINDOW)
                m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
                if m: duration = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
            except probe_errors as e:
                if _logger: _logger.warning(f"Длительность {vid_id} не определена: {e}")
        # Нулевая длительность превратила бы расчёт процента в делление на ноль.
        if duration <= 0: duration = 1

        has_audio = False
        audio_codec = None
        try:
            probe = subprocess.run([paths.ffprobe_path(), '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', input_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10, **_NO_WINDOW)
            acodec = probe.stdout.strip().lower()
            if acodec:
                has_audio = True
                audio_codec = acodec
        except probe_errors as e:
            # Не голый except: молчаливый перехват всего скрывал и Ctrl+C.
            if _logger: _logger.warning(f"Аудиодорожка {vid_id} не определена: {e}")

        audio_opts = build_audio_opts(quality, audio_codec if has_audio else None)

        cmd = build_command(input_path, quality, audio_opts, tmp_path)
        if _logger: _logger.info(f"Конвертация {vid_id} -> {quality}")

        process = None
        try:
            with open(log_path, 'w', encoding='utf-8') as log_f:
                process = subprocess.Popen(cmd, stderr=log_f, stdout=subprocess.DEVNULL,
                                           **_NO_WINDOW)
                last_size = 0
                while process.poll() is None:
                    time.sleep(2)
                    try:
                        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f_log:
                            f_log.seek(last_size)
                            new_data = f_log.read()
                            last_size = f_log.tell()
                            for m in re.finditer(r'time=(\d+):(\d+):(\d+\.\d+)', new_data):
                                t = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
                                with CONVERSION_LOCK: CONVERSION_TASKS[task_key] = min(99, int((t / duration) * 100))
                    except OSError:
                        # Лог держит ffmpeg, на Windows чтение иногда не удаётся.
                        # Это лишь обновление процента — ждём следующей итерации.
                        pass
                returncode = process.wait(timeout=7200)

            if returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 1024:
                # os.replace, а не remove+rename: на Windows os.rename поверх
                # существующего файла падает с FileExistsError, а пара
                # remove+rename оставляла окно, в котором прежнего файла уже
                # нет, а нового ещё нет — сбой между ними терял обе версии.
                os.replace(tmp_path, output_path)
                with CONVERSION_LOCK: CONVERSION_TASKS[task_key] = TASK_DONE
            else:
                if _logger: _logger.error(f"Конвертация ошибка. Код: {returncode}")
                with CONVERSION_LOCK: CONVERSION_TASKS[task_key] = TASK_FAILED
                _remove_quietly(tmp_path)
        except Exception as e:
            if _logger: _logger.error(f"Конвертация прервана: {e}")
            if process and process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=10)
                except Exception: pass
            with CONVERSION_LOCK: CONVERSION_TASKS[task_key] = TASK_FAILED
            _remove_quietly(tmp_path)
        finally:
            _remove_quietly(log_path)

    def run_conversion_guarded():
        """Не даёт задаче зависнуть в прогрессе при неожиданной ошибке.

        Часть работы (уборка старых файлов, ffprobe) идёт до внутреннего
        try/except: PermissionError на занятом файле убивал поток, задача
        навсегда оставалась на 0%, а интерфейс крутил полосу до перезапуска
        сервера — повторить конвертацию тоже было нельзя, потому что ключ
        задачи считался активным.
        """
        try:
            run_conversion()
        except Exception as e:
            if _logger: _logger.error(f"Конвертация сорвалась: {e}")
        finally:
            with CONVERSION_LOCK:
                if CONVERSION_TASKS.get(task_key) not in (TASK_DONE, TASK_FAILED):
                    CONVERSION_TASKS[task_key] = TASK_FAILED

    threading.Thread(target=run_conversion_guarded, daemon=True).start()
    return jsonify({"status": "started", "task_key": task_key})