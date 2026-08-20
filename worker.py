#!/usr/bin/env python3
"""
worker.py – УНИВЕРСАЛЬНЫЙ ПОМОЩНИК ДЛЯ LOCALTUBE NEO.
Автоматически отключает прокси для pip.
"""

import os
import sys
import subprocess
import shutil
import platform
import json
import time
import importlib
import importlib.metadata
from pathlib import Path

# ========== КОНСТАНТЫ ==========
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config.json")
COOKIES_PATH = os.path.join(PROJECT_ROOT, "cookies.txt")
PLUGIN_DIR = os.path.join(PROJECT_ROOT, "yt_dlp_plugins")
REQUIRED_DIRS = ["videos", "avas", "subtitles", "playlists", "thumbnails", "uservideos", "static/fonts", "templates"]
REQUIRED_FILES = ["app.py", "downloader.py", "download_lib.py", "po_manager.py", "server.py", "utils.py", "logger.py", "user_videos.py", "subtitles.py"]
REQUIRED_TEMPLATES = ["index.html", "video.html", "upload.html", "edit.html", "playlist.html"]
REQUIRED_FONTS = ["Roboto-Regular.woff2", "Roboto-Medium.woff2", "Roboto-Bold.woff2"]
REQUIRED_PYTHON_PACKAGES = {
    "flask": "Flask",
    "yt-dlp": "yt-dlp",
    "requests": "requests",
    "yt-dlp-ejs": "yt-dlp-ejs",
}
EXTERNAL_TOOLS = {
    "deno": "https://deno.com/",
    "ffmpeg": "https://ffmpeg.org/download.html",
}
CLI_TOOL = "bgutil-pot-windows-x86_64.exe"
PLUGIN_FILES = ["__init__.py", "getpot_bgutil.py", "getpot_bgutil_http.py", "getpot_bgutil_cli.py"]

# ========== ЦВЕТА ==========
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def cprint(text, color=Colors.RESET, bold=False):
    output = f"{Colors.BOLD if bold else ''}{color}{text}{Colors.RESET}"
    try:
        print(output)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(output.encode(encoding, errors="replace").decode(encoding))

# ========== ОБЩИЕ ФУНКЦИИ ==========
def disable_proxy():
    """Отключает все прокси-переменные окружения."""
    for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
        if var in os.environ:
            del os.environ[var]
    cprint("✅ Прокси отключены", Colors.GREEN)

def run_cmd(cmd, capture=True, check=False, no_proxy=True):
    """Выполняет команду, отключая прокси."""
    env = os.environ.copy()
    if no_proxy:
        for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
            if var in env:
                del env[var]
    try:
        if capture:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
            return result.stdout.strip(), result.stderr.strip(), result.returncode
        else:
            return subprocess.run(cmd, shell=True, check=check, env=env)
    except Exception as e:
        return "", str(e), 1

def is_package_installed(package_name):
    try:
        importlib.metadata.distribution(package_name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False

def get_package_version(package_name):
    try:
        return importlib.metadata.distribution(package_name).version
    except:
        return None

def install_package(package_name, extra_args=""):
    cprint(f"Установка {package_name}...", Colors.YELLOW)
    cmd = f'"{sys.executable}" -m pip install {package_name} {extra_args}'
    stdout, stderr, code = run_cmd(cmd)
    if code == 0:
        cprint(f"✅ {package_name} установлен", Colors.GREEN)
        return True
    else:
        cprint(f"❌ Ошибка установки {package_name}: {stderr}", Colors.RED)
        return False

def file_exists(path):
    return os.path.exists(path)

def dir_exists(path):
    return os.path.isdir(path)

def create_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)
        cprint(f"📁 Создана папка: {path}", Colors.CYAN)
        return True
    return False

# ========== ОСНОВНЫЕ ПРОВЕРКИ ==========
def check_python():
    version = sys.version_info
    cprint(f"🐍 Python: {version.major}.{version.minor}.{version.micro}", Colors.CYAN)
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        cprint("⚠️ Рекомендуется Python 3.8 или новее", Colors.YELLOW)
        return False
    return True

def check_pip():
    stdout, stderr, code = run_cmd(f'"{sys.executable}" -m pip --version')
    if code == 0:
        cprint(f"✅ pip: {stdout.split()[1]}", Colors.GREEN)
        return True
    else:
        cprint("❌ pip не найден", Colors.RED)
        return False

def check_python_packages():
    all_ok = True
    cprint("\n📦 Проверка Python-пакетов:", Colors.BOLD)
    for pkg_name, import_name in REQUIRED_PYTHON_PACKAGES.items():
        if is_package_installed(pkg_name):
            version = get_package_version(pkg_name)
            cprint(f"  ✅ {pkg_name} {version if version else ''}", Colors.GREEN)
        else:
            cprint(f"  ❌ {pkg_name} НЕ УСТАНОВЛЕН", Colors.RED)
            all_ok = False
    return all_ok

def check_external_tools():
    all_ok = True
    cprint("\n🔧 Проверка внешних инструментов:", Colors.BOLD)
    
    stdout, stderr, code = run_cmd("deno --version")
    if code == 0:
        version = stdout.split()[1] if stdout else "unknown"
        cprint(f"  ✅ Deno {version}", Colors.GREEN)
    else:
        cprint(f"  ❌ Deno НЕ НАЙДЕН → {EXTERNAL_TOOLS['deno']}", Colors.RED)
        all_ok = False
    
    stdout, stderr, code = run_cmd("ffmpeg -version")
    if code == 0:
        version = stdout.split()[2] if stdout else "unknown"
        cprint(f"  ✅ ffmpeg {version}", Colors.GREEN)
    else:
        cprint(f"  ❌ ffmpeg НЕ НАЙДЕН → {EXTERNAL_TOOLS['ffmpeg']}", Colors.RED)
        all_ok = False
    
    if file_exists(os.path.join(PROJECT_ROOT, CLI_TOOL)):
        cprint(f"  ✅ {CLI_TOOL} найден", Colors.GREEN)
    else:
        cprint(f"  ❌ {CLI_TOOL} НЕ НАЙДЕН", Colors.RED)
        all_ok = False
    
    return all_ok

def check_directories():
    all_ok = True
    cprint("\n📁 Проверка папок:", Colors.BOLD)
    for dir_name in REQUIRED_DIRS:
        full_path = os.path.join(PROJECT_ROOT, dir_name)
        if dir_exists(full_path):
            cprint(f"  ✅ {dir_name}", Colors.GREEN)
        else:
            cprint(f"  ❌ {dir_name} ОТСУТСТВУЕТ", Colors.RED)
            all_ok = False
    return all_ok

def check_files():
    all_ok = True
    cprint("\n📄 Проверка файлов:", Colors.BOLD)
    for file_name in REQUIRED_FILES:
        full_path = os.path.join(PROJECT_ROOT, file_name)
        if file_exists(full_path):
            cprint(f"  ✅ {file_name}", Colors.GREEN)
        else:
            cprint(f"  ❌ {file_name} ОТСУТСТВУЕТ", Colors.RED)
            all_ok = False
    return all_ok

def check_templates():
    all_ok = True
    templates_dir = os.path.join(PROJECT_ROOT, "templates")
    if not dir_exists(templates_dir):
        cprint("  ❌ Папка templates отсутствует", Colors.RED)
        return False
    cprint("\n📄 Проверка шаблонов:", Colors.BOLD)
    for tmpl in REQUIRED_TEMPLATES:
        full_path = os.path.join(templates_dir, tmpl)
        if file_exists(full_path):
            cprint(f"  ✅ {tmpl}", Colors.GREEN)
        else:
            cprint(f"  ❌ {tmpl} ОТСУТСТВУЕТ", Colors.RED)
            all_ok = False
    return all_ok

def check_fonts():
    all_ok = True
    fonts_dir = os.path.join(PROJECT_ROOT, "static", "fonts")
    if not dir_exists(fonts_dir):
        cprint("  ❌ Папка static/fonts отсутствует", Colors.RED)
        return False
    cprint("\n🔤 Проверка шрифтов:", Colors.BOLD)
    for font in REQUIRED_FONTS:
        full_path = os.path.join(fonts_dir, font)
        if file_exists(full_path):
            cprint(f"  ✅ {font}", Colors.GREEN)
        else:
            cprint(f"  ❌ {font} ОТСУТСТВУЕТ", Colors.RED)
            all_ok = False
    return all_ok

def check_cookies():
    if file_exists(COOKIES_PATH):
        size = os.path.getsize(COOKIES_PATH)
        cprint(f"  ✅ cookies.txt ({size} байт)", Colors.GREEN)
        return True
    else:
        cprint("  ❌ cookies.txt ОТСУТСТВУЕТ", Colors.RED)
        cprint("     📌 Инструкция:", Colors.YELLOW)
        cprint("     1. Установите расширение Get cookies.txt для браузера", Colors.YELLOW)
        cprint("     2. Авторизуйтесь на YouTube", Colors.YELLOW)
        cprint("     3. Экспортируйте куки и сохраните как cookies.txt в папку проекта", Colors.YELLOW)
        return False

def check_plugins():
    all_ok = True
    plugin_path = os.path.join(PLUGIN_DIR, "extractor", "getpot_bgutil")
    cprint("\n🧩 Проверка плагинов:", Colors.BOLD)
    if not dir_exists(plugin_path):
        cprint("  ❌ Плагины отсутствуют", Colors.RED)
        return False
    for pf in PLUGIN_FILES:
        full_path = os.path.join(plugin_path, pf)
        if file_exists(full_path):
            cprint(f"  ✅ {pf}", Colors.GREEN)
        else:
            cprint(f"  ❌ {pf} ОТСУТСТВУЕТ", Colors.RED)
            all_ok = False
    return all_ok

def check_config():
    if file_exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            cprint("  ✅ config.json (валидный)", Colors.GREEN)
            return True
        except:
            cprint("  ❌ config.json повреждён", Colors.RED)
            return False
    else:
        cprint("  ❌ config.json ОТСУТСТВУЕТ", Colors.RED)
        return False

# ========== ДЕЙСТВИЯ ==========
def install_all_packages():
    cprint("\n📦 Установка Python-пакетов...", Colors.BOLD)
    disable_proxy()
    # Обновляем pip
    run_cmd(f'"{sys.executable}" -m pip install --upgrade pip')
    
    packages = list(REQUIRED_PYTHON_PACKAGES.keys())
    for pkg in packages:
        if not is_package_installed(pkg):
            install_package(pkg)
        else:
            cprint(f"  ✅ {pkg} уже установлен", Colors.GREEN)
    
    if is_package_installed("yt-dlp"):
        install_package("yt-dlp[default]")

def install_external_tools():
    cprint("\n🔧 Установка внешних инструментов:", Colors.BOLD)
    if not run_cmd("deno --version")[2] == 0:
        cprint("  📌 Для установки Deno выполните:", Colors.YELLOW)
        cprint("     winget install DenoLand.Deno", Colors.CYAN)
        cprint("     Или скачайте с https://deno.com/", Colors.CYAN)
    else:
        cprint("  ✅ Deno уже установлен", Colors.GREEN)
    
    if not run_cmd("ffmpeg -version")[2] == 0:
        cprint("  📌 Для установки ffmpeg выполните:", Colors.YELLOW)
        cprint("     winget install Gyan.FFmpeg", Colors.CYAN)
        cprint("     Или скачайте с https://ffmpeg.org/", Colors.CYAN)
    else:
        cprint("  ✅ ffmpeg уже установлен", Colors.GREEN)

def create_all_dirs():
    cprint("\n📁 Создание папок...", Colors.BOLD)
    for dir_name in REQUIRED_DIRS:
        full_path = os.path.join(PROJECT_ROOT, dir_name)
        create_dir(full_path)

def fix_plugins():
    cprint("\n🧩 Создание плагинов...", Colors.BOLD)
    plugin_base = os.path.join(PLUGIN_DIR, "extractor", "getpot_bgutil")
    os.makedirs(plugin_base, exist_ok=True)
    
    plugin_contents = {
        "__init__.py": 'from .getpot_bgutil import BgUtilPTPBase\nfrom . import getpot_bgutil_http, getpot_bgutil_cli\n__all__ = ["BgUtilPTPBase", "getpot_bgutil", "getpot_bgutil_http", "getpot_bgutil_cli"]\n',
        "getpot_bgutil.py": "from __future__ import annotations\n__version__ = \"0.8.1\"\nimport abc, json\nfrom yt_dlp.extractor.youtube.pot.provider import (\n    ExternalRequestFeature, PoTokenContext, PoTokenProvider,\n    PoTokenProviderRejectedRequest,\n)\nfrom yt_dlp.extractor.youtube.pot.utils import WEBPO_CLIENTS\nfrom yt_dlp.utils import js_to_json\nfrom yt_dlp.utils.traversal import traverse_obj\n\nclass BgUtilPTPBase(PoTokenProvider, abc.ABC):\n    PROVIDER_VERSION = __version__\n    BUG_REPORT_LOCATION = \"https://github.com/jim60105/bgutil-ytdlp-pot-provider/issues\"\n    _SUPPORTED_EXTERNAL_REQUEST_FEATURES = (\n        ExternalRequestFeature.PROXY_SCHEME_HTTP,\n        ExternalRequestFeature.PROXY_SCHEME_HTTPS,\n        ExternalRequestFeature.PROXY_SCHEME_SOCKS4,\n        ExternalRequestFeature.PROXY_SCHEME_SOCKS4A,\n        ExternalRequestFeature.PROXY_SCHEME_SOCKS5,\n        ExternalRequestFeature.PROXY_SCHEME_SOCKS5H,\n        ExternalRequestFeature.SOURCE_ADDRESS,\n        ExternalRequestFeature.DISABLE_TLS_VERIFICATION,\n    )\n    _SUPPORTED_CLIENTS = WEBPO_CLIENTS\n    _SUPPORTED_CONTEXTS = (PoTokenContext.GVS, PoTokenContext.PLAYER, PoTokenContext.SUBS)\n    _GETPOT_TIMEOUT = 20.0\n    _GET_SERVER_VSN_TIMEOUT = 5.0\n    _MIN_NODE_VSN = (18, 0, 0)\n\n    def _info_and_raise(self, msg, raise_from=None):\n        self.logger.info(msg)\n        raise PoTokenProviderRejectedRequest(msg) from raise_from\n\n    def _warn_and_raise(self, msg, once=True, raise_from=None):\n        self.logger.warning(msg, once=once)\n        raise PoTokenProviderRejectedRequest(msg) from raise_from\n\n    def _get_attestation(self, webpage: str | None):\n        if not webpage:\n            return None\n        raw_cd = (\n            traverse_obj(\n                self.ie._search_regex(\n                    r\"(?sx)window\\s*\\.\\s*ytAtN\\s*\\(\\s*(?P<js>\\{.+?}\\s*)\\s*\\)\\s*;\",\n                    webpage, \"ytAtN challenge\", default=None),\n                ({js_to_json}, {json.loads}, \"R\"))\n            or traverse_obj(\n                self.ie._search_regex(\n                    r\"(?sx)window\\.ytAtR\\s*=\\s*(?P<raw_cd>(?P<q>[\\\"'])(?:\\.|(?!(?P=q)).)*(?P=q))\\s*;\",\n                    webpage, \"ytAtR challenge\", default=None),\n                ({js_to_json}, {json.loads})))\n        if att_txt := traverse_obj(raw_cd, ({json.loads}, \"bgChallenge\")):\n            return att_txt\n        self.logger.warning(\"Failed to extract initial attestation\")\n        return None\n\n__all__ = [\"__version__\"]\n",
        "getpot_bgutil_http.py": "from __future__ import annotations\nimport functools, json, time\nfrom yt_dlp.extractor.youtube.pot.provider import (\n    PoTokenProviderError, PoTokenProviderRejectedRequest, PoTokenRequest,\n    PoTokenResponse, register_preference, register_provider,\n)\nfrom yt_dlp.extractor.youtube.pot.utils import get_webpo_content_binding\nfrom yt_dlp.networking.common import Request\nfrom yt_dlp.networking.exceptions import HTTPError, TransportError\nfrom yt_dlp_plugins.extractor.getpot_bgutil import BgUtilPTPBase\n\n@register_provider\nclass BgUtilHTTPPTP(BgUtilPTPBase):\n    PROVIDER_NAME = \"bgutil:http\"\n    DEFAULT_BASE_URL = \"http://127.0.0.1:4416\"\n    def __init__(self, *args, **kwargs):\n        super().__init__(*args, **kwargs)\n        self._last_server_check = 0\n        self._server_available = True\n    @functools.cached_property\n    def _base_url(self):\n        base_url = self._configuration_arg(\"base_url\", default=[None])[0]\n        if base_url:\n            return base_url\n        self.logger.debug(f\"No base_url provided, defaulting to {self.DEFAULT_BASE_URL}\")\n        return self.DEFAULT_BASE_URL\n    def _check_server_availability(self, ctx: PoTokenRequest):\n        if self._last_server_check + 60 > time.time():\n            return self._server_available\n        self._server_available = False\n        try:\n            self.logger.trace(f\"Checking server at {self._base_url}/ping\")\n            response = json.load(self._request_webpage(Request(\n                f\"{self._base_url}/ping\",\n                extensions={\"timeout\": self._GET_SERVER_VSN_TIMEOUT},\n                proxies={\"all\": None}\n            ), note=False))\n        except TransportError as e:\n            self._warn_and_raise(\n                f\"Error reaching {self._base_url}/ping (caused by {e.__class__.__name__}). \"\n                f\"Please make sure server is reachable.\")\n            return\n        except HTTPError as e:\n            self.logger.warning(f\"HTTP Error reaching /ping (caused by {e!r})\", once=True)\n            return\n        except json.JSONDecodeError as e:\n            self._warn_and_raise(f\"Error parsing ping response JSON (caused by {e!r})\")\n            return\n        except Exception as e:\n            self._warn_and_raise(f\"Unknown error reaching GET /ping (caused by {e!r})\", raise_from=e)\n            return\n        else:\n            version = response.get(\"version\", \"unknown\")\n            self.logger.debug(f\"HTTP server version: {version}\")\n            self._server_available = True\n            return True\n        finally:\n            self._last_server_check = time.time()\n    def is_available(self):\n        return (self._server_available or self._last_server_check + 60 < int(time.time()))\n    def _real_request_pot(self, request: PoTokenRequest) -> PoTokenResponse:\n        if not self._check_server_availability(request):\n            raise PoTokenProviderRejectedRequest(f\"{self.PROVIDER_NAME} server not available\")\n        self.logger.trace(\"Generating POT via HTTP server\")\n        disable_innertube = bool(self._configuration_arg(\"disable_innertube\", default=[None])[0])\n        challenge = self._get_attestation(None if disable_innertube else request.video_webpage)\n        if not challenge and request.internal_client_name == \"web_music\":\n            if not disable_innertube:\n                self.logger.warning(\"BotGuard challenges missing, overriding disable_innertube=True\")\n            disable_innertube = True\n        try:\n            response = self._request_webpage(\n                request=Request(\n                    f\"{self._base_url}/get_pot\", data=json.dumps({\n                        \"bypass_cache\": request.bypass_cache,\n                        \"challenge\": challenge,\n                        \"content_binding\": get_webpo_content_binding(request)[0],\n                        \"disable_innertube\": disable_innertube,\n                        \"disable_tls_verification\": not request.request_verify_tls,\n                        \"proxy\": request.request_proxy,\n                        \"innertube_context\": request.innertube_context,\n                        \"source_address\": request.request_source_address,\n                    }).encode(), headers={\"Content-Type\": \"application/json\"},\n                    extensions={\"timeout\": self._GETPOT_TIMEOUT},\n                    proxies={\"all\": None}\n                ),\n                note=f\"Generating PO Token for {request.internal_client_name} client via bgutil HTTP server\",\n            )\n        except Exception as e:\n            raise PoTokenProviderError(f\"Error reaching POST /get_pot (caused by {e!r})\") from e\n        try:\n            response_json = json.load(response)\n        except Exception as e:\n            response_data = response.read().decode()\n            raise PoTokenProviderError(\n                f\"Error parsing response JSON (caused by {e!r}). response = {response_data}\"\n            ) from e\n        if error_msg := response_json.get(\"error\"):\n            raise PoTokenProviderError(error_msg)\n        if \"poToken\" not in response_json:\n            raise PoTokenProviderError(f\"Server did not respond with a poToken. Received: {response}\")\n        po_token = response_json[\"poToken\"]\n        self.logger.trace(f\"Generated POT: {po_token}\")\n        return PoTokenResponse(po_token=po_token)\n\n@register_preference(BgUtilHTTPPTP)\ndef bgutil_HTTP_getpot_preference(provider, request):\n    return 130\n\n__all__ = [BgUtilHTTPPTP.__name__, bgutil_HTTP_getpot_preference.__name__]\n",
        "getpot_bgutil_cli.py": "from __future__ import annotations\nimport functools, json, os.path, shutil, subprocess\nfrom yt_dlp.extractor.youtube.pot.provider import (\n    PoTokenProviderError, PoTokenRequest, PoTokenResponse,\n    register_preference, register_provider,\n)\nfrom yt_dlp.extractor.youtube.pot.utils import get_webpo_content_binding\nfrom yt_dlp.utils import Popen\nfrom yt_dlp_plugins.extractor.getpot_bgutil import BgUtilPTPBase\n\n@register_provider\nclass BgUtilCliPTP(BgUtilPTPBase):\n    PROVIDER_NAME = \"bgutil:cli\"\n    def __init__(self, *args, **kwargs):\n        super().__init__(*args, **kwargs)\n        self._check_cli = functools.cache(self._check_cli_impl)\n    @functools.cached_property\n    def _cli_path(self):\n        cli_path = self._configuration_arg(\"cli_path\", casesense=True, default=[None])[0]\n        if cli_path:\n            return os.path.expandvars(cli_path)\n        if self._get_executable_path(\"bgutil-pot\"):\n            self.logger.debug(\"Found bgutil-pot in PATH\")\n            return \"bgutil-pot\"\n        file_paths = [\n            os.path.join(os.getcwd(), \"target\", \"debug\", \"bgutil-pot\"),\n            os.path.join(os.getcwd(), \"target\", \"release\", \"bgutil-pot\"),\n            os.path.expanduser(\"~/bgutil-ytdlp-pot-provider/target/debug/bgutil-pot\"),\n            os.path.expanduser(\"~/bgutil-ytdlp-pot-provider/target/release/bgutil-pot\"),\n        ]\n        for path in file_paths:\n            if self._get_executable_path(path):\n                self.logger.debug(f\"Found bgutil-pot at: {path}\")\n                return path\n        self.logger.debug(\"No CLI path found, defaulting to bgutil-pot\")\n        return \"bgutil-pot\"\n    def is_available(self):\n        return self._check_cli(self._cli_path)\n    def _get_executable_path(self, cli_path):\n        if os.path.sep not in cli_path:\n            executable_path = shutil.which(cli_path)\n            if executable_path:\n                return executable_path\n        if os.path.isfile(cli_path):\n            return cli_path\n        return None\n    def _check_cli_impl(self, cli_path):\n        executable_path = self._get_executable_path(cli_path)\n        if not executable_path:\n            self.logger.debug(f\"Executable path doesn\'t exist: {cli_path}\")\n            return False\n        stdout, stderr, returncode = Popen.run(\n            [executable_path, \"--version\"],\n            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,\n            timeout=self._GET_SERVER_VSN_TIMEOUT\n        )\n        if returncode:\n            self.logger.warning(\n                f\"Failed to check executable version. Returncode {returncode}\", once=True)\n            return False\n        else:\n            self.logger.debug(f\"bgutil-pot version: {stdout.strip()}\")\n            return True\n    def _real_request_pot(self, request: PoTokenRequest) -> PoTokenResponse:\n        self.logger.trace(f\"Generating POT via Rust executable: {self._cli_path}\")\n        executable_path = self._get_executable_path(self._cli_path)\n        if not executable_path:\n            raise PoTokenProviderError(f\"Executable not found: {self._cli_path}\")\n        command_args = [executable_path]\n        if proxy := request.request_proxy:\n            command_args.extend([\"-p\", proxy])\n        command_args.extend([\"-c\", get_webpo_content_binding(request)[0]])\n        if request.bypass_cache:\n            command_args.append(\"--bypass-cache\")\n        if request.request_source_address:\n            command_args.extend([\"--source-address\", request.request_source_address])\n        if request.request_verify_tls is False:\n            command_args.append(\"--disable-tls-verification\")\n        self.logger.info(\n            f\"Generating {request.context.value} PO Token for {request.internal_client_name} client via bgutil CLI\")\n        self.logger.debug(f\"Command: {\" \".join(command_args)}\")\n        try:\n            stdout, stderr, returncode = Popen.run(\n                command_args,\n                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,\n                timeout=self._GETPOT_TIMEOUT\n            )\n        except subprocess.TimeoutExpired as e:\n            raise PoTokenProviderError(f\"_get_pot_via_cli timeout (caused by {e!r})\")\n        except Exception as e:\n            raise PoTokenProviderError(f\"_get_pot_via_cli failed (caused by {e!r})\") from e\n        msg = \"\"\n        if stdout_extra := stdout.strip().splitlines()[:-1]:\n            msg = f\"stdout:\\\\n{stdout_extra}\\\\n\"\n        if stderr_stripped := stderr.strip():\n            msg += f\"stderr:\\\\n{stderr_stripped}\\\\n\"\n        if msg:\n            self.logger.trace(msg)\n        if returncode:\n            raise PoTokenProviderError(f\"_get_pot_via_cli failed with returncode {returncode}\")\n        try:\n            json_resp = stdout.splitlines()[-1]\n            self.logger.trace(f\"JSON response:\\\\n{json_resp}\")\n            cli_data_resp = json.loads(json_resp)\n        except json.JSONDecodeError as e:\n            raise PoTokenProviderError(f\"Error parsing JSON (caused by {e!r})\") from e\n        if \"poToken\" not in cli_data_resp:\n            raise PoTokenProviderError(\"Executable did not respond with a po_token\")\n        return PoTokenResponse(po_token=cli_data_resp[\"poToken\"])\n\n@register_preference(BgUtilCliPTP)\ndef bgutil_cli_getpot_preference(provider, request):\n    return 1\n\n__all__ = [BgUtilCliPTP.__name__, bgutil_cli_getpot_preference.__name__]\n",
    }
    
    for filename, content in plugin_contents.items():
        filepath = os.path.join(plugin_base, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        cprint(f"  ✅ Создан {filename}", Colors.GREEN)
    
    extractor_init = os.path.join(PLUGIN_DIR, "extractor", "__init__.py")
    if not os.path.exists(extractor_init):
        with open(extractor_init, 'w') as f:
            f.write("# Plugin package\n")
        cprint("  ✅ Создан extractor/__init__.py", Colors.GREEN)

def fix_config():
    if not file_exists(CONFIG_FILE):
        default_config = {
            "video_dir": "videos",
            "avatars_dir": "avas",
            "thumbnails_dir": "thumbnails",
            "playlists_dir": "playlists",
            "subtitles_dir": "subtitles"
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2)
        cprint("  ✅ Создан config.json", Colors.GREEN)

def update_packages():
    cprint("\n🔄 Обновление пакетов...", Colors.BOLD)
    disable_proxy()
    packages = list(REQUIRED_PYTHON_PACKAGES.keys())
    for pkg in packages:
        if is_package_installed(pkg):
            cprint(f"  ⬆️ Обновление {pkg}...", Colors.YELLOW)
            install_package(f"{pkg} --upgrade")
        else:
            install_package(pkg)

def fix_all():
    cprint("\n🔧 Запуск полного исправления...", Colors.BOLD)
    create_all_dirs()
    fix_plugins()
    fix_config()
    install_all_packages()
    install_external_tools()
    cprint("\n✅ Исправление завершено!", Colors.GREEN)

def check_all():
    cprint("\n🔍 ДИАГНОСТИКА LOCALTUBE NEO", Colors.BOLD)
    cprint("=" * 50, Colors.CYAN)
    
    results = {}
    results["python"] = check_python()
    results["pip"] = check_pip()
    results["packages"] = check_python_packages()
    results["tools"] = check_external_tools()
    results["dirs"] = check_directories()
    results["files"] = check_files()
    results["templates"] = check_templates()
    results["fonts"] = check_fonts()
    results["cookies"] = check_cookies()
    results["plugins"] = check_plugins()
    results["config"] = check_config()
    
    cprint("\n" + "=" * 50, Colors.CYAN)
    
    all_ok = all(results.values())
    if all_ok:
        cprint("✅ ВСЁ В ПОРЯДКЕ! Проект готов к запуску.", Colors.GREEN, bold=True)
    else:
        cprint("⚠️ НАЙДЕНЫ ПРОБЛЕМЫ! Запустите: python worker.py fix", Colors.RED, bold=True)
        
        cprint("\n📋 Детали:", Colors.BOLD)
        for name, status in results.items():
            if status:
                cprint(f"  ✅ {name}: OK", Colors.GREEN)
            else:
                cprint(f"  ❌ {name}: ТРЕБУЕТ ВНИМАНИЯ", Colors.RED)
    
    return all_ok

# ========== ПОМОЩЬ ==========
def show_help():
    help_text = f"""
{Colors.CYAN}{Colors.BOLD}worker.py – Универсальный помощник для LocalTube NEO{Colors.RESET}

{Colors.YELLOW}Команды:{Colors.RESET}
  {Colors.GREEN}check{Colors.RESET}    — Проверить всё окружение
  {Colors.GREEN}install{Colors.RESET}  — Установить недостающие пакеты и инструменты
  {Colors.GREEN}fix{Colors.RESET}      — Создать недостающие папки, файлы, плагины
  {Colors.GREEN}update{Colors.RESET}   — Обновить все пакеты
  {Colors.GREEN}status{Colors.RESET}   — Показать краткий статус
  {Colors.GREEN}auto{Colors.RESET}     — Выполнить check + fix + install (всё автоматически)
  {Colors.GREEN}help{Colors.RESET}     — Показать эту справку

{Colors.YELLOW}Примеры:{Colors.RESET}
  python worker.py check
  python worker.py auto
"""
    print(help_text)

# ========== ГЛАВНАЯ ФУНКЦИЯ ==========
def main():
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == "check":
        check_all()
    elif command == "install":
        install_all_packages()
        install_external_tools()
    elif command == "fix":
        fix_all()
    elif command == "update":
        update_packages()
    elif command == "status":
        check_python()
        check_pip()
        check_python_packages()
        check_external_tools()
        check_cookies()
    elif command == "auto":
        cprint("\n🚀 ЗАПУСК АВТОМАТИЧЕСКОЙ НАСТРОЙКИ...", Colors.BOLD, bold=True)
        if not check_all():
            fix_all()
            install_all_packages()
            check_all()
        else:
            cprint("\n✅ Всё уже настроено! Запускайте app.py", Colors.GREEN)
    elif command == "help":
        show_help()
    else:
        cprint(f"❌ Неизвестная команда: {command}", Colors.RED)
        show_help()

if __name__ == "__main__":
    main()