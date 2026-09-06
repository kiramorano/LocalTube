"""Импорт cookies: битые строки не должны ломать весь файл.

В логе пользователя yt-dlp отвергал cookies.txt целиком с сообщением
«does not look like a Netscape format cookies file», потому что значение одной
cookie содержало перевод строки и разрывало запись на две неполные.
Сеть не используется.
"""
import io
import os

import pytest


HEADER = "# Netscape HTTP Cookie File"


def _good(name="SID", value="abc"):
    return "\t".join([".youtube.com", "TRUE", "/", "TRUE", "1814618168", name, value])


def _write(client, text):
    return client.post("/api/cookies/import", json={"text": text})


@pytest.fixture(autouse=True)
def cookies_path(app_module, tmp_path, monkeypatch):
    """Настоящий cookies.txt пользователя трогать нельзя.

    Путь подменяется во всех модулях, которые пишут этот файл: импорт текстом
    идёт через app, импорт из браузера — через auth_options.
    """
    import auth_options

    path = str(tmp_path / "cookies.txt")
    monkeypatch.setattr(app_module, "COOKIES_PATH", path)
    monkeypatch.setattr(auth_options, "COOKIES_PATH", path)
    return path


def test_valid_cookies_are_saved(client, cookies_path):
    res = _write(client, HEADER + "\n" + _good() + "\n")

    assert res.status_code == 200
    assert res.get_json().get("error") is None
    saved = open(cookies_path, encoding="utf-8").read()
    assert "SID" in saved


def test_broken_entry_is_dropped(client, cookies_path):
    """Строка с неверным числом полей не должна попадать в файл."""
    broken = "\t".join([".stg.html-load.com", "TRUE", "/ses"])
    tail = "\t".join(["sion/g8c", "TRUE", "1814618168", "img_x", "1783082168"])

    res = _write(client, "\n".join([HEADER, broken, tail, _good()]) + "\n")

    assert res.status_code == 200
    saved = open(cookies_path, encoding="utf-8").read()
    assert "SID" in saved, "нормальная cookie потеряна"
    assert "stg.html-load.com" not in saved, "битая запись сохранена"


def test_saved_file_is_accepted_by_yt_dlp(client, cookies_path):
    """Проверка на настоящем yt-dlp: файл должен читаться без предупреждений."""
    yt_dlp = pytest.importorskip("yt_dlp")
    broken = "\t".join([".x.com", "TRUE", "/ses"])

    _write(client, "\n".join([HEADER, broken, _good()]) + "\n")

    warnings = []

    class Logger:
        def debug(self, m): pass
        def info(self, m): pass
        def warning(self, m): warnings.append(str(m))
        def error(self, m): warnings.append(str(m))

    ydl = yt_dlp.YoutubeDL({"quiet": True, "cookiefile": cookies_path,
                            "logger": Logger()})

    assert len(ydl.cookiejar) == 1
    assert not [w for w in warnings if "invalid length" in w], warnings


def test_reported_count_matches_saved(client, cookies_path):
    """Счётчик не должен считать битые строки принятыми."""
    broken = "\t".join([".x.com", "TRUE", "/ses"])

    body = _write(client, "\n".join([HEADER, broken, _good(), _good("HSID", "d")]) + "\n").get_json()

    assert body.get("cookies_count") == 2, body


def test_json_cookies_with_newline_are_sanitised(client, cookies_path):
    """Значение с переводом строки из JSON тоже нельзя писать как есть."""
    payload = [{"domain": ".youtube.com", "path": "/", "secure": True,
                "expires": 1814618168, "name": "SID", "value": "a\nb"}]

    res = client.post("/api/cookies/import", json={"text": __import__("json").dumps(payload)})

    assert res.status_code == 200
    saved = open(cookies_path, encoding="utf-8").read()
    entries = [l for l in saved.splitlines() if l.strip() and not l.startswith("#")]
    assert all(len(l.split("\t")) == 7 for l in entries), entries
    # Cookie должна сохраниться, а не пропасть вместе с переводом строки.
    assert len(entries) == 1, entries
    assert entries[0].split("\t")[6] == "a b", entries[0]


def test_json_cookies_with_tab_are_sanitised(client, cookies_path):
    """Табуляция внутри значения — такой же разрыв записи, как перевод строки."""
    payload = [{"domain": ".youtube.com", "path": "/", "secure": True,
                "expires": 1814618168, "name": "SID", "value": "a\tb"}]

    client.post("/api/cookies/import", json={"text": __import__("json").dumps(payload)})

    saved = open(cookies_path, encoding="utf-8").read()
    entries = [l for l in saved.splitlines() if l.strip() and not l.startswith("#")]
    assert len(entries) == 1, entries
    assert entries[0].split("\t")[6] == "a b", entries[0]


# --- Импорт из установленного браузера ----------------------------------

def _cookie(name, value, domain=".youtube.com", expires=1814618168):
    """Cookie в том виде, в каком её отдаёт yt-dlp при чтении браузера."""
    import http.cookiejar as cookiejar

    return cookiejar.Cookie(0, name, value, None, False, domain, True,
                            domain.startswith("."), "/", True, True,
                            expires, False, None, None, {})


def _session_cookie(name, value):
    """Cookie без срока жизни: браузер отдаёт expires=None."""
    return _cookie(name, value, expires=None)


@pytest.fixture
def fake_browser(monkeypatch):
    """Подменяет чтение браузера: настоящие профили трогать нельзя."""
    import auth_options

    def _install(cookies=None, error=None):
        def fake_extract(browser_name, *a, **k):
            if error is not None:
                raise error
            from yt_dlp.cookies import YoutubeDLCookieJar

            jar = YoutubeDLCookieJar()
            for c in cookies or []:
                jar.set_cookie(c)
            return jar

        monkeypatch.setattr(auth_options, "extract_browser_cookies", fake_extract)
        return fake_extract

    return _install


def test_browser_import_saves_cookies(client, cookies_path, fake_browser):
    fake_browser(cookies=[_cookie("SID", "abc")])

    res = client.post("/api/cookies/from-browser", json={"browser": "firefox"})

    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["cookies_count"] == 1, body
    assert "SID" in open(cookies_path, encoding="utf-8").read()


def test_browser_import_sanitises_broken_values(client, cookies_path, fake_browser):
    """Перевод строки в значении рвал запись на две неполные.

    jar.save() пишет значение как есть, поэтому импорт из браузера должен
    проходить через ту же очистку, что и вставка текста: иначе yt-dlp отвергает
    файл целиком или теряет часть cookies.
    """
    fake_browser(cookies=[_cookie("GOOD", "plain"),
                          _cookie("BAD_NL", "line1\nline2"),
                          _cookie("BAD_TAB", "a\tb")])

    res = client.post("/api/cookies/from-browser", json={"browser": "firefox"})

    assert res.status_code == 200, res.get_json()
    saved = open(cookies_path, encoding="utf-8").read()
    entries = [l for l in saved.splitlines() if l.strip() and not l.startswith("#")]
    assert all(len(l.split("\t")) == 7 for l in entries), entries
    # Ни одна cookie не должна потеряться: битые значения только чистятся.
    assert sorted(l.split("\t")[5] for l in entries) == ["BAD_NL", "BAD_TAB", "GOOD"], entries
    assert res.get_json()["cookies_count"] == len(entries)


def test_browser_import_result_is_readable_by_yt_dlp(client, cookies_path, fake_browser):
    """Проверка на настоящем yt-dlp: файл должен читаться целиком."""
    yt_dlp = pytest.importorskip("yt_dlp")
    fake_browser(cookies=[_cookie("GOOD", "plain"),
                          _cookie("BAD_NL", "line1\nline2")])

    client.post("/api/cookies/from-browser", json={"browser": "firefox"})

    warnings = []

    class Logger:
        def debug(self, m): pass
        def info(self, m): pass
        def warning(self, m, only_once=False): warnings.append(str(m))
        def error(self, m): warnings.append(str(m))

    ydl = yt_dlp.YoutubeDL({"quiet": True, "cookiefile": cookies_path,
                            "logger": Logger()})

    assert len(ydl.cookiejar) == 2, sorted(c.name for c in ydl.cookiejar)
    assert not warnings, warnings


def test_browser_import_drops_unusable_entries(client, cookies_path, fake_browser):
    """Запись без имени или домена нельзя писать в файл.

    Чистка значений такие записи не ловит: там поле формально есть, но пустое,
    а http.cookiejar на нём спотыкается.
    """
    fake_browser(cookies=[_cookie("GOOD", "ok"),
                          _cookie("", "no-name"),
                          _cookie("NO_DOMAIN", "v", domain="")])

    res = client.post("/api/cookies/from-browser", json={"browser": "firefox"})

    assert res.status_code == 200, res.get_json()
    saved = open(cookies_path, encoding="utf-8").read()
    entries = [l for l in saved.splitlines() if l.strip() and not l.startswith("#")]
    assert [l.split("\t")[5] for l in entries] == ["GOOD"], entries
    assert res.get_json()["cookies_count"] == 1


def test_session_cookies_survive_browser_import(client, cookies_path, fake_browser):
    """Сессионная cookie (expires=None) нужна для авторизации, терять нельзя."""
    fake_browser(cookies=[_session_cookie("SESSION", "v")])

    res = client.post("/api/cookies/from-browser", json={"browser": "firefox"})

    assert res.status_code == 200, res.get_json()
    saved = open(cookies_path, encoding="utf-8").read()
    assert "SESSION" in saved
    entries = [l for l in saved.splitlines() if l.strip() and not l.startswith("#")]
    # expires должен стать числом, иначе запись отбросится при чтении.
    assert entries[0].split("\t")[4] == "0", entries


def test_browser_import_requires_browser(client, cookies_path):
    res = client.post("/api/cookies/from-browser", json={})

    assert res.status_code == 400
    assert res.get_json()["error"]


def test_unknown_browser_is_rejected(client, cookies_path, monkeypatch):
    """Неизвестное имя отсекается до обращения к yt-dlp.

    Иначе оно уходит в чтение профиля и возвращается путаная низкоуровневая
    ошибка вместо понятного «Неизвестный браузер».
    """
    import auth_options

    called = []
    monkeypatch.setattr(auth_options, "extract_browser_cookies",
                        lambda *a, **k: called.append(a) or (_ for _ in ()).throw(
                            AssertionError("чтение браузера не должно вызываться")))

    res = client.post("/api/cookies/from-browser", json={"browser": "netscape4"})

    assert res.status_code == 400
    assert "netscape4" in res.get_json()["error"]
    assert called == [], "неизвестный браузер ушёл в чтение профиля"


def test_locked_database_gives_readable_error(client, cookies_path, fake_browser):
    """Chrome/Edge на Windows падают с DPAPI-ошибкой (yt-dlp #10927).

    Пользователю нужно понятное объяснение, а не питоновский трейсбек.
    """
    import yt_dlp.utils

    fake_browser(error=yt_dlp.utils.DownloadError(
        "Failed to decrypt with DPAPI. See  https://github.com/yt-dlp/yt-dlp/issues/10927"))

    res = client.post("/api/cookies/from-browser", json={"browser": "chrome"})

    assert res.status_code == 400
    text = res.get_json()["error"].lower()
    assert "chrome" in text
    assert "закр" in text or "расшифров" in text, text


def test_failed_import_keeps_old_cookies(client, cookies_path, fake_browser):
    """Неудачный импорт не должен затирать рабочий cookies.txt."""
    with open(cookies_path, "w", encoding="utf-8") as f:
        f.write(HEADER + "\n" + _good("OLD", "keepme") + "\n")
    fake_browser(error=RuntimeError("профиль занят"))

    res = client.post("/api/cookies/from-browser", json={"browser": "firefox"})

    assert res.status_code == 400
    assert "keepme" in open(cookies_path, encoding="utf-8").read(), \
        "старые cookies потеряны при неудачном импорте"


def test_empty_browser_jar_is_reported(client, cookies_path, fake_browser):
    """Пустой результат — не успех: пользователь должен понять, что не вышло."""
    with open(cookies_path, "w", encoding="utf-8") as f:
        f.write(HEADER + "\n" + _good("OLD", "keepme") + "\n")
    fake_browser(cookies=[])

    res = client.post("/api/cookies/from-browser", json={"browser": "firefox"})

    assert res.status_code == 400, res.get_json()
    assert "keepme" in open(cookies_path, encoding="utf-8").read()


# --- Список браузеров для выбора ----------------------------------------

def test_browsers_endpoint_lists_supported(client):
    res = client.get("/api/cookies/browsers")

    assert res.status_code == 200
    names = [b["name"] for b in res.get_json()["browsers"]]
    for expected in ("firefox", "chrome", "edge"):
        assert expected in names, names


def test_browsers_endpoint_marks_installed(client):
    """Ставить в список браузер, которого нет, — вести пользователя к ошибке."""
    body = client.get("/api/cookies/browsers").get_json()

    for item in body["browsers"]:
        assert set(item) >= {"name", "label", "installed"}, item
        assert isinstance(item["installed"], bool)
    # Хотя бы один браузер в системе есть, иначе проверять нечего.
    assert [b for b in body["browsers"] if b["installed"]], body


def test_available_browsers_detects_missing(monkeypatch):
    """Признак установленности считается по каталогу профиля."""
    import auth_options

    monkeypatch.setattr(auth_options, "browser_profile_dirs",
                        lambda: {"firefox": [str(os.path.dirname(__file__))],
                                 "chrome": [os.path.join(os.path.dirname(__file__), "нет-такого")]})

    found = {b["name"]: b["installed"] for b in auth_options.available_browsers()}

    assert found["firefox"] is True
    assert found["chrome"] is False


# --- Токены авторизации с флагом HttpOnly -------------------------------
#
# YouTube помечает cookies входа (LOGIN_INFO, SID, SAPISID) флагом HttpOnly.
# В Netscape-файле такая запись начинается с «#HttpOnly_». Строка похожа на
# комментарий, но yt-dlp её читает. Санитайзер отбрасывал её вместе с
# комментариями, поэтому из файла пропадали ровно те cookies, которые
# подтверждают возраст, и видео 18+ падало с «Sign in to confirm your age».

HTTPONLY_PREFIX = "#HttpOnly_"


def _httponly_line(name, value=".youtube.com"):
    return f"{HTTPONLY_PREFIX}.youtube.com\tTRUE\t/\tTRUE\t1814618168\t{name}\tv-{name}"


def test_httponly_auth_cookies_survive_paste(client, cookies_path):
    """Вставка экспорта расширения не должна терять LOGIN_INFO и SID."""
    text = "\n".join([
        "# Netscape HTTP Cookie File",
        _httponly_line("LOGIN_INFO"),
        _httponly_line("SID"),
        _good("PREF", "f6=40000000"),
    ]) + "\n"

    resp = _write(client, text)
    assert resp.status_code == 200, resp.data

    saved = io.open(cookies_path, encoding="utf-8").read()
    names = {l.split("\t")[5] for l in saved.splitlines()
             if l.strip() and not l.startswith("#") or l.startswith(HTTPONLY_PREFIX)}
    assert {"LOGIN_INFO", "SID", "PREF"} <= names, saved


def test_httponly_cookies_are_readable_by_yt_dlp(client, cookies_path):
    """Сохранённый файл должен отдавать HttpOnly-токены настоящему yt-dlp."""
    from yt_dlp.cookies import YoutubeDLCookieJar

    text = "\n".join([
        "# Netscape HTTP Cookie File",
        _httponly_line("LOGIN_INFO"),
        _good("PREF", "f6=40000000"),
    ]) + "\n"
    _write(client, text)

    jar = YoutubeDLCookieJar(str(cookies_path))
    jar.load()

    assert {c.name for c in jar} == {"LOGIN_INFO", "PREF"}


def test_httponly_prefix_is_preserved_on_save(client, cookies_path):
    """Префикс не должен потеряться: без него cookie станет обычной."""
    _write(client, "# Netscape HTTP Cookie File\n" + _httponly_line("SAPISID") + "\n")

    saved = io.open(cookies_path, encoding="utf-8").read()

    assert HTTPONLY_PREFIX + ".youtube.com" in saved, saved


def test_broken_httponly_entry_is_still_dropped(client, cookies_path):
    """Отсев битых строк должен работать и для HttpOnly-записей."""
    text = "\n".join([
        "# Netscape HTTP Cookie File",
        HTTPONLY_PREFIX + ".youtube.com\tTRUE\t/\tTRUE\tне-число\tBAD\tx",
        _httponly_line("LOGIN_INFO"),
    ]) + "\n"

    _write(client, text)
    saved = io.open(cookies_path, encoding="utf-8").read()

    assert "BAD" not in saved, saved
    assert "LOGIN_INFO" in saved, saved


def test_real_comments_are_still_dropped(client, cookies_path):
    """Обычные комментарии по-прежнему не должны попадать в файл."""
    text = "\n".join([
        "# Netscape HTTP Cookie File",
        "# Это комментарий расширения",
        _good("PREF", "f6=40000000"),
    ]) + "\n"

    _write(client, text)
    saved = io.open(cookies_path, encoding="utf-8").read()

    assert "комментарий расширения" not in saved, saved


def test_commented_out_cookie_stays_disabled(client, cookies_path):
    """Закомментированная cookie не должна оживать.

    Строку с cookie отключают, добавив «#» в начало. Полей в ней ровно 7,
    поэтому отсев по числу полей её не поймает: если перестать отбрасывать
    комментарии, отключённая cookie вернётся в файл. HttpOnly-префикс —
    единственное исключение, и он проверяется отдельно.
    """
    text = "\n".join([
        "# Netscape HTTP Cookie File",
        "#" + _good("DISABLED", "не-использовать"),
        _good("PREF", "f6=40000000"),
    ]) + "\n"

    _write(client, text)
    saved = io.open(cookies_path, encoding="utf-8").read()

    assert "DISABLED" not in saved, saved
    assert "PREF" in saved, saved


def test_browser_import_keeps_httponly_flag(client, cookies_path, fake_browser):
    """Экспорт из браузера тоже должен помечать HttpOnly-cookies префиксом."""
    import http.cookiejar as cookiejar

    c = cookiejar.Cookie(0, "LOGIN_INFO", "AFmmF2s", None, False,
                         ".youtube.com", True, True, "/", True, True,
                         1814618168, False, None, None, {"HttpOnly": None})
    fake_browser(cookies=[c])

    resp = client.post("/api/cookies/from-browser", json={"browser": "firefox"})
    assert resp.status_code == 200, resp.data

    saved = io.open(cookies_path, encoding="utf-8").read()
    assert HTTPONLY_PREFIX + ".youtube.com" in saved, saved
