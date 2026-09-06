"""Тесты своих плейлистов: коллекции из уже скачанных видео.

Это НЕ те плейлисты, что скачаны с YouTube (папки в playlists/ с playlist.json).
Здесь пользователь сам собирает списки из библиотеки — как «Смотреть позже» на
YouTube. Хранится в userdata.json рядом с избранным и историей: файл уже
переживает перезапуск, доступен со всех устройств и умеет откатываться на .bak.
"""
import json

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


def read_disk(store):
    with open(store.USERDATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ================= Создание =================

def test_no_collections_initially(store):
    """Пустое хранилище не должно придумывать списки само."""
    assert store.get_all()["collections"] == []


def test_create_collection(store):
    """Основной сценарий: создать свой список."""
    created = store.create_collection("Посмотреть на выходных")
    assert created["title"] == "Посмотреть на выходных"
    assert created["videos"] == []
    assert created["id"], "у списка нет идентификатора"


def test_create_persists_on_disk(store):
    """Список должен уцелеть после перезапуска сервера."""
    store.create_collection("Музыка")
    assert read_disk(store)["collections"][0]["title"] == "Музыка"


def test_create_rejects_empty_title(store):
    """Список без названия невозможно отличить от другого такого же."""
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            store.create_collection(bad)


def test_create_rejects_duplicate_title(store):
    """Два списка с одним названием пользователь не различит."""
    store.create_collection("Ремонт")
    with pytest.raises(ValueError):
        store.create_collection("Ремонт")


def test_duplicate_check_ignores_case_and_spaces(store):
    """«ремонт» и «Ремонт  » — для человека одно и то же."""
    store.create_collection("Ремонт")
    with pytest.raises(ValueError):
        store.create_collection("  ремонт ")


def test_titles_are_trimmed(store):
    """Пробелы по краям не должны попадать в название."""
    created = store.create_collection("  Кино  ")
    assert created["title"] == "Кино"


def test_long_title_is_rejected(store):
    """Название на тысячу символов ломает вёрстку сайдбара."""
    with pytest.raises(ValueError):
        store.create_collection("я" * (userdata_module.COLLECTION_TITLE_LIMIT + 1))


def test_collection_ids_are_unique(store):
    """Одинаковые id сделали бы списки неразличимыми для API."""
    ids = {store.create_collection(f"Список {i}")["id"] for i in range(20)}
    assert len(ids) == 20


# ================= Добавление и удаление видео =================

def test_add_video(store):
    """Смысл функции: положить видео в свой список."""
    coll = store.create_collection("Кино")
    store.add_to_collection(coll["id"], "abcdefghijk")
    assert store.get_collection(coll["id"])["videos"] == ["abcdefghijk"]


def test_add_video_twice_keeps_one(store):
    """Повторное добавление не должно плодить дубли."""
    coll = store.create_collection("Кино")
    store.add_to_collection(coll["id"], "abcdefghijk")
    store.add_to_collection(coll["id"], "abcdefghijk")
    assert store.get_collection(coll["id"])["videos"] == ["abcdefghijk"]


def test_new_videos_go_to_end(store):
    """Порядок добавления — это порядок просмотра, как в плейлисте."""
    coll = store.create_collection("Кино")
    for vid in ("aaa", "bbb", "ccc"):
        store.add_to_collection(coll["id"], vid)
    assert store.get_collection(coll["id"])["videos"] == ["aaa", "bbb", "ccc"]


def test_remove_video(store):
    coll = store.create_collection("Кино")
    store.add_to_collection(coll["id"], "aaa")
    store.add_to_collection(coll["id"], "bbb")
    store.remove_from_collection(coll["id"], "aaa")
    assert store.get_collection(coll["id"])["videos"] == ["bbb"]


def test_remove_missing_video_is_quiet(store):
    """Двойной клик по «убрать» не должен давать ошибку."""
    coll = store.create_collection("Кино")
    store.remove_from_collection(coll["id"], "нет такого")
    assert store.get_collection(coll["id"])["videos"] == []


def test_add_to_unknown_collection_raises(store):
    """Список могли удалить в другой вкладке."""
    with pytest.raises(KeyError):
        store.add_to_collection("нет такого", "abcdefghijk")


def test_add_rejects_empty_video_id(store):
    coll = store.create_collection("Кино")
    with pytest.raises(ValueError):
        store.add_to_collection(coll["id"], "  ")


def test_video_can_be_in_several_collections(store):
    """Как на YouTube: одно видео в нескольких плейлистах.

    В том числе одновременно в своём списке и во встроенном «Смотреть позже».
    """
    a = store.create_collection("Кино")
    b = store.watch_later()
    store.add_to_collection(a["id"], "abcdefghijk")
    store.add_to_collection(b["id"], "abcdefghijk")
    assert store.get_collection(a["id"])["videos"] == ["abcdefghijk"]
    assert store.get_collection(b["id"])["videos"] == ["abcdefghijk"]


def test_collection_size_is_capped(store):
    """Без предела один список мог бы разрастись до неограниченного размера."""
    coll = store.create_collection("Большой")
    limit = userdata_module.COLLECTION_VIDEOS_LIMIT
    for i in range(limit):
        store.add_to_collection(coll["id"], f"vid{i}")
    with pytest.raises(ValueError):
        store.add_to_collection(coll["id"], "ещё одно")


def test_number_of_collections_is_capped(store):
    """Без предела список плейлистов раздувал бы userdata.json без границы."""
    limit = userdata_module.COLLECTIONS_LIMIT
    for i in range(limit):
        store.create_collection(f"Плейлист {i}")
    with pytest.raises(ValueError):
        store.create_collection("Лишний")
    # Отказ не должен затирать уже созданное.
    assert len(store.get_all()["collections"]) == limit


# ================= Переименование и удаление списка =================

def test_rename_collection(store):
    coll = store.create_collection("Кино")
    store.rename_collection(coll["id"], "Фильмы")
    assert store.get_collection(coll["id"])["title"] == "Фильмы"


def test_rename_keeps_videos(store):
    """Переименование не должно терять содержимое."""
    coll = store.create_collection("Кино")
    store.add_to_collection(coll["id"], "abcdefghijk")
    store.rename_collection(coll["id"], "Фильмы")
    assert store.get_collection(coll["id"])["videos"] == ["abcdefghijk"]


def test_rename_rejects_duplicate(store):
    store.create_collection("Кино")
    other = store.create_collection("Музыка")
    with pytest.raises(ValueError):
        store.rename_collection(other["id"], "Кино")


def test_rename_to_same_title_is_allowed(store):
    """Сохранение без изменений не должно выглядеть как конфликт с собой."""
    coll = store.create_collection("Кино")
    store.rename_collection(coll["id"], "Кино")
    assert store.get_collection(coll["id"])["title"] == "Кино"


def test_delete_collection(store):
    coll = store.create_collection("Кино")
    store.delete_collection(coll["id"])
    assert store.get_all()["collections"] == []


def test_delete_unknown_collection_raises(store):
    with pytest.raises(KeyError):
        store.delete_collection("нет такого")


# ================= «Смотреть позже» =================

def test_watch_later_is_created_on_demand(store):
    """Встроенный список как на YouTube: пользователю не надо его создавать."""
    coll = store.watch_later()
    assert coll["title"] == userdata_module.WATCH_LATER_TITLE
    assert coll["id"] == userdata_module.WATCH_LATER_ID


def test_watch_later_is_not_duplicated(store):
    """Повторное обращение должно давать тот же список, а не новый."""
    first = store.watch_later()
    store.add_to_collection(first["id"], "abcdefghijk")
    second = store.watch_later()
    assert second["videos"] == ["abcdefghijk"]
    assert len(store.get_all()["collections"]) == 1


def test_watch_later_cannot_be_deleted(store):
    """Встроенный список удалять нельзя: иначе кнопка на видео сломается."""
    coll = store.watch_later()
    with pytest.raises(ValueError):
        store.delete_collection(coll["id"])


def test_watch_later_cannot_be_renamed(store):
    coll = store.watch_later()
    with pytest.raises(ValueError):
        store.rename_collection(coll["id"], "Другое имя")


def test_user_cannot_occupy_watch_later_title(store):
    """Свой список с тем же названием был бы неотличим от встроенного."""
    with pytest.raises(ValueError):
        store.create_collection(userdata_module.WATCH_LATER_TITLE)


# ================= Устойчивость хранилища =================

def test_broken_collections_are_dropped(store):
    """Файл могли поправить руками: мусор не должен ломать загрузку."""
    with open(store.USERDATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"collections": ["строка вместо объекта", {"нет": "полей"},
                                   {"id": "ok", "title": "Годный", "videos": ["a", "a", 5]}]}, f)
    store.reload_from_disk()
    colls = store.get_all()["collections"]
    assert len(colls) == 1, colls
    assert colls[0]["title"] == "Годный"
    # Дубли и не-строки внутри списка видео тоже отбрасываются.
    assert colls[0]["videos"] == ["a"]


def test_existing_userdata_survives_upgrade(store):
    """Обновление не должно терять избранное и историю.

    Старый userdata.json ключа collections не содержит вовсе.
    """
    with open(store.USERDATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"favorites": ["fav1"], "history": ["h1"],
                   "hidden_channels": ["Канал"]}, f)
    store.reload_from_disk()
    data = store.get_all()
    assert data["favorites"] == ["fav1"]
    assert data["history"] == ["h1"]
    assert data["hidden_channels"] == ["Канал"]
    assert data["collections"] == []


def test_clear_does_not_touch_collections(store):
    """Очистка истории не должна уносить собранные плейлисты."""
    coll = store.create_collection("Кино")
    store.add_to_collection(coll["id"], "abcdefghijk")
    store.mark_watched("abcdefghijk")
    store.clear("history")
    assert store.get_collection(coll["id"])["videos"] == ["abcdefghijk"]


def test_collections_can_be_cleared_explicitly(store):
    """Отдельный раздел для очистки — как у остальных списков."""
    store.create_collection("Кино")
    store.clear("collections")
    assert store.get_all()["collections"] == []


def test_migrate_keeps_collections(store):
    """Разовый перенос из localStorage не должен затрагивать плейлисты."""
    coll = store.create_collection("Кино")
    store.merge_from_client({"favorites": ["fav1"]})
    assert store.get_collection(coll["id"])["title"] == "Кино"
    assert "fav1" in store.get_all()["favorites"]


def test_failed_save_rolls_back(store, monkeypatch):
    """Сбой записи не должен оставлять изменение только в памяти."""
    coll = store.create_collection("Кино")

    def boom():
        raise store.UserDataSaveError("диск переполнен")

    monkeypatch.setattr(store, "_save_locked", boom)
    with pytest.raises(store.UserDataSaveError):
        store.add_to_collection(coll["id"], "abcdefghijk")
    monkeypatch.undo()
    assert store.get_collection(coll["id"])["videos"] == []


# ================= API =================

@pytest.fixture
def api(store, client):
    return client


def test_api_list_collections(api):
    res = api.get("/api/collections")
    assert res.status_code == 200
    assert res.get_json()["collections"] == []


def test_api_create(api):
    res = api.post("/api/collections", json={"title": "Кино"})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["collection"]["title"] == "Кино"


def test_api_create_rejects_empty(api):
    res = api.post("/api/collections", json={"title": "  "})
    assert res.status_code == 400
    assert res.get_json().get("error")


def test_api_create_rejects_duplicate(api):
    api.post("/api/collections", json={"title": "Кино"})
    res = api.post("/api/collections", json={"title": "Кино"})
    assert res.status_code == 400


def test_api_add_and_remove_video(api):
    coll = api.post("/api/collections", json={"title": "Кино"}).get_json()["collection"]
    add = api.post(f"/api/collections/{coll['id']}/videos", json={"video_id": "abcdefghijk"})
    assert add.status_code == 200, add.get_json()
    assert add.get_json()["collection"]["videos"] == ["abcdefghijk"]

    rem = api.delete(f"/api/collections/{coll['id']}/videos/abcdefghijk")
    assert rem.status_code == 200
    assert rem.get_json()["collection"]["videos"] == []


def test_api_add_to_unknown_collection_is_404(api):
    res = api.post("/api/collections/неттакого/videos", json={"video_id": "abcdefghijk"})
    assert res.status_code == 404


def test_api_rename(api):
    coll = api.post("/api/collections", json={"title": "Кино"}).get_json()["collection"]
    res = api.patch(f"/api/collections/{coll['id']}", json={"title": "Фильмы"})
    assert res.status_code == 200
    assert res.get_json()["collection"]["title"] == "Фильмы"


def test_api_delete(api):
    coll = api.post("/api/collections", json={"title": "Кино"}).get_json()["collection"]
    res = api.delete(f"/api/collections/{coll['id']}")
    assert res.status_code == 200
    assert api.get("/api/collections").get_json()["collections"] == []


def test_api_watch_later_shortcut(api):
    """Кнопка «Смотреть позже» не должна требовать заранее созданного списка."""
    res = api.post("/api/collections/watch-later/videos", json={"video_id": "abcdefghijk"})
    assert res.status_code == 200, res.get_json()
    colls = api.get("/api/collections").get_json()["collections"]
    assert len(colls) == 1
    assert colls[0]["videos"] == ["abcdefghijk"]


def test_api_non_json_payload_is_400(api):
    res = api.post("/api/collections", data="мусор", content_type="text/plain")
    assert res.status_code == 400


def test_api_reports_video_count(api):
    """Сайдбару нужно число видео, а не весь список."""
    coll = api.post("/api/collections", json={"title": "Кино"}).get_json()["collection"]
    api.post(f"/api/collections/{coll['id']}/videos", json={"video_id": "abcdefghijk"})
    listed = api.get("/api/collections").get_json()["collections"][0]
    assert listed["count"] == 1


# ================= Страница плейлиста =================

def test_collection_page_renders(api):
    coll = api.post("/api/collections", json={"title": "Кино"}).get_json()["collection"]
    res = api.get(f"/collection/{coll['id']}")
    assert res.status_code == 200
    assert "Кино" in res.get_data(as_text=True)


def test_unknown_collection_page_is_404(api):
    assert api.get("/collection/неттакого").status_code == 404


def test_collection_page_skips_missing_videos(api, monkeypatch):
    """Видео могли удалить с диска: страница не должна падать.

    Битая ссылка в списке — обычное дело, если файл убрали вручную.
    """
    import app as app_module

    coll = api.post("/api/collections", json={"title": "Кино"}).get_json()["collection"]
    api.post(f"/api/collections/{coll['id']}/videos", json={"video_id": "нет_на_диске"})
    monkeypatch.setattr(app_module, "VIDEO_MAP", {})
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {})

    res = api.get(f"/collection/{coll['id']}")
    assert res.status_code == 200


# ================= Просмотр по порядку =================

def test_watch_page_gets_playlist_context(api, monkeypatch):
    """Кнопка «Смотреть» открывает видео с ?collection=<id>.

    Страница должна получить сам плейлист, иначе после конца видео некуда
    переходить: параметр был, а никто его не читал.
    """
    import app as app_module

    monkeypatch.setattr(app_module, "VIDEO_MAP", {})
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {})

    coll = api.post("/api/collections", json={"title": "Кино"}).get_json()["collection"]
    api.post(f"/api/collections/{coll['id']}/videos", json={"video_id": "a"})
    api.post(f"/api/collections/{coll['id']}/videos", json={"video_id": "b"})

    ctx = api.application.view_functions
    assert "watch" in ctx, "нет роута /watch"

    # Само видео на диске отсутствует, поэтому проверяем через сборку контекста.
    order = app_module.collection_playback_order(coll["id"])
    assert order == ["a", "b"], f"порядок видео не пришёл: {order}"


def test_playback_order_is_empty_for_unknown_collection():
    """Неизвестный плейлист не должен ронять страницу видео."""
    import app as app_module

    assert app_module.collection_playback_order("нет-такого") == []


def test_playback_order_ignores_missing_collection_param():
    """Без параметра порядок пустой: обычный просмотр не меняется."""
    import app as app_module

    assert app_module.collection_playback_order(None) == []
    assert app_module.collection_playback_order("") == []


# ================= Защита данных пользователя =================

def test_real_userdata_file_is_not_used_by_tests():
    """Прогон не должен трогать настоящий userdata.json.

    Там история, избранное и плейлисты пользователя. Изоляцию даёт autouse
    фикстура в conftest.py, и без неё любой тест, дошедший до /api/userdata,
    писал бы в живой файл. Проверяем, что подмена действительно сделана: файл
    в корне проекта использоваться не должен.

    Тест намеренно без фикстуры store: она подменяет путь сама и скрыла бы
    снятую защиту в conftest.py.
    """
    import os

    real = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "userdata.json")
    used = os.path.abspath(userdata_module.USERDATA_FILE)
    assert used != os.path.abspath(real), (
        "тесты работают с настоящим userdata.json, изоляция в conftest.py снята"
    )
