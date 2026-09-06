import os
import json
import subprocess
from flask import Blueprint, jsonify, request, send_file, abort, send_from_directory

import paths
from proc import NO_WINDOW as _NO_WINDOW
from subtitles import get_available_subtitles, download_youtube_subtitles, upload_subtitle_file, delete_subtitle

bp = Blueprint('audio_language', __name__)

_BASE_VIDEO_DIR = ""
_SUBTITLES_DIR = ""
_logger = None
_get_video_map = None
_get_user_video_map = None
_build_video_map = None

def init(base_dir, sub_dir, logger_inst, get_v_map, get_uv_map, build_v_map):
    global _BASE_VIDEO_DIR, _SUBTITLES_DIR, _logger, _get_video_map, _get_user_video_map, _build_video_map
    _BASE_VIDEO_DIR = base_dir
    _SUBTITLES_DIR = sub_dir
    _logger = logger_inst
    _get_video_map = get_v_map
    _get_user_video_map = get_uv_map
    _build_video_map = build_v_map

def find_file(folder, exts):
    # OSError, а не голый except: голый перехватывал и KeyboardInterrupt.
    try:
        for f in os.listdir(folder):
            if any(f.lower().endswith(e) for e in exts): return f
    except OSError:
        pass
    return None


def _read_youtube_id(folder):
    """Достаёт YouTube ID из info.json в папке видео.

    Общий helper на два маршрута: раньше это был скопированный блок, и в обеих
    копиях стоял encoding='utf-8' вместо utf-8-sig (файл с BOM не читался) и
    голый except, скрывавший причину.
    """
    m_file = find_file(folder, ['info.json', '.info.json'])
    if not m_file:
        return None
    try:
        with open(os.path.join(folder, m_file), 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        return data.get('id') if isinstance(data, dict) else None
    except (OSError, ValueError) as e:
        if _logger: _logger.warning(f"Не удалось прочитать {m_file}: {e}")
        return None

def get_video_dir_and_file(vid_id):
    v_map = _get_video_map()
    if not v_map:
        _build_video_map()
        v_map = _get_video_map()
    if v_map and vid_id in v_map:
        return os.path.join(_BASE_VIDEO_DIR, v_map[vid_id]['author'], v_map[vid_id]['folder']), v_map[vid_id]['filename']
    uv_map = _get_user_video_map()
    if uv_map and vid_id in uv_map:
        return os.path.dirname(uv_map[vid_id]['video_path']), os.path.basename(uv_map[vid_id]['video_path'])
    return None, None

@bp.route('/api/audio/download/<vid_id>')
def download_audio_file(vid_id):
    vdir, vfile = get_video_dir_and_file(vid_id)
    if not vdir or not vfile: abort(404)
    input_path = os.path.join(vdir, vfile)
    output_path = os.path.join(vdir, os.path.splitext(vfile)[0] + '.mp3')
    if not os.path.exists(output_path):
        try:
            subprocess.run([paths.ffmpeg_path(), '-y', '-i', input_path, '-q:a', '0', '-map', 'a', output_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, **_NO_WINDOW)
        except Exception as e:
            if _logger: _logger.error(f"Ошибка извлечения аудио: {e}")
            return "Ошибка при конвертации аудио. Убедитесь, что установлен ffmpeg.", 500
    if os.path.exists(output_path): return send_file(output_path, as_attachment=True)
    return "Файл не найден", 404

@bp.route('/subtitles/<video_id>/<lang>.<ext>')
def serve_subtitle(video_id, lang, ext):
    if ext not in ('vtt', 'srt'): return "Invalid extension", 400
    source = request.args.get('source', 'youtube')
    if source not in ('youtube', 'user'): return "Invalid source", 400
    folder = os.path.join(_SUBTITLES_DIR, source, video_id)
    if os.path.exists(os.path.join(folder, f"{lang}.{ext}")): return send_from_directory(folder, f"{lang}.{ext}")
    return "Not found", 404

@bp.route('/api/subtitles/<video_id>', methods=['GET'])
def api_get_subtitles(video_id):
    return jsonify({"subtitles": get_available_subtitles(video_id, request.args.get('source', 'youtube'))})

@bp.route('/api/subtitles/download/<video_id>', methods=['POST'])
def api_download_subtitles(video_id):
    # get_json(silent=True): request.json без Content-Type поднимает 415 и
    # отдаёт HTML-страницу вместо JSON, на котором клиент падает.
    payload = request.get_json(silent=True) or {}
    lang, source = payload.get('lang', 'ru'), payload.get('source', 'youtube')
    if source != 'youtube': return jsonify({"error": "Только вручную"}), 400
    v = _get_video_map().get(video_id)
    if not v: return jsonify({"error": "Видео не найдено"}), 404
    y_id = v.get('youtube_id')
    if not y_id:
        y_id = _read_youtube_id(os.path.join(_BASE_VIDEO_DIR, v['author'], v['folder']))
    if not y_id: return jsonify({"error": "Нет YouTube ID"}), 400
    if download_youtube_subtitles(f"https://youtu.be/{y_id}", video_id, lang): return jsonify({"status": "ok"})
    return jsonify({"error": "Ошибка скачивания"}), 500

@bp.route('/api/subtitles/upload/<video_id>', methods=['POST'])
def api_upload_subtitles(video_id):
    source, lang, f = request.form.get('source', 'youtube'), request.form.get('lang', 'ru'), request.files.get('file')
    if not f: return jsonify({"error": "Нет файла"}), 400
    if upload_subtitle_file(video_id, source, f, lang): return jsonify({"status": "ok"})
    return jsonify({"error": "Ошибка"}), 500

@bp.route('/api/subtitles/<video_id>/<lang>', methods=['DELETE'])
def api_delete_subtitle(video_id, lang):
    if delete_subtitle(video_id, request.args.get('source', 'youtube'), lang): return jsonify({"status": "ok"})
    return jsonify({"error": "Не найдено"}), 404

@bp.route('/api/subtitles/download_all', methods=['POST'])
def api_download_all_subtitles():
    # silent=True: без него request.get_json() на запросе без заголовка
    # Content-Type поднимает 415 ещё до `or {}` и отдаёт HTML вместо JSON.
    lang = (request.get_json(silent=True) or {}).get('lang', 'ru')
    _build_video_map()
    v_map = _get_video_map()
    count = 0
    for vid, v in v_map.items():
        if not any(s['lang'] == lang for s in get_available_subtitles(vid, 'youtube')):
            y_id = v.get('youtube_id')
            if not y_id:
                y_id = _read_youtube_id(os.path.join(_BASE_VIDEO_DIR, v['author'], v['folder']))
            if y_id and download_youtube_subtitles(f"https://youtu.be/{y_id}", vid, lang): count += 1
    return jsonify({"status": "ok", "downloaded": count, "total": len(v_map)})