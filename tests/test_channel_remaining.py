"""Кнопка «Скачать остальные видео»: разбор табов канала без обращения к сети."""
import pytest


def test_tab_urls_cover_videos_shorts_streams(app_module):
    urls = app_module.channel_tab_urls("https://www.youtube.com/channel/UC_x")

    assert urls == [
        "https://www.youtube.com/channel/UC_x/videos",
        "https://www.youtube.com/channel/UC_x/shorts",
        "https://www.youtube.com/channel/UC_x/streams",
    ]


@pytest.mark.parametrize("source", [
    "https://www.youtube.com/channel/UC_x/videos",
    "https://www.youtube.com/channel/UC_x/shorts",
    "https://www.youtube.com/channel/UC_x/featured",
    "https://www.youtube.com/channel/UC_x/",
])
def test_tab_urls_normalize_existing_suffix(app_module, source):
    """Ссылка из info.json может уже указывать на таб — дубля /videos/videos быть не должно."""
    assert app_module.channel_tab_urls(source)[0] == "https://www.youtube.com/channel/UC_x/videos"


def test_tab_urls_empty_for_blank(app_module):
    assert app_module.channel_tab_urls("") == []
    assert app_module.channel_tab_urls(None) == []


def test_tab_entry_is_not_a_video(app_module):
    """Корень канала отдаёт табы; они не должны попадать в список на скачивание."""
    tab = {"_type": "url", "ie_key": "YoutubeTab", "id": "UC_x",
           "url": "https://www.youtube.com/channel/UC_x/videos"}

    assert app_module.channel_entry_video_url(tab) is None


def test_video_entries_are_recognized(app_module):
    watch = {"id": "abc", "url": "https://www.youtube.com/watch?v=abc"}
    short = {"id": "sid", "url": "https://www.youtube.com/shorts/sid"}
    bare = {"id": "xyz", "url": "xyz"}

    assert app_module.channel_entry_video_url(watch).endswith("watch?v=abc")
    assert app_module.channel_entry_video_url(short).endswith("/shorts/sid")
    # Плоское извлечение иногда отдаёт вместо ссылки один id.
    assert app_module.channel_entry_video_url(bare) == "https://www.youtube.com/watch?v=xyz"


def test_nested_playlists_are_flattened(app_module):
    info = {
        "_type": "playlist",
        "entries": [
            {"_type": "playlist", "entries": [{"id": "a", "url": "https://www.youtube.com/watch?v=a"}]},
            {"id": "b", "url": "https://www.youtube.com/shorts/b"},
            None,
            {"_type": "url", "ie_key": "YoutubeTab", "id": "UC_x", "url": "https://www.youtube.com/channel/UC_x/shorts"},
        ],
    }

    assert [e["id"] for e in app_module.iter_channel_videos(info)] == ["a", "b"]


@pytest.fixture
def stub_channel(app_module, monkeypatch):
    """Канал с одним локальным видео и подменённым yt-dlp."""
    monkeypatch.setattr(app_module, "VIDEO_MAP", {
        "local1": {"author": "Chan", "channel_url": "https://www.youtube.com/channel/UC_x"},
    }, raising=False)
    monkeypatch.setattr(app_module, "build_video_map", lambda: 1)

    class FakeYDL:
        tabs = {}

        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            result = FakeYDL.tabs.get(url)
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(app_module.yt_dlp, "YoutubeDL", FakeYDL)
    return FakeYDL


def _video(vid):
    return {"id": vid, "title": vid, "url": f"https://www.youtube.com/watch?v={vid}"}


def test_remaining_keeps_authcheck_and_allows_solver(client, stub_channel):
    """Настройки авторизации не должны затирать youtubetab:skip=authcheck.

    Без authcheck канал не извлекается, если cookies остались от другого
    аккаунта, а без remote_components yt-dlp не решает JS-челлендж.
    """
    seen = []
    original_init = stub_channel.__init__

    def spy_init(self, options):
        seen.append(options)
        original_init(self, options)

    stub_channel.__init__ = spy_init
    stub_channel.tabs = {
        "https://www.youtube.com/channel/UC_x/videos": {"entries": [_video("new1")]},
    }

    client.post("/api/channel/Chan/remaining")

    assert seen, "yt-dlp не вызывался"
    opts = seen[0]
    assert opts["extractor_args"]["youtubetab"]["skip"] == ["authcheck"]
    assert "ejs:github" in (opts.get("remote_components") or [])


def test_remaining_merges_tabs_and_skips_local(client, stub_channel):
    stub_channel.tabs = {
        "https://www.youtube.com/channel/UC_x/videos": {"entries": [_video("local1"), _video("new1")]},
        "https://www.youtube.com/channel/UC_x/shorts": {"entries": [{"id": "s1", "title": "s", "url": "https://www.youtube.com/shorts/s1"}]},
        "https://www.youtube.com/channel/UC_x/streams": {"entries": [_video("new1")]},
    }

    body = client.post("/api/channel/Chan/remaining").get_json()

    # local1 уже скачан, new1 не должен продублироваться из /streams.
    assert [v["id"] for v in body["videos"]] == ["new1", "s1"]
    assert body["count"] == 2


def test_remaining_survives_missing_tab(client, stub_channel):
    """Канал без трансляций не должен ломать список видео."""
    stub_channel.tabs = {
        "https://www.youtube.com/channel/UC_x/videos": {"entries": [_video("new1")]},
        "https://www.youtube.com/channel/UC_x/shorts": RuntimeError("This channel does not have a shorts tab"),
        "https://www.youtube.com/channel/UC_x/streams": RuntimeError("This channel does not have a live tab"),
    }

    res = client.post("/api/channel/Chan/remaining")

    assert res.status_code == 200
    assert [v["id"] for v in res.get_json()["videos"]] == ["new1"]


def test_remaining_reports_error_when_nothing_collected(client, stub_channel):
    stub_channel.tabs = {
        url: RuntimeError("Sign in to confirm you're not a bot")
        for url in [
            "https://www.youtube.com/channel/UC_x/videos",
            "https://www.youtube.com/channel/UC_x/shorts",
            "https://www.youtube.com/channel/UC_x/streams",
        ]
    }

    res = client.post("/api/channel/Chan/remaining")

    assert res.status_code == 502
    assert "bot" in res.get_json()["error"]


def test_remaining_404_without_channel_url(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "VIDEO_MAP", {}, raising=False)
    monkeypatch.setattr(app_module, "build_video_map", lambda: 0)

    assert client.post("/api/channel/Chan/remaining").status_code == 404


def test_remaining_uses_in_playlist_flat_mode(client, stub_channel):
    """extract_flat=True отдавал сами табы вместо видео."""
    stub_channel.tabs = {
        "https://www.youtube.com/channel/UC_x/videos": {"entries": [_video("new1")]},
        "https://www.youtube.com/channel/UC_x/shorts": {"entries": []},
        "https://www.youtube.com/channel/UC_x/streams": {"entries": []},
    }
    seen = []
    original_init = stub_channel.__init__

    def spy_init(self, options):
        seen.append(options.get("extract_flat"))
        original_init(self, options)

    stub_channel.__init__ = spy_init
    try:
        client.post("/api/channel/Chan/remaining")
    finally:
        stub_channel.__init__ = original_init

    assert seen and set(seen) == {"in_playlist"}


def test_remaining_exposes_duration(client, stub_channel):
    """Модалке выбора нужна длительность, чтобы показать её рядом с названием."""
    stub_channel.tabs = {
        "https://www.youtube.com/channel/UC_x/videos": {
            "entries": [dict(_video("new1"), duration=95.4)]
        },
        "https://www.youtube.com/channel/UC_x/shorts": {"entries": []},
        "https://www.youtube.com/channel/UC_x/streams": {"entries": []},
    }

    body = client.post("/api/channel/Chan/remaining").get_json()

    assert body["videos"][0]["duration"] == pytest.approx(95.4)


@pytest.mark.parametrize("raw", [None, "", "неизвестно", {}])
def test_remaining_duration_is_none_when_unusable(client, stub_channel, raw):
    """Пустая или нечисловая длительность не должна ломать ответ."""
    entry = dict(_video("new1"))
    entry["duration"] = raw
    stub_channel.tabs = {
        "https://www.youtube.com/channel/UC_x/videos": {"entries": [entry]},
        "https://www.youtube.com/channel/UC_x/shorts": {"entries": []},
        "https://www.youtube.com/channel/UC_x/streams": {"entries": []},
    }

    res = client.post("/api/channel/Chan/remaining")

    assert res.status_code == 200
    assert res.get_json()["videos"][0]["duration"] is None


def test_network_error_on_tab_is_retried(client, stub_channel, monkeypatch, app_module):
    """Обрыв сети на табе не должен молча терять все его видео.

    В логе пользователя таб канала падал с SSL EOF, и «остальные видео»
    собирались только из уцелевших табов — часть видео просто исчезала.
    """
    monkeypatch.setattr(app_module, "STREAM_RETRY_DELAY", 0, raising=False)
    calls = {"n": 0}
    videos_url = "https://www.youtube.com/channel/UC_x/videos"
    good = {"entries": [_video("new1")]}

    class Flaky(stub_channel):
        def extract_info(self, url, download=False):
            if url == videos_url:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise Exception(
                        "Unable to download API page: [SSL: "
                        "UNEXPECTED_EOF_WHILE_READING] EOF occurred")
                return good
            return {"entries": []}

    monkeypatch.setattr(app_module.yt_dlp, "YoutubeDL", Flaky)

    body = client.post("/api/channel/Chan/remaining").get_json()

    assert calls["n"] >= 2, "повтора запроса таба не было"
    assert [v["id"] for v in body["videos"]] == ["new1"], body


def test_missing_tab_is_not_retried(client, stub_channel, monkeypatch, app_module):
    """Отсутствующий таб (нет трансляций) повторять не нужно."""
    monkeypatch.setattr(app_module, "STREAM_RETRY_DELAY", 0, raising=False)
    calls = {"n": 0}
    streams_url = "https://www.youtube.com/channel/UC_x/streams"

    class NoStreams(stub_channel):
        def extract_info(self, url, download=False):
            if url == streams_url:
                calls["n"] += 1
                raise Exception("This channel does not have a streams tab")
            return {"entries": []}

    monkeypatch.setattr(app_module.yt_dlp, "YoutubeDL", NoStreams)

    client.post("/api/channel/Chan/remaining")

    assert calls["n"] == 1, "отсутствующий таб не нужно запрашивать повторно"
