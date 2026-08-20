"""Тесты безопасной записи JSON (utils.write_json_atomic / read_json)."""
import json
import os
import time

import pytest

from utils import write_json_atomic, read_json, JsonWriteError


def test_write_and_read(tmp_path):
    path = str(tmp_path / "a.json")
    write_json_atomic(path, {"a": 1})
    assert read_json(path) == {"a": 1}


def test_no_temp_file_left(tmp_path):
    path = str(tmp_path / "a.json")
    write_json_atomic(path, {"a": 1})
    assert not os.path.exists(path + ".tmp")


def test_backup_keeps_previous_version(tmp_path):
    path = str(tmp_path / "a.json")
    write_json_atomic(path, {"v": 1})
    write_json_atomic(path, {"v": 2})
    assert read_json(path) == {"v": 2}
    assert read_json(path + ".bak", use_backup=False) == {"v": 1}


def test_backup_can_be_disabled(tmp_path):
    path = str(tmp_path / "a.json")
    write_json_atomic(path, {"v": 1}, backup=False)
    write_json_atomic(path, {"v": 2}, backup=False)
    assert not os.path.exists(path + ".bak")


def test_broken_file_falls_back_to_backup(tmp_path):
    """Повреждённый файл не должен означать потерю данных."""
    path = str(tmp_path / "a.json")
    write_json_atomic(path, {"v": 1})
    write_json_atomic(path, {"v": 2})  # создаёт .bak со {"v": 1}
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ битый json")

    assert read_json(path) == {"v": 1}


def test_broken_file_without_backup_returns_default(tmp_path):
    path = str(tmp_path / "a.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("не json")
    assert read_json(path, default={"d": True}) == {"d": True}


def test_missing_file_returns_default(tmp_path):
    assert read_json(str(tmp_path / "nope.json"), default=[]) == []


def test_file_with_bom_is_read(tmp_path):
    path = str(tmp_path / "a.json")
    with open(path, "w", encoding="utf-8-sig") as f:
        json.dump({"v": 1}, f)
    assert read_json(path) == {"v": 1}


def test_write_failure_raises(tmp_path, monkeypatch):
    """Сбой записи обязан подниматься наружу, а не проглатываться."""
    path = str(tmp_path / "a.json")

    def boom(*args, **kwargs):
        raise OSError("нет места")

    monkeypatch.setattr("utils.json.dump", boom)
    with pytest.raises(JsonWriteError):
        write_json_atomic(path, {"a": 1})


def test_write_failure_keeps_old_file_intact(tmp_path, monkeypatch):
    """Неудачная запись не должна портить уже сохранённые данные.

    Прямая запись через open(path, 'w') обрезала бы файл сразу.
    """
    path = str(tmp_path / "a.json")
    write_json_atomic(path, {"v": "важные данные"})

    def boom(*args, **kwargs):
        raise OSError("сбой")

    monkeypatch.setattr("utils.json.dump", boom)
    with pytest.raises(JsonWriteError):
        write_json_atomic(path, {"v": "новое"})

    assert read_json(path) == {"v": "важные данные"}
    assert not os.path.exists(path + ".tmp")


def test_config_save_preserves_unrelated_keys(tmp_path, monkeypatch):
    """Сохранение настроек авторизации не должно терять пути к библиотеке.

    save_options делает read-modify-write всего config.json, поэтому потеря
    сторонних ключей сбросила бы video_dir и остальные каталоги.
    """
    import auth_options

    config = str(tmp_path / "config.json")
    monkeypatch.setattr(auth_options, "CONFIG_FILE", config)
    write_json_atomic(config, {"video_dir": "D:/videos", "avatars_dir": "D:/avas"})

    assert auth_options.save_options({"player_client": "tv"}) is True

    saved = read_json(config)
    assert saved["video_dir"] == "D:/videos"
    assert saved["avatars_dir"] == "D:/avas"
    assert saved["youtube_auth"]["player_client"] == "tv"


def test_channel_meta_keeps_sync_fields(channel_assets, test_author):
    """Запись описания канала не должна стирать диагностику синхронизации.

    save_channel_assets перезаписывает файл целиком, а поля sync_* живут в том
    же JSON: без их сохранения статус терялся при каждой догрузке описания.
    """
    channel_assets.update_sync_status(test_author, "ok", success=True)

    # Штатная запись описания: аватар и баннер не указываем, чтобы не ходить в сеть.
    channel_assets.save_channel_assets(test_author, {
        "description": "Описание канала",
        "subscribers": "1,2 млн",
    })

    meta = channel_assets.load_channel_meta(test_author)
    assert meta["description"] == "Описание канала"
    assert meta.get("sync_status") == "ok", "статус синхронизации потерян"

    status = channel_assets.get_sync_status(test_author)
    assert status["status"] == "ok"
    assert status["success"] is True


def test_channel_page_does_not_touch_real_metadata(client, app_module):
    """Открытие страницы канала не должно менять реальные avas/meta/*.json.

    Раньше страница поднимала фоновый поток догрузки, который шёл в YouTube и
    писал статус синхронизации в рабочие файлы пользователя.
    """
    import channel_assets

    meta_dir = channel_assets.META_DIR
    if not os.path.isdir(meta_dir):
        pytest.skip("нет каталога метаданных")

    def snapshot():
        return {n: os.stat(os.path.join(meta_dir, n)).st_mtime_ns
                for n in os.listdir(meta_dir)}

    app_module.build_video_map()
    author = next(iter({v["author"] for v in app_module.VIDEO_MAP.values()}), None)
    if not author:
        pytest.skip("библиотека пуста")

    before = snapshot()
    assert client.get(f"/channel/{author}").status_code == 200

    # Догрузка идёт в отдельном потоке: без ожидания проверка успевает раньше
    # записи и не заметила бы обращения к реальным файлам.
    deadline = time.time() + 3
    while time.time() < deadline:
        if snapshot() != before:
            break
        time.sleep(0.1)

    assert snapshot() == before, "страница канала изменила реальные метаданные"


def test_creates_missing_directory(tmp_path):
    path = str(tmp_path / "sub" / "dir" / "a.json")
    write_json_atomic(path, {"a": 1})
    assert read_json(path) == {"a": 1}


def test_non_ascii_survives_roundtrip(tmp_path):
    path = str(tmp_path / "a.json")
    write_json_atomic(path, {"название": "Кэш-тест живьём"})
    assert read_json(path)["название"] == "Кэш-тест живьём"
