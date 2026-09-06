"""safe_name и is_shorts_video: имена файлов и признак Shorts."""
import os

import pytest

from utils import safe_name, is_shorts_video


@pytest.mark.parametrize("author", ["..", ".", "...", "   ", "", None])
def test_degenerate_names_never_collapse_to_empty(author):
    """Пустое имя писало метаданные разных каналов в один файл META_DIR/.json."""
    assert safe_name(author) == "unknown"


@pytest.mark.parametrize("name", ["CON", "con", "NUL", "COM1", "LPT9", "PRN", "AUX", "con.txt"])
def test_windows_device_names_are_escaped(name):
    """os.path.abspath('CON') даёт '\\\\.\\CON' — путь уходит за пределы каталога."""
    result = safe_name(name)

    assert result.split('.')[0].upper() not in {"CON", "NUL", "COM1", "LPT9", "PRN", "AUX"}
    assert result.startswith("_")


@pytest.mark.parametrize("author", ["..", "   ", "CON", "NUL"])
def test_meta_path_stays_inside_directory(channel_assets, author, tmp_path, monkeypatch):
    monkeypatch.setattr(channel_assets, "META_DIR", str(tmp_path))

    path = os.path.abspath(channel_assets._meta_path(author))

    assert path.startswith(os.path.abspath(str(tmp_path)) + os.sep)


def test_distinct_degenerate_authors_do_not_share_a_file(channel_assets, tmp_path, monkeypatch):
    """'..' и '.' раньше давали один и тот же путь."""
    monkeypatch.setattr(channel_assets, "META_DIR", str(tmp_path))

    # Оба сводятся к 'unknown', но важно, что это валидное имя внутри каталога,
    # а не пустая строка, дающая скрытый файл '.json'.
    for author in ("..", "."):
        assert os.path.basename(channel_assets._meta_path(author)) == "unknown.json"


def test_output_path_stays_inside_base(tmp_path):
    from download_lib import get_output_path

    path = os.path.abspath(get_output_path(str(tmp_path), "..", "vid1", "t"))

    assert path.startswith(os.path.abspath(str(tmp_path)) + os.sep)


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_path_separators_are_replaced(separator):
    assert separator not in safe_name(f"a{separator}b")


def test_control_characters_are_replaced():
    assert "\n" not in safe_name("a\nb")
    assert "\x00" not in safe_name("a\x00b")


def test_normal_names_are_untouched():
    assert safe_name("Avocado Animations") == "Avocado Animations"
    assert safe_name("ANATA CARS") == "ANATA CARS"


# --- is_shorts_video ---

def test_vertical_video_is_short():
    assert is_shorts_video({"height": 1920, "width": 1080})


def test_short_duration_without_dimensions_is_short():
    """Ветка по длительности была недостижима: h > w уже возвращало True выше.

    Тот же порядок проверок используется в Android-клиенте (Library.kt).
    """
    assert is_shorts_video({"duration": 30})
    assert is_shorts_video({"duration": 30, "height": 0, "width": 0})


def test_landscape_short_duration_is_not_short():
    assert not is_shorts_video({"duration": 30, "height": 1080, "width": 1920})


def test_long_vertical_video_is_still_short():
    assert is_shorts_video({"duration": 600, "height": 1920, "width": 1080})


@pytest.mark.parametrize("info", [
    {"title": "Смешное видео #shorts"},
    {"webpage_url": "https://www.youtube.com/shorts/abc"},
])
def test_markers_detect_shorts(info):
    assert is_shorts_video(info)


@pytest.mark.parametrize("info", [{}, None, "not a dict", {"duration": 0}, {"duration": 3600}])
def test_non_shorts_inputs(info):
    assert not is_shorts_video(info)
