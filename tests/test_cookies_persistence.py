# -*- coding: utf-8 -*-
"""cookies.txt не должен деградировать от работы yt-dlp.

yt-dlp вызывает save_cookies() при каждом close() и перезаписывает cookiefile
содержимым своего jar. Из-за этого файл пользователя усыхал (371 запись -> 238),
а экспорт из браузера, сделанный во время загрузки, затирался старым jar из
памяти: пропадали LOGIN_INFO и SID, и видео 18+ падало на
«Sign in to confirm your age».

Сеть не используется: настоящий yt-dlp работает с локальным файлом.
"""
import io
import os

import pytest

import utils


HEADER = "# Netscape HTTP Cookie File"
AUTH_NAMES = ["LOGIN_INFO", "SID", "HSID", "SAPISID", "__Secure-1PSID"]


def _netscape(names, domain=".youtube.com", expires=1814618168):
    lines = [HEADER]
    for n in names:
        lines.append(f"{domain}\tTRUE\t/\tTRUE\t{expires}\t{n}\tv-{n}")
    return "\n".join(lines) + "\n"


def _names_in(path):
    raw = io.open(path, encoding="utf-8").read()
    return {l.split("\t")[5] for l in raw.splitlines()
            if l.strip() and not l.startswith("#")}


@pytest.fixture
def cookies_file(tmp_path):
    path = str(tmp_path / "cookies.txt")
    io.open(path, "w", encoding="utf-8").write(_netscape(AUTH_NAMES))
    return path


def _ydl(cookiefile):
    import yt_dlp

    class Log:
        def debug(self, m): pass
        def info(self, m): pass
        def warning(self, m, only_once=False): pass
        def error(self, m): pass

    return yt_dlp.YoutubeDL({"quiet": True, "cookiefile": cookiefile,
                             "logger": Log()})


def test_ydl_reads_cookies_through_helper(cookies_file):
    """Через помощник yt-dlp должен видеть все cookies из файла."""
    ydl = _ydl(utils.cookiefile_for_ydl(cookies_file))
    try:
        assert {c.name for c in ydl.cookiejar} == set(AUTH_NAMES)
    finally:
        ydl.close()


def test_close_does_not_shrink_cookies_file(cookies_file):
    """close() не должен удалять из файла cookies, которых нет в jar."""
    before = io.open(cookies_file, encoding="utf-8").read()

    ydl = _ydl(utils.cookiefile_for_ydl(cookies_file))
    ydl.cookiejar.clear()          # как будто YouTube не прислал ничего
    ydl.close()

    assert io.open(cookies_file, encoding="utf-8").read() == before


def test_fresh_export_is_not_overwritten_by_old_download(cookies_file):
    """Экспорт во время загрузки не должен затираться старым jar из памяти.

    Это ровно тот случай из жизни: пользователь нажал «Экспортировать из
    браузера», пока шла загрузка, и после её завершения токены входа исчезли.
    """
    # Загрузка идёт со старым, уже деградировавшим файлом.
    io.open(cookies_file, "w", encoding="utf-8").write(_netscape(["PREF"]))
    ydl = _ydl(utils.cookiefile_for_ydl(cookies_file))
    assert {c.name for c in ydl.cookiejar} == {"PREF"}

    # Пользователь экспортировал свежие cookies.
    io.open(cookies_file, "w", encoding="utf-8").write(_netscape(AUTH_NAMES))

    # Загрузка завершилась.
    ydl.close()

    names = _names_in(cookies_file)
    assert "LOGIN_INFO" in names, names
    assert set(AUTH_NAMES) <= names, names


def test_helper_returns_none_without_file(tmp_path):
    """Нет файла — нет cookies: yt-dlp должен работать без них."""
    assert utils.cookiefile_for_ydl(str(tmp_path / "нет.txt")) is None
    assert utils.cookiefile_for_ydl(None) is None


def test_helper_gives_stream_not_path(cookies_file):
    """Путь отдавать нельзя: именно он разрешает yt-dlp запись в файл."""
    value = utils.cookiefile_for_ydl(cookies_file)

    assert not isinstance(value, (str, bytes, os.PathLike))
    assert hasattr(value, "read")


# --- Вливание обновлений --------------------------------------------------
#
# YouTube обновляет короткоживущие токены при каждом запросе. Если их не
# сохранять, авторизация протухает за часы и видео 18+ снова падает на
# «Sign in to confirm your age». Проверено вживую: подстановка пяти значений
# (SIDCC, __Secure-1PSIDTS/3PSIDTS, __Secure-1PSIDCC/3PSIDCC) из браузера в
# устаревший файл возвращает доступ.

ROTATING = ["SIDCC", "__Secure-1PSIDTS", "__Secure-3PSIDTS"]


def _values_in(path):
    raw = io.open(path, encoding="utf-8").read()
    return {l.split("\t")[5]: l.split("\t")[6] for l in raw.splitlines()
            if l.strip() and not l.startswith("#") and len(l.split("\t")) == 7}


def test_flush_saves_updates(cookies_file):
    """flush() должен вливать обновления: не все клиенты доходят до close()."""
    io.open(cookies_file, "w", encoding="utf-8").write(_netscape(["SIDCC", "SID"]))

    stream = utils.cookiefile_for_ydl(cookies_file)
    stream.truncate(0)
    stream.write(_netscape(["SIDCC"]).replace("v-SIDCC", "ПОСЛЕ-FLUSH"))
    stream.flush()

    values = _values_in(cookies_file)
    assert values.get("SIDCC") == "ПОСЛЕ-FLUSH", values
    assert "SID" in values, "запись, которой yt-dlp не видел, пропала"


def test_close_saves_updates(cookies_file):
    """close() тоже должен вливать обновления, а не терять их."""
    io.open(cookies_file, "w", encoding="utf-8").write(_netscape(["SIDCC", "SID"]))

    stream = utils.cookiefile_for_ydl(cookies_file)
    stream.truncate(0)
    stream.write(_netscape(["SIDCC"]).replace("v-SIDCC", "ПОСЛЕ-CLOSE"))
    stream.close()

    values = _values_in(cookies_file)
    assert values.get("SIDCC") == "ПОСЛЕ-CLOSE", values
    assert "SID" in values, "запись, которой yt-dlp не видел, пропала"


def test_real_ydl_survives_second_load(cookies_file):
    """Настоящий YoutubeDL должен дважды загрузить cookies из одного потока.

    Живьём это выглядело так: первая попытка падала по сети, вторая шла с тем же
    объектом потока и yt-dlp отдавал CookieLoadError('failed to load cookies') —
    задача останавливалась целиком, хотя достаточно было повторить попытку.
    Сеть здесь не нужна: важен только повторный разбор cookies самим yt-dlp.
    """
    import yt_dlp

    io.open(cookies_file, "w", encoding="utf-8").write(
        _netscape(AUTH_NAMES + ROTATING))

    opts = {"quiet": True, "no_warnings": True,
            "cookiefile": utils.cookiefile_for_ydl(cookies_file)}
    counts = []
    for _ in range(2):
        with yt_dlp.YoutubeDL(opts) as ydl:
            counts.append(len(ydl.cookiejar))
        utils.apply_cookie_updates(opts)

    assert counts[0] == counts[1], (
        "второй разбор cookies дал другой результат: %r" % (counts,))
    assert counts[0] == len(AUTH_NAMES + ROTATING), counts


def test_stream_is_reusable_after_write(cookies_file):
    """После записи поток должен снова читаться: повтор попытки идёт с ним же.

    yt-dlp читает cookies до конца и не возвращает позицию, а truncate(0) её
    тоже не сбрасывает. Без восстановления содержимого повторная попытка падала
    с CookieLoadError('failed to load cookies'), и задача останавливалась.
    """
    from yt_dlp.cookies import YoutubeDLCookieJar

    io.open(cookies_file, "w", encoding="utf-8").write(_netscape(["SIDCC", "SID"]))
    stream = utils.cookiefile_for_ydl(cookies_file)

    first = YoutubeDLCookieJar(stream)
    first.load()
    assert len(first) == 2, len(first)
    first.save()                       # так делает yt-dlp при close()
    utils.apply_cookie_updates({"cookiefile": stream})

    second = YoutubeDLCookieJar(stream)
    second.load()                      # раньше здесь падало
    assert len(second) == 2, len(second)


def test_refreshed_token_is_saved(cookies_file):
    """Обновлённое значение токена должно попасть в файл."""
    io.open(cookies_file, "w", encoding="utf-8").write(
        _netscape(AUTH_NAMES + ROTATING))

    opts = {"cookiefile": utils.cookiefile_for_ydl(cookies_file)}
    ydl = _ydl(opts["cookiefile"])
    import http.cookiejar as cookiejar
    ydl.cookiejar.set_cookie(cookiejar.Cookie(
        0, "SIDCC", "СВЕЖЕЕ", None, False, ".youtube.com", True, True,
        "/", True, True, 1899999999, False, None, None, {}))
    ydl.close()
    utils.apply_cookie_updates(opts)

    values = _values_in(cookies_file)
    assert values["SIDCC"] == "СВЕЖЕЕ", values["SIDCC"]


def test_refresh_keeps_other_cookies(cookies_file):
    """Обновление одного токена не должно терять остальные записи."""
    io.open(cookies_file, "w", encoding="utf-8").write(
        _netscape(AUTH_NAMES + ROTATING))
    before = set(_names_in(cookies_file))

    opts = {"cookiefile": utils.cookiefile_for_ydl(cookies_file)}
    ydl = _ydl(opts["cookiefile"])
    import http.cookiejar as cookiejar
    ydl.cookiejar.clear()          # jar опустел: YouTube ничего не присылал
    ydl.cookiejar.set_cookie(cookiejar.Cookie(
        0, "SIDCC", "СВЕЖЕЕ", None, False, ".youtube.com", True, True,
        "/", True, True, 1899999999, False, None, None, {}))
    ydl.close()
    utils.apply_cookie_updates(opts)

    after = set(_names_in(cookies_file))
    assert before <= after, before - after
    assert "LOGIN_INFO" in after


def test_new_cookie_is_added(cookies_file):
    """Cookie, которую YouTube завёл в этом запросе, должна появиться."""
    opts = {"cookiefile": utils.cookiefile_for_ydl(cookies_file)}
    ydl = _ydl(opts["cookiefile"])
    import http.cookiejar as cookiejar
    ydl.cookiejar.set_cookie(cookiejar.Cookie(
        0, "НОВАЯ", "значение", None, False, ".youtube.com", True, True,
        "/", True, True, 1899999999, False, None, None, {}))
    ydl.close()
    utils.apply_cookie_updates(opts)

    names = _names_in(cookies_file)
    assert "НОВАЯ" in names
    assert set(AUTH_NAMES) <= names


def test_merge_ignores_nul_padding(cookies_file):
    """truncate(0) у yt-dlp оставляет NUL-байты: они не должны попасть в файл."""
    written = "\x00" * 40 + _netscape(["SIDCC"]).replace("v-SIDCC", "ОБНОВЛЕНО")

    utils.merge_cookie_updates(cookies_file, written)

    raw = io.open(cookies_file, encoding="utf-8").read()
    assert "\x00" not in raw
    assert _values_in(cookies_file)["SIDCC"] == "ОБНОВЛЕНО"


def test_merge_keeps_httponly_prefix(cookies_file):
    """Префикс HttpOnly не должен пропасть при вливании обновлений."""
    line = ("#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1814618168\tSIDCC\tстарое")
    io.open(cookies_file, "w", encoding="utf-8").write(HEADER + "\n" + line + "\n")

    utils.merge_cookie_updates(
        cookies_file, _netscape(["SIDCC"]).replace("v-SIDCC", "новое"))

    raw = io.open(cookies_file, encoding="utf-8").read()
    assert "#HttpOnly_.youtube.com" in raw, raw
    assert "новое" in raw, raw


def test_merge_does_nothing_without_changes(cookies_file):
    """Без изменений файл не должен переписываться.

    Проверяем время изменения: содержимое совпало бы и при лишней записи,
    а лишняя запись — это гонка с одновременным экспортом из браузера.
    """
    before = io.open(cookies_file, encoding="utf-8").read()
    os.utime(cookies_file, (1_600_000_000, 1_600_000_000))
    stamp = os.stat(cookies_file).st_mtime

    utils.merge_cookie_updates(cookies_file, before)

    assert io.open(cookies_file, encoding="utf-8").read() == before
    assert os.stat(cookies_file).st_mtime == stamp, "файл переписан без нужды"


def test_merge_replaces_file_atomically(cookies_file, monkeypatch):
    """Замена должна быть атомарной: обрыв не оставит огрызок файла."""
    calls = []
    real_replace = os.replace
    monkeypatch.setattr(os, "replace",
                        lambda a, b: (calls.append((a, b)), real_replace(a, b))[1])

    utils.merge_cookie_updates(
        cookies_file, _netscape(["SIDCC"]).replace("v-SIDCC", "новое"))

    assert calls, "os.replace не вызывался: запись не атомарна"
    assert not os.path.exists(cookies_file + ".tmp"), "временный файл остался"


def test_commented_line_with_seven_fields_stays_disabled(cookies_file):
    """Строка-комментарий с 7 полями не должна обновляться и оживать.

    Отдельно от предыдущего теста: там проверяется, что запись не появилась,
    а здесь — что её не «обновили» значением с сервера.
    """
    disabled = "#.youtube.com\tTRUE\t/\tTRUE\t1814618168\tSIDCC\tстарое"
    io.open(cookies_file, "w", encoding="utf-8").write(
        HEADER + "\n" + disabled + "\n" + _netscape(["PREF"]).split("\n")[1] + "\n")

    utils.merge_cookie_updates(
        cookies_file, _netscape(["SIDCC"]).replace("v-SIDCC", "новое"))

    raw = io.open(cookies_file, encoding="utf-8").read()
    rows = [l for l in raw.splitlines() if l.strip() and not l.startswith("#")]
    names = {l.split("\t")[5]: l.split("\t")[6] for l in rows}
    # SIDCC придёт как новая запись, но старая закомментированная строка
    # не должна превратиться в действующую.
    assert names.get("SIDCC") == "новое", names
    assert "старое" not in raw, raw
    assert len([l for l in rows if l.split("\t")[5] == "SIDCC"]) == 1, rows


def test_merge_skips_missing_file(tmp_path):
    """Нет файла — вливать некуда, и создавать его не нужно."""
    missing = str(tmp_path / "нет.txt")

    utils.merge_cookie_updates(missing, _netscape(["SIDCC"]))

    assert not os.path.exists(missing)


def test_commented_cookie_is_not_revived_by_merge(cookies_file):
    """Отключённая cookie не должна оживать при вливании обновлений."""
    io.open(cookies_file, "w", encoding="utf-8").write(
        HEADER + "\n"
        + "#.youtube.com\tTRUE\t/\tTRUE\t1814618168\tDISABLED\tстарое\n"
        + ".youtube.com\tTRUE\t/\tTRUE\t1814618168\tPREF\tf6=1\n")

    utils.merge_cookie_updates(
        cookies_file, _netscape(["PREF"]).replace("v-PREF", "f6=2"))

    raw = io.open(cookies_file, encoding="utf-8").read()
    assert "DISABLED" not in raw, raw
    assert "f6=2" in raw, raw


def test_every_module_with_cookies_path_is_protected():
    """Все модули с COOKIES_PATH должны быть уведены во временный файл.

    Настоящий cookies.txt уже терялся из-за модуля, которого не было в списке
    подмены. Проверяем автоматически, а не глазами.
    """
    import glob
    import importlib
    import re

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    real = os.path.join(root, "cookies.txt")
    unprotected = []
    for path in glob.glob(os.path.join(root, "*.py")):
        source = io.open(path, encoding="utf-8", errors="replace").read()
        if not re.search(r"^COOKIES_PATH\s*=", source, re.M):
            continue
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue                      # модуль-скрипт, в тестах не участвует
        value = getattr(mod, "COOKIES_PATH", None)
        if value and os.path.abspath(value) == os.path.abspath(real):
            unprotected.append(name)

    assert not unprotected, f"пишут в настоящий cookies.txt: {unprotected}"


@pytest.mark.parametrize("module_name", [
    "app",
    "download_lib",
    "downloader",
    "youtube_extractor",
    "channel_assets",
    "subtitles",
    "download_video",
    "download_avatars",
])
def test_modules_do_not_pass_path_as_cookiefile(module_name):
    """Ни один модуль не должен отдавать yt-dlp путь к cookies.txt.

    Путь в cookiefile — это и есть разрешение на перезапись. Проверяем текст
    модуля: подобное легко вернуть назад при следующей правке.
    """
    import importlib

    mod = importlib.import_module(module_name)
    source = io.open(mod.__file__, encoding="utf-8").read()

    for bad in ("'cookiefile': COOKIES_PATH",
                '"cookiefile": COOKIES_PATH',
                "'cookiefile'] = COOKIES_PATH",
                "'cookiefile': cookies_path",
                "'cookiefile'] = cookies_path"):
        assert bad not in source, f"{module_name}: {bad}"


def test_get_ydl_opts_gives_stream(tmp_path, monkeypatch):
    """download_lib.get_ydl_opts должен отдавать поток, а не путь."""
    import download_lib

    path = str(tmp_path / "cookies.txt")
    io.open(path, "w", encoding="utf-8").write(_netscape(AUTH_NAMES))
    monkeypatch.setattr(download_lib, "COOKIES_PATH", path)

    opts = download_lib.get_ydl_opts(None, "mp4", lambda d: None,
                                     str(tmp_path / "tmp"))

    assert not isinstance(opts["cookiefile"], str)
    assert hasattr(opts["cookiefile"], "read")


def test_download_saves_refreshed_tokens(tmp_path, monkeypatch):
    """download_single_sync должен сохранять обновлённые токены.

    Без этого файл остаётся с устаревшими SIDCC/__Secure-*PSIDTS, и через
    несколько часов видео 18+ снова падает на «Sign in to confirm your age».
    Сеть не нужна: подменяем YoutubeDL, который «обновляет» токен.
    """
    import http.cookiejar as cookiejar

    import download_lib

    path = str(tmp_path / "cookies.txt")
    io.open(path, "w", encoding="utf-8").write(_netscape(AUTH_NAMES + ROTATING))
    monkeypatch.setattr(download_lib, "COOKIES_PATH", path)

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            self.cookiejar = cookiejar.CookieJar()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            # Пишем в поток только на самой загрузке: иначе обновление успел бы
            # сохранить запрос метаданных, и проверка ничего бы не показала.
            if not download:
                return {"id": "x", "title": "видео", "uploader": "автор",
                        "formats": [{"protocol": "https", "url": "http://x/v",
                                     "vcodec": "avc1", "acodec": "mp4a"}]}
            stream = self.opts.get("cookiefile")
            stream.truncate(0)
            stream.write(_netscape(["SIDCC"]).replace("v-SIDCC", "ОБНОВЛЕНО"))
            return None                      # дальше нас не интересует

    # Подстраховка CookieStream.close() здесь мешает: без неё видно, что
    # обновления сохраняет именно apply_cookie_updates в download_lib.
    monkeypatch.setattr(utils.CookieStream, "close",
                        lambda self: io.StringIO.close(self))
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", FakeYDL)
    download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=x"], None, lambda *a, **k: None)

    values = _values_in(path)
    assert values.get("SIDCC") == "ОБНОВЛЕНО", values.get("SIDCC")
    # Остальные записи должны остаться.
    assert set(AUTH_NAMES) <= set(values), set(AUTH_NAMES) - set(values)


def test_metadata_request_saves_refreshed_tokens(tmp_path, monkeypatch):
    """Запрос метаданных тоже должен сохранять обновлённые токены.

    Это отдельный набор опций (info_opts) в download_single_sync: обновления
    приходят и здесь, потому что запрос метаданных идёт первым.
    """
    import http.cookiejar as cookiejar

    import download_lib

    path = str(tmp_path / "cookies.txt")
    io.open(path, "w", encoding="utf-8").write(_netscape(AUTH_NAMES + ROTATING))
    monkeypatch.setattr(download_lib, "COOKIES_PATH", path)

    seen = {}

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            self.cookiejar = cookiejar.CookieJar()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            # Метаданные запрашиваются с download=False и своими опциями.
            if not download:
                seen["info"] = True
                stream = self.opts.get("cookiefile")
                stream.truncate(0)
                stream.write(_netscape(["__Secure-1PSIDTS"]).replace(
                    "v-__Secure-1PSIDTS", "СВЕЖИЙ-TS"))
            return None

    monkeypatch.setattr(utils.CookieStream, "close",
                        lambda self: io.StringIO.close(self))
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", FakeYDL)
    download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=x"], None, lambda *a, **k: None)

    assert seen.get("info"), "запрос метаданных не выполнялся"
    values = _values_in(path)
    assert values.get("__Secure-1PSIDTS") == "СВЕЖИЙ-TS", values.get("__Secure-1PSIDTS")


def test_download_keeps_cookies_after_full_cycle(tmp_path, monkeypatch):
    """Полный цикл get_ydl_opts -> YoutubeDL -> close() не трогает файл."""
    import download_lib

    path = str(tmp_path / "cookies.txt")
    original = _netscape(AUTH_NAMES)
    io.open(path, "w", encoding="utf-8").write(original)
    monkeypatch.setattr(download_lib, "COOKIES_PATH", path)

    opts = download_lib.get_ydl_opts(None, "mp4", lambda d: None,
                                     str(tmp_path / "tmp"))
    ydl = _ydl(opts["cookiefile"])
    assert {c.name for c in ydl.cookiejar} == set(AUTH_NAMES)
    ydl.cookiejar.clear()
    ydl.close()

    assert io.open(path, encoding="utf-8").read() == original
