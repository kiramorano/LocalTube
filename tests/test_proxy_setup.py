"""Настройка прокси: без неё yt-dlp не мог получить метаданные.

app.py раньше стирал HTTP_PROXY/HTTPS_PROXY. Если доступ к YouTube идёт через
локальный прокси, yt-dlp шёл напрямую и падал с ConnectionResetError(10054)
на «Unable to download API page». Сеть не используется.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import proxy_setup  # noqa: E402


def test_existing_proxy_is_kept():
    """Прокси пользователя должен остаться: без него запросы к YouTube рвутся."""
    env = {"HTTPS_PROXY": "http://127.0.0.1:10809"}

    proxy = proxy_setup.apply_proxy_environment(env)

    assert proxy == "http://127.0.0.1:10809"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:10809"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:10809"


def test_localhost_is_excluded_from_proxy():
    """Запросы к bgutil-серверу на 127.0.0.1 не должны идти через прокси."""
    env = {"HTTPS_PROXY": "http://127.0.0.1:10809"}

    proxy_setup.apply_proxy_environment(env)

    for host in ("127.0.0.1", "localhost", "::1"):
        assert host in env["NO_PROXY"].split(",")
    # requests смотрит на no_proxy в нижнем регистре.
    assert env["no_proxy"] == env["NO_PROXY"]


def test_user_exclusions_are_preserved():
    env = {"HTTPS_PROXY": "http://p:1", "NO_PROXY": "example.com"}

    proxy_setup.apply_proxy_environment(env)

    hosts = env["NO_PROXY"].split(",")
    assert "example.com" in hosts
    assert "127.0.0.1" in hosts


def test_scheme_is_added_to_bare_address():
    """Без схемы yt-dlp не понимает адрес прокси."""
    env = {"HTTP_PROXY": "127.0.0.1:10809"}

    assert proxy_setup.apply_proxy_environment(env) == "http://127.0.0.1:10809"


def test_registry_proxy_is_written_to_environment(monkeypatch):
    """Ключевой случай: NO_PROXY есть, а HTTP(S)_PROXY нет.

    urllib.getproxies() тогда возвращает только «no» и игнорирует прокси из
    реестра Windows, поэтому адрес нужно прописать в переменные явно.
    """
    monkeypatch.setattr(proxy_setup, "registry_proxy_url",
                        lambda: "http://127.0.0.1:10809")
    env = {"NO_PROXY": "127.0.0.1,localhost,::1"}

    proxy = proxy_setup.apply_proxy_environment(env)

    assert proxy == "http://127.0.0.1:10809"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:10809"


def test_no_proxy_variables_without_proxy(monkeypatch):
    """Без прокси в системе переменные придумывать не нужно."""
    monkeypatch.setattr(proxy_setup, "registry_proxy_url", lambda: "")
    env = {}

    assert proxy_setup.apply_proxy_environment(env) == ""
    assert "HTTPS_PROXY" not in env
    assert env["NO_PROXY"].startswith("127.0.0.1")


def test_registry_reads_per_protocol_format(monkeypatch):
    if os.name != "nt":
        pytest.skip("реестр есть только в Windows")

    import winreg

    values = {"ProxyEnable": (1, 0), "ProxyServer": ("http=a:1;https=b:2", 0)}

    class FakeKey:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: FakeKey())
    monkeypatch.setattr(winreg, "QueryValueEx", lambda key, name: values[name])

    assert proxy_setup.registry_proxy_url() == "http://b:2"


def test_disabled_registry_proxy_is_ignored(monkeypatch):
    if os.name != "nt":
        pytest.skip("реестр есть только в Windows")

    import winreg

    class FakeKey:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: FakeKey())
    monkeypatch.setattr(winreg, "QueryValueEx",
                        lambda key, name: {"ProxyEnable": (0, 0),
                                           "ProxyServer": ("a:1", 0)}[name])

    assert proxy_setup.registry_proxy_url() == ""


def test_app_does_not_clear_proxy_variables():
    """Регресс: стирание прокси возвращало ConnectionResetError(10054)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "app.py"), encoding="utf-8") as fh:
        head = fh.read(2000)

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        assert "os.environ.pop('%s'" % var not in head
        assert 'os.environ.pop("%s"' % var not in head
    assert "apply_proxy_environment" in head
