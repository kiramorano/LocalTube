import os
import re
import time
import threading
import subprocess
from flask import Blueprint, jsonify, request

bp = Blueprint('quality', __name__)

CONVERSION_TASKS = {}
CONVERSION_LOCK = threading.Lock()

_BASE_VIDEO_DIR = ""
_logger = None
_get_video_map = None
_get_user_video_map = None
_build_video_map = None
_build_user_video_map = None

def init(base_dir, logger_inst, get_v_map, get_uv_map, build_v_map, build_uv_map):
    global _BASE_VIDEO_DIR, _logger, _get_video_map, _get_user_video_map, _build_video_map, _build_user_video_map
    _BASE_VIDEO_DIR = base_dir
    _logger = logger_inst
    _get_video_map = get_v_map
    _get_user_video_map = get_uv_map
    _build_video_map = build_v_map
    _build_user_video_map = build_uv_map

def _check_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except: return False

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
    ext = os.path.splitext(vfile)[1]
    qualities = {
        "original": {"label": "Оригинал", "available": True, "file": vfile},
        "1080": {"label": "1080p (FHD)", "available": False, "file": f"video_1080{ext}"},
        "720": {"label": "720p (HD)", "available": False, "file": f"video_720{ext}"},
        "480": {"label": "480p (SD)", "available": False, "file": f"video_480{ext}"},
        "144": {"label": "Шакализатор 🐕 (144p)", "available": False, "file": f"video_144{ext}"},
        "enhance": {"label": "Улучшайзер 💎 (Четкость+)", "available": False, "file": f"video_enhance{ext}"}
    }
    for q in qualities.keys():
        if q != "original" and os.path.exists(os.path.join(vdir, qualities[q]["file"])): qualities[q]["available"] = True
    
    tasks = {}
    with CONVERSION_LOCK:
        for k, v in CONVERSION_TASKS.items():
            if k.startswith(vid_id + "_"): tasks[k.split("_")[1]] = v
    return jsonify({"qualities": qualities, "tasks": tasks})

@bp.route('/api/convert/<vid_id>', methods=['POST'])
def api_convert_video(vid_id):
    quality = request.json.get('quality')
    vdir, vfile = get_video_dir_and_file(vid_id)
    if not vdir: return jsonify({"error": "Not found"}), 404
    if not _check_ffmpeg(): return jsonify({"error": "ffmpeg не найден"}), 500

    task_key = f"{vid_id}_{quality}"
    with CONVERSION_LOCK:
        if task_key in CONVERSION_TASKS and CONVERSION_TASKS[task_key] not in [-1, 100]: return jsonify({"status": "already_running"})
        CONVERSION_TASKS[task_key] = 0

    def run_conversion():
        input_path = os.path.join(vdir, vfile)
        ext = os.path.splitext(vfile)[1]
        output_path = os.path.join(vdir, f"video_{quality}{ext}")
        tmp_path = os.path.join(vdir, f"video_{quality}_tmp{ext}")
        log_path = os.path.join(vdir, f"video_{quality}_ffmpeg.log")

        for old in [tmp_path, output_path + ".tmp", log_path]:
            if os.path.exists(old): os.remove(old)

        duration = 1
        try:
            r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if r.stdout.strip(): duration = float(r.stdout.strip())
        except:
            try:
                r = subprocess.run(['ffmpeg', '-i', input_path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=15)
                m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
                if m: duration = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
            except: pass

        has_audio = False
        audio_codec = None
        try:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', input_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            acodec = probe.stdout.strip().lower()
            if acodec:
                has_audio = True
                audio_codec = acodec
        except: pass

        if has_audio:
            if audio_codec in ('aac', 'mp4a'):
                audio_opts = ["-c:a", "copy"]
            else:
                audio_opts = ["-c:a", "aac", "-b:a", "192k"]
        else:
            audio_opts = []

        audio_144 = ["-c:a", "aac", "-b:a", "32k", "-ac", "1", "-ar", "22050"] if has_audio else []

        presets = {
            "1080": ["-vf", "scale=-2:1080:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"] + audio_opts,
            "720": ["-vf", "scale=-2:720:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"] + audio_opts,
            "480": ["-vf", "scale=-2:480:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"] + audio_opts,
            "144": ["-vf", "scale=256:144:flags=neighbor,format=yuv420p", "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0", "-preset", "ultrafast", "-b:v", "100k", "-maxrate", "150k", "-bufsize", "200k", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-movflags", "+faststart"] + audio_144,
            "enhance": ["-vf", "unsharp=lx=5:ly=5:la=1.2:cx=5:cy=5:ca=0.8,eq=contrast=1.10:brightness=0.03:saturation=1.08,hqdn3d=luma_spatial=4.0:chroma_spatial=3.0:luma_tmp=6.0:chroma_tmp=4.5,format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-tune", "film", "-pix_fmt", "yuv420p", "-movflags", "+faststart"] + audio_opts
        }

        cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', input_path] + presets.get(quality, presets["720"]) + [tmp_path]
        if _logger: _logger.info(f"Конвертация {vid_id} -> {quality}")

        process = None
        try:
            with open(log_path, 'w', encoding='utf-8') as log_f:
                process = subprocess.Popen(cmd, stderr=log_f, stdout=subprocess.DEVNULL)
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
                    except: pass
                returncode = process.wait(timeout=7200)

            if returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 1024:
                if os.path.exists(output_path): os.remove(output_path)
                os.rename(tmp_path, output_path)
                with CONVERSION_LOCK: CONVERSION_TASKS[task_key] = 100
            else:
                if _logger: _logger.error(f"Конвертация ошибка. Код: {returncode}")
                with CONVERSION_LOCK: CONVERSION_TASKS[task_key] = -1
                if os.path.exists(tmp_path): os.remove(tmp_path)
        except Exception as e:
            if _logger: _logger.error(f"Конвертация прервана: {e}")
            if process and process.poll() is None:
                try: process.kill(); process.wait(timeout=10)
                except: pass
            with CONVERSION_LOCK: CONVERSION_TASKS[task_key] = -1
            if os.path.exists(tmp_path): os.remove(tmp_path)
        finally:
            if os.path.exists(log_path): os.remove(log_path)

    threading.Thread(target=run_conversion, daemon=True).start()
    return jsonify({"status": "started", "task_key": task_key})