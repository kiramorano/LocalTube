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

import paths
from utils import write_json_atomic, read_json, cookie_jar_to_netscape

SCRIPT_DIR = paths.data_dir()
CONFIG_FILE = paths.data_path("config.json")

# Сериализует read-modify-write config.json.
_config_lock = threading.RLock()
COOKIES_PATH = paths.data_path("cookies.txt")
# Плагины PO Token живут в каталоге данных, а не рядом с кодом: ensure_plugins
# дописывает их при первом запуске, а каталог установки в MSI, DEB и RPM
# доступен только для чтения. Каталог данных добавлен в sys.path (см.
# register_plugin_path), поэтому yt-dlp находит пакет там же.
PLUGINS_DIR = paths.data_path("yt_dlp_plugins")


def register_plugin_path():
    """Делает каталог данных видимым для загрузчика плагинов yt-dlp.

    yt-dlp ищет пакет ``yt_dlp_plugins`` по элементам sys.path. Плагины лежат в
    каталоге данных, которого в sys.path нет, поэтому без этой регистрации
    провайдер PO Token не подключался бы вовсе — молча, потому что отсутствие
    плагина не считается ошибкой.
    """
    root = paths.ensure_data_dir()
    if root not in sys.path:
        sys.path.append(root)
    return root

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


# Подписи для выпадающего списка. Порядок задаёт порядок в интерфейсе:
# Firefox первым, потому что на Windows он единственный отдаёт cookies без
# препятствий — у Chrome и Edge база зашифрована DPAPI и читается только при
# полностью закрытом браузере (yt-dlp #10927).
BROWSER_LABELS = {
    "firefox": "Firefox",
    "chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "brave": "Brave",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
    "chromium": "Chromium",
    "whale": "Naver Whale",
    "safari": "Safari",
}


def browser_profile_dirs():
    """Каталоги профилей браузеров: по ним видно, установлен ли браузер.

    Ставить в список браузер, которого нет в системе, — вести пользователя к
    заведомой ошибке «could not find ... cookies database».
    """
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    home = os.path.expanduser("~")
    if os.name == "nt":
        return {
            "firefox": [os.path.join(roaming, "Mozilla", "Firefox", "Profiles")],
            "chrome": [os.path.join(local, "Google", "Chrome", "User Data")],
            "edge": [os.path.join(local, "Microsoft", "Edge", "User Data")],
            "brave": [os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data")],
            "opera": [os.path.join(roaming, "Opera Software", "Opera Stable")],
            "vivaldi": [os.path.join(local, "Vivaldi", "User Data")],
            "chromium": [os.path.join(local, "Chromium", "User Data")],
            "whale": [os.path.join(local, "Naver", "Naver Whale", "User Data")],
            "safari": [],
        }
    return {
        "firefox": [os.path.join(home, ".mozilla", "firefox"),
                    os.path.join(home, "Library", "Application Support", "Firefox", "Profiles")],
        "chrome": [os.path.join(home, ".config", "google-chrome"),
                   os.path.join(home, "Library", "Application Support", "Google", "Chrome")],
        "edge": [os.path.join(home, ".config", "microsoft-edge"),
                 os.path.join(home, "Library", "Application Support", "Microsoft Edge")],
        "brave": [os.path.join(home, ".config", "BraveSoftware", "Brave-Browser"),
                  os.path.join(home, "Library", "Application Support", "BraveSoftware",
                               "Brave-Browser")],
        "opera": [os.path.join(home, ".config", "opera"),
                  os.path.join(home, "Library", "Application Support", "com.operasoftware.Opera")],
        "vivaldi": [os.path.join(home, ".config", "vivaldi"),
                    os.path.join(home, "Library", "Application Support", "Vivaldi")],
        "chromium": [os.path.join(home, ".config", "chromium"),
                     os.path.join(home, "Library", "Application Support", "Chromium")],
        "whale": [os.path.join(home, ".config", "naver-whale")],
        "safari": [os.path.join(home, "Library", "Cookies")],
    }


def supported_browsers():
    """Браузеры, которые умеет читать установленный yt-dlp."""
    try:
        from yt_dlp.cookies import SUPPORTED_BROWSERS
        return sorted(SUPPORTED_BROWSERS)
    except Exception:
        return sorted(BROWSER_LABELS)


def available_browsers():
    """Список браузеров для выбора в интерфейсе.

    Каждый элемент: name (для API), label (подпись), installed (найден ли
    профиль). Установленные идут первыми, чтобы не приходилось искать нужный
    среди отсутствующих.
    """
    supported = supported_browsers()
    dirs = browser_profile_dirs()
    result = []
    for name in supported:
        paths = dirs.get(name) or []
        installed = any(os.path.isdir(p) for p in paths)
        result.append({
            "name": name,
            "label": BROWSER_LABELS.get(name, name.title()),
            "installed": installed,
        })
    # Порядок: сначала установленные, внутри группы — как в BROWSER_LABELS.
    order = list(BROWSER_LABELS)
    result.sort(key=lambda b: (not b["installed"],
                               order.index(b["name"]) if b["name"] in order else len(order)))
    return result


def extract_browser_cookies(browser, **kwargs):
    """Тонкая обёртка над yt-dlp: точка подмены в тестах.

    Читать настоящие профили браузеров в тестах нельзя, поэтому вызов вынесен
    в отдельную функцию.
    """
    from yt_dlp.cookies import extract_cookies_from_browser
    return extract_cookies_from_browser(browser, **kwargs)


def explain_browser_error(browser, error):
    """Переводит ошибку чтения браузера в понятный пользователю текст."""
    label = BROWSER_LABELS.get(browser, browser)
    text = str(error or "")
    low = text.lower()
    if "dpapi" in low or "failed to decrypt" in low:
        return (f"{label}: не удалось расшифровать cookies. Закройте браузер "
                f"полностью (включая фоновые процессы) и повторите. Если не "
                f"поможет, экспортируйте cookies.txt расширением и вставьте "
                f"текстом.")
    if "could not find" in low and "database" in low:
        return (f"{label}: файл cookies не найден. Похоже, браузер не установлен "
                f"или в нём ещё нет профиля.")
    if "permission" in low or "being used by another process" in low or "locked" in low:
        return f"{label}: файл cookies занят. Закройте браузер и повторите."
    if "unsupported platform" in low:
        return f"{label}: на этой системе чтение cookies не поддерживается."
    return f"{label}: {text}" if text else f"{label}: не удалось прочитать cookies."


def import_cookies_from_browser(browser):
    """Извлекает куки из установленного браузера и пишет их в cookies.txt.

    Возвращает {"status": "ok", "count": N, "browser": ...} либо {"error": ...}.
    Результат обязательно проходит очистку: jar.save() пишет значения как есть,
    и cookie с переводом строки внутри разрывала запись на две неполные — yt-dlp
    затем терял такие записи или отвергал весь файл.
    """
    if browser not in supported_browsers():
        return {"error": f"Неизвестный браузер: {browser}"}
    try:
        jar = extract_browser_cookies(browser)
    except Exception as e:
        return {"error": explain_browser_error(browser, e)}

    content, count = cookie_jar_to_netscape(jar)
    if not count:
        label = BROWSER_LABELS.get(browser, browser)
        # Пустой результат нельзя записывать: это затрёт рабочие cookies.
        return {"error": (f"{label}: cookies не найдены. Войдите в аккаунт "
                          f"YouTube в этом браузере и повторите.")}
    try:
        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return {"error": f"Не удалось сохранить cookies.txt: {e}"}
    return {"status": "ok", "count": count, "browser": browser}


# yt-dlp 2026.08 решает «n challenge» YouTube внешним скриптом (EJS), который
# скачивается с GitHub при первом запуске и затем лежит в кэше. В API-режиме
# скачивание по умолчанию запрещено, и yt-dlp ограничивается предупреждением
# «n challenge solving failed: Some formats may be missing», после чего
# ОТБРАСЫВАЕТ все https-форматы. В info остаются только storyboard (mhtml), и
# любой селектор формата падает с «Requested format is not available» — так за
# один прогон провалились все 79 видео задачи. В CLI это ключ
# --remote-components ejs:github.
REMOTE_COMPONENTS = ["ejs:github"]


def build_ydl_args():
    """Формирует аргументы для yt-dlp (extractor_args) по настройкам.

    Важно: extractor-arg youtube:po_token — это ГОТОВЫЙ токен в формате
    "CLIENT.CONTEXT+PO_TOKEN", а не имя провайдера. Раньше туда писалось
    "bgutil:http", и yt-dlp отвечал предупреждением «Invalid po_token
    configuration format», то есть настройка не работала совсем.
    Провайдер подключается автоматически плагином из yt_dlp_plugins; ему
    передаётся только адрес сервера через youtubepot-bgutilhttp:base_url.

    Помимо настроек пользователя всегда разрешаем скачать решатель
    JS-челленджа (см. REMOTE_COMPONENTS): без него список форматов приходит
    пустым независимо от PO Token и cookies.
    """
    opts = get_options()
    args = {}
    client = opts.get("player_client") or ""
    if client:
        args["youtube"] = {"player_client": [client]}
    po = opts.get("po_token") or "off"
    if po == "bgutil:http":
        base_url = (opts.get("bgutil_base_url") or "").strip()
        if base_url:
            args["youtubepot-bgutilhttp"] = {"base_url": [base_url.rstrip('/')]}
    elif po == "bgutil:cli":
        cli_path = find_bgutil_cli()
        if cli_path:
            args["youtubepot-bgutilscript"] = {"script_path": [cli_path]}
    result = {"remote_components": list(REMOTE_COMPONENTS)}
    if args:
        result["extractor_args"] = args
    return result


def apply_ydl_args(opts, args=None):
    """Вливает аргументы авторизации в уже готовые опции yt-dlp.

    Простой dict.update затирал extractor_args целиком: в запросе списка видео
    канала так терялся youtubetab:skip=authcheck, и канал не извлекался, если
    cookies остались от другого аккаунта.
    """
    if args is None:
        args = build_ydl_args()
    for key, value in args.items():
        if key == "extractor_args":
            merged = dict(opts.get("extractor_args") or {})
            for ie, ie_args in value.items():
                section = dict(merged.get(ie) or {})
                section.update(ie_args)
                merged[ie] = section
            opts["extractor_args"] = merged
        elif key == "remote_components":
            existing = list(opts.get("remote_components") or [])
            for item in value:
                if item not in existing:
                    existing.append(item)
            opts["remote_components"] = existing
        else:
            opts.setdefault(key, value)
    return opts


def ensure_plugins():
    """Создаёт плагины getpot_bgutil (yt_dlp_plugins), если их нет."""
    register_plugin_path()
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
        import importlib
        import importlib.util
        # Каталог плагинов создаётся уже после старта процесса, а импортёр
        # кэширует содержимое каталогов: без сброса кэша find_spec продолжал бы
        # отвечать «нет», хотя файлы на диске уже появились.
        importlib.invalidate_caches()
        return importlib.util.find_spec("yt_dlp_plugins") is not None
    except Exception:
        return False


def bgutil_http_alive():
    """Проверяет, отвечает ли локальный bgutil-сервер."""
    base = get_options().get("bgutil_base_url", "http://127.0.0.1:4416")
    try:
        import requests
        # proxies={} обязателен: системный прокси перехватывал бы localhost и
        # проверка всегда падала бы, объявляя живой сервер мёртвым.
        resp = requests.get(base.rstrip('/') + "/ping", timeout=3,
                            proxies={"http": None, "https": None})
        return resp.status_code == 200
    except Exception:
        return False


def find_bgutil_server_main():
    """Ищет собранный build/main.js HTTP-сервера bgutil в tools/."""
    tools = os.path.join(SCRIPT_DIR, "tools")
    if not os.path.isdir(tools):
        return None
    for entry in sorted(os.listdir(tools), reverse=True):
        candidate = os.path.join(tools, entry, "server", "build", "main.js")
        if os.path.isfile(candidate):
            return candidate
    return None


def system_proxy_url():
    """Возвращает адрес системного прокси Windows или ''.

    Python читает эти настройки сам, а Node — нет, поэтому bgutil-серверу
    прокси приходится передавать явно через переменные окружения.
    """
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value if "://" in value else "http://" + value
    if os.name != "nt":
        return ""
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            if not winreg.QueryValueEx(key, "ProxyEnable")[0]:
                return ""
            server = (winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
    except Exception:
        return ""
    if not server:
        return ""
    # Формат может быть «host:port» или «http=host:port;https=host:port».
    if "=" in server:
        parts = dict(p.split("=", 1) for p in server.split(";") if "=" in p)
        server = parts.get("https") or parts.get("http") or ""
        if not server:
            return ""
    return server if "://" in server else "http://" + server


def ensure_bgutil_server(timeout=25):
    """Поднимает локальный bgutil-сервер, если он настроен, но не отвечает.

    Сервер живёт отдельным процессом node и нужен для PO-токена: без него
    YouTube отдаёт HTTP 403 на середине длинных видео.
    """
    if get_options().get("po_token") != "bgutil:http":
        return False
    if bgutil_http_alive():
        return True

    main_js = find_bgutil_server_main()
    node = shutil.which("node")
    if not main_js or not node:
        return False

    try:
        import subprocess
        env = dict(os.environ)
        # NO_PROXY мешает: он выключает прокси и для youtube.com.
        for key in ("NO_PROXY", "no_proxy"):
            env.pop(key, None)
        # Node НЕ использует системный прокси Windows, в отличие от Python.
        # Если доступ к YouTube идёт через прокси (VPN-клиенты вроде xray),
        # провайдер падал с getaddrinfo ENOTFOUND www.youtube.com, токен не
        # выдавался, и YouTube обрезал любую загрузку на 16 МБ.
        proxy = system_proxy_url()
        if proxy and not any(env.get(k) for k in ("HTTPS_PROXY", "https_proxy")):
            env["HTTPS_PROXY"] = proxy
            env["HTTP_PROXY"] = proxy
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [node, main_js], cwd=os.path.dirname(os.path.dirname(main_js)),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, env=env, creationflags=creation)
    except Exception:
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        if bgutil_http_alive():
            return True
        time.sleep(0.5)
    return False


def find_bgutil_script():
    """Ищет generate_once.js из bgutil-ytdlp-pot-provider в tools/.

    Провайдер распространяется исходниками (в npm его нет), поэтому путь
    заранее неизвестен: версия входит в имя каталога.
    """
    tools = os.path.join(SCRIPT_DIR, "tools")
    if not os.path.isdir(tools):
        return None
    for entry in sorted(os.listdir(tools), reverse=True):
        candidate = os.path.join(tools, entry, "server", "build", "generate_once.js")
        if os.path.isfile(candidate):
            return candidate
    return None


def find_bgutil_cli():
    """Путь к генератору PO-токена: сначала собранный скрипт, потом бинарник."""
    script = find_bgutil_script()
    if script:
        return script
    found = shutil.which("bgutil-pot")
    if found:
        return found
    for candidate in (
        os.path.join(SCRIPT_DIR, "bgutil-pot-windows-x86_64.exe"),
        os.path.join(SCRIPT_DIR, "tools", "bgutil-pot-windows-x86_64.exe"),
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def bgutil_cli_available():
    """Доступен ли генератор PO-токена без HTTP-сервера."""
    return find_bgutil_cli() is not None


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
        po_msg = ("генератор найден" if po_ok else
                  "генератор не найден (нужен bgutil-ytdlp-pot-provider в tools/)")
    return {
        "options": opts,
        "cookies_exists": os.path.exists(COOKIES_PATH),
        "plugins_dir": os.path.isdir(PLUGINS_DIR),
        "plugins_loaded": plugins_loaded(),
        "bgutil_http_alive": bgutil_http_alive(),
        "bgutil_cli_available": bgutil_cli_available(),
        "po_token_ok": po_ok,
        "po_token_message": po_msg,
        "bgutil_server_installed": find_bgutil_server_main() is not None,
        "player_client": opts.get("player_client", ""),
        "player_client_choices": PLAYER_CLIENT_CHOICES,
        "po_token_choices": PO_TOKEN_CHOICES,
    }
