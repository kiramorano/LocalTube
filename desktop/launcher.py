# -*- coding: utf-8 -*-
"""
LocalTube Portable Launcher (Windows)
=====================================
Точка входа для PyInstaller onefile-сборки.

Как это работает:
1. PyInstaller упаковывает весь исходный код проекта (py/templates/static),
   а также ffmpeg.exe/ffprobe.exe внутрь одного exe.
2. При запуске лаунчер распаковывает код в папку "LocalTube_Data" рядом
   с exe-файлом. Пользовательские данные (config.json, cookies.txt, видео,
   превью, плейлисты и т.д.) НЕ перезаписываются при обновлении.
3. Папка с ffmpeg добавляется в PATH, LocalTube_Data становится рабочей
   директорией, после чего запускается app.py как обычно.

Таким образом exe полностью портативный: все данные хранятся рядом с ним.
"""
import os
import sys
import shutil
import runpy
import webbrowser
import threading
import time


def _pyinstaller_hidden_imports():  # pragma: no cover
    """app.py запускается через runpy, поэтому PyInstaller не видит его
    зависимостей при статическом анализе. Явно перечисляем их здесь,
    чтобы они попали в сборку. Функция никогда не вызывается."""
    import flask  # noqa: F401
    import jinja2  # noqa: F401
    import werkzeug  # noqa: F401
    import requests  # noqa: F401
    import PIL.Image  # noqa: F401
    import yt_dlp  # noqa: F401

# Файлы/папки кода, которые перезаписываются при каждом запуске (обновление версии)
CODE_ITEMS = [
    "app.py", "downloader.py", "download_lib.py", "download_video.py",
    "download_avatars.py", "download_thumbnails.py", "utils.py",
    "user_videos.py", "subtitles.py", "logger.py", "po_manager.py",
    "youtube_extractor.py", "worker.py", "diagnostic.py", "server.py",
    "templates",
]
# Файлы/папки данных: создаются только если отсутствуют (не перезаписываются)
DATA_ITEMS = ["config.json", "cookies.txt"]
# static: код + пользовательский кэш вперемешку — обновляем файлы кода,
# но не удаляем ничего лишнего
STATIC_DIR = "static"
BIN_ITEMS = ["ffmpeg.exe", "ffprobe.exe"]

PORT = int(os.environ.get("PORT", "8000"))


def get_bundle_dir() -> str:
    """Папка с распакованными PyInstaller ресурсами."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def get_exe_dir() -> str:
    """Папка, где лежит exe (или скрипт при запуске из исходников)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def copy_tree_overwrite(src: str, dst: str) -> None:
    """Рекурсивно копирует src в dst, перезаписывая файлы, не удаляя лишние."""
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isdir(s):
            copy_tree_overwrite(s, d)
        else:
            shutil.copy2(s, d)


def prepare_data_dir(bundle: str, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)

    src_root = os.path.join(bundle, "localtube_src")

    # 1. Код — всегда обновляем
    for item in CODE_ITEMS:
        src = os.path.join(src_root, item)
        dst = os.path.join(data_dir, item)
        if not os.path.exists(src):
            continue
        if os.path.isdir(src):
            copy_tree_overwrite(src, dst)
        else:
            shutil.copy2(src, dst)

    # 2. static — обновляем файлы, сохраняя пользовательский кэш
    src_static = os.path.join(src_root, STATIC_DIR)
    if os.path.isdir(src_static):
        copy_tree_overwrite(src_static, os.path.join(data_dir, STATIC_DIR))

    # 3. Данные — только если отсутствуют
    for item in DATA_ITEMS:
        src = os.path.join(src_root, item)
        dst = os.path.join(data_dir, item)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)

    # 4. ffmpeg/ffprobe — кладём в bin рядом с данными
    bin_dir = os.path.join(data_dir, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    for item in BIN_ITEMS:
        src = os.path.join(bundle, "bin", item)
        dst = os.path.join(bin_dir, item)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)


def open_browser_when_ready() -> None:
    """Открывает браузер, когда сервер поднялся."""
    import urllib.request
    url = f"http://127.0.0.1:{PORT}"
    for _ in range(120):
        try:
            urllib.request.urlopen(url, timeout=1)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.5)


def main() -> None:
    bundle = get_bundle_dir()
    exe_dir = get_exe_dir()
    data_dir = os.path.join(exe_dir, "LocalTube_Data")

    print("=" * 60)
    print("  LocalTube NEO — Portable")
    print(f"  Данные: {data_dir}")
    print("=" * 60)

    prepare_data_dir(bundle, data_dir)

    # ffmpeg в PATH
    bin_dir = os.path.join(data_dir, "bin")
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")

    # Запускаем app.py из папки данных: __file__ будет указывать на data_dir,
    # поэтому все SCRIPT_DIR/PROJECT_ROOT пути будут корректными.
    os.chdir(data_dir)
    sys.path.insert(0, data_dir)

    threading.Thread(target=open_browser_when_ready, daemon=True).start()

    app_path = os.path.join(data_dir, "app.py")
    runpy.run_path(app_path, run_name="__main__")


if __name__ == "__main__":
    main()
