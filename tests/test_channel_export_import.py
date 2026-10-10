"""Тесты для экспорта и импорта каналов."""
import os
import io
import tarfile
import pytest


@pytest.fixture
def channel_with_video(app_module, monkeypatch, tmp_path):
    """Создаёт тестовый канал с одним видео на диске."""
    video_dir = tmp_path / "videos"
    author_dir = video_dir / "TestChan"
    author_dir.mkdir(parents=True, exist_ok=True)

    video_folder = author_dir / "vid1"
    video_folder.mkdir()
    (video_folder / "video.mp4").write_bytes(b"\x00\x00\x00\x20ftypmp42")
    (video_folder / "info.json").write_text('{"id":"vid1","title":"Test"}')
    (video_folder / "thumbnail.jpg").write_bytes(b"\xff\xd8\xff\xe0thumbnail")

    monkeypatch.setattr(app_module, "BASE_VIDEO_DIR", str(video_dir))
    monkeypatch.setattr(app_module, "VIDEO_MAP", {
        "vid1": {"author": "TestChan", "folder": "vid1", "filename": "video.mp4"},
    }, raising=False)
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {}, raising=False)
    monkeypatch.setattr(app_module, "build_video_map", lambda: 1, raising=False)
    monkeypatch.setattr(app_module, "build_user_video_map", lambda: 1, raising=False)
    return {"video_dir": str(video_dir), "author": "TestChan"}


def test_export_creates_tarball(client, channel_with_video):
    """Экспорт канала возвращает tar.gz с содержимым канала."""
    res = client.post("/api/channel/TestChan/export")
    assert res.status_code == 200
    assert res.mimetype == 'application/gzip'


def test_export_404_for_missing_channel(client, app_module, monkeypatch, tmp_path):
    """Экспорт несуществующего канала возвращает 404."""
    video_dir = tmp_path / "videos"
    monkeypatch.setattr(app_module, "BASE_VIDEO_DIR", str(video_dir))
    res = client.post("/api/channel/Nonexistent/export")
    assert res.status_code == 404


def test_export_contains_channel_files(client, channel_with_video):
    """Экспорт включает видео, info.json и миниатюру из папки канала."""
    res = client.post("/api/channel/TestChan/export")
    assert res.status_code == 200

    data = res.data
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
        names = tar.getnames()

    assert any(n.endswith("vid1/video.mp4") for n in names) or \
           any("video.mp4" in n for n in names)
    assert any(n.endswith("vid1/info.json") for n in names) or \
           any("info.json" in n for n in names)


def test_export_renames_webm_to_mp4_after_reencode(client, app_module, monkeypatch, tmp_path):
    """Экспорт с перекодировкой переименовывает .webm в .mp4: контейнер изменился,
    расширение должно соответствовать содержимому."""
    video_dir = tmp_path / "videos"
    author_dir = video_dir / "TestChan"
    author_dir.mkdir(parents=True, exist_ok=True)

    video_folder = author_dir / "vid1"
    video_folder.mkdir()
    (video_folder / "video.webm").write_bytes(b"fake webm content")
    (video_folder / "info.json").write_text('{"id":"vid1","title":"Test"}')

    monkeypatch.setattr(app_module, "BASE_VIDEO_DIR", str(video_dir))
    monkeypatch.setattr(app_module, "VIDEO_MAP", {}, raising=False)
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {}, raising=False)
    monkeypatch.setattr(app_module, "build_video_map", lambda: 0, raising=False)
    monkeypatch.setattr(app_module, "build_user_video_map", lambda: 0, raising=False)

    # Мокаем subprocess.run: ffmpeg -version проходит, re-encode создаёт .tmp.mp4.
    import subprocess as sp
    def mock_run(cmd, **kwargs):
        if cmd[1] == '-version':
            return sp.CompletedProcess(cmd, 0)
        if '-c:v' in cmd:
            out_path = cmd[-1]
            with open(out_path, 'wb') as f:
                f.write(b"\x00\x00\x00\x20ftypmp42")
            return sp.CompletedProcess(cmd, 0)
        return sp.CompletedProcess(cmd, 0)
    monkeypatch.setattr(app_module.subprocess, "run", mock_run)

    res = client.post("/api/channel/TestChan/export")
    assert res.status_code == 200

    with tarfile.open(fileobj=io.BytesIO(res.data), mode='r:gz') as tar:
        names = tar.getnames()

    # В архиве не должно остаться .webm — перекодированный файл стал .mp4.
    assert not any(n.endswith(".webm") for n in names)
    assert any(n.endswith("video.mp4") for n in names)


def test_export_preserves_mp4_filename_after_reencode(client, app_module, monkeypatch, tmp_path):
    """Экспорт .mp4 с перекодировкой сохраняет имя файла (только перезаписывает)."""
    video_dir = tmp_path / "videos"
    author_dir = video_dir / "TestChan"
    author_dir.mkdir(parents=True, exist_ok=True)

    video_folder = author_dir / "vid1"
    video_folder.mkdir()
    (video_folder / "clip.mp4").write_bytes(b"fake mp4 content")
    (video_folder / "info.json").write_text('{"id":"vid1","title":"Test"}')

    monkeypatch.setattr(app_module, "BASE_VIDEO_DIR", str(video_dir))
    monkeypatch.setattr(app_module, "VIDEO_MAP", {}, raising=False)
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {}, raising=False)
    monkeypatch.setattr(app_module, "build_video_map", lambda: 0, raising=False)
    monkeypatch.setattr(app_module, "build_user_video_map", lambda: 0, raising=False)

    import subprocess as sp
    def mock_run(cmd, **kwargs):
        if cmd[1] == '-version':
            return sp.CompletedProcess(cmd, 0)
        if '-c:v' in cmd:
            out_path = cmd[-1]
            with open(out_path, 'wb') as f:
                f.write(b"\x00\x00\x00\x20ftypmp42")
            return sp.CompletedProcess(cmd, 0)
        return sp.CompletedProcess(cmd, 0)
    monkeypatch.setattr(app_module.subprocess, "run", mock_run)

    res = client.post("/api/channel/TestChan/export")
    assert res.status_code == 200

    with tarfile.open(fileobj=io.BytesIO(res.data), mode='r:gz') as tar:
        names = tar.getnames()

    assert any(n.endswith("clip.mp4") for n in names)


def test_import_extracts_channel_archive(client, app_module, monkeypatch, tmp_path):
    """Импорт tar.gz создаёт папку канала с видео."""
    video_dir = tmp_path / "videos"
    monkeypatch.setattr(app_module, "BASE_VIDEO_DIR", str(video_dir))
    monkeypatch.setattr(app_module, "build_video_map", lambda: 1, raising=False)
    monkeypatch.setattr(app_module, "build_user_video_map", lambda: 1, raising=False)

    # Создаём архив с тестовым каналом
    archive_buf = io.BytesIO()
    with tarfile.open(fileobj=archive_buf, mode='w:gz') as tar:
        chan_dir = tarfile.TarInfo("ImportedChan")
        chan_dir.type = tarfile.DIRTYPE
        tar.addfile(chan_dir)

        vid_dir = tarfile.TarInfo("ImportedChan/vid1")
        vid_dir.type = tarfile.DIRTYPE
        tar.addfile(vid_dir)

        info = tarfile.TarInfo("ImportedChan/vid1/info.json")
        info_content = b'{"id":"vid1","title":"Imported"}'
        info.size = len(info_content)
        tar.addfile(info, io.BytesIO(info_content))

        video = tarfile.TarInfo("ImportedChan/vid1/video.mp4")
        video_content = b"\x00\x00\x00\x20ftypmp42"
        video.size = len(video_content)
        tar.addfile(video, io.BytesIO(video_content))

    archive_buf.seek(0)

    res = client.post("/api/channel/import", data={
        "archive": (archive_buf, "test.tar.gz"),
    }, content_type='multipart/form-data')

    assert res.status_code == 200
    body = res.get_json()
    assert body["imported"] >= 1
    assert "ImportedChan" in body["channels"]

    chan_path = video_dir / "ImportedChan"
    assert chan_path.exists()
    assert (chan_path / "vid1" / "info.json").exists()
    assert (chan_path / "vid1" / "video.mp4").exists()


def test_import_returns_400_without_file(client):
    """Импорт без файла возвращает 400."""
    res = client.post("/api/channel/import")
    assert res.status_code == 400


def test_import_skips_invalid_archive(client, app_module, monkeypatch, tmp_path):
    """Импорт не-tar.gz файла возвращает ошибку."""
    video_dir = tmp_path / "videos"
    monkeypatch.setattr(app_module, "BASE_VIDEO_DIR", str(video_dir))

    res = client.post("/api/channel/import", data={
        "archive": (io.BytesIO(b"not gzip"), "bad.tar.gz"),
    }, content_type='multipart/form-data')

    assert res.status_code == 400
