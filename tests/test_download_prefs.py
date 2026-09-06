"""Тесты настроек загрузки: языки аудиодорожек и субтитров.

До этого раздела язык аудио выбрать было нельзя вовсе (yt-dlp брал дорожку по
умолчанию, и озвучка приходила на языке оригинала), а субтитры качались только
вручную с одной страницы видео, по одному языку, кнопкой «Скачать с YouTube».

Главное, что проверяют эти тесты: настройки доходят до опций yt-dlp. Раздел в
интерфейсе, который сохраняет значения в config.json, но не влияет на загрузку,
выглядит рабочим и молча ничего не делает.
"""
import json
import os

import pytest

import download_lib
import download_prefs


@pytest.fixture
def prefs_config(tmp_path, monkeypatch):
    """Уводит config.json во временный файл.

    Без этого тесты писали бы в настоящий конфиг пользователя: раздел хранит
    языки рядом с путями к библиотеке.
    """
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"video_dir": "videos"}), encoding="utf-8")
    monkeypatch.setattr(download_prefs, "CONFIG_FILE", str(cfg))
    return cfg


# ================= Значения по умолчанию =================

def test_defaults_keep_current_behaviour(prefs_config):
    """Пустой конфиг не должен менять то, как работала загрузка раньше.

    Язык аудио не задан (берётся дорожка по умолчанию), субтитры выключены:
    иначе обновление программы начало бы качать лишние файлы без спроса.
    """
    prefs = download_prefs.get_prefs()
    assert prefs["audio_langs"] == []
    assert prefs["subtitles_enabled"] is False


def test_defaults_offer_russian_subtitles(prefs_config):
    """Языки субтитров по умолчанию заполнены: включить — один клик."""
    assert download_prefs.get_prefs()["subtitle_langs"] == ["ru"]
    assert download_prefs.get_prefs()["subtitles_auto"] is True


def test_languages_catalog_has_russian_and_english():
    """Список языков — общий для настроек и подписей дорожек."""
    codes = [code for code, _ in download_prefs.LANGUAGES]
    assert "ru" in codes and "en" in codes
    assert len(codes) == len(set(codes)), "повторы в списке языков"


# ================= Чтение и запись =================

def test_save_and_get_roundtrip(prefs_config):
    download_prefs.save_prefs({"audio_langs": ["en"], "subtitles_enabled": True,
                               "subtitle_langs": ["ru", "en"], "subtitles_auto": False})
    prefs = download_prefs.get_prefs()
    assert prefs["audio_langs"] == ["en"]
    assert prefs["subtitles_enabled"] is True
    assert prefs["subtitle_langs"] == ["ru", "en"]
    assert prefs["subtitles_auto"] is False


def test_save_keeps_other_config_keys(prefs_config):
    """Пути к библиотеке лежат в том же файле: затирать их нельзя."""
    download_prefs.save_prefs({"audio_langs": ["ru"]})
    cfg = json.loads(prefs_config.read_text(encoding="utf-8"))
    assert cfg["video_dir"] == "videos"
    assert cfg["downloads"]["audio_langs"] == ["ru"]


def test_save_ignores_unknown_keys(prefs_config):
    """Мусор из запроса не должен попадать в конфиг."""
    download_prefs.save_prefs({"audio_langs": ["ru"], "evil": "x"})
    cfg = json.loads(prefs_config.read_text(encoding="utf-8"))
    assert "evil" not in cfg["downloads"]


def test_langs_accept_comma_separated_string(prefs_config):
    """Поле может прислать строку: «ru, en» — это тоже два языка."""
    download_prefs.save_prefs({"subtitle_langs": "ru, en ,, ru"})
    assert download_prefs.get_prefs()["subtitle_langs"] == ["ru", "en"]


def test_langs_reject_broken_codes(prefs_config):
    """Код языка уходит в имя файла субтитров и в фильтр формата yt-dlp.

    Строка вида '../../evil' раньше увела бы запись за пределы папки, а пробел
    внутри фильтра ломает разбор селектора формата.
    """
    result = download_prefs.save_prefs({"subtitle_langs": ["../../evil"]})
    assert isinstance(result, dict) and result.get("error"), "битый код языка принят"
    assert download_prefs.get_prefs()["subtitle_langs"] == ["ru"], "конфиг изменён"


def test_langs_accept_regional_codes(prefs_config):
    """pt-BR и zh-Hans — обычные коды YouTube, отвергать их нельзя."""
    download_prefs.save_prefs({"subtitle_langs": ["pt-BR", "zh-Hans"]})
    assert download_prefs.get_prefs()["subtitle_langs"] == ["pt-BR", "zh-Hans"]


def test_every_module_with_config_file_is_protected():
    """Ни один модуль не должен писать в настоящий config.json во время прогона.

    Изоляция была только в фикстурах отдельных файлов тестов. Любой другой тест,
    дошедший до сохранения настроек, писал в рабочий config.json пользователя —
    так в него попали разделы «downloads» и «youtube_auth» из тестовых данных.
    Проверяем автоматически, а не списком: новый модуль со своей копией пути
    иначе снова остался бы без защиты.
    """
    import glob
    import importlib
    import io
    import re

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    real = os.path.join(root, "config.json")
    unprotected = []
    for path in glob.glob(os.path.join(root, "*.py")):
        source = io.open(path, encoding="utf-8", errors="replace").read()
        if not re.search(r"^CONFIG_FILE\s*=", source, re.M):
            continue
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue                      # скрипт-утилита, к вебу отношения не имеет
        value = getattr(mod, "CONFIG_FILE", None)
        if value and os.path.abspath(value) == os.path.abspath(real):
            unprotected.append(name)

    assert not unprotected, f"пишут в настоящий config.json: {unprotected}"


def test_broken_config_falls_back_to_defaults(tmp_path, monkeypatch):
    """Повреждённый конфиг не должен ронять загрузку."""
    cfg = tmp_path / "config.json"
    cfg.write_text("{не json", encoding="utf-8")
    monkeypatch.setattr(download_prefs, "CONFIG_FILE", str(cfg))
    assert download_prefs.get_prefs()["subtitles_enabled"] is False


def test_wrong_types_in_config_do_not_crash(tmp_path, monkeypatch):
    """Правка руками может положить в ключ что угодно."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"downloads": {"audio_langs": "ru", "subtitles_enabled": 1,
                                             "subtitle_langs": 5}}), encoding="utf-8")
    monkeypatch.setattr(download_prefs, "CONFIG_FILE", str(cfg))
    prefs = download_prefs.get_prefs()
    assert prefs["audio_langs"] == ["ru"]
    assert prefs["subtitles_enabled"] is True
    assert prefs["subtitle_langs"] == ["ru"], "нечитаемое значение не заменено по умолчанию"


# ================= Селектор языка аудиодорожки =================

def test_audio_selector_untouched_without_langs():
    assert download_prefs.audio_format_selector("bestvideo+bestaudio/best", []) == \
        "bestvideo+bestaudio/best"


def test_audio_selector_adds_language_filter():
    """Фильтр вешается на аудиочасть: видео у дорожек языка не имеет."""
    out = download_prefs.audio_format_selector("bestvideo+bestaudio/best", ["ru"])
    assert out.startswith("bestvideo+bestaudio[language^=ru]/")


def test_audio_selector_keeps_original_as_fallback():
    """У большинства видео одна дорожка без языка: без запаса ничего не скачается."""
    out = download_prefs.audio_format_selector("bestvideo+bestaudio/best", ["ru"])
    assert out.endswith("bestvideo+bestaudio/best")


def test_audio_selector_respects_language_order():
    """Порядок в настройках — это приоритет: сначала русская, потом английская."""
    out = download_prefs.audio_format_selector("bestvideo+bestaudio/best", ["ru", "en"])
    assert out.index("language^=ru") < out.index("language^=en")


def test_audio_selector_uses_prefix_match():
    """ru должен подходить и для ru-RU: точного совпадения у YouTube часто нет."""
    out = download_prefs.audio_format_selector("bestvideo+bestaudio/best", ["ru"])
    assert "language^=ru" in out, "строгое равенство отсекает ru-RU"


def test_audio_selector_handles_audio_only():
    """Выбор «Только звук» тоже должен уметь язык."""
    out = download_prefs.audio_format_selector("bestaudio/best", ["en"])
    assert out.startswith("bestaudio[language^=en]/")


def test_audio_selector_handles_numeric_video_format():
    """Числовой id формата: аудио дописывается загрузчиком как bestaudio."""
    out = download_prefs.audio_format_selector("137+bestaudio/best", ["en"])
    assert "137+bestaudio[language^=en]" in out


def test_audio_selector_skips_single_stream_selector():
    """У TikTok единый поток 'best': фильтр языка сделал бы формат недостижимым."""
    assert download_prefs.audio_format_selector("best", ["ru"]) == "best"


def test_audio_selector_survives_empty_selector():
    assert download_prefs.audio_format_selector("", ["ru"]) == ""
    assert download_prefs.audio_format_selector(None, ["ru"]) is None


# ================= Опции субтитров =================

def test_subtitle_opts_absent_when_disabled(prefs_config):
    opts = download_prefs.apply_subtitle_opts({}, download_prefs.get_prefs())
    assert "writesubtitles" not in opts, "субтитры качаются при выключенной настройке"


def test_subtitle_opts_set_when_enabled(prefs_config):
    download_prefs.save_prefs({"subtitles_enabled": True, "subtitle_langs": ["ru", "en"]})
    opts = download_prefs.apply_subtitle_opts({}, download_prefs.get_prefs())
    assert opts["writesubtitles"] is True
    assert opts["subtitleslangs"] == ["ru", "en"]


def test_subtitle_opts_auto_flag_follows_setting(prefs_config):
    """Автоматические субтитры — отдельный выбор: они хуже ручных."""
    download_prefs.save_prefs({"subtitles_enabled": True, "subtitles_auto": False})
    assert download_prefs.apply_subtitle_opts({}, download_prefs.get_prefs())["writeautomaticsub"] is False
    download_prefs.save_prefs({"subtitles_auto": True})
    assert download_prefs.apply_subtitle_opts({}, download_prefs.get_prefs())["writeautomaticsub"] is True


def test_subtitle_opts_ignore_empty_language_list(prefs_config):
    """Включённые субтитры без языков качать нечего."""
    download_prefs.save_prefs({"subtitles_enabled": True})
    download_prefs.save_prefs({"subtitle_langs": []})
    assert "writesubtitles" not in download_prefs.apply_subtitle_opts({}, download_prefs.get_prefs())


# ================= Встраивание в загрузчик =================

def test_ydl_opts_apply_audio_language(prefs_config, monkeypatch, tmp_path):
    monkeypatch.setattr(download_lib, "get_download_prefs", lambda: {
        **download_prefs.DEFAULTS, "audio_langs": ["ru"]})
    opts = download_lib.get_ydl_opts(None, "mp4", lambda d: None, str(tmp_path / "t"),
                                     "https://youtu.be/x")
    assert "language^=ru" in opts["format"]


def test_ydl_opts_apply_subtitles(prefs_config, monkeypatch, tmp_path):
    monkeypatch.setattr(download_lib, "get_download_prefs", lambda: {
        **download_prefs.DEFAULTS, "subtitles_enabled": True, "subtitle_langs": ["en"]})
    opts = download_lib.get_ydl_opts(None, "mp4", lambda d: None, str(tmp_path / "t"),
                                     "https://youtu.be/x")
    assert opts["subtitleslangs"] == ["en"]
    assert opts["writesubtitles"] is True


def test_ydl_opts_without_prefs_unchanged(prefs_config, tmp_path):
    """Настройки по умолчанию: опции такие же, как до появления раздела."""
    opts = download_lib.get_ydl_opts(None, "mp4", lambda d: None, str(tmp_path / "t"),
                                     "https://youtu.be/x")
    assert opts["format"] == "bestvideo+bestaudio/best"
    assert "writesubtitles" not in opts


def test_ydl_opts_skip_audio_language_for_tiktok(prefs_config, monkeypatch, tmp_path):
    """У TikTok селектор 'best': фильтр языка сломал бы загрузку."""
    monkeypatch.setattr(download_lib, "get_download_prefs", lambda: {
        **download_prefs.DEFAULTS, "audio_langs": ["ru"]})
    opts = download_lib.get_ydl_opts(None, "mp4", lambda d: None, str(tmp_path / "t"),
                                     "https://www.tiktok.com/@a/video/123")
    assert opts["format"] == "best"


# ================= Раскладка скачанных субтитров =================

def test_downloaded_subtitles_move_to_subtitles_dir(tmp_path, monkeypatch):
    """Файлы .vtt лежат во временной папке и удалялись вместе с ней.

    Перенос обязателен: плеер читает субтитры из subtitles/<источник>/<id>.
    """
    import subtitles as subtitles_module

    subs_root = tmp_path / "subs"
    monkeypatch.setattr(subtitles_module, "get_subtitles_dir", lambda: str(subs_root))
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    (temp_dir / "video.ru.vtt").write_text("WEBVTT", encoding="utf-8")

    saved = download_lib.save_subtitles(str(temp_dir), "abc123")

    assert saved == 1
    assert (subs_root / "youtube" / "abc123" / "ru.vtt").read_text(encoding="utf-8") == "WEBVTT"


def test_downloaded_subtitles_keep_regional_code(tmp_path, monkeypatch):
    import subtitles as subtitles_module

    subs_root = tmp_path / "subs"
    monkeypatch.setattr(subtitles_module, "get_subtitles_dir", lambda: str(subs_root))
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    (temp_dir / "video.pt-BR.vtt").write_text("WEBVTT", encoding="utf-8")

    download_lib.save_subtitles(str(temp_dir), "abc123")

    assert (subs_root / "youtube" / "abc123" / "pt-BR.vtt").exists()


def test_downloaded_subtitles_ignore_other_files(tmp_path, monkeypatch):
    """Видео и превью в папку субтитров попадать не должны."""
    import subtitles as subtitles_module

    subs_root = tmp_path / "subs"
    monkeypatch.setattr(subtitles_module, "get_subtitles_dir", lambda: str(subs_root))
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    (temp_dir / "video.mp4").write_bytes(b"x")
    (temp_dir / "video.info.json").write_text("{}", encoding="utf-8")

    assert download_lib.save_subtitles(str(temp_dir), "abc123") == 0
    assert not (subs_root / "youtube" / "abc123").exists()


def test_downloaded_subtitles_survive_missing_video_id(tmp_path, monkeypatch):
    """Без id складывать некуда, но падать нельзя: видео уже скачано."""
    import subtitles as subtitles_module

    monkeypatch.setattr(subtitles_module, "get_subtitles_dir", lambda: str(tmp_path / "subs"))
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    (temp_dir / "video.ru.vtt").write_text("WEBVTT", encoding="utf-8")
    assert download_lib.save_subtitles(str(temp_dir), "") == 0


# ================= API =================

def test_api_returns_prefs(client, prefs_config):
    res = client.get("/api/download/prefs")
    assert res.status_code == 200
    data = res.get_json()
    assert data["subtitle_langs"] == ["ru"]
    assert [code for code, _ in download_prefs.LANGUAGES] == [l["code"] for l in data["languages"]], \
        "список языков для интерфейса не совпадает с модулем"


def test_api_saves_prefs(client, prefs_config):
    res = client.post("/api/download/prefs", json={"audio_langs": ["en"],
                                                   "subtitles_enabled": True})
    assert res.status_code == 200
    assert download_prefs.get_prefs()["audio_langs"] == ["en"]


def test_api_rejects_broken_lang(client, prefs_config):
    res = client.post("/api/download/prefs", json={"subtitle_langs": ["../evil"]})
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_api_survives_request_without_content_type(client, prefs_config):
    """Запрос без Content-Type раньше отдавал HTML-страницу 415."""
    res = client.post("/api/download/prefs", data="{}")
    assert res.status_code in (200, 400)
    assert res.is_json, "ответ не JSON"
