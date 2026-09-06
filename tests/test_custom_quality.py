"""Тесты выбора качества видео в плеере (144p-2160p).

Файл в библиотеке лежит в одном качестве — том, в котором его скачали. Чтобы
посмотреть его в другом разрешении, LocalTube пересобирает файл через ffmpeg:
уменьшает («шакализатор» 144p) или растягивает («улучшайзер» 4K). Результат
сохраняется рядом с исходником как video_<качество>.<расширение> и остаётся
доступным без повторной конвертации.

Проверяется главное: набор качеств не разъезжается между проверкой запроса,
меню и рецептами ffmpeg. Раньше такое расхождение приводило к тому, что кнопка
в меню была, а запрос отклонялся с «Неизвестное качество», либо наоборот —
неизвестное значение молча конвертировалось в 720p и складывалось в файл,
которого интерфейс потом не находил.
"""
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import custom_quality  # noqa: E402
import i18n  # noqa: E402


@pytest.fixture
def library(tmp_path, app_module, monkeypatch):
    """Библиотека из одного видео во временной папке.

    Настоящий каталог пользователя не годится: конвертация пишет файлы рядом с
    исходником, и прогон оставлял бы в библиотеке video_144.mp4.
    """
    # Пробел и «+» в имени автора — не редкость, и именно они ломали адрес без
    # кодирования: «+» браузер читает как пробел, а пробел рвёт ссылку.
    folder = tmp_path / "Канал Автора +1" / "vid1"
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"0" * 2048)
    monkeypatch.setattr(custom_quality, "_BASE_VIDEO_DIR", str(tmp_path))
    # /media отдаёт файлы по своей копии пути: без подмены проверка адреса
    # ушла бы в настоящую библиотеку пользователя.
    monkeypatch.setattr(app_module, "BASE_VIDEO_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "VIDEO_MAP", {
        "vid1": {"author": "Канал Автора +1", "folder": "vid1",
                 "filename": "video.mp4"},
    }, raising=False)
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {}, raising=False)
    monkeypatch.setattr(app_module, "build_video_map", lambda: 1)
    monkeypatch.setattr(app_module, "build_user_video_map", lambda: 0)
    return folder


# ================= Набор качеств =================

# Разрешения, которые обязан предлагать плеер. Верх и низ заданы задачей:
# 144p («шакализатор») и 2160p (4K). Промежуточные ступени — стандартный ряд
# YouTube, без них выбор рвётся: между 480p и 144p нет ничего.
EXPECTED_HEIGHTS = ("2160", "1440", "1080", "720", "480", "360", "240", "144")


@pytest.mark.parametrize("height", EXPECTED_HEIGHTS)
def test_every_standard_height_can_be_requested(height):
    """Ряд качеств без пропусков: 240p и 360p однажды забыли добавить."""
    assert height in custom_quality.CONVERSION_QUALITIES, \
        f"качество {height}p нельзя запросить"


@pytest.mark.parametrize("quality", custom_quality.CONVERSION_QUALITIES)
def test_every_quality_has_its_own_recipe(quality):
    """У каждого качества свой рецепт ffmpeg, без молчаливой подмены.

    Раньше неизвестное качество уходило в рецепт 720p, но имя файла брало
    запрошенное значение: на диске появлялся video_360.mp4 с картинкой 720p.
    """
    assert quality in custom_quality.FFMPEG_PRESETS, \
        f"для {quality} нет рецепта ffmpeg"


def test_command_refuses_quality_without_recipe():
    """Сборка команды не должна подставлять чужой рецепт.

    Подстановка «по умолчанию» молча писала картинку 720p в файл с именем
    запрошенного качества, и заметить подмену можно было только открыв видео.
    Отсутствие рецепта — ошибка в коде, и падать она должна сразу.
    """
    with pytest.raises(KeyError):
        custom_quality.build_command("in.mp4", "999", [], "out.mp4")


def test_command_uses_recipe_of_requested_quality():
    args = custom_quality.build_command("in.mp4", "360", ["-c:a", "copy"], "out.mp4")
    assert "scale=-2:360:flags=lanczos,format=yuv420p" in args, \
        f"в команду попал рецепт другого качества: {args}"
    assert args[-1] == "out.mp4", "путь результата не последним аргументом"
    assert "-c:a" in args, "настройки звука потерялись"


@pytest.mark.parametrize("height", EXPECTED_HEIGHTS)
def test_recipe_scales_to_requested_height(height):
    """Рецепт должен масштабировать именно в запрошенную высоту.

    Ошибка в цифре давала бы файл с чужим разрешением под правильным именем, и
    заметить это можно только открыв видео.
    """
    args = " ".join(custom_quality.FFMPEG_PRESETS[height])
    assert f":{height}" in args or f"{height}:" in args, \
        f"рецепт {height}p не масштабирует в {height} строк: {args}"


def test_quality_list_matches_menu(client, library):
    """Меню и проверка запроса берут один и тот же список.

    Разъехавшиеся списки давали кнопку, на которую сервер отвечает
    «Неизвестное качество», либо качество, которого нет в меню.
    """
    body = client.get("/api/quality/vid1").get_json()
    menu = set(body["qualities"]) - {"original"}
    assert menu == set(custom_quality.CONVERSION_QUALITIES), \
        f"меню и список допустимых качеств разошлись: {menu ^ set(custom_quality.CONVERSION_QUALITIES)}"


def test_quality_list_keeps_order_from_high_to_low(client, library):
    """Порядок показа задаётся отдельным списком, а не порядком ключей.

    Flask сортирует ключи JSON-объектов, поэтому по словарю порядок не
    восстановить: сортировка строк ставила 1080p ниже 144p. Клиент рисует меню
    по полю order, где оригинал сверху, дальше от высокого качества к низкому.
    """
    body = client.get("/api/quality/vid1").get_json()

    order = body.get("order")
    assert order, "порядок показа качеств не отдан"
    assert order[0] == "original", f"оригинал не первым: {order[:3]}"
    assert [k for k in order if k in EXPECTED_HEIGHTS] == list(EXPECTED_HEIGHTS), \
        f"порядок качеств нарушен: {order}"
    assert set(order) == set(body["qualities"]), \
        "порядок и список качеств разошлись"


# ================= Ответ эндпоинта =================

def test_quality_answer_marks_existing_file_available(client, library):
    """Уже пересобранное качество доступно сразу, без второй конвертации."""
    (library / "video_360.mp4").write_bytes(b"0" * 2048)

    body = client.get("/api/quality/vid1").get_json()

    assert body["qualities"]["360"]["available"] is True, \
        "готовый файл не отмечен доступным"
    assert body["qualities"]["720"]["available"] is False, \
        "отсутствующее качество отмечено доступным"


def test_quality_answer_gives_playable_url(client, library):
    """Клиенту нужен адрес файла, а не только имя.

    Собирать путь на клиенте пришлось бы из имени автора и папки, а они
    содержат пробелы и кириллицу: без кодирования плеер получал 404.
    """
    (library / "video_360.mp4").write_bytes(b"0" * 2048)

    body = client.get("/api/quality/vid1").get_json()

    url = body["qualities"]["360"]["url"]
    assert url, "адрес файла не отдан"
    assert " " not in url, f"адрес не закодирован: {url}"
    assert "+" not in url, f"«+» в адресе браузер прочитает как пробел: {url}"
    # Запрос идёт по адресу как есть: незакодированный путь Flask разбирает
    # иначе, и файл не находится.
    assert client.get(url).status_code == 200, f"по адресу {url} файла нет"


def test_original_quality_is_playable_too(client, library):
    """Возврат к оригиналу — такой же пункт меню, ему тоже нужен адрес."""
    body = client.get("/api/quality/vid1").get_json()
    original = body["qualities"]["original"]
    assert original["available"] is True
    assert client.get(original["url"]).status_code == 200, \
        "оригинал недоступен по отданному адресу"


def test_unknown_video_answers_404(client, library):
    assert client.get("/api/quality/нет-такого").status_code == 404


# ================= Запуск конвертации =================

def test_convert_rejects_unknown_quality(client, library):
    res = client.post("/api/convert/vid1", json={"quality": "999"})
    assert res.status_code == 400


def test_convert_rejects_path_traversal(client, library):
    """Качество подставляется в имя файла: обход каталога увёл бы запись наружу."""
    res = client.post("/api/convert/vid1", json={"quality": "../../evil"})
    assert res.status_code == 400
    assert not (library.parent.parent / "evil.mp4").exists()


def test_convert_reports_progress_for_running_task(client, library, monkeypatch):
    """Плеер ждёт готовности по проценту из того же ответа, что рисует меню."""
    monkeypatch.setitem(custom_quality.CONVERSION_TASKS, "vid1_360", 42)

    body = client.get("/api/quality/vid1").get_json()

    assert body["tasks"].get("360") == 42, "прогресс задачи не виден клиенту"


def test_convert_does_not_start_second_task(client, library, monkeypatch):
    """Повторное нажатие не должно запускать второй ffmpeg на тот же файл."""
    monkeypatch.setattr(custom_quality, "_check_ffmpeg", lambda: True)
    monkeypatch.setitem(custom_quality.CONVERSION_TASKS, "vid1_360", 10)

    body = client.post("/api/convert/vid1", json={"quality": "360"}).get_json()

    assert body["status"] == "already_running"


def test_convert_without_ffmpeg_explains_reason(client, library, monkeypatch):
    """Без ffmpeg пересобрать нечем: причина должна быть видна в интерфейсе."""
    monkeypatch.setattr(custom_quality, "_check_ffmpeg", lambda: False)

    res = client.post("/api/convert/vid1", json={"quality": "360"})

    assert res.status_code == 500
    assert "ffmpeg" in res.get_json()["error"].lower()


# ================= Перевод подписей =================

def test_quality_labels_are_translated(client, library):
    """Русские подписи качества обязаны быть в словаре.

    Подписи приходят с сервера, и клиент прогоняет их через t(). «1080p (FHD)»
    в переводе не нуждается — строка одинакова в обоих языках, а ключ словаря по
    договорённости русский. Проверяем только те подписи, где есть русский текст:
    «Шакализатор» и «Улучшайзер» иначе остались бы в английском интерфейсе.
    """
    strings = i18n.load_dictionary('en')
    body = client.get("/api/quality/vid1").get_json()
    missing = [q["label"] for q in body["qualities"].values()
               if re.search(r"[А-Яа-яЁё]", q["label"]) and q["label"] not in strings]
    assert not missing, f"подписи качества без перевода: {missing}"


# ================= Контейнер результата =================

# Расширения, которые попадают в библиотеку: yt-dlp отдаёт mkv и webm при
# склейке несовместимых потоков, а свои загрузки принимают ещё avi и mov.
LIBRARY_EXTENSIONS = ('.mp4', '.mkv', '.webm', '.avi', '.mov')


@pytest.mark.parametrize("ext", LIBRARY_EXTENSIONS)
def test_result_is_always_mp4(client, library, app_module, monkeypatch, ext):
    """Пересобранный файл всегда mp4, каким бы ни был исходник.

    Рецепты кодируют H.264 + AAC, а контейнер WebM их не принимает: ffmpeg
    отказывался с «Only VP8 or VP9 or AV1 video and Vorbis or Opus audio and
    WebVTT subtitles are supported in WebM». Расширение, взятое от исходника,
    делало пересборку webm-файлов невозможной в принципе.
    """
    (library / "video.mp4").unlink()
    (library / f"video{ext}").write_bytes(b"0" * 2048)
    monkeypatch.setitem(app_module.VIDEO_MAP["vid1"], "filename", f"video{ext}")

    body = client.get("/api/quality/vid1").get_json()

    assert body["qualities"]["360"]["file"] == "video_360.mp4", \
        f"для исходника {ext} результат назван {body['qualities']['360']['file']}"


def test_original_keeps_its_own_extension(client, library, app_module, monkeypatch):
    """Оригинал остаётся как есть: его не пересобирают, менять контейнер нечем."""
    (library / "video.mp4").unlink()
    (library / "video.webm").write_bytes(b"0" * 2048)
    monkeypatch.setitem(app_module.VIDEO_MAP["vid1"], "filename", "video.webm")

    body = client.get("/api/quality/vid1").get_json()

    assert body["qualities"]["original"]["file"] == "video.webm"
    assert body["qualities"]["original"]["url"].endswith("video.webm")


@pytest.mark.parametrize("quality", custom_quality.CONVERSION_QUALITIES)
def test_output_name_is_mp4_for_every_quality(quality):
    """Имя результата у всех ступеней с расширением mp4.

    Проверяется именно output_name: он один решает, какой контейнер получится.
    Передать готовый путь в build_command и проверить его же расширение — значит
    проверить собственный аргумент, а не код.
    """
    name = custom_quality.output_name(quality)
    assert name == f"video_{quality}.mp4", f"неожидаемое имя: {name}"


# ================= Свои загрузки =================

def test_own_upload_can_be_rebuilt(client, tmp_path, app_module, monkeypatch):
    """Свои загрузки лежат в отдельном корне и отдаются через /usermedia.

    Без этого пути адрес пересобранного файла не построить: клиент получал
    url=null и пункт меню молча ничего не делал.
    """
    root = tmp_path / "uservideos"
    folder = root / "Я" / "own1"
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"0" * 2048)
    (folder / "video_360.mp4").write_bytes(b"0" * 2048)
    monkeypatch.setattr(custom_quality, "_USER_VIDEOS_ROOT", str(root))
    monkeypatch.setattr(app_module, "USER_VIDEOS_ROOT", str(root))
    monkeypatch.setattr(app_module, "VIDEO_MAP", {}, raising=False)
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {
        "own1": {"id": "own1", "video_path": str(folder / "video.mp4")},
    }, raising=False)
    monkeypatch.setattr(app_module, "build_video_map", lambda: 0)
    monkeypatch.setattr(app_module, "build_user_video_map", lambda: 1)

    body = client.get("/api/quality/own1").get_json()

    url = body["qualities"]["360"]["url"]
    assert url and url.startswith("/usermedia/"), \
        f"свои загрузки отдаются не через /usermedia: {url}"
    assert client.get(url).status_code == 200, f"по адресу {url} файла нет"


def test_user_videos_root_is_passed_on_init():
    """app.py обязан передать корень своих загрузок при инициализации.

    Модуль держит свою копию пути: без передачи он остаётся пустым, и адрес для
    своих загрузок не строится вовсе.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "app.py"), encoding="utf-8") as f:
        source = f.read()
    calls = [line for line in source.splitlines() if "custom_quality.init(" in line]
    assert calls, "custom_quality.init не вызывается"
    for line in calls:
        assert "USER_VIDEOS_ROOT" in line, \
            f"корень своих загрузок не передан: {line.strip()}"


# ================= Настоящая пересборка через FFmpeg =================
#
# Проверки выше работают с рецептами как с данными, но не запускают ffmpeg.
# Ошибка в фильтре или несовместимость кодека с контейнером там не видна: она
# проявляется только при настоящем вызове. Эти тесты собирают короткий ролик и
# пересобирают его по-настоящему — они медленнее остальных, но покрывают то,
# ради чего вся задача и делалась.

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
FFPROBE_AVAILABLE = shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(
    not (FFMPEG_AVAILABLE and FFPROBE_AVAILABLE),
    reason="нужны ffmpeg и ffprobe: пересборка без них невозможна")


def make_sample(path, seconds=1, size="640x360"):
    """Собирает короткий ролик со звуком встроенными генераторами ffmpeg.

    Звук намеренно стерео и 48 кГц: у моно-исходника с низкой частотой урезание
    дорожки для 144p ничего бы не меняло, и проверка не увидела бы разницы.
    """
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=size={size}:rate=15:duration={seconds}",
         "-f", "lavfi",
         "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-af", "pan=stereo|c0=c0|c1=c0", "-c:a", "aac", "-ar", "48000",
         "-shortest", str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=120)


def probe_stream(path, stream, field):
    """Значение поля первой дорожки нужного типа ('v' видео, 'a' звук)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", f"{stream}:0",
         "-show_entries", f"stream={field}", "-of",
         "default=noprint_wrappers=1:nokey=1", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
    return out.stdout.strip()


def probe_height(path):
    return int(probe_stream(path, "v", "height"))


@needs_ffmpeg
@pytest.mark.parametrize("quality,expected_height", [
    ("480", 480),   # даунскейл
    ("720", 720),   # апскейл: исходник 360p
    ("144", 144),   # шакализатор с отдельной звуковой дорожкой
])
def test_real_conversion_produces_requested_height(tmp_path, quality, expected_height):
    """Пересборка действительно даёт файл запрошенной высоты.

    Ошибка в цифре или в фильтре здесь видна сразу, а проверка рецепта как
    строки её пропускала: команда выглядела правильной и не запускалась.
    """
    source = tmp_path / "video.mp4"
    make_sample(source)
    result = tmp_path / custom_quality.output_name(quality)
    # Аудио-часть берётся из модуля, а не собирается в тесте: иначе проверялась
    # бы копия логики, а настоящий выбор дорожки оставался бы без покрытия.
    audio = custom_quality.build_audio_opts(quality, "aac")

    proc = subprocess.run(custom_quality.build_command(
        str(source), quality, audio, str(result)),
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=600)

    assert proc.returncode == 0, f"ffmpeg отказался: {proc.stderr[-400:]}"
    assert result.exists() and result.stat().st_size > 1024, "результат пустой"
    assert probe_height(result) == expected_height, \
        f"ожидалась высота {expected_height}, получена {probe_height(result)}"
    assert probe_stream(result, "a", "codec_name"), "звук потерялся при пересборке"


@needs_ffmpeg
def test_real_conversion_from_webm_source(tmp_path):
    """Из webm-исходника пересборка обязана работать.

    Именно здесь ломалось расширение, взятое от исходника: ffmpeg отказывался
    писать H.264 в контейнер WebM, и пересобрать такой файл было нельзя вовсе.
    """
    source = tmp_path / "video.webm"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=640x360:rate=15:duration=1",
         "-c:v", "libvpx-vp9", "-b:v", "200k", str(source)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=300)
    result = tmp_path / custom_quality.output_name("480")

    proc = subprocess.run(custom_quality.build_command(
        str(source), "480", [], str(result)),
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=600)

    assert proc.returncode == 0, f"ffmpeg отказался: {proc.stderr[-400:]}"
    assert probe_height(result) == 480


@needs_ffmpeg
def test_real_conversion_of_enhancer_keeps_resolution(tmp_path):
    """«Улучшайзер» правит резкость, а разрешение оставляет исходным.

    Цепочка фильтров у него самая длинная: опечатка в имени фильтра роняла бы
    ffmpeg, а проверка рецепта как строки этого не видит.
    """
    source = tmp_path / "video.mp4"
    make_sample(source)
    result = tmp_path / custom_quality.output_name("enhance")

    proc = subprocess.run(custom_quality.build_command(
        str(source), "enhance",
        custom_quality.build_audio_opts("enhance", "aac"), str(result)),
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=900)

    assert proc.returncode == 0, f"ffmpeg отказался: {proc.stderr[-400:]}"
    assert probe_height(result) == 360, "улучшайзер сменил разрешение"


@pytest.mark.parametrize("quality", ["enhance", "enhance_2160"])
def test_enhancer_sharpens_picture(quality):
    """Улучшайзер обязан повышать резкость: без unsharp он бесполезен.

    Пользователь выбирает его именно за «Четкость+», и рецепт без фильтра
    резкости просто перекодировал бы файл впустую.
    """
    recipe = " ".join(custom_quality.FFMPEG_PRESETS[quality])
    assert "unsharp=" in recipe, f"в рецепте {quality} нет повышения резкости"


@needs_ffmpeg
def test_real_conversion_keeps_audio(tmp_path):
    """Звук не должен пропадать: без дорожки пересобранный файл бесполезен."""
    source = tmp_path / "video.mp4"
    make_sample(source)
    result = tmp_path / custom_quality.output_name("480")

    subprocess.run(custom_quality.build_command(
        str(source), "480", custom_quality.build_audio_opts("480", "opus"),
        str(result)),
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)

    assert probe_stream(result, "a", "codec_name"), "в результате нет звуковой дорожки"


@needs_ffmpeg
def test_real_conversion_without_audio_track(tmp_path):
    """Видео без звука пересобирается, а не падает.

    Для беззвучного исходника аудио-часть обязана быть пустой: с «-c:a aac»
    ffmpeg отказывается, потому что кодировать нечего.
    """
    source = tmp_path / "video.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=640x360:rate=15:duration=1",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         str(source)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    result = tmp_path / custom_quality.output_name("360")

    proc = subprocess.run(custom_quality.build_command(
        str(source), "360", custom_quality.build_audio_opts("360", None),
        str(result)),
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=600)

    assert proc.returncode == 0, f"ffmpeg отказался: {proc.stderr[-400:]}"
    assert probe_height(result) == 360


@needs_ffmpeg
def test_low_quality_audio_is_really_smaller(tmp_path):
    """У шакализатора звук действительно урезан, а не только в аргументах.

    Проверяется результат: частота дискретизации и один канал видны в файле.
    """
    source = tmp_path / "video.mp4"
    make_sample(source, seconds=2)
    result = tmp_path / custom_quality.output_name("144")

    subprocess.run(custom_quality.build_command(
        str(source), "144", custom_quality.build_audio_opts("144", "aac"),
        str(result)),
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)

    assert probe_stream(result, "a", "channels") == "1", "звук не сведён в моно"
    assert probe_stream(result, "a", "sample_rate") == "22050", \
        "частота дискретизации не понижена"


# ================= Выбор звуковой дорожки =================

def test_audio_opts_empty_without_track():
    """Без дорожки аудио-часть пустая: иначе ffmpeg падает на пустом потоке."""
    assert custom_quality.build_audio_opts("480", None) == []


@pytest.mark.parametrize("codec", ["aac", "AAC", "mp4a"])
def test_ready_aac_is_copied(codec):
    """Готовый AAC копируется: перекодирование только теряет качество и время."""
    assert custom_quality.build_audio_opts("480", codec) == ["-c:a", "copy"]


@pytest.mark.parametrize("codec", ["opus", "vorbis", "mp3", "flac"])
def test_other_codecs_are_reencoded_to_aac(codec):
    """Не-AAC дорожки перекодируются: mp4 принимает не всякий звук."""
    opts = custom_quality.build_audio_opts("480", codec)
    assert opts[:2] == ["-c:a", "aac"], f"{codec} не приведён к aac: {opts}"


def test_low_quality_gets_narrow_audio():
    """У 144p звук урезан, даже если исходник уже в AAC.

    Копирование дорожки здесь дало бы звук тяжелее самой картинки. Ступень
    указана явно, а не взята из LOW_AUDIO_QUALITIES: с пустым списком
    параметризация просто пропустила бы проверку вместо провала.
    """
    assert "144" in custom_quality.LOW_AUDIO_QUALITIES, \
        "144p выпал из списка качеств с урезанным звуком"
    opts = custom_quality.build_audio_opts("144", "aac")
    assert "copy" not in opts, f"дорожка скопирована вместо урезания: {opts}"
    assert "32k" in opts and "-ac" in opts and "22050" in opts, opts


@needs_ffmpeg
def test_real_conversion_through_endpoint(client, library, app_module, monkeypatch):
    """Полный путь: запрос пересборки, ожидание и готовый файл в меню.

    Проверки выше вызывают ffmpeg напрямую. Здесь работает сам эндпоинт вместе с
    потоком, прогрессом и переименованием результата — то, что видит плеер.
    """
    # Исходник webm со звуком: на mp4-исходнике не видно ни подмены контейнера,
    # ни потери дорожки — оба дефекта прошли бы незамеченными.
    (library / "video.mp4").unlink()
    source = library / "video.webm"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=640x360:rate=15:duration=1",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libvpx-vp9", "-b:v", "200k", "-c:a", "libopus",
         "-shortest", str(source)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=300)
    monkeypatch.setitem(app_module.VIDEO_MAP["vid1"], "filename", "video.webm")

    res = client.post("/api/convert/vid1", json={"quality": "240"})
    assert res.status_code == 200, res.get_data(as_text=True)
    assert res.get_json()["status"] == "started"

    # Пересборка идёт в отдельном потоке: ждём завершения по состоянию задачи.
    deadline = time.time() + 300
    while time.time() < deadline:
        with custom_quality.CONVERSION_LOCK:
            progress = custom_quality.CONVERSION_TASKS.get("vid1_240")
        if progress in (custom_quality.TASK_DONE, custom_quality.TASK_FAILED):
            break
        time.sleep(0.5)

    assert progress == custom_quality.TASK_DONE, f"пересборка не удалась: {progress}"
    result = library / "video_240.mp4"
    assert result.exists(), "готовый файл не появился рядом с исходником"
    assert probe_height(result) == 240
    # Дорожка opus не годится для mp4: её обязаны перекодировать, а не выбросить.
    assert probe_stream(result, "a", "codec_name") == "aac", \
        "звук пропал или остался в неподходящем кодеке"
    # Временные файлы убираются: иначе папка видео копит мусор.
    assert not list(library.glob("*_tmp*")), "остался временный файл"
    assert not list(library.glob("*ffmpeg.log")), "остался журнал ffmpeg"

    body = client.get("/api/quality/vid1").get_json()
    assert body["qualities"]["240"]["available"] is True
    assert client.get(body["qualities"]["240"]["url"]).status_code == 200


# ================= Меню в плеере =================

def read_player():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "templates", "video.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_player_menu_reads_quality_api():
    """Меню строится по /api/quality, а не по форматам YouTube.

    Прежний вариант спрашивал /api/direct_formats — параметры уже скачанного
    файла — и печатал «Качество скачанного файла», то есть выбора не давал
    вообще.
    """
    html = read_player()
    assert "/api/quality/" in html, "меню не запрашивает список качеств"
    assert "/api/direct_formats" not in html, \
        "меню по-прежнему строится по форматам исходника"


def test_player_menu_orders_options_by_server_order():
    """Порядок пунктов берётся из ответа, а не из перебора ключей.

    Перебор ключей JSON-объекта даёт алфавитный порядок: 1080p оказывался ниже
    144p.
    """
    html = read_player()
    body = html.split("function renderQualityOptions", 1)[1].split("\n            }", 1)[0]
    assert "data.order" in body, "порядок показа игнорируется"


def test_player_starts_conversion_for_missing_quality():
    """Недоступное качество нужно сначала пересобрать через /api/convert."""
    html = read_player()
    assert "/api/convert/" in html, "плеер не умеет запускать пересборку"


def test_player_switches_source_and_keeps_position():
    """При смене качества позиция и состояние проигрывания сохраняются.

    Смена src сбрасывает плеер на нулевую секунду и ставит на паузу: без
    возврата currentTime переключение качества отбрасывало бы в начало ролика.
    """
    html = read_player()
    body = html.split("function applyQuality", 1)[1].split("\n            }", 1)[0]
    assert "video.src" in body, "источник видео не переключается"
    # Ищем именно присваивание: чтение video.currentTime в переменную есть и
    # так, и проверка на подстроку «currentTime» проходила даже без возврата
    # позиции.
    assert re.search(r"video\.currentTime\s*=", body), \
        "позиция просмотра не восстанавливается"
    # Восстанавливать позицию нужно после загрузки метаданных: сразу после смены
    # src длительность ещё неизвестна, и присваивание молча сбрасывается в ноль.
    # Проверяется именно подписка на событие: одного упоминания «loadedmetadata»
    # мало — слово остаётся и в removeEventListener, когда подписки уже нет.
    assert re.search(r"addEventListener\(\s*['\"]loadedmetadata['\"]", body), \
        "позиция возвращается до загрузки метаданных"


def test_player_keeps_playback_rate():
    """Выбранная скорость не сбрасывается при переключении качества.

    Смена src возвращает playbackRate к 1x, а кнопка продолжала показывать «2x»:
    подпись и настоящая скорость расходились до следующего нажатия.
    """
    body = read_player().split("function applyQuality", 1)[1].split("\n            }", 1)[0]
    assert re.search(r"video\.playbackRate\s*=\s*rate", body), \
        "скорость воспроизведения не восстанавливается"
    saved = body.split("video.src", 1)[0]
    # Снимать скорость нужно до смены src: после неё там уже 1x, и возврат стал
    # бы бессмысленным присваиванием того же значения.
    assert re.search(r"=\s*video\.playbackRate", saved), \
        "скорость снимается после смены источника"


def test_player_keeps_pause_state():
    """Остановленный ролик не начинает играть сам.

    У <video> стоит autoplay: video.load() применяет атрибут заново, и пауза
    превращалась в воспроизведение с середины.
    """
    body = read_player().split("function applyQuality", 1)[1].split("\n            }", 1)[0]
    assert re.search(r"else\s+video\.pause\(\)", body), \
        "пауза не удерживается после переключения"


def test_player_polls_conversion_progress():
    """Пересборка идёт минутами: пользователю нужен процент, а не замерший пункт.

    Опрос должен повторяться сам: одного отложенного вызова хватило бы только на
    первый процент, дальше пункт замирал бы до перезагрузки страницы.
    """
    html = read_player()
    body = html.split("async function pollQuality", 1)[1].split("\n            }\n", 1)[0]
    # Повтор нужен на успешном пути, а не только в catch: повтор по ошибке сети
    # прогресс не обновляет, и пункт замирал бы на «Пересобрать», пока сервер
    # исправно отвечает.
    success = body.split("} catch", 1)[0]
    assert re.search(r"setTimeout\(pollQuality", success), \
        "прогресс пересборки не опрашивается повторно"
    assert "data.tasks" in success, "опрос не смотрит на состояние задач"


def test_menu_stays_open_on_quality_click():
    """Клик по ступени качества не должен считаться «кликом снаружи».

    Меню качества лежит рядом с меню настроек, а не внутри него, и общий
    обработчик закрытия по клику вне меню срабатывал на выбор качества: меню
    захлопывалось сразу, и прогресс пересборки становилось не видно.
    """
    html = read_player()
    # Обработчиков клика по документу несколько (закрытие ползунков громкости и
    # другие), нужен именно тот, что закрывает меню плеера.
    body = html.split("playerQualityMenu.style.display = 'none';\n                }\n            });", 1)[0]
    body = body.rsplit("document.addEventListener('click'", 1)[1]
    assert "playerQualityMenu.contains" in body, \
        "клик по меню качества закрывает само меню"


def test_quality_menu_fits_into_player():
    """Одиннадцать ступеней не влезают в высоту плеера.

    Без ограничения верхние пункты выезжали за край плеера, попадали под
    содержимое страницы и не нажимались вовсе.
    """
    html = read_player()
    assert "#qualityOptionsList { max-height" in html, \
        "высота списка качеств не ограничена"
    block = html.split("#qualityOptionsList {", 1)[1].split("}", 1)[0]
    assert "overflow-y: auto" in block, "список качеств без прокрутки"


def test_player_hides_rebuild_from_guest():
    """Гостю пересборка закрыта: /api/convert отвечает ему 403.

    Кнопка, которая гарантированно выдаёт ошибку, хуже отсутствующей: гость
    видел бы пункты качества и получал отказ на каждый.
    """
    html = read_player()
    body = html.split("function renderQualityOptions", 1)[1].split("function applyQuality", 1)[0]
    # Недоступный пункт гостю не показываем вовсе: обработчик, повешенный на
    # него, привёл бы к 403 на каждый клик. Проверяем именно выход из отрисовки
    # ряда, а не просто упоминание прав — подпись «Пересобрать» скрывалась, но
    # сам пункт оставался нажимаемым.
    assert re.search(r"if\s*\(!item\.available && !IS_OWNER\)\s*return;", body), \
        "гостю по-прежнему предлагают пересборку"


def test_player_quality_strings_are_translated():
    """Подписи меню, собираемые на клиенте, идут через t()."""
    html = read_player()
    body = html.split("async function fetchQualityOptions", 1)[1].split("function applyQuality", 1)[0]
    for text in ("Загрузка", "Пересобрать"):
        assert f"t('{text}" in body or f't("{text}' in body, \
            f"строка «{text}» в меню качества без перевода"
