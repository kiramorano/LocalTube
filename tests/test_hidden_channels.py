"""Тесты серверной фильтрации скрытых каналов.

Раньше скрытие работало только в браузере: сервер отдавал видео скрытых
каналов, и любой другой клиент их видел.
"""
import os

import pytest

import userdata as userdata_module


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(userdata_module, "USERDATA_FILE",
                        str(tmp_path / "userdata.json"))
    userdata_module.reload_from_disk()
    yield userdata_module
    userdata_module.reload_from_disk()


@pytest.fixture
def library(app_module, tmp_path, monkeypatch):
    """Небольшая библиотека из двух каналов."""
    root = tmp_path / "videos"
    monkeypatch.setattr(app_module, "BASE_VIDEO_DIR", str(root))
    monkeypatch.setattr(app_module, "USER_VIDEOS_ROOT", str(tmp_path / "uservideos"))
    app_module.invalidate_scan_cache()

    def add(author, vid, is_short=False):
        vdir = root / author / vid
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "video.mp4").write_bytes(b"\0" * 2048)
        import json
        meta = {"id": vid, "title": f"Видео {vid}", "duration": 30,
                "upload_date": "20260101"}
        if is_short:
            meta.update({"width": 720, "height": 1280, "duration": 20})
        else:
            meta.update({"width": 1920, "height": 1080})
        with open(vdir / "info.json", "w", encoding="utf-8") as f:
            json.dump(meta, f)

    add("Keep", "keep1")
    add("Keep", "keepshort", is_short=True)
    add("Hide", "hide1")
    add("Hide", "hideshort", is_short=True)
    app_module.build_video_map()
    yield add
    app_module.invalidate_scan_cache()


def hide(store, author):
    store.toggle_hidden_channel(author, True)


# ---------- helper ----------

def test_hidden_channels_set_reads_userdata(app_module, store):
    hide(store, "Hide")
    assert app_module.hidden_channels_set() == {"Hide"}


def test_hidden_channels_set_survives_read_error(app_module, store, monkeypatch):
    """Сбой чтения не должен ломать выдачу: показываем всё."""
    def boom():
        raise OSError("диск недоступен")

    monkeypatch.setattr(userdata_module, "get_all", boom)
    assert app_module.hidden_channels_set() == set()


# ---------- /api/catalog ----------

def test_catalog_excludes_hidden_channel(client, store, library):
    hide(store, "Hide")
    data = client.get("/api/catalog").get_json()
    assert {v["author"] for v in data["videos"]} == {"Keep"}
    assert {s["author"] for s in data["shorts"]} == {"Keep"}
    assert [a["name"] for a in data["authors"]] == ["Keep"]


def test_catalog_include_hidden_shows_everything(client, store, library):
    hide(store, "Hide")
    data = client.get("/api/catalog?include_hidden=1").get_json()
    assert {v["author"] for v in data["videos"]} == {"Keep", "Hide"}
    assert sorted(a["name"] for a in data["authors"]) == ["Hide", "Keep"]


def test_catalog_shows_all_when_nothing_hidden(client, store, library):
    data = client.get("/api/catalog").get_json()
    assert {v["author"] for v in data["videos"]} == {"Keep", "Hide"}


# ---------- /api/search ----------

def test_search_excludes_hidden_channel(client, store, library):
    hide(store, "Hide")
    results = client.get("/api/search?q=видео").get_json()["results"]
    assert results, "поиск ничего не нашёл, тест бессмысленен"
    assert {r["author"] for r in results} == {"Keep"}


def test_search_by_hidden_author_name_returns_nothing(client, store, library):
    hide(store, "Hide")
    results = client.get("/api/search?q=hide").get_json()["results"]
    assert results == []


def test_search_include_hidden(client, store, library):
    hide(store, "Hide")
    results = client.get("/api/search?q=hide&include_hidden=1").get_json()["results"]
    assert {r["author"] for r in results} == {"Hide"}


# ---------- главная страница ----------

def test_index_does_not_render_hidden_cards(client, store, library):
    hide(store, "Hide")
    html = client.get("/").get_data(as_text=True)
    assert 'data-author="Hide"' not in html
    assert 'data-author="Keep"' in html


def test_index_passes_hidden_list_to_client(client, store, library):
    """Список нужен сайдбару, чтобы канал можно было вернуть."""
    hide(store, "Hide")
    html = client.get("/").get_data(as_text=True)
    assert '"Hide"' in html


# ---------- лента Shorts ----------

def test_shorts_feed_excludes_hidden(client, store, library):
    hide(store, "Hide")
    html = client.get("/watch/keepshort").get_data(as_text=True)
    assert "hideshort" not in html


def test_shorts_feed_keeps_current_video_even_if_hidden(client, store, library):
    """Открытое намеренно видео скрытого канала должно проигрываться.

    Иначе лента Shorts окажется пустой: сам ролик выпадет из выдачи и
    воспроизводить будет нечего.
    """
    hide(store, "Hide")
    res = client.get("/watch/hideshort")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    # Проверяем именно элемент ленты, а не любое упоминание id на странице.
    assert 'data-id="hideshort"' in html, "текущий Short выпал из ленты"
    # И при этом другие ролики скрытого канала в ленту не попадают.
    assert 'data-id="hide1"' not in html


# ---------- рекомендации ----------

def test_recommendations_exclude_hidden(client, store, library):
    hide(store, "Hide")
    html = client.get("/watch/keep1").get_data(as_text=True)
    assert 'data-author="Hide"' not in html


# ---------- страница канала ----------

def test_channel_page_shows_hide_button(client, store, library):
    html = client.get("/channel/Keep").get_data(as_text=True)
    assert 'id="hideChannelBtn"' in html
    assert "Скрыть канал" in html


def test_channel_page_reflects_hidden_state(client, store, library):
    hide(store, "Hide")
    html = client.get("/channel/Hide").get_data(as_text=True)
    assert "Показать канал" in html
    assert 'aria-pressed="true"' in html


def test_channel_page_still_lists_own_videos_when_hidden(client, store, library):
    """Страница скрытого канала должна работать: скрытие влияет на подборки."""
    hide(store, "Hide")
    html = client.get("/channel/Hide").get_data(as_text=True)
    assert "hide1" in html
