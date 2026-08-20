"""Тесты серверного хранилища пользовательских данных."""
import json
import os

import pytest

import userdata as userdata_module


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Изолированное хранилище во временном файле."""
    monkeypatch.setattr(userdata_module, "USERDATA_FILE",
                        str(tmp_path / "userdata.json"))
    userdata_module.reload_from_disk()
    yield userdata_module
    userdata_module.reload_from_disk()


@pytest.fixture
def api(store, client):
    """HTTP-клиент вместе с изолированным хранилищем."""
    return client


def read_disk(store):
    with open(store.USERDATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------- базовые операции ----------

def test_empty_state(store):
    data = store.get_all()
    assert data["favorites"] == []
    assert data["history"] == []
    assert data["hidden_channels"] == []


def test_toggle_favorite_adds_and_removes(store):
    active, items = store.toggle_favorite("vid1")
    assert active is True and items == ["vid1"]

    active, items = store.toggle_favorite("vid1")
    assert active is False and items == []


def test_explicit_state_is_idempotent(store):
    """Повторная установка того же состояния ничего не переворачивает.

    Клиент может отправить запрос до загрузки актуального списка, поэтому он
    передаёт желаемое состояние, а не команду «переключи».
    """
    assert store.toggle_favorite("vid1", True) == (True, ["vid1"])
    assert store.toggle_favorite("vid1", True) == (True, ["vid1"])
    assert store.toggle_favorite("vid1", False) == (False, [])
    assert store.toggle_favorite("vid1", False) == (False, [])


def test_explicit_state_for_hidden_channels(store):
    assert store.toggle_hidden_channel("Chan", True)[0] is True
    assert store.toggle_hidden_channel("Chan", True)[1] == ["Chan"]
    assert store.toggle_hidden_channel("Chan", False)[1] == []


def test_favorite_persists_on_disk(store):
    store.toggle_favorite("vid1")
    store.reload_from_disk()
    assert store.get_all()["favorites"] == ["vid1"]


def test_toggle_hidden_channel(store):
    hidden, items = store.toggle_hidden_channel("Chan")
    assert hidden is True and items == ["Chan"]
    assert store.toggle_hidden_channel("Chan")[0] is False


def test_mark_watched_moves_to_front(store):
    store.mark_watched("a")
    store.mark_watched("b")
    assert store.get_all()["history"] == ["b", "a"]

    # Повторный просмотр поднимает видео наверх, а не дублирует запись.
    store.mark_watched("a")
    assert store.get_all()["history"] == ["a", "b"]


def test_history_is_capped(store):
    monkeyed = store.HISTORY_LIMIT
    for i in range(monkeyed + 20):
        store.mark_watched(f"vid{i}")
    history = store.get_all()["history"]
    assert len(history) == monkeyed
    # Остаться должны самые свежие.
    assert history[0] == f"vid{monkeyed + 19}"


def test_clear_section(store):
    store.toggle_favorite("vid1")
    store.mark_watched("vid2")
    store.clear("favorites")
    assert store.get_all()["favorites"] == []
    # Другие разделы не затронуты.
    assert store.get_all()["history"] == ["vid2"]


def test_clear_unknown_section_raises(store):
    with pytest.raises(ValueError):
        store.clear("nope")


def test_empty_values_rejected(store):
    with pytest.raises(ValueError):
        store.toggle_favorite("   ")
    with pytest.raises(ValueError):
        store.mark_watched("")
    with pytest.raises(ValueError):
        store.toggle_hidden_channel(None)


# ---------- устойчивость файла ----------

def test_broken_file_falls_back_to_backup(store):
    store.toggle_favorite("vid1")
    store.toggle_favorite("vid2")  # создаёт .bak с состоянием ["vid1"]
    with open(store.USERDATA_FILE, "w", encoding="utf-8") as f:
        f.write("{ это не json")
    store.reload_from_disk()

    # Данные восстановлены из бэкапа, а не потеряны целиком.
    assert store.get_all()["favorites"] == ["vid1"]


def test_broken_file_without_backup_starts_empty(store):
    with open(store.USERDATA_FILE, "w", encoding="utf-8") as f:
        f.write("не json")
    store.reload_from_disk()
    assert store.get_all()["favorites"] == []


def test_file_with_bom_is_read(store):
    with open(store.USERDATA_FILE, "w", encoding="utf-8-sig") as f:
        json.dump({"favorites": ["vid1"]}, f)
    store.reload_from_disk()
    assert store.get_all()["favorites"] == ["vid1"]


def test_garbage_values_are_filtered(store):
    with open(store.USERDATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "favorites": ["ok", 42, None, "  ", "ok", "  spaced  "],
            "history": "не список",
            "hidden_channels": [{"a": 1}, "Chan"],
        }, f)
    store.reload_from_disk()
    data = store.get_all()
    assert data["favorites"] == ["ok", "spaced"]
    assert data["history"] == []
    assert data["hidden_channels"] == ["Chan"]


def test_no_temp_file_left_behind(store):
    store.toggle_favorite("vid1")
    assert not os.path.exists(store.USERDATA_FILE + ".tmp")


# ---------- сбой записи ----------

def test_save_failure_raises_and_rolls_back(store, monkeypatch):
    """Ошибка записи не должна оставлять память расходиться с диском."""
    store.toggle_favorite("kept")

    def boom(*args, **kwargs):
        raise OSError("диск переполнен")

    monkeypatch.setattr(userdata_module.json, "dump", boom)
    with pytest.raises(store.UserDataSaveError):
        store.toggle_favorite("lost")

    # Откат: неудачное изменение не видно ни в памяти, ни на диске.
    assert store.get_all()["favorites"] == ["kept"]
    store.reload_from_disk()
    assert store.get_all()["favorites"] == ["kept"]


def test_save_failure_cleans_temp_file(store, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("сбой")

    monkeypatch.setattr(userdata_module.json, "dump", boom)
    with pytest.raises(store.UserDataSaveError):
        store.toggle_favorite("vid1")
    assert not os.path.exists(store.USERDATA_FILE + ".tmp")


# ---------- миграция ----------

def test_merge_from_client_imports_data(store):
    added, state = store.merge_from_client({
        "favorites": ["f1", "f2"],
        "history": ["h1"],
        "hidden_channels": ["Chan"],
    })
    assert added == {"favorites": 2, "history": 1, "hidden_channels": 1}
    assert state["favorites"] == ["f1", "f2"]


def test_merge_does_not_delete_server_data(store):
    """Пустой localStorage второго браузера не должен стирать серверные данные."""
    store.toggle_favorite("server_fav")
    added, state = store.merge_from_client({"favorites": [], "history": []})
    assert added["favorites"] == 0
    assert state["favorites"] == ["server_fav"]


def test_merge_does_not_duplicate(store):
    store.toggle_favorite("both")
    added, state = store.merge_from_client({"favorites": ["both", "new"]})
    assert added["favorites"] == 1
    assert state["favorites"] == ["both", "new"]


def test_merge_verifies_data_reached_disk(store, monkeypatch):
    """Если запись не дошла до диска, миграция обязана сообщить об ошибке.

    Клиент по успешному ответу стирает localStorage, поэтому мнимый успех
    означал бы безвозвратную потерю данных.
    """
    real_save = userdata_module._save_locked

    def fake_save():
        # Притворяемся, что сохранение прошло, ничего не записывая.
        return None

    monkeypatch.setattr(userdata_module, "_save_locked", fake_save)
    with pytest.raises(store.UserDataSaveError):
        store.merge_from_client({"favorites": ["f1"]})

    monkeypatch.setattr(userdata_module, "_save_locked", real_save)


def test_merge_reads_state_from_disk(store):
    """Ответ на миграцию должен строиться по содержимому файла."""
    _, state = store.merge_from_client({"favorites": ["f1"]})
    assert state["favorites"] == read_disk(store)["favorites"]


# ---------- HTTP API ----------

def test_api_get_userdata(api):
    res = api.get("/api/userdata")
    assert res.status_code == 200
    assert res.get_json()["favorites"] == []


def test_api_toggle_favorite(api):
    res = api.post("/api/userdata/favorite/vid1")
    assert res.status_code == 200
    body = res.get_json()
    assert body["active"] is True and body["favorites"] == ["vid1"]

    assert api.post("/api/userdata/favorite/vid1").get_json()["active"] is False


def test_api_favorite_explicit_state(api):
    """Повторный запрос с тем же active не переворачивает состояние."""
    first = api.post("/api/userdata/favorite/vid1", json={"active": True}).get_json()
    second = api.post("/api/userdata/favorite/vid1", json={"active": True}).get_json()
    assert first["active"] is True and second["active"] is True
    assert second["favorites"] == ["vid1"]

    off = api.post("/api/userdata/favorite/vid1", json={"active": False}).get_json()
    assert off["active"] is False and off["favorites"] == []


def test_api_hidden_channel_explicit_state(api):
    body = {"author": "Chan", "hidden": True}
    assert api.post("/api/userdata/hidden-channel", json=body).get_json()["hidden"] is True
    repeated = api.post("/api/userdata/hidden-channel", json=body).get_json()
    assert repeated["hidden"] is True and repeated["hidden_channels"] == ["Chan"]

    off = api.post("/api/userdata/hidden-channel",
                   json={"author": "Chan", "hidden": False}).get_json()
    assert off["hidden"] is False and off["hidden_channels"] == []


def test_api_watched(api):
    res = api.post("/api/userdata/watched/vid1")
    assert res.status_code == 200
    assert res.get_json()["history"] == ["vid1"]


def test_api_hidden_channel(api):
    res = api.post("/api/userdata/hidden-channel", json={"author": "Chan"})
    assert res.status_code == 200
    assert res.get_json()["hidden"] is True


def test_api_hidden_channel_requires_author(api):
    assert api.post("/api/userdata/hidden-channel", json={"author": ""}).status_code == 400


def test_api_clear_unknown_section(api):
    assert api.post("/api/userdata/clear/nope").status_code == 400


def test_api_clear(api):
    api.post("/api/userdata/favorite/vid1")
    res = api.post("/api/userdata/clear/favorites")
    assert res.status_code == 200
    assert res.get_json()["favorites"] == []


def test_api_migrate(api):
    res = api.post("/api/userdata/migrate", json={"favorites": ["f1"], "history": ["h1"]})
    assert res.status_code == 200
    body = res.get_json()
    assert body["added"]["favorites"] == 1
    assert body["favorites"] == ["f1"]


def test_api_reports_save_failure(api, store, monkeypatch):
    """При сбое записи API обязан вернуть 500, а не мнимый успех."""
    def boom(*args, **kwargs):
        raise OSError("нет места")

    monkeypatch.setattr(userdata_module.json, "dump", boom)
    assert api.post("/api/userdata/favorite/vid1").status_code == 500
    assert api.post("/api/userdata/watched/vid1").status_code == 500
    assert api.post("/api/userdata/migrate", json={"favorites": ["f1"]}).status_code == 500


def test_api_migrate_failure_keeps_nothing_lost(api, store, monkeypatch):
    """После неудачной миграции серверные данные остаются прежними."""
    api.post("/api/userdata/favorite/existing")

    def boom(*args, **kwargs):
        raise OSError("нет места")

    # Отдельный контекст: общий monkeypatch откатил бы и подмену пути к файлу.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(userdata_module.json, "dump", boom)
        assert api.post("/api/userdata/migrate",
                        json={"favorites": ["new"]}).status_code == 500

    store.reload_from_disk()
    assert store.get_all()["favorites"] == ["existing"]
