# Тесты багов загрузки, найденных аудитом: плейлист вместо одного видео,
# ложный «успех» при занятом локе, потеря аудио-only, дубли папок #shorts,
# потеря причины ошибки и дедупликация уже скачанного.
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import download_lib  # noqa: E402


@pytest.fixture(autouse=True)
def clean_locks():
    """Локи глобальные: незакрытый ключ ломал бы следующие тесты."""
    download_lib.download_locks.clear()
    yield
    download_lib.download_locks.clear()


# --- Плейлист в одиночной загрузке ---------------------------------------

def test_ydl_opts_disable_playlist():
    """Ссылка с &list= без noplaylist тянула весь плейлист в одну папку.

    yt-dlp отдаёт такой URL в YoutubeTabIE, и все видео пишутся в один
    outtmpl (video.%(ext)s), перезаписывая друг друга.
    """
    opts = download_lib.get_ydl_opts(None, "mp4", None, "tmp_playlist_check")
    assert opts.get("noplaylist") is True


def test_info_extraction_disables_playlist(monkeypatch, tmp_path):
    """Предварительное извлечение тоже должно смотреть на одно видео.

    Иначе uploader/id берутся у плейлиста, и папка выходит Unknown/PLxxxx.
    """
    seen = {}

    class _SpyYDL:
        def __init__(self, opts):
            seen.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            return {"id": "vid", "title": "T", "uploader": "A",
                    "width": 1920, "height": 1080, "duration": 300}

    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _SpyYDL)
    monkeypatch.setattr(download_lib, "download_single_video_impl",
                        lambda *a, **k: True)

    download_lib.download_single_sync(
        ["https://www.youtube.com/watch?v=vid&list=PLxxxx"], None, lambda p, m: None)

    assert seen.get("noplaylist") is True


# --- Ложный «успех» при занятом локе -------------------------------------

def test_busy_lock_is_not_reported_as_success(tmp_path):
    """`return True` при занятом локе давал «Готово» без файла на диске.

    Параллельный /api/direct_download на тот же URL мгновенно «завершал»
    задачу очереди, хотя она ничего не скачала.
    """
    download_lib.download_locks["busy"] = True

    result = download_lib.download_single_video_impl(
        "busy", None, str(tmp_path), None, None, "mp4")

    assert not result, "занятый лок не должен выглядеть как успешная загрузка"


def test_busy_lock_keeps_foreign_lock(tmp_path):
    """Свой лок чужой загрузки снимать нельзя."""
    download_lib.download_locks["busy"] = True

    download_lib.download_single_video_impl("busy", None, str(tmp_path), None, None, "mp4")

    assert download_lib.download_locks.get("busy") is True


def test_temp_dir_initialized_before_try():
    """temp_dir должен существовать к моменту входа в try.

    Иначе падение на его вычислении даёт UnboundLocalError уже из finally:
    исходная ошибка подменяется, а лок не снимается.
    """
    import inspect

    src = inspect.getsource(download_lib.download_single_video_impl)
    # Ищем оператор, а не подстроку: слово «try:» встречается и в комментариях.
    init = src.find("\n    temp_dir = None")
    opener = src.find("\n    try:")
    assert init != -1, "нет инициализации temp_dir на уровне функции"
    assert opener != -1, "не найден блок try"
    assert init < opener, "temp_dir инициализирован позже входа в try"


def test_lock_released_when_temp_dir_fails():
    """UnboundLocalError из finally оставлял ключ лока навсегда.

    temp_dir присваивался внутри try, поэтому падение на этой строке приводило
    к UnboundLocalError уже из finally: исходная ошибка подменялась, а
    download_locks.pop не выполнялся. После этого URL нельзя было скачать до
    перезапуска процесса — каждая попытка попадала в ветку «уже скачивается».
    """
    result = download_lib.download_single_video_impl(None, None, ".", None, None, "mp4")

    assert result is False
    assert download_lib.download_locks == {}, "ключ лока утёк"


# --- Аудио-only ----------------------------------------------------------

class _AudioOnlyYDL:
    """Отдаёт то, что yt-dlp реально пишет для bestaudio: .m4a."""

    info = {"id": "aud1", "title": "Только звук", "uploader": "Канал",
            "duration": 30, "acodec": "aac", "vcodec": "none"}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if not download:
            return dict(self.info)
        temp = os.path.dirname(self.opts["outtmpl"])
        os.makedirs(temp, exist_ok=True)
        (Path(temp) / "video.m4a").write_bytes(b"audio")
        (Path(temp) / "video.info.json").write_text("{}", encoding="utf-8")
        return dict(self.info)


def test_audio_only_download_succeeds(monkeypatch, tmp_path):
    """Кнопка «Только звук» отдавала «Ошибка скачивания».

    Фильтр media_files принимал только видеоконтейнеры, поэтому .m4a
    не считался результатом и файл удалялся вместе с temp-папкой.
    """
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _AudioOnlyYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)

    outcome = download_lib.download_single_sync(
        ["https://youtu.be/aud1"], "bestaudio/best", lambda p, m: None, "mp4")

    assert (outcome.succeeded, outcome.failed) == (1, 0)
    saved = [p.name for p in tmp_path.rglob("video.*") if p.is_file()]
    assert "video.m4a" in saved, f"аудиофайл не сохранён, есть только: {saved}"


def test_audio_only_keeps_metadata(monkeypatch, tmp_path):
    """Метаданные аудиозагрузки тоже должны сохраниться."""
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _AudioOnlyYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)

    download_lib.download_single_sync(["https://youtu.be/aud1"], "bestaudio/best",
                                      lambda p, m: None, "mp4")

    assert [p.name for p in tmp_path.rglob("info.json")] == ["info.json"]


class _ShortsYDL:
    """Короткое вертикальное видео: получает суффикс « #shorts» в имени папки."""

    downloads = 0
    info = {"id": "sh1", "title": "Вертикаль", "uploader": "Канал",
            "width": 720, "height": 1280, "duration": 30}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if not download:
            return dict(self.info)
        _ShortsYDL.downloads += 1
        temp = os.path.dirname(self.opts["outtmpl"])
        os.makedirs(temp, exist_ok=True)
        (Path(temp) / "video.mp4").write_bytes(b"video")
        return dict(self.info)


def test_shorts_folder_is_not_duplicated(monkeypatch, tmp_path):
    """Проверка «уже скачано» должна учитывать суффикс « #shorts».

    Папка Shorts называется «<id> #shorts», а обычная — «<id>». Если искать
    только по «<id>», повтор создаст второй каталог для того же видео, и одна
    из папок исчезнет из библиотеки: ключ VIDEO_MAP у них общий.
    """
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _ShortsYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    _ShortsYDL.downloads = 0

    download_lib.download_single_sync(["https://youtu.be/sh1"], None, lambda p, m: None, "mp4")
    download_lib.download_single_sync(["https://youtu.be/sh1"], None, lambda p, m: None, "mp4")

    dirs = sorted(p.name for p in tmp_path.rglob("sh1*") if p.is_dir())
    assert dirs == ["sh1 #shorts"], f"каталоги: {dirs}"
    assert _ShortsYDL.downloads == 1, "Shorts скачан повторно"


# --- Дедупликация уже скачанного -----------------------------------------

class _CountingYDL:
    """Считает, сколько раз реально запускалась загрузка."""

    downloads = 0
    info = {"id": "dup1", "title": "Ролик", "uploader": "Канал",
            "width": 1920, "height": 1080, "duration": 300}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if not download:
            return dict(self.info)
        _CountingYDL.downloads += 1
        temp = os.path.dirname(self.opts["outtmpl"])
        os.makedirs(temp, exist_ok=True)
        (Path(temp) / "video.mp4").write_bytes(b"video-data")
        (Path(temp) / "video.info.json").write_text("{}", encoding="utf-8")
        return dict(self.info)


def test_existing_video_is_not_downloaded_again(monkeypatch, tmp_path):
    """Повтор задачи качал заново все видео, включая уже лежащие на диске.

    На пачке из 79 ссылок, упавшей на 12-й, «Повторить» означало полную
    перекачку первых одиннадцати.
    """
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _CountingYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    _CountingYDL.downloads = 0

    first = download_lib.download_single_sync(["https://youtu.be/dup1"], None,
                                              lambda p, m: None, "mp4")
    second = download_lib.download_single_sync(["https://youtu.be/dup1"], None,
                                               lambda p, m: None, "mp4")

    assert (first.succeeded, first.failed) == (1, 0)
    assert (second.succeeded, second.failed) == (1, 0), "повтор должен считаться успехом"
    assert _CountingYDL.downloads == 1, "видео скачано повторно, хотя уже было на диске"


def test_existing_video_survives_repeat(monkeypatch, tmp_path):
    """Уже скачанный файл не должен пострадать при повторной попытке."""
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _CountingYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    _CountingYDL.downloads = 0

    download_lib.download_single_sync(["https://youtu.be/dup1"], None, lambda p, m: None, "mp4")
    video = next(p for p in tmp_path.rglob("video.mp4"))
    video.write_bytes(b"user-copy")

    download_lib.download_single_sync(["https://youtu.be/dup1"], None, lambda p, m: None, "mp4")

    assert video.read_bytes() == b"user-copy"


def test_progress_reports_skipped_video(monkeypatch, tmp_path):
    """Пропуск уже скачанного должен быть виден в прогрессе, а не молчать."""
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _CountingYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    _CountingYDL.downloads = 0

    download_lib.download_single_sync(["https://youtu.be/dup1"], None, lambda p, m: None, "mp4")
    messages = []
    download_lib.download_single_sync(["https://youtu.be/dup1"], None,
                                      lambda p, m: messages.append(m), "mp4")

    assert any("уже" in m.lower() for m in messages), messages


# --- Причина ошибки ------------------------------------------------------

class _NoFileYDL:
    """Загрузка «прошла», но файла нет: ignoreerrors гасит настоящую ошибку."""

    info = {"id": "err1", "title": "Ролик", "uploader": "Канал",
            "width": 1920, "height": 1080, "duration": 300}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if not download:
            return dict(self.info)
        temp = os.path.dirname(self.opts["outtmpl"])
        os.makedirs(temp, exist_ok=True)
        return dict(self.info)


def test_direct_download_reports_http_error(client, app_module, monkeypatch):
    """Отказ приходил с HTTP 200 и телом error: клиент считал его успехом."""
    monkeypatch.setattr(app_module, "download_single_sync",
                        lambda *a, **k: download_lib.DownloadOutcome(0, 1, "HTTP Error 403"))

    res = client.post("/api/direct_download", json={"url": "https://youtu.be/x"})

    assert res.status_code == 502
    assert "403" in res.get_json()["error"]


def test_direct_download_reports_partial(client, app_module, monkeypatch):
    """Частичный провал отдавался как «Загрузка завершена»."""
    monkeypatch.setattr(app_module, "download_single_sync",
                        lambda *a, **k: download_lib.DownloadOutcome(1, 4, "таймаут"))
    monkeypatch.setattr(app_module, "build_video_map", lambda: 0)

    body = client.post("/api/direct_download", json={"url": "https://youtu.be/x"}).get_json()

    assert body["status"] == "partial"
    assert "4" in body["title"]


def test_direct_download_combined_format_has_fallback(client, app_module, monkeypatch):
    """Пара id без fallback приводила к отказу, если формата у видео нет."""
    seen = {}

    def fake(urls, fmt, cb, merge_format="mp4", should_cancel=None):
        seen["fmt"] = fmt
        return download_lib.DownloadOutcome(1, 0)

    monkeypatch.setattr(app_module, "download_single_sync", fake)
    monkeypatch.setattr(app_module, "build_video_map", lambda: 0)

    client.post("/api/direct_download",
                json={"url": "https://youtu.be/x", "format_id": "137", "audio_format_id": "251"})

    assert seen["fmt"].endswith("/best"), seen["fmt"]


def test_direct_formats_requires_video_id(client):
    """Эндпоинт получал локальный путь вместо URL и всегда отдавал пустой список."""
    assert client.post("/api/direct_formats", json={}).status_code == 400


def test_direct_formats_returns_local_quality(client, app_module, monkeypatch):
    """Меню качества в плеере всегда показывало «Нет доступных форматов»."""
    monkeypatch.setattr(app_module, "ensure_video_map", lambda: None)
    monkeypatch.setattr(app_module, "VIDEO_MAP", {
        "vid1": {"author": "Канал", "folder": "vid1", "filename": "video.mp4", "size_mb": 12.3},
    }, raising=False)
    monkeypatch.setattr(app_module, "find_file", lambda *a, **k: None)

    body = client.post("/api/direct_formats", json={"video_id": "vid1"}).get_json()

    assert body["formats"], "список форматов пуст"
    assert body["formats"][0]["size_mb"] == 12.3


def test_direct_formats_404_for_unknown(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "ensure_video_map", lambda: None)
    monkeypatch.setattr(app_module, "VIDEO_MAP", {}, raising=False)
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {}, raising=False)

    assert client.post("/api/direct_formats", json={"video_id": "нет"}).status_code == 404


def test_failure_reason_reaches_progress(monkeypatch, tmp_path):
    """Пользователь видел только «Ошибка скачивания» без причины.

    yt-dlp с ignoreerrors=True не бросает исключение, поэтому текст ошибки
    надо доставать самостоятельно и передавать наверх.
    """
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _NoFileYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)

    messages = []
    outcome = download_lib.download_single_sync(
        ["https://youtu.be/err1"], None, lambda p, m: messages.append(m), "mp4")

    assert not outcome
    assert any("файл" in m.lower() for m in messages), messages


class _TalkingYDL:
    """Пишет причину отказа в logger, как это делает yt-dlp при ignoreerrors."""

    message = "ERROR: [youtube] err2: HTTP Error 403: Forbidden"

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        info = {"id": "err2", "title": "Ролик", "uploader": "Канал",
                "width": 1920, "height": 1080, "duration": 300}
        if not download:
            return info
        # Файл не создаём: загрузка «прошла», но результата нет.
        logger = self.opts.get("logger")
        if logger:
            logger.error(self.message)
        os.makedirs(os.path.dirname(self.opts["outtmpl"]), exist_ok=True)
        return info


def test_ydl_error_text_is_collected(monkeypatch, tmp_path):
    """Текст, который yt-dlp пишет в logger, должен попасть в результат.

    Без перехвата настоящая причина (403, гео-блок, нет формата) оставалась
    только в stdout процесса, куда пользователь не смотрит.
    """
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _TalkingYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)

    messages = []
    outcome = download_lib.download_single_sync(
        ["https://youtu.be/err2"], None, lambda p, m: messages.append(m), "mp4")

    assert "403" in outcome.last_error, outcome.last_error
    assert any("403" in m for m in messages), messages


def test_error_collector_strips_noise():
    """Префикс ERROR: и [youtube] пользователю не нужны."""
    collector = download_lib._ErrorCollector()
    collector.error("ERROR: [youtube] dQw4w9WgXcQ: Video unavailable")
    assert collector.last_error() == "[youtube] dQw4w9WgXcQ: Video unavailable"
    # _short_reason снимает и «[youtube] », и 11-символьный id видео.
    assert download_lib._short_reason(collector.last_error()) == "Video unavailable"


def test_error_collector_ignores_ffmpeg_notice():
    """Предупреждение о склейке — не причина отказа."""
    collector = download_lib._ErrorCollector()
    collector.error("You have requested merging of multiple formats")
    assert collector.last_error() == ""


def test_ffmpeg_call_is_bounded():
    """Зависший ffmpeg вечно держал единственный поток очереди.

    yt-dlp вызывает Popen.run без timeout, а кооперативная отмена читается
    только из хуков прогресса, которых на этапе склейки уже нет. Ни
    «Отменить», ни «Удалить» воркер не освобождали.
    """
    from yt_dlp.postprocessor import ffmpeg as ffmpeg_pp

    original = ffmpeg_pp.Popen
    try:
        download_lib.install_ffmpeg_timeout(2)
        started = time.time()
        with pytest.raises(Exception) as excinfo:
            ffmpeg_pp.Popen.run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
        spent = time.time() - started
        assert spent < 20, f"вызов не был прерван, прошло {spent:.1f} c"
        assert "Timeout" in type(excinfo.value).__name__, excinfo.value
    finally:
        ffmpeg_pp.Popen = original


def test_ffmpeg_timeout_allows_fast_commands():
    """Ограничение не должно ломать нормальную склейку."""
    from yt_dlp.postprocessor import ffmpeg as ffmpeg_pp

    original = ffmpeg_pp.Popen
    try:
        download_lib.install_ffmpeg_timeout(30)
        out, _, code = ffmpeg_pp.Popen.run(
            [sys.executable, "-c", "print(42)"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
        assert code == 0 and out.strip() == "42"
    finally:
        ffmpeg_pp.Popen = original


def test_repeated_install_does_not_nest():
    """Патч ставится на каждую загрузку, цепочка наследования расти не должна."""
    from yt_dlp.postprocessor import ffmpeg as ffmpeg_pp

    original = ffmpeg_pp.Popen
    try:
        first = download_lib.install_ffmpeg_timeout(30)
        for _ in range(5):
            last = download_lib.install_ffmpeg_timeout(30)
        # Классы разные при каждой установке — это нормально. Важно, что
        # глубина наследования постоянна: иначе каждый вызов добавлял бы
        # обёртку поверх предыдущей.
        assert len(last.__mro__) == len(first.__mro__), "класс обёртки наращивается"
        assert last.__mro__[1:] == first.__mro__[1:], "базовый класс подменён"
    finally:
        ffmpeg_pp.Popen = original


def test_download_installs_ffmpeg_timeout(monkeypatch, tmp_path):
    """Ограничение должно ставиться на реальном пути загрузки."""
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _NoFileYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    calls = []
    monkeypatch.setattr(download_lib, "install_ffmpeg_timeout", lambda *a: calls.append(True))

    download_lib.download_single_sync(["https://youtu.be/t1"], None, lambda p, m: None, "mp4")

    assert calls, "install_ffmpeg_timeout не вызывается при загрузке"


def test_metadata_fetch_has_socket_timeout(monkeypatch, tmp_path):
    """Без socket_timeout запрос метаданных висел бесконечно.

    По умолчанию таймаута у yt-dlp нет вовсе, и зависшее соединение занимало
    единственный поток очереди ещё до начала загрузки.
    """
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    seen = []

    class _SpyYDL(_NoFileYDL):
        def __init__(self, opts):
            seen.append(opts)
            super().__init__(opts)

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _SpyYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)

    download_lib.download_single_sync(["https://youtu.be/t2"], None, lambda p, m: None, "mp4")

    info_opts = seen[0]
    assert info_opts.get("socket_timeout"), "у запроса метаданных нет socket_timeout"


# --- Версия yt-dlp -------------------------------------------------------

def test_yt_dlp_is_new_enough_for_sabr():
    """yt-dlp до 2026.8 не умел обходить SABR-стриминг YouTube.

    Ссылки приходили от android_vr без PO-токена, и YouTube обрывал загрузку
    на 13-17 МБ с HTTP 403: маленькие видео скачивались, большие — нет.
    """
    yt_dlp = pytest.importorskip("yt_dlp")

    parts = yt_dlp.version.__version__.split(".")
    year, month = int(parts[0]), int(parts[1])

    assert (year, month) >= (2026, 8), (
        "yt-dlp %s слишком старый: YouTube будет отдавать 403 на середине"
        % yt_dlp.version.__version__)


# --- Решение JS-челленджа (n challenge) ----------------------------------
#
# yt-dlp 2026.08 решает n challenge внешним скриптом (EJS), который качается
# с GitHub при первом запуске. Без разрешения на скачивание он пишет
# «n challenge solving failed: Some formats may be missing» и ОТБРАСЫВАЕТ все
# https-форматы: в info остаются только storyboard (mhtml), а любой селектор
# формата падает с «Requested format is not available». В логе пользователя
# так провалились ВСЕ 79 видео задачи.

def test_download_opts_allow_challenge_solver():
    """Без remote_components yt-dlp отбрасывает все видео-форматы."""
    opts = download_lib.get_ydl_opts(None, "mp4", None, "tmp_ejs_check")

    assert "ejs:github" in (opts.get("remote_components") or []), \
        "загрузка не разрешает скачать решатель JS-челленджа"


def test_download_opts_keep_player_client(monkeypatch):
    """Выбор player-клиента должен доходить до загрузки вместе с решателем."""
    monkeypatch.setattr(download_lib, "get_po_args",
                        lambda: {"remote_components": ["ejs:github"],
                                 "extractor_args": {"youtube": {"player_client": ["tv"]}}})

    opts = download_lib.get_ydl_opts(None, "mp4", None, "tmp_ejs_check2")

    assert opts["extractor_args"]["youtube"]["player_client"] == ["tv"]
    assert "ejs:github" in opts["remote_components"]


def test_metadata_opts_allow_challenge_solver(monkeypatch, tmp_path):
    """Запрос метаданных тоже отдаёт пустой список форматов без решателя."""
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    seen = []

    class _SpyYDL(_NoFileYDL):
        def __init__(self, opts):
            seen.append(opts)
            super().__init__(opts)

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _SpyYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)

    download_lib.download_single_sync(["https://youtu.be/t3"], None, lambda p, m: None, "mp4")

    assert "ejs:github" in (seen[0].get("remote_components") or []), \
        "у запроса метаданных нет remote_components"


def test_yt_dlp_knows_the_remote_component():
    """Имя компонента должно быть тем, которое yt-dlp реально принимает.

    Неизвестное значение он молча выбрасывает с предупреждением «Ignoring
    unsupported remote component», и форматы снова пропадут.
    """
    pytest.importorskip("yt_dlp")
    from yt_dlp.globals import supported_remote_components

    assert "ejs:github" in supported_remote_components.value


def test_only_storyboards_is_not_a_usable_result():
    """Раскадровка (mhtml) — не видео и не звук.

    Именно она остаётся, когда решатель челленджа не сработал; принимать такой
    список за успех значит уйти в загрузку и получить невнятное
    «Requested format is not available».
    """
    only_storyboards = [{"format_id": "sb0", "ext": "mhtml", "protocol": "mhtml",
                         "vcodec": "none", "acodec": "none", "url": "http://x/sb"}]

    assert download_lib.has_media_formats(only_storyboards) is False
    assert download_lib.has_media_formats(
        only_storyboards + [{"format_id": "137", "ext": "mp4", "protocol": "https",
                             "vcodec": "avc1", "acodec": "none",
                             "url": "http://x/v"}]) is True


def test_storyboard_is_rejected_by_protocol_alone():
    """Отбор по протоколу нужен сам по себе, без опоры на кодеки."""
    lying_storyboard = [{"format_id": "sb0", "ext": "mhtml", "protocol": "mhtml",
                         "vcodec": "avc1", "acodec": "mp4a", "url": "http://x/sb"}]

    assert download_lib.has_media_formats(lying_storyboard) is False


def test_stream_without_codecs_is_rejected_by_codecs_alone():
    """Отбор по кодекам нужен сам по себе, без опоры на протокол."""
    no_codecs = [{"format_id": "sb9", "ext": "jpg", "protocol": "https",
                  "vcodec": "none", "acodec": "none", "url": "http://x/sb"}]

    assert download_lib.has_media_formats(no_codecs) is False


def test_unknown_codecs_are_accepted():
    """Отсутствие данных о кодеке — не повод отвергать поток.

    yt-dlp не всегда заполняет vcodec/acodec; 'none' он ставит осознанно, а
    None означает «неизвестно».
    """
    unknown = [{"format_id": "0", "ext": "mp4", "protocol": "https",
                "url": "http://x/v"}]

    assert download_lib.has_media_formats(unknown) is True


def test_format_without_url_is_not_usable():
    """SABR-форматы приходят без URL — качать их нечем."""
    sabr_only = [{"format_id": "137", "ext": "mp4", "protocol": "https",
                  "vcodec": "avc1", "acodec": "none"}]

    assert download_lib.has_media_formats(sabr_only) is False
    # Фрагментный формат (HLS/DASH) URL не имеет, но скачивается.
    assert download_lib.has_media_formats(
        [{"format_id": "270", "ext": "mp4", "protocol": "m3u8_native",
          "vcodec": "avc1", "acodec": "none",
          "fragments": [{"url": "http://x/1"}]}]) is True


def test_missing_media_formats_are_reported(monkeypatch, tmp_path):
    """Понятная причина вместо «Requested format is not available».

    Пользователь видел этот текст 79 раз и не мог понять, что дело в
    несработавшем решателе JS-челленджа.
    """
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})

    class _StoryboardOnlyYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            return {"id": "sb1", "title": "Видео", "uploader": "Автор",
                    "formats": [{"format_id": "sb0", "ext": "mhtml",
                                 "protocol": "mhtml", "vcodec": "none",
                                 "acodec": "none", "url": "http://x/sb"}]}

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _StoryboardOnlyYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    messages = []

    result = download_lib.download_single_sync(
        ["https://youtu.be/sb1"], None, lambda p, m: messages.append(m), "mp4")

    assert result.failed == 1 and result.succeeded == 0
    text = (" ".join(messages) + " " + result.last_error).lower()
    assert "формат" in text, text
    assert "js" in text or "челлендж" in text, \
        "причина не указывает на несработавший решатель челленджа: " + text


def test_requirements_pin_sabr_capable_yt_dlp():
    """Свежая версия должна требоваться и при установке с нуля."""
    root = Path(__file__).resolve().parent.parent
    text = (root / "requirements.txt").read_text(encoding="utf-8")

    line = [l for l in text.splitlines() if l.strip().startswith("yt-dlp")
            and "ejs" not in l]
    assert line, "yt-dlp не указан в requirements.txt"

    floor = line[0].split(">=")[1].strip()
    year, month = (int(x) for x in floor.split(".")[:2])
    assert (year, month) >= (2026, 8), "нижняя граница yt-dlp слишком старая: " + floor


# --- Временные сетевые сбои ---------------------------------------------

class _FlakyMetadataYDL:
    """Метаданные падают N раз с сетевой ошибкой, потом отдаются нормально."""

    fail_times = 1
    attempts = 0

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        type(self).attempts += 1
        if type(self).attempts <= type(self).fail_times:
            logger = self.opts.get("logger")
            if logger:
                logger.error(
                    "ERROR: [youtube] x: Unable to download API page: "
                    "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in "
                    "violation of protocol (_ssl.c:1081)")
            return None
        return {"id": "vid1", "title": "Видео", "uploader": "Канал",
                "width": 1920, "height": 1080}

    def download(self, urls):
        return 0


def test_network_error_on_metadata_is_retried(monkeypatch, tmp_path):
    """Обрыв сети при запросе метаданных должен приводить к повтору.

    Раньше видео сразу уходило в «Пропуск видео»: ретраи стояли только на
    самой загрузке, а сбой на метаданных не давал ни одной повторной попытки.
    За один прогон так терялось 55 видео из 79.
    """
    _FlakyMetadataYDL.attempts = 0
    _FlakyMetadataYDL.fail_times = 1
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _FlakyMetadataYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    monkeypatch.setattr(download_lib, "load_config",
                        lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib, "download_single_video_impl",
                        lambda *a, **k: True)

    outcome = download_lib.download_single_sync(
        ["https://youtu.be/vid1"], None, lambda p, m: None, "mp4")

    assert _FlakyMetadataYDL.attempts >= 2, "повтора не было"
    assert outcome.succeeded == 1, "видео потеряно из-за временного сбоя"


def test_metadata_retries_are_limited(monkeypatch, tmp_path):
    """Постоянно недоступное видео не должно крутиться бесконечно."""
    _FlakyMetadataYDL.attempts = 0
    _FlakyMetadataYDL.fail_times = 999
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _FlakyMetadataYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    monkeypatch.setattr(download_lib, "load_config",
                        lambda: {"video_dir": str(tmp_path)})

    outcome = download_lib.download_single_sync(
        ["https://youtu.be/vid1"], None, lambda p, m: None, "mp4")

    assert outcome.failed == 1
    assert _FlakyMetadataYDL.attempts <= download_lib.STREAM_RETRIES
    assert "SSL" in outcome.last_error or "EOF" in outcome.last_error


def test_permanent_error_is_not_retried(monkeypatch, tmp_path):
    """«Video unavailable» повторять бессмысленно — это не сетевой сбой."""

    class _GoneYDL(_FlakyMetadataYDL):
        def extract_info(self, url, download=False):
            type(self).attempts += 1
            logger = self.opts.get("logger")
            if logger:
                logger.error("ERROR: [youtube] x: Video unavailable")
            return None

    _GoneYDL.attempts = 0
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _GoneYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    monkeypatch.setattr(download_lib, "load_config",
                        lambda: {"video_dir": str(tmp_path)})

    download_lib.download_single_sync(
        ["https://youtu.be/vid1"], None, lambda p, m: None, "mp4")

    assert _GoneYDL.attempts == 1, "недоступное видео не нужно повторять"


def test_transient_network_error_is_recognised():
    """Классификатор должен отличать сетевой сбой от отказа YouTube."""
    transient = [
        "Unable to download API page: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF",
        "ConnectionResetError(10054)",
        "[Errno 11001] getaddrinfo failed",
        "HTTP Error 403: Forbidden",
        "Remote end closed connection without response",
        "timed out",
    ]
    permanent = [
        "Video unavailable",
        "Private video. Sign in if you've been granted access",
        "This channel does not have a streams tab",
        "Requested format is not available",
    ]

    # Незнакомый текст повторять не нужно: иначе любая ошибка (например,
    # неверные настройки) крутилась бы по три раза с паузами.
    unknown = [
        "Something completely unexpected happened",
        "Unable to parse metadata",
        "",
        "   ",
    ]

    for text in transient:
        assert download_lib.is_transient_error(text), text
    for text in permanent:
        assert not download_lib.is_transient_error(text), text
    for text in unknown:
        assert not download_lib.is_transient_error(text), text


class _DeadNetworkYDL:
    """Сеть лежит: метаданные не приходят ни для одного видео."""

    attempts = 0

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        type(self).attempts += 1
        logger = self.opts.get("logger")
        if logger:
            logger.error("ERROR: [youtube] x: Unable to download API page: "
                         "ConnectionResetError(10054)")
        return None

    def download(self, urls):
        return 0


def test_dead_network_stops_task_early(monkeypatch, tmp_path):
    """При полностью недоступной сети задача не должна перебирать все ссылки.

    Каждое видео тратит три попытки с паузами, поэтому на списке из 79 ссылок
    очередь молотила бы часами вместо того, чтобы остановиться и дать повторить
    задачу позже.
    """
    _DeadNetworkYDL.attempts = 0
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _DeadNetworkYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    monkeypatch.setattr(download_lib, "load_config",
                        lambda: {"video_dir": str(tmp_path)})

    urls = ["https://youtu.be/v%d" % i for i in range(20)]
    outcome = download_lib.download_single_sync(
        urls, None, lambda p, m: None, "mp4")

    limit = download_lib.NETWORK_FAILURE_STREAK * download_lib.STREAM_RETRIES
    assert _DeadNetworkYDL.attempts <= limit, (
        "перебрали слишком много ссылок при лежащей сети: %d"
        % _DeadNetworkYDL.attempts)
    assert outcome.failed >= 1
    assert "сет" in outcome.last_error.lower() or "network" in outcome.last_error.lower()


def test_single_bad_video_does_not_stop_task(monkeypatch, tmp_path):
    """Одно недоступное видео не должно обрывать всю задачу."""
    calls = {"n": 0}

    class _OneBadYDL(_DeadNetworkYDL):
        def extract_info(self, url, download=False):
            calls["n"] += 1
            if calls["n"] == 1:
                logger = self.opts.get("logger")
                if logger:
                    logger.error("ERROR: [youtube] x: Video unavailable")
                return None
            return {"id": "v%d" % calls["n"], "title": "T", "uploader": "Chan",
                    "width": 1920, "height": 1080}

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _OneBadYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    monkeypatch.setattr(download_lib, "load_config",
                        lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib, "download_single_video_impl",
                        lambda *a, **k: True)

    outcome = download_lib.download_single_sync(
        ["https://youtu.be/a", "https://youtu.be/b", "https://youtu.be/c"],
        None, lambda p, m: None, "mp4")

    assert outcome.succeeded == 2, outcome
    assert outcome.failed == 1, outcome


def test_many_unavailable_videos_do_not_stop_task(monkeypatch, tmp_path):
    """Подряд идущие «Video unavailable» — не повод обрывать задачу.

    Остановка нужна только при сетевом сбое: удалённые видео в списке из 79
    ссылок встречаются часто, и терять из-за них остальные нельзя.
    """
    seen = {"n": 0}

    class _AllGoneYDL(_DeadNetworkYDL):
        def extract_info(self, url, download=False):
            seen["n"] += 1
            logger = self.opts.get("logger")
            if logger:
                logger.error("ERROR: [youtube] x: Video unavailable")
            return None

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _AllGoneYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    monkeypatch.setattr(download_lib, "load_config",
                        lambda: {"video_dir": str(tmp_path)})

    urls = ["https://youtu.be/v%d" % i for i in range(8)]
    outcome = download_lib.download_single_sync(
        urls, None, lambda p, m: None, "mp4")

    assert seen["n"] == 8, "задача оборвалась на недоступных видео"
    assert outcome.failed == 8


def test_success_resets_network_streak(monkeypatch, tmp_path):
    """Успешное видео обнуляет счётчик сетевых сбоев.

    Иначе редкие обрывы, разбросанные по длинному списку, накопились бы и
    остановили задачу, хотя сеть работает.
    """
    calls = {"n": 0}
    # Схема: сбой, успех, сбой, успех, ... — подряд никогда не больше одного.
    class _AlternatingYDL(_DeadNetworkYDL):
        def extract_info(self, url, download=False):
            calls["n"] += 1
            if calls["n"] % 2 == 1:
                logger = self.opts.get("logger")
                if logger:
                    logger.error("ERROR: [youtube] x: Unable to download API "
                                 "page: ConnectionResetError(10054)")
                return None
            return {"id": "v%d" % calls["n"], "title": "T", "uploader": "Chan",
                    "width": 1920, "height": 1080}

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _AlternatingYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    monkeypatch.setattr(download_lib, "load_config",
                        lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib, "download_single_video_impl",
                        lambda *a, **k: True)

    urls = ["https://youtu.be/v%d" % i for i in range(10)]
    outcome = download_lib.download_single_sync(
        urls, None, lambda p, m: None, "mp4")

    # Первая попытка каждого видео падает, вторая проходит, поэтому задача
    # доходит до конца списка и ни одно видео не теряется.
    assert outcome.succeeded == 10, outcome
    assert outcome.failed == 0, outcome
    assert calls["n"] == 20, calls


def test_scattered_network_failures_do_not_stop_task(monkeypatch, tmp_path):
    """Одиночные сетевые отказы, разбросанные по списку, не обрывают задачу.

    Счётчик подряд идущих сбоев обязан обнуляться после каждого успеха: без
    этого третий отказ где-то в конце длинного списка останавливал задачу,
    хотя между отказами всё скачивалось нормально.
    """
    calls = {"n": 0}
    # Видео 1, 4, 7 проваливаются насовсем (сеть), остальные скачиваются.
    dead = {1, 4, 7}

    class _ScatteredYDL(_DeadNetworkYDL):
        def extract_info(self, url, download=False):
            calls["n"] += 1
            idx = int(url.rsplit("/v", 1)[1])
            if idx in dead:
                logger = self.opts.get("logger")
                if logger:
                    logger.error("ERROR: [youtube] x: Unable to download API "
                                 "page: ConnectionResetError(10054)")
                return None
            return {"id": "v%d" % idx, "title": "T", "uploader": "Chan",
                    "width": 1920, "height": 1080}

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _ScatteredYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    monkeypatch.setattr(download_lib, "load_config",
                        lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib, "download_single_video_impl",
                        lambda *a, **k: True)

    urls = ["https://youtu.be/v%d" % i for i in range(9)]
    outcome = download_lib.download_single_sync(
        urls, None, lambda p, m: None, "mp4")

    assert outcome.succeeded == 6, outcome
    assert outcome.failed == 3, outcome
