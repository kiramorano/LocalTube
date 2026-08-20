#!/usr/bin/env python3
"""
auth_options.py – Управление способами авторизации и получения данных YouTube.
Способы как в Seal (JunkFood02/Seal):
  - выбор player-клиента (tv, web, web_safari, android, android_vr, ios, mweb)
  - PO Token через bgutil-провайдер (bgutil:http — локальный сервер, bgutil:cli — бинарник)
  - cookies.txt (уже используется)
OAuth2 больше не работает в yt-dlp (YouTube отключил), поэтому его нет.
"""

import os
import sys
import json
import shutil
import threading
import time

from utils import write_json_atomic, read_json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

# Сериализует read-modify-write config.json.
_config_lock = threading.RLock()
COOKIES_PATH = os.path.join(SCRIPT_DIR, "cookies.txt")
PLUGINS_DIR = os.path.join(SCRIPT_DIR, "yt_dlp_plugins")

DEFAULT_OPTIONS = {
    "player_client": "",     # "" = авто (как решает yt-dlp), или tv/web/web_safari/android/android_vr/ios/mweb
    "po_token": "off",       # off / bgutil:http / bgutil:cli
    "bgutil_base_url": "http://127.0.0.1:4416",
}

PLAYER_CLIENT_CHOICES = {
    "": "Авто (по умолчанию)",
    "tv": "TV (без PO Token, нужны cookies)",
    "web": "Web (SABR, нужен PO Token)",
    "web_safari": "Web Safari (HLS часто без PO Token)",
    "web_embedded": "Web Embedded (только встраиваемые)",
    "mweb": "Mobile Web (рекомендуется с PO Token)",
    "android": "Android (нужен PO Token)",
    "android_vr": "Android VR (некоторые без PO Token)",
    "ios": "iOS (нужен PO Token)",
}

PO_TOKEN_CHOICES = {
    "off": "Выключено",
    "bgutil:http": "bgutil: HTTP (сервер на 127.0.0.1:4416)",
    "bgutil:cli": "bgutil: CLI (бинарник bgutil-pot)",
}


def get_options():
    """Читает настройки авторизации из config.json."""
    default = dict(DEFAULT_OPTIONS)
    cfg = read_json(CONFIG_FILE, default={})
    if isinstance(cfg, dict):
        auth = cfg.get("youtube_auth", {})
        if isinstance(auth, dict):
            for k in default:
                if k in auth and auth[k] is not None:
                    default[k] = auth[k]
    return default


def save_options(data):
    """Сохраняет настройки авторизации в config.json.

    Запись атомарная: config.json хранит и пути к библиотеке, а прямая
    перезапись при обрыве оставила бы битый файл без всех настроек.
    """
    try:
        # Лок вокруг read-modify-write: иначе одновременные сохранения
        # затирают чужие ключи.
        with _config_lock:
            cfg = read_json(CONFIG_FILE, default={})
            if not isinstance(cfg, dict):
                cfg = {}
            auth = get_options()
            for k in DEFAULT_OPTIONS:
                if k in data and data[k] is not None:
                    auth[k] = data[k]
            cfg["youtube_auth"] = auth
            write_json_atomic(CONFIG_FILE, cfg)
        return True
    except Exception as e:
        return {"error": str(e)}


def import_cookies_from_browser(browser):
    """Извлекает куки из установленного браузера и пишет их в cookies.txt.
    Возвращает число кук или сообщение об ошибке."""
    try:
        from yt_dlp.cookies import extract_cookies_from_browser, SUPPORTED_BROWSERS
        if browser not in SUPPORTED_BROWSERS:
            return {"error": f"Неизвестный браузер: {browser}"}
        jar = extract_cookies_from_browser(browser)
        jar.save(COOKIES_PATH, ignore_discard=True, ignore_expires=True)
        return {"status": "ok", "count": len(jar), "browser": browser}
    except Exception as e:
        return {"error": str(e)}


def build_ydl_args():
    """Формирует аргументы для yt-dlp (extractor_args) по настройкам."""
    opts = get_options()
    extractor_args = {}
    client = opts.get("player_client") or ""
    if client:
        extractor_args["player_client"] = [client]
    po = opts.get("po_token") or "off"
    if po and po != "off":
        extractor_args["po_token"] = [po]
    if not extractor_args:
        return {}
    return {"extractor_args": {"youtube": extractor_args}}


def ensure_plugins():
    """Создаёт плагины getpot_bgutil (yt_dlp_plugins), если их нет."""
    marker = os.path.join(PLUGINS_DIR, "extractor", "getpot_bgutil", "getpot_bgutil_http.py")
    if os.path.exists(marker):
        return True
    try:
        from worker import fix_plugins
        fix_plugins()
        return os.path.exists(marker)
    except Exception as e:
        return False


def plugins_loaded():
    """Пакет yt_dlp_plugins виден в sys.path (загрузится при первом YoutubeDL)."""
    try:
        import importlib.util
        return importlib.util.find_spec("yt_dlp_plugins") is not None
    except Exception:
        return False


def bgutil_http_alive():
    """Проверяет, отвечает ли локальный bgutil-сервер."""
    base = get_options().get("bgutil_base_url", "http://127.0.0.1:4416")
    try:
        import requests
        resp = requests.get(base.rstrip('/') + "/ping", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def bgutil_cli_available():
    """Ищет бинарник bgutil-pot (PATH или стандартные пути)."""
    if shutil.which("bgutil-pot"):
        return True
    candidates = [
        "bgutil-pot-windows-x86_64.exe",
        os.path.join(SCRIPT_DIR, "bgutil-pot-windows-x86_64.exe"),
        os.path.join(SCRIPT_DIR, "tools", "bgutil-pot-windows-x86_64.exe"),
    ]
    return any(os.path.exists(c) for c in candidates)


def status():
    """Диагностика способов загрузки."""
    opts = get_options()
    po = opts.get("po_token", "off")
    po_ok = False
    po_msg = "не настроен"
    if po == "bgutil:http":
        po_ok = bgutil_http_alive()
        po_msg = "сервер отвечает" if po_ok else "сервер не найден (нужен bgutil-ytdlp-pot-provider на 127.0.0.1:4416)"
    elif po == "bgutil:cli":
        po_ok = bgutil_cli_available()
        po_msg = "бинарник найден" if po_ok else "bgutil-pot не найден (скачайте с GitHub jim60105/bgutil-ytdlp-pot-provider)"
    return {
        "options": opts,
        "cookies_exists": os.path.exists(COOKIES_PATH),
        "plugins_dir": os.path.isdir(PLUGINS_DIR),
        "plugins_loaded": plugins_loaded(),
        "bgutil_http_alive": bgutil_http_alive(),
        "bgutil_cli_available": bgutil_cli_available(),
        "po_token_ok": po_ok,
        "po_token_message": po_msg,
        "player_client": opts.get("player_client", ""),
        "player_client_choices": PLAYER_CLIENT_CHOICES,
        "po_token_choices": PO_TOKEN_CHOICES,
    }
