"""Диагностика и повторная синхронизация каналов (без обращения к сети)."""
import os
import time

import pytest


def test_status_without_metadata_is_never(channel_assets, test_author):
    status = channel_assets.get_sync_status(test_author)
    assert status["status"] == "never"
    assert status["error"] == ""


def test_update_status_keeps_channel_data(channel_assets, test_author):
    channel_assets.save_channel_assets(test_author, {
        "description": "desc", "subscribers": 1200, "channel_id": "UC_test",
    })
    channel_assets.update_sync_status(
        test_author, "error", error="Connection reset",
        started_at=100.0, finished_at=140.0, success=False,
    )

    meta = channel_assets.load_channel_meta(test_author)
    assert meta["description"] == "desc"
    assert meta["subscribers"] == 1200
    assert meta["sync_error"] == "Connection reset"
    assert meta["last_sync_success"] is False

    status = channel_assets.get_sync_status(test_author)
    assert status["status"] == "error"
    assert status["finished_at"] == 140.0


def test_successful_sync_updates_metadata(channel_assets, test_author, monkeypatch):
    monkeypatch.setattr(channel_assets, "fetch_channel_info", lambda url, raise_on_error=False: {
        "description": "Новое описание", "subscribers": 4242, "channel_id": "UC_ok",
        "country": "RU", "joined_date": "20200101", "avatar": None, "banner": None,
    })

    assert channel_assets.sync_channel(test_author, "https://www.youtube.com/channel/UC_ok") is True

    meta = channel_assets.load_channel_meta(test_author)
    assert meta["sync_status"] == "success"
    assert meta["sync_error"] == ""
    assert meta["description"] == "Новое описание"
    assert meta["last_sync_success"] is True
    assert meta["last_sync_finished_at"]


def test_network_error_recorded_without_losing_data(channel_assets, test_author, monkeypatch):
    channel_assets.save_channel_assets(test_author, {"description": "Прежнее описание"})

    def boom(url, raise_on_error=False):
        raise RuntimeError("Connection aborted: ConnectionResetError 10054")

    monkeypatch.setattr(channel_assets, "fetch_channel_info", boom)

    assert channel_assets.sync_channel(test_author, "https://www.youtube.com/channel/UC_ok") is False

    meta = channel_assets.load_channel_meta(test_author)
    assert meta["sync_status"] == "error"
    assert "10054" in meta["sync_error"]
    assert meta["description"] == "Прежнее описание"


def test_non_string_error_is_stringified(channel_assets, test_author):
    """Исключение или любой объект в error не должны срывать запись JSON."""
    channel_assets.update_sync_status(test_author, "error", error=RuntimeError("boom"), success=False)

    meta = channel_assets.load_channel_meta(test_author)
    assert isinstance(meta["sync_error"], str)
    assert "boom" in meta["sync_error"]
    # Статус обязан сохраниться, а не потеряться из-за ошибки сериализации.
    assert meta["sync_status"] == "error"


def test_empty_error_stored_as_empty_string(channel_assets, test_author):
    channel_assets.update_sync_status(test_author, "success", error=None, success=True)
    assert channel_assets.load_channel_meta(test_author)["sync_error"] == ""


def test_fetch_channel_info_without_ytdlp(channel_assets, monkeypatch):
    monkeypatch.setattr(channel_assets, "yt_dlp", None)

    assert channel_assets.fetch_channel_info("u") is None
    with pytest.raises(RuntimeError):
        channel_assets.fetch_channel_info("u", raise_on_error=True)


def test_sync_without_channel_url_raises(channel_assets):
    with pytest.raises(RuntimeError, match="URL канала не найден"):
        channel_assets.sync_channel("__no_such_author__")


def test_stale_checking_becomes_interrupted(channel_assets, test_author):
    """Перезапуск процесса посреди проверки не должен блокировать кнопку навсегда."""
    channel_assets.update_sync_status(test_author, "checking", error="", started_at=time.time())
    with channel_assets._fetch_lock:
        channel_assets._fetching.discard(test_author)

    status = channel_assets.get_sync_status(test_author)

    assert status["status"] == "interrupted"
    assert status["in_progress"] is False
    assert "прерван" in status["error"].lower()


def test_checking_stays_while_thread_alive(channel_assets, test_author):
    channel_assets.update_sync_status(test_author, "checking", error="", started_at=time.time())
    with channel_assets._fetch_lock:
        channel_assets._fetching.add(test_author)
    try:
        status = channel_assets.get_sync_status(test_author)
    finally:
        with channel_assets._fetch_lock:
            channel_assets._fetching.discard(test_author)

    assert status["status"] == "checking"
    assert status["in_progress"] is True


def test_auto_retry_respects_cooldown(channel_assets, test_author, monkeypatch,
                                      real_try_fetch_if_missing):
    # Глобальная фикстура подменяет try_fetch_if_missing заглушкой, поэтому
    # здесь берём исходную функцию — её поведение и проверяем.
    try_fetch = real_try_fetch_if_missing
    channel_assets.update_sync_status(
        test_author, "error", error="net down",
        started_at=time.time(), finished_at=time.time(), success=False,
    )
    calls = []
    monkeypatch.setattr(channel_assets, "sync_channel", lambda a, url=None: calls.append(a))

    try_fetch(test_author)
    assert calls == []

    channel_assets.update_sync_status(
        test_author, "error", error="net down",
        finished_at=time.time() - channel_assets.AUTO_RETRY_COOLDOWN - 5, success=False,
    )
    try_fetch(test_author)
    assert calls == [test_author]


def test_concurrent_sync_is_skipped(channel_assets, test_author):
    with channel_assets._fetch_lock:
        channel_assets._fetching.add(test_author)
    try:
        assert channel_assets.sync_channel(test_author, "https://www.youtube.com/channel/UC_ok") is False
    finally:
        with channel_assets._fetch_lock:
            channel_assets._fetching.discard(test_author)


# --- HTTP API ---

def test_sync_status_endpoint_fields(client, test_author):
    res = client.get(f"/api/channel/{test_author}/sync-status")
    assert res.status_code == 200

    body = res.get_json()
    for field in ("status", "error", "started_at", "finished_at", "success",
                  "in_progress", "author", "channel_url"):
        assert field in body
    assert body["in_progress"] is False


def test_sync_endpoint_404_without_channel_url(client):
    res = client.post("/api/channel/__no_such_author__/sync")
    assert res.status_code == 404
    assert "error" in res.get_json()


def test_sync_status_reports_in_progress(client, channel_assets, test_author):
    with channel_assets._fetch_lock:
        channel_assets._fetching.add(test_author)
    try:
        body = client.get(f"/api/channel/{test_author}/sync-status").get_json()
    finally:
        with channel_assets._fetch_lock:
            channel_assets._fetching.discard(test_author)

    assert body["in_progress"] is True


@pytest.fixture
def local_author(app_module, channel_assets, tmp_path, monkeypatch):
    """Автор реально существующего локального видео с известным channel_url.

    META_DIR подменяется на временный каталог: эндпоинт синхронизации пишет
    статус в метаданные, и без подмены тест портил бы рабочие avas/meta/*.json.
    """
    app_module.build_video_map()
    author = next((v["author"] for v in app_module.VIDEO_MAP.values() if v.get("channel_url")), None)
    if not author:
        pytest.skip("в библиотеке нет видео с channel_url")
    monkeypatch.setattr(channel_assets, "META_DIR", str(tmp_path / "meta"))
    os.makedirs(channel_assets.META_DIR, exist_ok=True)
    return author


def test_sync_endpoint_starts_background_job(client, app_module, channel_assets, local_author, monkeypatch):
    calls = []
    monkeypatch.setattr(channel_assets, "sync_channel", lambda a, url=None: calls.append((a, url)))

    res = client.post(f"/api/channel/{local_author}/sync")
    for _ in range(20):
        if calls:
            break
        time.sleep(0.05)

    assert res.status_code == 200
    assert res.get_json()["status"] == "checking"
    assert len(calls) == 1
    assert calls[0][1]


def test_channel_page_renders_sync_panel(client, local_author):
    res = client.get("/channel/" + local_author)
    assert res.status_code == 200

    html = res.get_data(as_text=True)
    assert 'id="syncStatus"' in html
    assert 'id="syncButton"' in html
    assert "initialSyncStatus" in html
