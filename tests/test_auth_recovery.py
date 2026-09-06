# -*- coding: utf-8 -*-
"""Обход отказа авторизации: cookies обновляются сами.

Проверено замером: возрастное видео A_K5zspHD30 не отдаёт форматы ни одному
клиенту YouTube без cookies (проверены tv, tv_embedded, web_embedded, mweb,
web_safari, android_vr, ios, web, tv_simply). Значит обойти отказ подменой
клиента нельзя, а лечит его свежий экспорт из браузера: сразу после экспорта
то же видео отдаёт 27 форматов.

Отсюда решение: при ошибке авторизации LocalTube один раз обновляет cookies из
браузера и повторяет попытку. Сеть в тестах не используется.
"""
import io
import os

import pytest


HEADER = "# Netscape HTTP Cookie File"
AGE_ERROR = ("[youtube] A_K5zspHD30: Sign in to confirm your age. "
             "Use --cookies-from-browser or --cookies for the authentication.")
BOT_ERROR = ("[youtube] xyz: Sign in to confirm you're not a bot. "
             "Use --cookies-from-browser or --cookies for the authentication.")


def _netscape(names):
    lines = [HEADER]
    for n in names:
        lines.append(f".youtube.com\tTRUE\t/\tTRUE\t1814618168\t{n}\tv-{n}")
    return "\n".join(lines) + "\n"


@pytest.fixture
def cookies_file(tmp_path, monkeypatch):
    import auth_options
    import download_lib

    path = str(tmp_path / "cookies.txt")
    io.open(path, "w", encoding="utf-8").write(_netscape(["PREF"]))
    monkeypatch.setattr(download_lib, "COOKIES_PATH", path)
    monkeypatch.setattr(auth_options, "COOKIES_PATH", path)
    return path


# --- Распознавание отказа авторизации ------------------------------------

def test_age_error_is_recognised():
    """Отказ по возрасту должен опознаваться как проблема авторизации."""
    import download_lib

    assert download_lib.is_auth_error(AGE_ERROR)


def test_bot_check_is_recognised():
    """Проверка «не бот» лечится теми же свежими cookies."""
    import download_lib

    assert download_lib.is_auth_error(BOT_ERROR)


@pytest.mark.parametrize("text", [
    "",
    "Video unavailable",
    "Private video",
    "HTTP Error 403: Forbidden",
    "Requested format is not available",
])
def test_other_errors_are_not_auth(text):
    """Прочие отказы не должны запускать обновление cookies."""
    import download_lib

    assert not download_lib.is_auth_error(text)


def test_auth_reason_becomes_advice():
    """Пользователю нужен совет, а не ключ командной строки yt-dlp."""
    import download_lib

    text = download_lib.explain_reason(AGE_ERROR)

    assert "cookies-from-browser" not in text, text
    assert "Экспортировать из браузера" in text, text


def test_other_reasons_are_left_alone():
    """Осмысленные ошибки подменять нельзя."""
    import download_lib

    assert download_lib.explain_reason("Video unavailable") == "Video unavailable"


def test_failed_video_reports_advice(cookies_file, monkeypatch):
    """Если обновление не помогло, в отчёте должен быть совет."""
    import download_lib

    monkeypatch.setattr(download_lib, "refresh_cookies_from_browser", lambda: False)

    class AgeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            logger = self.opts.get("logger")
            if logger:
                logger.error(AGE_ERROR)
            return None

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", AgeYDL)

    outcome = download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=A_K5zspHD30"], None,
        lambda *a, **k: None)

    assert outcome.failed == 1
    assert "Экспортировать из браузера" in str(outcome.last_error), outcome.last_error


def test_advice_when_download_step_returns_nothing(cookies_file, monkeypatch, tmp_path):
    """Шаг загрузки не вернул ничего из-за отказа: пользователю нужен совет.

    Отличается от случая «файла нет»: тут extract_info(download=True) вернул
    None, то есть yt-dlp отказал сразу.
    """
    import download_lib

    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib, "refresh_cookies_from_browser", lambda: False)

    class NoDownloadYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            if not download:
                return {"id": "x", "title": "видео", "uploader": "автор",
                        "formats": [{"protocol": "https", "url": "http://x/v",
                                     "vcodec": "avc1", "acodec": "mp4a"}]}
            logger = self.opts.get("logger")
            if logger:
                logger.error(AGE_ERROR)
            return None

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", NoDownloadYDL)

    outcome = download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=A_K5zspHD30"], None,
        lambda *a, **k: None)

    assert outcome.failed == 1
    assert "cookies-from-browser" not in str(outcome.last_error), outcome.last_error
    assert "Экспортировать из браузера" in str(outcome.last_error), outcome.last_error


def test_advice_when_media_file_missing(cookies_file, monkeypatch, tmp_path):
    """Метаданные получены, а файла нет из-за отказа: тоже нужен совет.

    Отдельная точка выдачи причины: видео прошло шаг метаданных, но
    скачивание ничего не дало.
    """
    import download_lib

    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib, "refresh_cookies_from_browser", lambda: False)
    monkeypatch.setattr(download_lib, "find_downloaded_media", lambda d: None)

    class MetaOkYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            if not download:
                return {"id": "x", "title": "видео", "uploader": "автор",
                        "formats": [{"protocol": "https", "url": "http://x/v",
                                     "vcodec": "avc1", "acodec": "mp4a"}]}
            # Сама загрузка отказана по возрасту.
            logger = self.opts.get("logger")
            if logger:
                logger.error(AGE_ERROR)
            return {"id": "x", "title": "видео", "uploader": "автор"}

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", MetaOkYDL)

    outcome = download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=A_K5zspHD30"], None,
        lambda *a, **k: None)

    assert outcome.failed == 1
    assert "cookies-from-browser" not in str(outcome.last_error), outcome.last_error


def test_age_error_is_not_transient():
    """Повторять запрос без обновления cookies бессмысленно."""
    import download_lib

    assert not download_lib.is_transient_error(AGE_ERROR)


# --- Обновление cookies из браузера --------------------------------------

def test_refresh_updates_cookies_file(cookies_file, monkeypatch):
    """Обновление должно записать свежие cookies в файл."""
    import auth_options
    import download_lib

    def fake_import(browser=None):
        io.open(cookies_file, "w", encoding="utf-8").write(
            _netscape(["LOGIN_INFO", "SID"]))
        return {"status": "ok", "count": 2, "browser": browser or "firefox"}

    monkeypatch.setattr(auth_options, "import_cookies_from_browser", fake_import)

    assert download_lib.refresh_cookies_from_browser() is True
    saved = io.open(cookies_file, encoding="utf-8").read()
    assert "LOGIN_INFO" in saved, saved


def test_refresh_reports_failure(cookies_file, monkeypatch):
    """Неудачное обновление не должно выглядеть успешным."""
    import auth_options
    import download_lib

    monkeypatch.setattr(auth_options, "import_cookies_from_browser",
                        lambda browser=None: {"status": "error",
                                              "error": "браузер не найден"})

    assert download_lib.refresh_cookies_from_browser() is False


def test_refresh_survives_exception(cookies_file, monkeypatch):
    """Сбой чтения профиля не должен ронять загрузку."""
    import auth_options
    import download_lib

    def boom(browser=None):
        raise RuntimeError("профиль занят")

    monkeypatch.setattr(auth_options, "import_cookies_from_browser", boom)

    assert download_lib.refresh_cookies_from_browser() is False


def test_refresh_tries_installed_browsers(cookies_file, monkeypatch):
    """Если первый браузер не дал cookies, пробуем остальные установленные."""
    import auth_options
    import download_lib

    tried = []

    def fake_import(browser=None):
        tried.append(browser)
        if browser != "chrome":
            return {"status": "error", "error": "нет cookies"}
        io.open(cookies_file, "w", encoding="utf-8").write(
            _netscape(["LOGIN_INFO"]))
        return {"status": "ok", "count": 1, "browser": browser}

    monkeypatch.setattr(auth_options, "available_browsers", lambda: [
        {"name": "firefox", "label": "Firefox", "installed": True},
        {"name": "chrome", "label": "Chrome", "installed": True},
        {"name": "safari", "label": "Safari", "installed": False},
    ])
    monkeypatch.setattr(auth_options, "import_cookies_from_browser", fake_import)

    assert download_lib.refresh_cookies_from_browser() is True
    assert tried == ["firefox", "chrome"], tried
    # Неустановленный браузер трогать бессмысленно.
    assert "safari" not in tried


# --- Повтор загрузки после обновления ------------------------------------

def test_download_retries_after_refresh(cookies_file, monkeypatch):
    """Отказ по возрасту -> обновление cookies -> повтор -> успех."""
    import download_lib

    attempts = {"n": 0}
    refreshed = {"n": 0}

    def fake_refresh():
        refreshed["n"] += 1
        return True

    monkeypatch.setattr(download_lib, "refresh_cookies_from_browser", fake_refresh)

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            if not download:
                attempts["n"] += 1
                if attempts["n"] == 1:
                    logger = self.opts.get("logger")
                    if logger:
                        logger.error(AGE_ERROR)
                    return None
                return {"id": "x", "title": "видео", "uploader": "автор",
                        "formats": [{"protocol": "https", "url": "http://x/v",
                                     "vcodec": "avc1", "acodec": "mp4a"}]}
            return None

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", FakeYDL)

    download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=A_K5zspHD30"], None,
        lambda *a, **k: None)

    assert refreshed["n"] == 1, "cookies не обновлялись"
    assert attempts["n"] >= 2, "повтора после обновления не было"


def test_retry_reads_refreshed_cookies(cookies_file, monkeypatch):
    """Повтор обязан увидеть НОВЫЕ cookies, а не старый снимок файла.

    cookiefile для yt-dlp — это поток CookieStream, снятый с файла один раз.
    Если после экспорта не перечитать файл, повтор пойдёт с тем же устаревшим
    содержимым, и обновление окажется бесполезным.
    """
    import download_lib

    def fake_refresh():
        # Экспорт из браузера: в файле появляется токен авторизации.
        io.open(cookies_file, "w", encoding="utf-8").write(
            _netscape(["PREF", "LOGIN_INFO"]))
        return True

    monkeypatch.setattr(download_lib, "refresh_cookies_from_browser", fake_refresh)

    seen = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            if not download:
                stream = self.opts.get("cookiefile")
                seen.append(stream.getvalue() if stream is not None else "")
                if len(seen) == 1:
                    logger = self.opts.get("logger")
                    if logger:
                        logger.error(AGE_ERROR)
                    return None
                return {"id": "x", "title": "видео", "uploader": "автор",
                        "formats": [{"protocol": "https", "url": "http://x/v",
                                     "vcodec": "avc1", "acodec": "mp4a"}]}
            return None

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", FakeYDL)

    download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=A_K5zspHD30"], None,
        lambda *a, **k: None)

    assert len(seen) >= 2, "повтора не было"
    assert "LOGIN_INFO" not in seen[0], "до обновления токена быть не должно"
    assert "LOGIN_INFO" in seen[1], "повтор пошёл со старым снимком cookies"


def test_each_attempt_gets_readable_cookies(cookies_file, monkeypatch):
    """Каждая попытка обязана получать ЧИТАЕМЫЙ поток cookies.

    CookieStream одноразовый: yt-dlp читает его до конца, а при сохранении
    делает truncate(0) и пишет туда свой jar. Повторная попытка с тем же
    объектом падала с 'failed to load cookies' — вместо повтора видео уходило
    в отказ. Проверяем через настоящий YoutubeDLCookieJar.
    """
    import download_lib
    from yt_dlp.cookies import YoutubeDLCookieJar

    monkeypatch.setattr(download_lib, "_sleep_cancellable", lambda *a, **k: None)
    monkeypatch.setattr(download_lib, "refresh_cookies_from_browser", lambda: True)

    # Ошибка сети, а не отказ авторизации: повтор идёт БЕЗ обновления cookies,
    # то есть с тем же объектом потока. Именно так баг и проявлялся живьём.
    NET_ERROR = "ERROR: unable to download video data: <urlopen error timed out>"

    loaded = []

    class ReloadingYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            if not download:
                # Повторяем то, что делает настоящий yt-dlp: грузит cookies...
                jar = YoutubeDLCookieJar(self.opts.get("cookiefile"))
                jar.load()
                loaded.append(len(jar))
                # ...и сохраняет обновлённый jar в тот же поток.
                jar.save()
                logger = self.opts.get("logger")
                if logger:
                    logger.error(NET_ERROR)
                return None
            return None

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", ReloadingYDL)

    download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=A_K5zspHD30"], None,
        lambda *a, **k: None)

    assert len(loaded) >= 2, "повтора не было, проверять нечего"
    assert all(n >= 1 for n in loaded), (
        "попытка получила пустой/непригодный поток cookies: %r" % (loaded,))


def test_refresh_happens_once_per_video(cookies_file, monkeypatch):
    """Обновлять cookies по кругу нельзя: браузер читается небыстро."""
    import download_lib

    refreshed = {"n": 0}
    monkeypatch.setattr(download_lib, "refresh_cookies_from_browser",
                        lambda: (refreshed.__setitem__("n", refreshed["n"] + 1), True)[1])

    class AlwaysAgeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            logger = self.opts.get("logger")
            if logger:
                logger.error(AGE_ERROR)
            return None

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", AlwaysAgeYDL)

    download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=A_K5zspHD30"], None,
        lambda *a, **k: None)

    assert refreshed["n"] == 1, f"обновлений {refreshed['n']}, ожидалось 1"


def test_auth_error_on_last_attempt_still_refreshes(cookies_file, monkeypatch):
    """Отказ авторизации на последней попытке тоже должен лечиться.

    Иначе видео, которому не хватило попыток из-за сетевых сбоев, уходит в
    отказ с сообщением про возраст, хотя свежие cookies его спасли бы.
    """
    import download_lib

    refreshed = {"n": 0}
    monkeypatch.setattr(download_lib, "refresh_cookies_from_browser",
                        lambda: (refreshed.__setitem__("n", refreshed["n"] + 1), True)[1])
    monkeypatch.setattr(download_lib, "_sleep_cancellable", lambda *a, **k: None)

    calls = {"n": 0}

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            if not download:
                calls["n"] += 1
                logger = self.opts.get("logger")
                # Сначала сетевые сбои съедают попытки, затем отказ авторизации.
                if calls["n"] < download_lib.STREAM_RETRIES:
                    if logger:
                        logger.error("ERROR: Connection reset by peer")
                    return None
                if calls["n"] == download_lib.STREAM_RETRIES:
                    if logger:
                        logger.error(AGE_ERROR)
                    return None
                return {"id": "x", "title": "видео", "uploader": "автор",
                        "formats": [{"protocol": "https", "url": "http://x/v",
                                     "vcodec": "avc1", "acodec": "mp4a"}]}
            return None

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", FakeYDL)

    download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=A_K5zspHD30"], None,
        lambda *a, **k: None)

    assert refreshed["n"] == 1, "cookies не обновлялись на последней попытке"
    assert calls["n"] > download_lib.STREAM_RETRIES, "повтора после обновления не было"


def test_download_step_also_recovers(cookies_file, monkeypatch, tmp_path):
    """Отказ авторизации на самой загрузке тоже должен лечиться.

    Метаданные могут пройти (они доступны и без подтверждения возраста), а
    отказ прийти уже при скачивании потока.
    """
    import download_lib

    refreshed = {"n": 0}
    monkeypatch.setattr(download_lib, "refresh_cookies_from_browser",
                        lambda: (refreshed.__setitem__("n", refreshed["n"] + 1), True)[1])

    downloads = {"n": 0}
    info_ok = {"id": "x", "title": "видео", "uploader": "автор",
               "formats": [{"protocol": "https", "url": "http://x/v",
                            "vcodec": "avc1", "acodec": "mp4a"}]}

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            if not download:
                return info_ok
            downloads["n"] += 1
            if downloads["n"] == 1:
                logger = self.opts.get("logger")
                if logger:
                    logger.error(AGE_ERROR)
                return None
            return info_ok

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", FakeYDL)
    # Иначе видео считается уже скачанным и до шага загрузки дело не доходит.
    monkeypatch.setattr(download_lib, "find_downloaded_media",
                        lambda *a, **k: None)

    download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=A_K5zspHD30"], None,
        lambda *a, **k: None)

    assert refreshed["n"] == 1, "cookies не обновлялись на шаге загрузки"
    assert downloads["n"] >= 2, "повтора загрузки после обновления не было"


def test_loop_terminates_even_if_refresh_always_wanted(cookies_file, monkeypatch):
    """Цикл обязан завершаться, даже если признак однократности сломан.

    Обновление cookies не тратит попытку, поэтому ошибка в условии делала цикл
    бесконечным: прогон тестов вис насмерть. Предел витков это исключает.
    """
    import download_lib

    # Имитируем именно сломанное условие: обновление «нужно» всегда.
    monkeypatch.setattr(download_lib, "is_auth_error", lambda text: True)
    monkeypatch.setattr(download_lib, "refresh_cookies_from_browser", lambda: True)
    monkeypatch.setattr(download_lib, "_sleep_cancellable", lambda *a, **k: None)

    calls = {"n": 0}

    class AlwaysFailYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            calls["n"] += 1
            if calls["n"] > 50:
                raise AssertionError("цикл не завершается")
            logger = self.opts.get("logger")
            if logger:
                logger.error(AGE_ERROR)
            return None

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", AlwaysFailYDL)

    outcome = download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=A_K5zspHD30"], None,
        lambda *a, **k: None)

    assert outcome.failed == 1
    assert calls["n"] <= download_lib.STREAM_RETRIES + 3, calls["n"]


def test_no_refresh_without_auth_error(cookies_file, monkeypatch):
    """Обычный отказ не должен читать браузер."""
    import download_lib

    refreshed = {"n": 0}
    monkeypatch.setattr(download_lib, "refresh_cookies_from_browser",
                        lambda: (refreshed.__setitem__("n", refreshed["n"] + 1), True)[1])

    class UnavailableYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            logger = self.opts.get("logger")
            if logger:
                logger.error("ERROR: [youtube] xyz: Video unavailable")
            return None

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", UnavailableYDL)

    download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=xyz"], None, lambda *a, **k: None)

    assert refreshed["n"] == 0, "cookies обновлялись без нужды"
