"""Кэш сканирования библиотеки: корректность инвалидации и производных полей.

Кэш опасен именно тем, что ускоряет ценой устаревших данных, поэтому здесь
проверяется, что каждое изменение на диске подхватывается.
"""
import json
import os
import shutil
import time

import pytest


def write_meta(vdir, **over):
    meta = {
        "id": os.path.basename(vdir), "title": "Original", "duration": 100,
        "upload_date": "20260101", "width": 1920, "height": 1080,
    }
    meta.update(over)
    with open(os.path.join(vdir, "info.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)


def add_video(lib, author, vid, size=1024, **meta):
    vdir = os.path.join(lib, author, vid)
    os.makedirs(vdir, exist_ok=True)
    with open(os.path.join(vdir, "video.mp4"), "wb") as f:
        f.write(b"\0" * size)
    write_meta(vdir, **meta)
    return vdir


@pytest.fixture
def library(tmp_path, app_module, monkeypatch):
    """Изолированная библиотека видео вместо реальной."""
    lib = tmp_path / "videos"
    lib.mkdir()
    monkeypatch.setattr(app_module, "BASE_VIDEO_DIR", str(lib))
    app_module.invalidate_scan_cache()
    yield str(lib)
    app_module.invalidate_scan_cache()


def test_first_scan_finds_video(app_module, library):
    add_video(library, "Chan", "vid1")
    assert app_module.build_video_map() == 1
    assert app_module.VIDEO_MAP["vid1"]["title"] == "Original"


def test_repeated_scan_is_stable(app_module, library):
    add_video(library, "Chan", "vid1")
    app_module.build_video_map()
    assert app_module.build_video_map() == 1
    assert app_module.VIDEO_MAP["vid1"]["title"] == "Original"


def test_metadata_edit_is_picked_up(app_module, library):
    vdir = add_video(library, "Chan", "vid1")
    app_module.build_video_map()

    time.sleep(1.1)  # mtime на Windows имеет посекундную точность
    write_meta(vdir, title="Renamed")
    app_module.build_video_map()

    assert app_module.VIDEO_MAP["vid1"]["title"] == "Renamed"


def test_video_file_rewrite_updates_size(app_module, library):
    vdir = add_video(library, "Chan", "vid1")
    app_module.build_video_map()
    old = app_module.VIDEO_MAP["vid1"]["size_mb"]

    time.sleep(1.1)
    with open(os.path.join(vdir, "video.mp4"), "wb") as f:
        f.write(b"\0" * (3 * 1024 * 1024))
    app_module.build_video_map()

    assert app_module.VIDEO_MAP["vid1"]["size_mb"] != old


def test_new_video_is_found(app_module, library):
    add_video(library, "Chan", "vid1")
    app_module.build_video_map()

    add_video(library, "Chan", "vid2", title="Second")

    assert app_module.build_video_map() == 2
    assert "vid2" in app_module.VIDEO_MAP


def test_deleted_video_disappears(app_module, library):
    add_video(library, "Chan", "vid1")
    vdir2 = add_video(library, "Chan", "vid2")
    app_module.build_video_map()

    shutil.rmtree(vdir2)

    assert app_module.build_video_map() == 1
    assert "vid2" not in app_module.VIDEO_MAP
    # Кэш не должен расти за счёт удалённых папок.
    assert all("vid2" not in path for path in app_module._scan_cache)


def test_folder_without_video_file_skipped(app_module, library):
    vdir = add_video(library, "Chan", "vid1")
    app_module.build_video_map()

    os.remove(os.path.join(vdir, "video.mp4"))

    assert app_module.build_video_map() == 0


def test_metadata_with_bom_is_read(app_module, library):
    """info.json с BOM должен читаться: иначе видео теряет название и дату."""
    vdir = add_video(library, "Chan", "vid1")
    with open(os.path.join(vdir, "info.json"), "w", encoding="utf-8-sig") as f:
        json.dump({"id": "vid1", "title": "С BOM", "duration": 42,
                   "upload_date": "20260201"}, f)

    app_module.build_video_map()

    assert app_module.VIDEO_MAP["vid1"]["title"] == "С BOM"
    assert app_module.VIDEO_MAP["vid1"]["duration"] == 42


def test_broken_metadata_does_not_break_scan(app_module, library):
    vdir = add_video(library, "Chan", "vid3")
    with open(os.path.join(vdir, "info.json"), "w", encoding="utf-8") as f:
        f.write("{ not json at all")

    assert app_module.build_video_map() == 1
    # Видео должно остаться видимым, пусть и с именем папки вместо названия.
    assert "vid3" in app_module.VIDEO_MAP


def test_thumb_file_recorded_during_scan(app_module, library):
    vdir = add_video(library, "Chan", "vid1")
    with open(os.path.join(vdir, "thumbnail.jpg"), "wb") as f:
        f.write(b"\xff\xd8\xff")
    app_module.build_video_map()

    assert app_module.VIDEO_MAP["vid1"]["thumb_file"] == "thumbnail.jpg"
    item = app_module._video_item("vid1", app_module.VIDEO_MAP["vid1"])
    assert item["thumb"] and item["thumb"].endswith("thumbnail.jpg")


def test_missing_thumb_yields_none(app_module, library):
    add_video(library, "Chan", "vid1")
    app_module.build_video_map()

    assert app_module.VIDEO_MAP["vid1"]["thumb_file"] is None
    assert app_module._video_item("vid1", app_module.VIDEO_MAP["vid1"])["thumb"] is None


def test_ensure_video_map_reuses_fresh_map(app_module, library, monkeypatch):
    add_video(library, "Chan", "vid1")
    app_module.build_video_map()

    calls = []
    real = app_module.build_video_map
    monkeypatch.setattr(app_module, "build_video_map",
                        lambda: calls.append(1) or real())

    app_module.ensure_video_map()
    assert calls == [], "свежая карта не должна пересканироваться"


def test_ensure_video_map_rescans_when_stale(app_module, library, monkeypatch):
    add_video(library, "Chan", "vid1")
    app_module.build_video_map()

    # Притворяемся, что карта собрана давно.
    monkeypatch.setattr(app_module, "_map_built_at", 0.0)
    add_video(library, "Chan", "vid2")

    assert app_module.ensure_video_map() == 2


def test_fresh_window_is_short_enough(app_module):
    """Окно свежести не должно быть бесконечным.

    Иначе новые видео не появлялись бы в интерфейсе до перезапуска сервера.
    """
    assert 0 < app_module.MAP_FRESH_WINDOW <= 10


def test_new_video_appears_after_window_expires(app_module, library, monkeypatch):
    add_video(library, "Chan", "vid1")
    monkeypatch.setattr(app_module, "MAP_FRESH_WINDOW", 0.05)
    assert app_module.ensure_video_map() == 1

    add_video(library, "Chan", "vid2")
    time.sleep(0.1)

    assert app_module.ensure_video_map(max_age=0.05) == 2


def test_invalidate_cache_forces_rescan(app_module, library):
    add_video(library, "Chan", "vid1")
    app_module.build_video_map()

    app_module.invalidate_scan_cache()

    assert app_module._scan_cache == {}
    assert app_module.ensure_video_map() == 1


# --- кэш аватарок ---

def test_avatar_cache_picks_up_new_file(app_module, tmp_path, monkeypatch):
    avatars = tmp_path / "avas"
    avatars.mkdir()
    monkeypatch.setattr(app_module, "AVATARS_DIR", str(avatars))

    assert app_module.get_avatar_url("Chan") is None

    time.sleep(1.1)
    (avatars / "Chan.jpg").write_bytes(b"\xff\xd8\xff")

    assert app_module.get_avatar_url("Chan") == "/avatars/Chan.jpg"


def test_avatar_cache_handles_missing_dir(app_module, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "AVATARS_DIR", str(tmp_path / "nope"))
    assert app_module.get_avatar_url("Chan") is None
