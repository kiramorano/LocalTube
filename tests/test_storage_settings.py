"""Тесты раздела «Хранение» в настройках: пути к папкам библиотеки.

До появления этого раздела пути можно было менять только руками в config.json,
причём часть из них вообще не читалась из конфига (баннеры и метаданные каналов
были зашиты в channel_assets.py, свои видео — в user_videos.py).

Главный риск, который проверяют эти тесты: app.py читает config.json один раз
при импорте модуля, а download_lib.py — на каждую загрузку. Без применения
путей «на живом сервере» смена папки приводила бы к расхождению: новые видео
уходили бы в новое место, а библиотека продолжала показывать старое.
"""
import json
import os

import pytest

import app as app_module
import channel_assets
import user_videos


# Ключи, которыми управляет раздел «Хранение». Порядок как в UI.
STORAGE_KEYS = (
    "video_dir",
    "avatars_dir",
    "banners_dir",
    "meta_dir",
    "playlists_dir",
    "subtitles_dir",
    "uservideos_dir",
)


@pytest.fixture
def storage_config(tmp_path, monkeypatch):
    """Уводит config.json во временный файл.

    Без этого тесты писали бы в настоящий конфиг пользователя и сбивали ему
    пути к библиотеке.
    """
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"video_dir": "videos"}), encoding="utf-8")
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(cfg))
    return cfg


@pytest.fixture
def restore_paths(monkeypatch):
    """Возвращает пути на место после теста.

    Эндпоинт меняет модульные атрибуты app.py, channel_assets и user_videos.
    Утечка изменённого пути в следующий тест выглядела бы как чужая поломка.
    """
    saved = {name: getattr(app_module, name) for name in (
        "BASE_VIDEO_DIR", "AVATARS_DIR", "PLAYLISTS_DIR", "SUBTITLES_DIR",
        "USER_VIDEOS_ROOT",
    )}
    saved_assets = {
        "CHANNEL_ASSETS_DIR": channel_assets.CHANNEL_ASSETS_DIR,
        "BANNERS_DIR": channel_assets.BANNERS_DIR,
        "META_DIR": channel_assets.META_DIR,
    }
    saved_user = user_videos.USER_VIDEOS_ROOT
    yield
    for name, value in saved.items():
        setattr(app_module, name, value)
    for name, value in saved_assets.items():
        setattr(channel_assets, name, value)
    user_videos.USER_VIDEOS_ROOT = saved_user


# ================= GET /api/storage =================

def test_storage_get_returns_all_paths(client, storage_config):
    """UI должен получать текущие пути: иначе поля нечем заполнить."""
    res = client.get("/api/storage")
    assert res.status_code == 200
    data = res.get_json()
    for key in STORAGE_KEYS:
        assert key in data, f"нет ключа {key}"
        assert isinstance(data[key], str) and data[key], f"пустое значение {key}"


def test_storage_get_reports_absolute_paths(client, storage_config):
    """Относительный 'videos' ничего не говорит о том, где лежат файлы.

    Пользователь должен видеть, какая папка используется на самом деле.
    """
    data = client.get("/api/storage").get_json()
    assert "resolved" in data, "нет абсолютных путей"
    for key in STORAGE_KEYS:
        assert os.path.isabs(data["resolved"][key]), f"{key} не абсолютный"


# ================= POST /api/storage: сохранение =================

def test_storage_post_saves_to_config(client, storage_config, restore_paths, tmp_path):
    """Основной сценарий: путь записан в config.json."""
    target = tmp_path / "новая библиотека"
    res = client.post("/api/storage", json={"video_dir": str(target)})
    assert res.status_code == 200, res.get_json()

    saved = json.loads(storage_config.read_text(encoding="utf-8"))
    assert saved["video_dir"] == str(target)


def test_storage_post_creates_directory(client, storage_config, restore_paths, tmp_path):
    """Папку нужно создать, иначе загрузка упадёт на первом же видео."""
    target = tmp_path / "ещё нет"
    client.post("/api/storage", json={"video_dir": str(target)})
    assert target.is_dir(), "папка не создана"


def test_storage_post_keeps_unrelated_config_keys(client, storage_config, restore_paths, tmp_path):
    """Настройки авторизации не должны пропадать при смене путей."""
    storage_config.write_text(json.dumps({
        "video_dir": "videos",
        "youtube_auth": {"player_client": "tv", "po_token": "bgutil:http"},
    }), encoding="utf-8")

    client.post("/api/storage", json={"video_dir": str(tmp_path / "lib")})

    saved = json.loads(storage_config.read_text(encoding="utf-8"))
    assert saved["youtube_auth"]["player_client"] == "tv"
    assert saved["youtube_auth"]["po_token"] == "bgutil:http"


def test_storage_post_accepts_partial_payload(client, storage_config, restore_paths, tmp_path):
    """Смена одной папки не должна сбрасывать остальные на значения по умолчанию."""
    storage_config.write_text(json.dumps({
        "video_dir": "videos", "avatars_dir": "мои авы",
    }), encoding="utf-8")

    client.post("/api/storage", json={"video_dir": str(tmp_path / "lib")})

    saved = json.loads(storage_config.read_text(encoding="utf-8"))
    assert saved["avatars_dir"] == "мои авы", "чужой путь затёрт"


# ================= POST /api/storage: горячее применение =================

def test_storage_post_applies_without_restart(client, storage_config, restore_paths, tmp_path):
    """Самое важное: путь должен подействовать сразу.

    app.py читает config.json один раз при импорте. Без обновления модульных
    констант новые видео шли бы в новую папку, а библиотека показывала старую —
    пользователь решил бы, что загрузка сломалась.
    """
    target = tmp_path / "hot"
    client.post("/api/storage", json={"video_dir": str(target)})
    assert app_module.BASE_VIDEO_DIR == str(target)


def test_storage_post_applies_to_channel_assets(client, storage_config, restore_paths, tmp_path):
    """Баннеры и метаданные жили в зашитом avas/, минуя конфиг."""
    banners = tmp_path / "шапки"
    meta = tmp_path / "мета"
    client.post("/api/storage", json={
        "banners_dir": str(banners), "meta_dir": str(meta),
    })
    assert channel_assets.BANNERS_DIR == str(banners)
    assert channel_assets.META_DIR == str(meta)


def test_storage_post_applies_to_user_videos(client, storage_config, restore_paths, tmp_path):
    """USER_VIDEOS_ROOT был зашитой строкой в user_videos.py."""
    target = tmp_path / "свои видео"
    client.post("/api/storage", json={"uservideos_dir": str(target)})
    assert user_videos.USER_VIDEOS_ROOT == str(target)
    assert app_module.USER_VIDEOS_ROOT == str(target), "app.py отдаёт файлы по своей копии"


def test_storage_applies_to_blueprints(client, storage_config, restore_paths, tmp_path):
    """custom_quality и audio_language получают путь копией при импорте.

    init() кладёт значение в модульную переменную, поэтому смена
    app.BASE_VIDEO_DIR их не затрагивает: без повторной инициализации смена
    качества и дорожки продолжала бы искать файлы в старой папке.
    """
    import audio_language
    import custom_quality

    target = tmp_path / "bp"
    client.post("/api/storage", json={"video_dir": str(target)})

    assert custom_quality._BASE_VIDEO_DIR == str(target)
    assert audio_language._BASE_VIDEO_DIR == str(target)


def test_storage_post_rebuilds_library(client, storage_config, restore_paths, tmp_path):
    """После смены папки библиотеку надо перечитать.

    Иначе в выдаче остаются видео из прежнего каталога — ссылки на файлы,
    которых по новому пути нет.
    """
    target = tmp_path / "lib"
    (target / "Автор" / "abcdefghijk").mkdir(parents=True)
    (target / "Автор" / "abcdefghijk" / "video.mp4").write_bytes(b"x")

    client.post("/api/storage", json={"video_dir": str(target)})

    assert "abcdefghijk" in app_module.VIDEO_MAP, "библиотека не перечитана"


def test_download_lib_and_web_agree_on_path(tmp_path, monkeypatch):
    """Загрузчик и веб должны считать путь одинаково.

    download_lib читает config.json сам, на каждую загрузку. Оба модуля берут
    файл из каталога данных (paths.data_path), поэтому подменяем именно каталог:
    расхождение этих двух источников и есть исходная причина задачи — веб
    показывал одну папку, а загрузчик писал в другую.
    """
    import download_lib
    import paths

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"video_dir": str(tmp_path / "общая")}), encoding="utf-8")
    monkeypatch.setattr(paths, "data_dir", lambda: str(tmp_path))
    # app.CONFIG_FILE вычисляется один раз при импорте, поэтому подменяется
    # отдельно: иначе тест сравнивал бы разные файлы.
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(cfg))

    # Настоящая функция: автофикстура conftest уводит загрузку во временную
    # папку, иначе тесты качали бы в рабочую библиотеку пользователя.
    real_load_config = getattr(download_lib, "_real_load_config", download_lib.load_config)

    assert real_load_config()["video_dir"] == app_module.load_config()["video_dir"]


def test_module_defaults_agree_with_app(tmp_path, monkeypatch):
    """Значения по умолчанию во всех модулях должны совпадать с app.py.

    Если config.json удалить, каждый модуль берёт свой default. Расхождение
    уже случалось: download_avatars.py ждал папку avatars, а веб искал avas,
    и аватарки скачивались туда, где их никто не показывает.
    """
    import download_avatars
    import download_lib
    import download_thumbnails
    import download_video

    missing = tmp_path / "нет" / "config.json"
    checks = {
        "download_lib": (download_lib, ("video_dir",)),
        "download_video": (download_video, ("video_dir",)),
        "download_thumbnails": (download_thumbnails, ("video_dir",)),
        "download_avatars": (download_avatars, ("video_dir", "avatars_dir")),
    }
    for name, (module, keys) in checks.items():
        # Настоящая функция: автофикстура conftest подменяет download_lib.load_config,
        # чтобы тесты не качали в рабочую библиотеку пользователя.
        load_config = getattr(module, "_real_load_config", module.load_config)
        monkeypatch.setattr(module.os.path, "join",
                            lambda *a, _m=str(missing): _m if a[-1] == "config.json" else os.sep.join(a))
        cfg = load_config()
        monkeypatch.undo()
        for key in keys:
            assert cfg[key] == app_module.DEFAULT_DIRS[key], \
                f"{name}: {key}={cfg[key]!r}, а app.py ждёт {app_module.DEFAULT_DIRS[key]!r}"


# ================= POST /api/storage: валидация =================

def test_storage_rejects_empty_path(client, storage_config, restore_paths):
    """Пустая строка сделала бы путь равным корню проекта."""
    res = client.post("/api/storage", json={"video_dir": "   "})
    assert res.status_code == 400
    assert res.get_json().get("error")


def test_storage_rejects_file_instead_of_directory(client, storage_config, restore_paths, tmp_path):
    """Если по пути лежит файл, сообщение должно объяснять причину.

    Одного кода 400 тут недостаточно: makedirs на файле тоже падает с OSError,
    и без отдельной проверки пользователь получал бы системную ошибку
    «Cannot create a file when that file already exists» вместо понятного
    объяснения.
    """
    victim = tmp_path / "занято.txt"
    victim.write_text("не папка", encoding="utf-8")

    res = client.post("/api/storage", json={"video_dir": str(victim)})
    assert res.status_code == 400
    error = res.get_json().get("error", "")
    # Именно эта формулировка: системное сообщение WinError 183 тоже содержит
    # слово «файл», поэтому проверка на него проходила и без явной проверки.
    assert "а не папка" in error, f"причина не объяснена: {error!r}"


def test_storage_rejects_unknown_key(client, storage_config, restore_paths, tmp_path):
    """Опечатка в имени ключа не должна тихо проглатываться."""
    res = client.post("/api/storage", json={"video_durr": str(tmp_path / "x")})
    assert res.status_code == 400


def test_storage_reports_uncreatable_path(client, storage_config, restore_paths):
    """Несуществующий диск: пользователь должен увидеть причину, а не 500."""
    res = client.post("/api/storage", json={"video_dir": "Q:/нет такого диска/lib"})
    assert res.status_code == 400
    assert res.get_json().get("error")


def test_storage_failure_keeps_old_path(client, storage_config, restore_paths, tmp_path):
    """Отказ не должен оставлять приложение с наполовину применёнными путями."""
    before = app_module.BASE_VIDEO_DIR
    client.post("/api/storage", json={"video_dir": ""})
    assert app_module.BASE_VIDEO_DIR == before


def test_storage_rejects_non_dict_payload(client, storage_config, restore_paths):
    """Запрос без JSON не должен приводить к 500."""
    res = client.post("/api/storage", data="мусор", content_type="text/plain")
    assert res.status_code == 400


# ================= Конфиг: единые значения по умолчанию =================

def test_default_avatars_dir_matches_across_modules():
    """app.py брал 'avas', а download_avatars.py — 'avatars'.

    При отсутствии config.json аватарки скачивались в одну папку, а веб искал
    их в другой, и на страницах каналов не было картинок.
    """
    import download_avatars

    app_default = "avas"
    src = open(download_avatars.__file__, encoding="utf-8").read()
    assert '"avatars_dir": "avas"' in src or f"'avatars_dir': '{app_default}'" in src, \
        "download_avatars.py ждёт другую папку по умолчанию"


def test_config_defaults_cover_all_storage_keys():
    """Каждый управляемый путь должен иметь значение по умолчанию."""
    defaults = app_module.load_config()
    for key in STORAGE_KEYS:
        assert key in defaults, f"нет значения по умолчанию для {key}"


def test_save_config_writes_atomically(tmp_path, monkeypatch):
    """save_config существовал, но никогда не вызывался и не был покрыт."""
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(cfg))
    app_module.save_config({"video_dir": "видео"})
    assert json.loads(cfg.read_text(encoding="utf-8"))["video_dir"] == "видео"
