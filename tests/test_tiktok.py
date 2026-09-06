"""TikTok: ссылки, загрузка и оставшиеся видео профиля.

Сеть не используется: yt-dlp заменяется предсказуемыми заглушками.
"""
import json

import app as app_module
import channel_assets
import download_lib
import pytest
from downloader import is_playlist_url


@pytest.mark.parametrize("url", [
    "https://www.tiktok.com/@creator/video/7461234567890123456",
    "https://m.tiktok.com/v/7461234567890123456.html",
    "https://vm.tiktok.com/ZM123AbCd/",
    "https://vt.tiktok.com/ZM123AbCd/",
    "https://www.tiktok.com/@creator",
])
def test_tiktok_url_is_supported(url):
    assert app_module.is_supported_download_url(url)


@pytest.mark.parametrize("url", [
    "ftp://www.tiktok.com/@creator/video/7461234567890123456",
    "https://not-tiktok.com/@creator/video/7461234567890123456",
    "https://www.tiktok.com/",
    "просто текст",
])
def test_invalid_tiktok_url_is_rejected(url):
    assert not app_module.is_supported_download_url(url)


def test_tiktok_profile_is_not_a_playlist():
    """Профиль — отдельный тип: надо развернуть в очередь, не включать noplaylist."""
    assert not is_playlist_url("https://www.tiktok.com/@creator")


def test_tiktok_video_id_is_not_truncated():
    value = "7461234567890123456"
    assert download_lib.get_video_id(f"https://www.tiktok.com/@creator/video/{value}") == value


def test_tiktok_is_short_even_when_metadata_has_no_dimensions():
    assert download_lib.is_shorts_video({
        "extractor_key": "TikTok",
        "id": "7461234567890123456",
    })


def test_tiktok_channel_url_comes_from_uploader_url():
    info = {
        "uploader_url": "https://www.tiktok.com/@creator",
        "uploader_id": "creator",
    }
    assert channel_assets.get_channel_url(info) == "https://www.tiktok.com/@creator"


class _TikTokProfileYDL:
    calls = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        type(self).calls.append((url, download, self.opts))
        return {
            "id": "creator",
            "entries": [
                {"id": "7461234567890123456", "url": "https://www.tiktok.com/@creator/video/7461234567890123456", "title": "Первый"},
                {"id": "7461234567890123457", "webpage_url": "https://www.tiktok.com/@creator/video/7461234567890123457", "title": "Второй"},
            ],
        }


def test_tiktok_channel_assets_have_no_youtube_args():
    opts = channel_assets._ydl_opts(True, "https://www.tiktok.com/@creator")
    assert "youtubetab" not in opts.get("extractor_args", {})


def test_profile_tiktok_expands_into_video_urls(monkeypatch):
    monkeypatch.setattr(app_module.yt_dlp, "YoutubeDL", _TikTokProfileYDL)
    _TikTokProfileYDL.calls.clear()

    urls = app_module.expand_download_urls("https://www.tiktok.com/@creator")

    assert urls == [
        "https://www.tiktok.com/@creator/video/7461234567890123456",
        "https://www.tiktok.com/@creator/video/7461234567890123457",
    ]
    opts = _TikTokProfileYDL.calls[0][2]
    assert opts["extract_flat"] == "in_playlist"
    assert "noplaylist" not in opts
    assert "youtubetab" not in opts.get("extractor_args", {})


def test_tiktok_remaining_uses_profile_once(client, app_module, monkeypatch):
    """У TikTok нет вкладок /videos, /shorts, /streams как у YouTube."""
    monkeypatch.setattr(app_module, "VIDEO_MAP", {
        "local": {
            "author": "TikToker", "channel_url": "https://www.tiktok.com/@creator",
        },
    })
    monkeypatch.setattr(app_module, "build_video_map", lambda: None)
    monkeypatch.setattr(app_module.yt_dlp, "YoutubeDL", _TikTokProfileYDL)
    _TikTokProfileYDL.calls.clear()

    res = client.post("/api/channel/TikToker/remaining")

    assert res.status_code == 200
    body = res.get_json()
    assert [v["id"] for v in body["videos"]] == [
        "7461234567890123456", "7461234567890123457",
    ]
    # Только обращения к этому профилю: calls — атрибут класса, общий на весь
    # прогон, и заглушка стоит на app_module.yt_dlp, то есть видна фоновым
    # потокам очереди. Чужая YouTube-ссылка, попавшая сюда, ломала проверку.
    ours = [c for c in _TikTokProfileYDL.calls if "tiktok.com" in c[0]]
    assert [_call[0] for _call in ours] == [
        "https://www.tiktok.com/@creator",
    ]
    assert "youtubetab" not in ours[0][2].get("extractor_args", {})


def test_queue_rejects_unsupported_url(client):
    res = client.post("/api/queue/add", json={"urls": ["https://example.org/video"]})

    assert res.status_code == 400
    assert "YouTube" in res.get_json()["error"]
    assert "TikTok" in res.get_json()["error"]


def test_tiktok_profile_queue_adds_each_video(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "expand_download_urls", lambda url: [
        "https://www.tiktok.com/@creator/video/7461234567890123456",
        "https://www.tiktok.com/@creator/video/7461234567890123457",
    ])
    monkeypatch.setattr(app_module, "ensure_queue_worker", lambda: None)

    res = client.post("/api/queue/add", json={
        "urls": ["https://www.tiktok.com/@creator"], "title": "TikTok",
    })

    assert res.status_code == 200
    task = app_module.queue_tasks[-1]
    assert task.urls == [
        "https://www.tiktok.com/@creator/video/7461234567890123456",
        "https://www.tiktok.com/@creator/video/7461234567890123457",
    ]


def test_tiktok_metadata_is_kept_in_catalog(tmp_path, app_module, monkeypatch):
    root = tmp_path / "videos"
    folder = root / "TikToker" / "7461234567890123456 #shorts"
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"video")
    (folder / "info.json").write_text(json.dumps({
        "id": "7461234567890123456",
        "title": "TikTok ролик",
        "uploader": "TikToker",
        "uploader_url": "https://www.tiktok.com/@creator",
        "extractor_key": "TikTok",
        "webpage_url": "https://www.tiktok.com/@creator/video/7461234567890123456",
    }), encoding="utf-8")
    monkeypatch.setattr(app_module, "BASE_VIDEO_DIR", str(root))
    app_module.build_video_map()

    item = app_module.VIDEO_MAP["7461234567890123456"]
    assert item["source"] == "tiktok"
    assert item["is_short"] is True
    assert item["channel_url"] == "https://www.tiktok.com/@creator"
    assert app_module._video_item("7461234567890123456", item)["source"] == "tiktok"

    response = app_module.app.test_client().get("/api/video/7461234567890123456")
    assert response.status_code == 200
    assert response.get_json()["source"] == "tiktok"


class _TikTokDownloadYDL:
    seen_options = []

    def __init__(self, opts):
        self.opts = opts
        type(self).seen_options.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        info = {
            "id": "7461234567890123456", "title": "Ролик", "uploader": "TikToker",
            "uploader_url": "https://www.tiktok.com/@creator", "extractor_key": "TikTok",
            "webpage_url": url,
            "formats": [{
                "format_id": "mp4", "vcodec": "h264", "acodec": "aac",
                "url": "https://v16.tiktokcdn.com/video.mp4",
            }],
        }
        if download:
            temp = self.opts["outtmpl"].rsplit("/", 1)[0].rsplit("\\", 1)[0]
            with open(temp + "/video.mp4", "wb") as fh:
                fh.write(b"video")
            with open(temp + "/video.info.json", "w", encoding="utf-8") as fh:
                json.dump(info, fh)
        return info


@pytest.fixture
def no_audio_langs(monkeypatch):
    """Отключает выбор языковых дорожек на время проверки селектора.

    Настроенный язык дорожки добавляет к селектору вариант с `language^=`, и
    сравнение с точной строкой ломалось от настроек пользователя, а не от
    дефекта. Здесь проверяется именно разница между TikTok и YouTube.
    """
    monkeypatch.setattr(download_lib, "get_download_prefs",
                        lambda: {"audio_langs": []})


@pytest.mark.parametrize("chosen, expected", [
    ("bestvideo[height<=720]+bestaudio/best", "best"),
    ("bestaudio/best", "bestaudio/best"),
    (None, "best"),
])
def test_tiktok_format_selector_is_single_stream(tmp_path, no_audio_langs,
                                                chosen, expected):
    """У TikTok нет отдельных потоков: YouTube-селектор давал отказ формата."""
    opts = download_lib.get_ydl_opts(
        chosen, "mp4", lambda d: None, str(tmp_path / "tmp"),
        "https://www.tiktok.com/@creator/video/7461234567890123456",
    )
    assert opts["format"] == expected


def test_youtube_format_selector_is_unchanged(tmp_path, no_audio_langs):
    chosen = "bestvideo[height<=720]+bestaudio/best"
    opts = download_lib.get_ydl_opts(
        chosen, "mp4", lambda d: None, str(tmp_path / "tmp2"),
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    assert opts["format"] == chosen


def test_tiktok_download_uses_generic_yt_dlp_options(tmp_path, monkeypatch):
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _TikTokDownloadYDL)
    monkeypatch.setattr(download_lib, "get_po_args", lambda: {"youtube": {"player_client": ["web"]}})
    monkeypatch.setattr(download_lib, "apply_po_args", lambda options, args: options.update({"extractor_args": args}))
    _TikTokDownloadYDL.seen_options.clear()

    url = "https://www.tiktok.com/@creator/video/7461234567890123456"
    result = download_lib.download_single_sync([url], None, lambda *_: None)

    assert result.succeeded == 1
    assert (tmp_path / "TikToker" / "7461234567890123456 #shorts" / "video.mp4").exists()

    # Смотрим только на скачивания этого теста: seen_options — атрибут класса,
    # общий на весь прогон. test_queue_worker запускает process_queue в
    # daemon-потоке и не дожидается его завершения, поэтому такой поток может
    # дописать сюда опции своей YouTube-загрузки уже после clear(). Проверка
    # падала примерно в одном полном прогоне из трёх, причём на файле, который
    # сам по себе всегда зелёный.
    ours = [
        opts for opts in _TikTokDownloadYDL.seen_options
        if str(tmp_path) in str(opts.get("outtmpl", ""))
    ]
    assert ours, "опции скачивания не записались: проверять нечего"
    assert not any("youtube" in opts.get("extractor_args", {}) for opts in ours)
