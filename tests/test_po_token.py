"""PO Token: аргументы для yt-dlp и поиск провайдера.

Без токена YouTube отдаёт HTTP 403 на середине длинных видео, поэтому важно,
что настройка реально доходит до yt-dlp, а не отбрасывается им как мусор.
Сеть не используется.
"""
import os

import pytest

import auth_options


@pytest.fixture
def options(monkeypatch):
    """Подменяет настройки авторизации, не трогая config.json."""
    def _set(**kwargs):
        opts = {"player_client": "", "po_token": "off",
                "bgutil_base_url": "http://127.0.0.1:4416"}
        opts.update(kwargs)
        monkeypatch.setattr(auth_options, "get_options", lambda: opts)
        return opts
    return _set


def test_po_token_is_not_passed_as_provider_name(options):
    """extractor-arg youtube:po_token — это готовый токен, а не имя провайдера.

    Раньше туда писалось "bgutil:http", и yt-dlp отвечал предупреждением
    «Invalid po_token configuration format», то есть настройка не работала.
    """
    options(po_token="bgutil:http")

    args = auth_options.build_ydl_args()

    youtube_args = args.get("extractor_args", {}).get("youtube", {})
    assert "po_token" not in youtube_args


def test_http_provider_receives_base_url(options):
    options(po_token="bgutil:http", bgutil_base_url="http://127.0.0.1:4416")

    args = auth_options.build_ydl_args()

    assert args["extractor_args"]["youtubepot-bgutilhttp"]["base_url"] == \
        ["http://127.0.0.1:4416"]


def test_base_url_trailing_slash_is_trimmed(options):
    """Плагин склеивает адрес с /ping, двойной слэш давал бы 404."""
    options(po_token="bgutil:http", bgutil_base_url="http://127.0.0.1:4416/")

    args = auth_options.build_ydl_args()

    assert args["extractor_args"]["youtubepot-bgutilhttp"]["base_url"] == \
        ["http://127.0.0.1:4416"]


def test_disabled_po_token_adds_no_extractor_args(options):
    """При выключенном токене extractor_args быть не должно.

    remote_components остаётся: решатель JS-челленджа нужен всегда, иначе
    YouTube не отдаёт ни одного формата.
    """
    options(po_token="off")

    args = auth_options.build_ydl_args()

    assert "extractor_args" not in args
    assert list(args) == ["remote_components"]


def test_player_client_still_passed(options):
    options(player_client="tv", po_token="off")

    args = auth_options.build_ydl_args()

    assert args["extractor_args"]["youtube"]["player_client"] == ["tv"]


def test_player_client_and_po_token_coexist(options):
    """Обе настройки должны попадать в разные секции, не затирая друг друга."""
    options(player_client="web_safari", po_token="bgutil:http")

    args = auth_options.build_ydl_args()["extractor_args"]

    assert args["youtube"]["player_client"] == ["web_safari"]
    assert "youtubepot-bgutilhttp" in args


def test_yt_dlp_accepts_arguments_without_warning(options):
    """Проверка на настоящем yt-dlp: предупреждений о формате быть не должно."""
    yt_dlp = pytest.importorskip("yt_dlp")
    from yt_dlp.extractor.youtube._video import _PoTokenContext

    options(po_token="bgutil:http")
    args = auth_options.build_ydl_args()

    warnings = []
    ydl = yt_dlp.YoutubeDL({"quiet": True, **args})
    ie = ydl.get_info_extractor("Youtube")
    ie.set_downloader(ydl)
    ie.report_warning = lambda msg, *a, **k: warnings.append(str(msg))
    ie.write_debug = lambda *a, **k: None

    ie._get_config_po_token("web", _PoTokenContext.GVS)

    assert not [w for w in warnings if "po_token" in w], warnings


def test_script_path_points_to_existing_file(options):
    """Для скриптового режима путь должен указывать на реальный generate_once.js."""
    script = auth_options.find_bgutil_script()
    if not script:
        pytest.skip("провайдер bgutil не установлен в tools/")

    options(po_token="bgutil:cli")
    args = auth_options.build_ydl_args()["extractor_args"]

    path = args["youtubepot-bgutilscript"]["script_path"][0]
    assert os.path.isfile(path)
    assert os.path.basename(path) == "generate_once.js"


def test_finders_return_none_without_tools(monkeypatch, tmp_path):
    """Отсутствие tools/ не должно приводить к исключению."""
    monkeypatch.setattr(auth_options, "SCRIPT_DIR", str(tmp_path))

    assert auth_options.find_bgutil_script() is None
    assert auth_options.find_bgutil_server_main() is None


def test_ensure_server_skipped_when_disabled(options, monkeypatch):
    """При выключенном PO token сервер поднимать не нужно."""
    options(po_token="off")
    called = []
    monkeypatch.setattr(auth_options, "find_bgutil_server_main",
                        lambda: called.append(1))

    assert auth_options.ensure_bgutil_server() is False
    assert called == []


def test_ensure_server_returns_true_if_already_alive(options, monkeypatch):
    """Живой сервер не должен запускаться повторно."""
    options(po_token="bgutil:http")
    monkeypatch.setattr(auth_options, "bgutil_http_alive", lambda: True)
    started = []
    monkeypatch.setattr(auth_options, "find_bgutil_server_main",
                        lambda: started.append(1))

    assert auth_options.ensure_bgutil_server() is True
    assert started == []


def test_alive_check_bypasses_proxy(options, monkeypatch):
    """Системный прокси перехватывал localhost и объявлял живой сервер мёртвым."""
    options(po_token="bgutil:http")
    seen = {}

    class FakeResponse:
        status_code = 200

    def fake_get(url, timeout=None, proxies=None):
        seen["url"] = url
        seen["proxies"] = proxies
        return FakeResponse()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)

    assert auth_options.bgutil_http_alive() is True
    assert seen["url"].endswith("/ping")
    assert seen["proxies"] == {"http": None, "https": None}


def _launch_env(options, monkeypatch, env_before):
    """Запускает ensure_bgutil_server со стабом Popen и возвращает env запуска."""
    options(po_token="bgutil:http")
    monkeypatch.setattr(auth_options, "bgutil_http_alive", lambda: True)
    monkeypatch.setattr(auth_options, "find_bgutil_server_main",
                        lambda: os.path.join("srv", "build", "main.js"))
    monkeypatch.setattr(auth_options.shutil, "which", lambda name: "node.exe")
    for key, value in env_before.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    captured = {}

    class FakePopen:
        def __init__(self, *args, **kwargs):
            captured["env"] = kwargs.get("env") or {}

    import subprocess

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    # bgutil_http_alive возвращает True, поэтому нужно обойти ранний выход.
    monkeypatch.setattr(auth_options, "bgutil_http_alive",
                        lambda _c=[0]: bool(_c.append(1)) or len(_c) > 2)

    auth_options.ensure_bgutil_server(timeout=1)
    return captured.get("env", {})


def test_server_gets_system_proxy(options, monkeypatch):
    """Node не читает прокси Windows сам.

    Без прокси провайдер падал с getaddrinfo ENOTFOUND www.youtube.com, токен
    не выдавался, и YouTube обрывал загрузку на 13-17 МБ с HTTP 403.
    """
    monkeypatch.setattr(auth_options, "system_proxy_url",
                        lambda: "http://127.0.0.1:10809")

    env = _launch_env(options, monkeypatch,
                      {"HTTPS_PROXY": None, "HTTP_PROXY": None, "NO_PROXY": "127.0.0.1"})

    assert env.get("HTTPS_PROXY") == "http://127.0.0.1:10809"
    assert env.get("HTTP_PROXY") == "http://127.0.0.1:10809"
    # NO_PROXY выключил бы прокси и для youtube.com.
    assert "NO_PROXY" not in env and "no_proxy" not in env


def test_existing_proxy_is_not_overridden(options, monkeypatch):
    """Явно заданный прокси пользователя важнее системного."""
    monkeypatch.setattr(auth_options, "system_proxy_url",
                        lambda: "http://127.0.0.1:10809")

    env = _launch_env(options, monkeypatch, {"HTTPS_PROXY": "http://proxy:3128"})

    assert env.get("HTTPS_PROXY") == "http://proxy:3128"


def test_no_proxy_variables_without_system_proxy(options, monkeypatch):
    """Без прокси в системе переменные добавлять не нужно."""
    monkeypatch.setattr(auth_options, "system_proxy_url", lambda: "")

    env = _launch_env(options, monkeypatch, {"HTTPS_PROXY": None, "HTTP_PROXY": None})

    assert "HTTPS_PROXY" not in env
    assert "HTTP_PROXY" not in env


def test_system_proxy_prefers_environment(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "127.0.0.1:9999")

    # Схема добавляется, иначе Node не понимает адрес.
    assert auth_options.system_proxy_url() == "http://127.0.0.1:9999"


def test_system_proxy_reads_per_protocol_registry(monkeypatch):
    """Windows хранит прокси и в виде «http=host:port;https=host:port»."""
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    if os.name != "nt":
        pytest.skip("реестр есть только в Windows")

    import winreg

    values = {"ProxyEnable": (1, 0), "ProxyServer": ("http=a:1;https=b:2", 0)}

    class FakeKey:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: FakeKey())
    monkeypatch.setattr(winreg, "QueryValueEx", lambda key, name: values[name])

    assert auth_options.system_proxy_url() == "http://b:2"


def test_ydl_args_allow_challenge_solver(options):
    """yt-dlp 2026.08 решает n challenge внешним скриптом (EJS).

    Без разрешения скачать его он пишет «n challenge solving failed» и
    отбрасывает ВСЕ https-форматы: остаются одни storyboard, и любая загрузка
    падает с «Requested format is not available».
    """
    options(po_token="off")

    args = auth_options.build_ydl_args()

    assert "ejs:github" in args.get("remote_components", [])


def test_challenge_solver_allowed_together_with_po_token(options):
    """Разрешение решателя не должно вытеснять extractor_args."""
    options(po_token="bgutil:http", player_client="tv")

    args = auth_options.build_ydl_args()

    assert "ejs:github" in args["remote_components"]
    assert args["extractor_args"]["youtube"]["player_client"] == ["tv"]
    assert "youtubepot-bgutilhttp" in args["extractor_args"]


def test_apply_keeps_foreign_extractor_args(options):
    """opts.update затирал extractor_args целиком.

    В запросе видео канала так терялся youtubetab:skip=authcheck, и канал не
    извлекался, если cookies остались от другого аккаунта.
    """
    options(po_token="bgutil:http", player_client="tv")
    opts = {"extractor_args": {"youtubetab": {"skip": ["authcheck"]}}}

    auth_options.apply_ydl_args(opts)

    assert opts["extractor_args"]["youtubetab"]["skip"] == ["authcheck"]
    assert opts["extractor_args"]["youtube"]["player_client"] == ["tv"]
    assert "youtubepot-bgutilhttp" in opts["extractor_args"]
    assert "ejs:github" in opts["remote_components"]


def test_apply_merges_remote_components_without_losing_existing(options):
    """Уже разрешённые компоненты нельзя терять при вливании настроек."""
    options(po_token="off")
    opts = {"remote_components": ["ejs:npm"]}

    auth_options.apply_ydl_args(opts)

    assert opts["remote_components"] == ["ejs:npm", "ejs:github"]


def test_apply_does_not_duplicate_remote_components(options):
    """Повторный вызов не должен размножать одно и то же значение."""
    options(po_token="off")
    opts = {}

    auth_options.apply_ydl_args(opts)
    auth_options.apply_ydl_args(opts)

    assert opts["remote_components"] == ["ejs:github"]


def test_apply_adds_remote_components_to_empty_opts(options):
    """Пустые опции тоже должны получить разрешение на решатель."""
    options(po_token="off")
    opts = {}

    auth_options.apply_ydl_args(opts)

    assert opts["remote_components"] == ["ejs:github"]


def test_save_options_keeps_other_config_keys(tmp_path, monkeypatch):
    """Настройки авторизации не должны затирать пути к библиотеке."""
    from utils import read_json, write_json_atomic

    config = tmp_path / "config.json"
    write_json_atomic(str(config), {"video_dir": "videos", "avatars_dir": "avas"})
    monkeypatch.setattr(auth_options, "CONFIG_FILE", str(config))

    assert auth_options.save_options({"po_token": "bgutil:http"}) is True

    saved = read_json(str(config), default={})
    assert saved["video_dir"] == "videos"
    assert saved["avatars_dir"] == "avas"
    assert saved["youtube_auth"]["po_token"] == "bgutil:http"
