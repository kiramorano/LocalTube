"""Тесты сборки: пути, версия, подавление консоли, оконная оболочка.

Эти проверки закрывают то, что легко ломается незаметно. Раньше каждый модуль
считал корень проекта сам (``os.path.dirname(__file__)``), и в собранной версии
приложение писало библиотеку внутрь временного каталога, который удаляется при
выходе: пользователь терял всё скачанное после закрытия окна. Тесты фиксируют
разделение «ресурсы только для чтения» и «данные для записи», а также поведение
портативного режима, где данные обязаны лежать рядом с программой.
"""
import os
import re
import socket
import subprocess
import sys

import pytest

import desktop
import paths
import proc
import version


# ================= РЕЖИМЫ КАТАЛОГА ДАННЫХ =================

def test_source_run_keeps_data_in_project(monkeypatch):
    """Запуск из исходников ведёт себя как раньше: всё в корне проекта.

    Это условие совместимости: тесты и привычный ``python app.py`` не должны
    внезапно начать искать библиотеку в профиле пользователя.
    """
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(paths, "is_frozen", lambda: False)

    assert paths.is_portable() is True
    assert paths.data_dir() == paths._SOURCE_DIR
    assert paths.resource_dir() == paths._SOURCE_DIR


def test_env_override_wins_over_portable(monkeypatch, tmp_path):
    """LOCALTUBE_DATA_DIR перекрывает любой режим."""
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(paths, "is_frozen", lambda: True)

    # Явно заданный каталог — это уже не портативный режим, а ручное управление.
    assert paths.is_portable() is False
    assert paths.data_dir() == str(tmp_path)


def test_env_override_expands_user(monkeypatch):
    """Тильда в пути раскрывается: '~/LocalTube' — рабочее значение."""
    monkeypatch.setenv(paths.DATA_DIR_ENV, os.path.join("~", "LocalTubeData"))

    result = paths.data_dir()

    assert "~" not in result
    assert os.path.isabs(result)


def test_frozen_portable_uses_app_dir(monkeypatch, tmp_path):
    """Маркер portable.txt рядом с программой уводит данные туда же.

    Без маркера портативная версия писала бы в профиль пользователя: на чужом
    компьютере это оставляет следы, а при переносе флешки теряет библиотеку.
    """
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path))
    (tmp_path / paths.PORTABLE_MARKER).write_text("portable", encoding="utf-8")

    assert paths.is_portable() is True
    assert paths.data_dir() == str(tmp_path)


def test_frozen_installed_uses_user_profile(monkeypatch, tmp_path):
    """Без маркера установленная версия пишет в профиль пользователя.

    Каталог установки (Program Files, /usr/lib) доступен только для чтения,
    поэтому запись рядом с программой падала бы с PermissionError.
    """
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path))

    assert paths.is_portable() is False
    data_dir = paths.data_dir()
    assert data_dir != str(tmp_path)
    assert os.path.isabs(data_dir)


def test_resource_dir_follows_meipass(monkeypatch, tmp_path):
    """В собранной версии ресурсы берутся из каталога бандла.

    Шаблоны и статика лежат в ``sys._MEIPASS``, а не рядом с exe: искать их
    возле исполняемого файла значило бы получить TemplateNotFound на каждой
    странице.
    """
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert paths.resource_dir() == str(tmp_path)


def test_data_and_resource_dirs_differ_when_installed(monkeypatch, tmp_path):
    """Ресурсы и данные в установленной версии — разные каталоги.

    Именно их совпадение и было исходной поломкой: данные писались внутрь
    бандла.
    """
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path / "program"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)

    assert paths.resource_dir() != paths.data_dir()


# ================= ПУТИ ВНУТРИ КАТАЛОГОВ =================

def test_user_path_keeps_absolute_values(monkeypatch, tmp_path):
    """Абсолютный путь из настроек не переписывается.

    Пользователь вправе держать библиотеку на другом диске (``D:/видео``), и
    join с каталогом данных ломал бы такой выбор.
    """
    monkeypatch.setattr(paths, "data_dir", lambda: str(tmp_path))
    absolute = os.path.abspath(os.path.join(os.sep, "media", "video"))

    assert paths.user_path(absolute) == absolute


def test_user_path_resolves_relative_from_data_dir(monkeypatch, tmp_path):
    """Относительное значение считается от каталога данных."""
    monkeypatch.setattr(paths, "data_dir", lambda: str(tmp_path))

    assert paths.user_path("videos") == os.path.join(str(tmp_path), "videos")


def test_user_path_without_value_returns_root(monkeypatch, tmp_path):
    """Пустое значение даёт сам каталог данных, а не путь с пустым сегментом."""
    monkeypatch.setattr(paths, "data_dir", lambda: str(tmp_path))

    assert paths.user_path("") == str(tmp_path)
    assert paths.user_path(None) == str(tmp_path)


def test_ensure_data_dir_creates_directory(monkeypatch, tmp_path):
    """Каталог данных создаётся: при первом запуске его ещё нет."""
    target = tmp_path / "nested" / "data"
    monkeypatch.setattr(paths, "data_dir", lambda: str(target))

    assert paths.ensure_data_dir() == str(target)
    assert target.is_dir()


# ================= ВНЕШНИЕ ПРОГРАММЫ =================

def test_bundled_ffmpeg_wins_over_path(monkeypatch, tmp_path):
    """Вложенный ffmpeg приоритетнее системного.

    В портативной сборке ffmpeg лежит внутри пакета, и брать версию из PATH
    (которой может не быть вовсе) нельзя: склейка видео с аудио падала после
    того, как файлы уже скачаны.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    bundled = bin_dir / name
    bundled.write_text("stub", encoding="utf-8")
    os.chmod(str(bundled), 0o755)

    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path))
    monkeypatch.setattr(paths, "resource_dir", lambda: str(tmp_path))

    assert paths.ffmpeg_path() == str(bundled)
    assert paths.ffmpeg_dir() == str(bin_dir)


def test_ffmpeg_path_falls_back_to_name(monkeypatch):
    """Если ffmpeg не найден, возвращается имя, а не None.

    Так сохраняется прежнее поведение вызовов subprocess: ошибка будет та же,
    что и раньше, а не TypeError на None внутри списка аргументов.
    """
    monkeypatch.setattr(paths, "find_binary", lambda name: None)

    assert paths.ffmpeg_path() == "ffmpeg"
    assert paths.ffprobe_path() == "ffprobe"
    assert paths.ffmpeg_dir() is None


def test_ydl_opts_point_to_bundled_ffmpeg(monkeypatch, tmp_path):
    """yt-dlp получает каталог с ffmpeg через ffmpeg_location.

    Без этого параметра постпроцессор искал ffmpeg только в PATH, и загрузка
    обрывалась на объединении потоков.
    """
    import download_lib

    monkeypatch.setattr(paths, "ffmpeg_dir", lambda: str(tmp_path))
    opts = download_lib.get_ydl_opts(
        format_id="best", merge_format="mp4", progress_hook=None,
        temp_dir=str(tmp_path / "tmp"))

    assert opts.get("ffmpeg_location") == str(tmp_path)


# ================= ПОДАВЛЕНИЕ КОНСОЛИ =================

def test_no_window_flags_only_on_windows():
    """CREATE_NO_WINDOW добавляется только в Windows.

    В оконном приложении каждый вызов ffmpeg открывал бы чёрное окно консоли, а
    на Linux такого флага не существует и его передача ломала бы subprocess.
    """
    if sys.platform == "win32":
        assert proc.NO_WINDOW.get("creationflags") == subprocess.CREATE_NO_WINDOW
    else:
        assert proc.NO_WINDOW == {}


def test_proc_run_passes_no_window(monkeypatch):
    """proc.run прокидывает флаги подавления окна в subprocess."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return "result"

    monkeypatch.setattr(proc.subprocess, "run", fake_run)
    assert proc.run(["cmd"]) == "result"

    for key, value in proc.NO_WINDOW.items():
        assert captured.get(key) == value


# ================= ВЕРСИЯ =================

def test_version_is_three_numbers():
    """Формат версии обязателен для MSI: ровно три числа.

    Windows Installer не понимает суффиксы вида ``-rc1`` и молча их обрезает,
    из-за чего две разные сборки выглядели бы для системы одинаково.
    """
    parts = version.__version__.split(".")

    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
    assert version.version_tuple() == tuple(int(p) for p in parts)


def test_app_id_is_reverse_dns():
    """APP_ID в формате reverse-DNS: требование .desktop и AppImage."""
    assert version.APP_ID.count(".") >= 2
    assert " " not in version.APP_ID


# ================= ТЕМА FRUTIGER AERO =================

def _read_static(*parts):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "static", *parts)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_aero_theme_has_fallback_backgrounds():
    """Если API обоев недоступен, тема не должна оставаться с чёрным экраном.

    Раньше `fetch('/api/...')` в WebView2 может вернуть пустой массив или
    бросить исключение, и `startBackground` тогда вызывал `clearBackground()`:
    фон стирался вообще. Теперь есть FALLBACK_IMAGES — набор обоев из той же
    папки, что лежит рядом с приложением, и они применяются в catch.
    """
    js = _read_static("js", "theme.js")
    assert "FALLBACK_IMAGES" in js, "нет запасных обоев"
    assert ".catch" in js, \
        "fetchImages не имеет catch: пустой ответ API убивал фон"
    # fallback должен лежать в той же папке, что и основные обои — тогда ссылка
    # на него работает независимо от API.
    assert "FALLBACK_IMAGES.slice()" in js, \
        "fallback копируется .slice(), иначе он мутирует глобальный массив"


def test_aero_theme_exports_background_url():
    """Функция backgroundUrl нужна наружу: шаблоны и fallback используют её."""
    js = _read_static("js", "theme.js")
    assert "backgroundUrl: backgroundUrl" in js, \
        "backgroundUrl не экспортирована в window.LocalTubeTheme"
    # Путь без ?w=&h=: параметры имели и сломали кэш.
    fn = re.search(r"function backgroundUrl\s*\([^)]*\)\s*\{[^}]*\}", js)
    assert fn, "backgroundUrl function not found"
    ret = re.search(r"return\s+[^;]+;", fn.group(0))
    assert ret, "backgroundUrl должен возвращать строку"
    assert "?w=" not in ret.group(0), \
        "в backgroundUrl есть ?w=&h= — ссылка уникальна, кэш сбрасыается"


def test_aero_theme_api_and_files_match():
    """Имена fallback-обоев должны действительно лежать в папке.

    Иначе fallback просто заменил бы одну битую картинкой на другую.
    """
    js = _read_static("js", "theme.js")
    # Выделяем имена из массива FALLBACK_IMAGES.
    block = re.search(r"var FALLBACK_IMAGES\s*=\s*\[([\s\S]*?)\]", js)
    assert block, "не найден блок FALLBACK_IMAGES"
    names = re.findall(r"'([^']+)'", block.group(1))
    assert names, "в блоке FALLBACK_IMAGES нет имён файлов"
    theme_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "static", "images", "themes", "frutiger-aero")
    for name in names:
        assert os.path.isfile(os.path.join(theme_dir, name)), \
            f"fallback {name}: файл не найден в static/images/themes/frutiger-aero"


# ================= ОКОННАЯ ОБОЛОЧКА =================

def test_single_instance_lock_blocks_second_call():
    """Второй экземпляр не должен занимать замок.

    Две копии подняли бы два сервера на одном порту и писали бы в один
    queue.json, портя очередь загрузок.
    """
    try:
        assert desktop.acquire_single_instance_lock() is True
        assert desktop.acquire_single_instance_lock() is False
    finally:
        desktop.release_single_instance_lock()


def test_single_instance_lock_frees_after_release():
    """После освобождения замок можно взять снова.

    Проверка на регрессию: файловый замок оставался бы лежать после падения, и
    приложение потом не запускалось вовсе.
    """
    assert desktop.acquire_single_instance_lock() is True
    desktop.release_single_instance_lock()
    try:
        assert desktop.acquire_single_instance_lock() is True
    finally:
        desktop.release_single_instance_lock()


def test_pick_port_skips_busy_port():
    """Занятый порт приводит к выбору следующего свободного.

    Порт 5000 занимают и другие программы, а приложение падало с
    «address already in use».
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("0.0.0.0", 0))
        busy.listen(1)
        port = busy.getsockname()[1]

        chosen = desktop.pick_port(port, limit=5)

        assert chosen != port
        assert port < chosen <= port + 5


def test_pick_port_returns_preferred_when_free():
    """Свободный порт берётся как есть, без сдвига."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("0.0.0.0", 0))
        free_port = probe.getsockname()[1]

    assert desktop.pick_port(free_port, limit=3) == free_port


def test_wait_for_server_detects_listening_socket():
    """Ожидание сервера видит открытый порт."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        assert desktop.wait_for_server(port, timeout=2.0) is True


def test_wait_for_server_times_out_on_dead_port():
    """На закрытом порту ожидание завершается отказом, а не зависает.

    Окно нельзя показывать раньше сервера: WebView2 рисует свою страницу
    «не удалось открыть» и больше не перезапрашивает адрес.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]

    assert desktop.wait_for_server(dead_port, timeout=0.5) is False


def test_server_port_is_single_source_of_truth():
    """Порт сервера задан в одном месте и синхронизируется с access.

    Раньше значение было записано дважды (app.run и access.DEFAULT_PORT), и при
    фолбэке на другой порт QR-код для телефона вёл в никуда.
    """
    import access
    import app as app_module

    original = app_module.SERVER_PORT
    try:
        assert original == access.DEFAULT_PORT
        assert app_module.set_server_port(5123) == 5123
        assert app_module.SERVER_PORT == 5123
        # Адреса для гостей должны собираться на новом порту.
        addresses = access.local_addresses(app_module.SERVER_PORT)
        assert all(":5123" in item["url"] for item in addresses)
    finally:
        app_module.set_server_port(original)


def test_pick_gui_avoids_cef_without_package(monkeypatch):
    """Движок CEF не навязывается, если пакета нет.

    Проверяется наличие cefpython3, а не версия Windows: указание
    отсутствующего движка ронял бы запуск на ImportError вместо запасного пути.
    """
    if sys.platform != "win32":
        pytest.skip("проверка только для Windows")

    monkeypatch.setattr(sys, "getwindowsversion",
                        lambda: (6, 1, 7601, 2, ""), raising=False)
    real_import = __import__

    def block_cef(name, *args, **kwargs):
        if name == "cefpython3":
            raise ImportError("нет пакета")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", block_cef)

    assert desktop.pick_gui() is None


# ================= СТАРЫЕ ДВИЖКИ (WINDOWS 7) =================
#
# Сборка для Windows 7 показывает интерфейс во встроенном Chromium 66: WebView2
# на «семёрке» нет. Этому движку не хватает свойств, на которых держится вся
# вёрстка, поэтому рядом лежит слой замен. Тесты ниже следят, чтобы он
# подключался только там, где нужен, и не разъезжался с основными стилями.

def _read_static(*parts):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "static", *parts)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_legacy_css_is_not_linked_in_templates():
    """legacy.css не должен подключаться тегом <link>.

    Он меняет способ вёрстки превью и отступов. На современном движке это
    испортило бы раскладку, поэтому файл добавляет compat.js — и только после
    проверки возможностей движка.
    """
    templates_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
    for name in os.listdir(templates_dir):
        if not name.endswith(".html"):
            continue
        with open(os.path.join(templates_dir, name), encoding="utf-8") as handle:
            html = handle.read()
        assert "css/legacy.css" not in html, \
            f"{name}: legacy.css подключён напрямую, он попадёт на новые движки"


def test_compat_loads_legacy_css_by_feature_check():
    """Слой замен включается по возможностям движка, а не по User-Agent."""
    js = _read_static("js", "compat.js")

    assert "/static/css/legacy.css" in js, "compat.js не подключает legacy.css"
    assert "CSS.supports" in js, "проверка возможностей заменена на что-то другое"
    assert "userAgent" not in js, \
        "движок определяется по User-Agent: строка подделывается и врёт о возможностях"


def test_compat_marks_each_missing_feature_separately():
    """У каждой нехватки свой класс.

    Одного общего флага мало: flex gap появился в Chrome 84, а aspect-ratio в 88.
    На движках между ними отступы наложились бы поверх работающего gap.
    """
    js = _read_static("js", "compat.js")
    css = _read_static("css", "legacy.css")

    for cls in ("lt-no-aspect-ratio", "lt-no-min-max", "lt-no-inset"):
        assert cls in js, f"compat.js не выставляет класс {cls}"
        assert cls in css, f"legacy.css не использует класс {cls}"
    # Отступы вместо gap считает скрипт, в CSS их быть не должно.
    assert "lt-no-flex-gap" in js


def test_legacy_css_rules_are_all_scoped():
    """Все правила слоя ограничены классами-флагами.

    Правило без флага применилось бы, как только файл загружен, — то есть и на
    движке, которому не хватает лишь одного свойства из четырёх.
    """
    css = re.sub(r"/\*.*?\*/", "", _read_static("css", "legacy.css"), flags=re.S)
    for block in re.finditer(r"([^{}]+)\{[^{}]*\}", css):
        selectors = [s.strip() for s in block.group(1).split(",") if s.strip()]
        for selector in selectors:
            assert selector.startswith(".lt-no-"), \
                f"правило {selector!r} не ограничено классом старого движка"


def test_legacy_css_keeps_aspect_ratio_pairs():
    """Пропорции пересчитаны верно: 16:9 → 56.25%, 9:16 → 177.78%.

    Приём с padding-top считает высоту от ширины, и перевёрнутая дробь давала бы
    вытянутые превью вместо горизонтальных.
    """
    css = _read_static("css", "legacy.css")

    assert "56.25%" in css, "нет пропорции 16:9"
    assert "177.78%" in css, "нет пропорции 9:16"
    # height:0 обязателен: иначе к padding добавится высота содержимого.
    assert re.search(r"height:\s*0", css), "нет height:0, блок будет выше нужного"


def test_compat_emulates_gap_by_measured_direction():
    """Отступы вместо gap считаются по фактическому направлению оси.

    Списком селекторов это делать нельзя: у одного класса направление зависит от
    страницы и медиазапроса (.video-details на главной — ряд, .card-actions —
    колонка), и отступ уезжал вниз вместо того, чтобы уйти вбок.
    """
    js = _read_static("js", "compat.js")

    assert "flexDirection" in js, "направление оси не определяется"
    assert "columnGap" in js and "rowGap" in js, \
        "берётся общий gap: в ряду и в колонке за расстояние отвечают разные оси"
    assert "MutationObserver" in js, \
        "нет пересчёта для узлов, которые интерфейс дорисовывает на ходу"


def test_compat_js_stays_es5():
    """Скрипт должен разбираться парсером Chromium 66.

    Стрелочные функции и шаблонные строки он ещё понимает, но опциональную
    цепочку — нет, и тогда отбрасывается весь файл: страница остаётся без
    полифиллов, то есть пустой.
    """
    js = _read_static("js", "compat.js")
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)

    for token in ("?.", "??", "=>", "const ", "let ", "`", "..."):
        assert token not in code, f"в compat.js используется {token!r}"


# ================= СОГЛАСОВАННОСТЬ PYINSTALLER-СПЕКОВ =================

PACKAGING_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "packaging")

SPECS = ("localtube.spec", "localtube-portable.spec", "localtube-legacy.spec")


def _read_spec(name):
    with open(os.path.join(PACKAGING_DIR, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("name", SPECS)
def test_specs_share_common_lists(name):
    """Списки данных и импортов должны идти из spec_common.

    В localtube.spec когда-то был свой список файлов, и он разошёлся с
    остальными: в сборку не попадали ffmpeg, локали и иконка, потому что
    добавляли их только в spec_common.
    """
    spec = _read_spec(name)
    assert "import spec_common as common" in spec, \
        f"{name} не использует spec_common — списки разъедутся"
    for call in ("common.collect_datas(", "common.collect_hidden_imports(",
                 "common.collect_binaries(", "common.EXCLUDES"):
        assert call in spec, f"{name}: нет {call}"


@pytest.mark.parametrize("name", SPECS)
def test_specs_build_windowed_app(name):
    """console=False и вход desktop.py.

    С console=True рядом с окном оставалось окно консоли, а вход на app.py
    поднимал сервер разработки Werkzeug и печатал адрес в консоль вместо
    открытия окна.
    """
    spec = _read_spec(name)
    assert "console=False" in spec, f"{name}: console=True — останется консоль"
    assert "console=True" not in spec, f"{name}: console=True"
    assert "common.entry_script()" in spec, \
        f"{name}: вход должен быть desktop.py через entry_script()"
    assert "'app.py'" not in spec, f"{name}: вход на app.py вместо desktop.py"


@pytest.mark.parametrize("name", SPECS)
def test_specs_set_icon_and_version(name):
    """Без иконки и версии SmartScreen относится к exe заметно хуже."""
    spec = _read_spec(name)
    assert "common.icon_path()" in spec, f"{name}: нет иконки"
    assert "common.version_file()" in spec, f"{name}: нет данных о версии"


@pytest.mark.parametrize("name", ("localtube.spec", "localtube-portable.spec"))
def test_linux_specs_bundle_gtk_stack(name):
    """Linux-спеки обязаны укладывать GTK и WebKit внутрь сборки.

    Иначе приложение зависит от версий в системе пользователя: на Debian 11
    и Ubuntu 20.04 WebKit старее 2.40, и интерфейс остаётся мёртвым, потому
    что pywebview 6 исполняет JS только через evaluate_javascript.

    Сбор идёт после Analysis: хуки PyInstaller дополняют списки уже после
    сбора, и добавленное ими иначе не попало бы под обработку.
    """
    spec = _read_spec(name)
    assert "common.collect_gtk_stack()" in spec, \
        f"{name}: GTK/WebKit не вкладываются — сборка зависит от системы"
    assert "common.collect_webkit_helpers()" in spec, \
        f"{name}: нет helper-процессов WebKit — окно останется пустым"
    assert "common.collect_gtk_support_files()" in spec, \
        f"{name}: нет typelib и модулей GIO — gi.require_version упадёт"
    assert "common.collect_gl_fallback()" in spec, \
        f"{name}: нет запасных libGL/libEGL — WebKit не загрузится без драйверов"
    assert "common.patch_webkit_exec_path(" in spec, \
        f"{name}: путь helper-процессов не исправлен — WebKit не сможет их запустить"
    assert "common.runtime_hooks()" in spec, \
        f"{name}: нет рантайм-хука — вложенный GTK не найдёт свои модули"


def test_gl_libraries_are_never_bundled_alongside_others():
    """libGL и libEGL не должны лежать рядом с остальными библиотеками.

    Наш каталог стоит первым в пути загрузчика, поэтому своя копия libGL
    перекрыла бы драйвер видеокарты пользователя, собранный под его ядро.
    Копия нужна (WebKit слинкован с libGL и без файла не загружается), но
    только в отдельном каталоге и только когда системной нет.
    """
    spec_common = _load_packaging_module("spec_common")

    for name in ("libGL.so.1", "libEGL.so.1", "libgbm.so.1", "libdrm.so.2",
                 "libc.so.6", "ld-linux-x86-64.so.2"):
        assert spec_common._is_never_bundled(name), \
            f"{name} попадёт в общий каталог и перекроет системную библиотеку"

    # А в запасном каталоге они, наоборот, обязаны быть.
    assert "libGL.so.1" in spec_common.LINUX_GL_FALLBACK
    assert "libEGL.so.1" in spec_common.LINUX_GL_FALLBACK


def test_webkit_exec_path_patch_keeps_size_and_shortens_path(monkeypatch, tmp_path):
    """Патч пути helper-процессов не смеет менять размер файла.

    WebKit запускает WebKitWebProcess по пути, вшитому при его сборке
    (/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/...). В системе пользователя
    такого каталога нет, и окно падает с «Unable to spawn a new child
    process». Переменная WEBKIT_EXEC_PATH не помогает: дистрибутивные сборки
    её не читают, строки с таким именем в библиотеке отсутствуют.

    Поэтому строка правится прямо в копии библиотеки. Новое значение обязано
    быть не длиннее исходного, а остаток забивается нулями: сдвинуть данные
    в ELF нельзя, следом идут другие структуры.
    """
    spec_common = _load_packaging_module("spec_common")
    # Патч нужен только Linux-сборке, поэтому на других платформах функция
    # сразу выходит. Подменяем платформу и каталог для промежуточных файлов.
    monkeypatch.setattr(spec_common.sys, "platform", "linux")
    monkeypatch.setattr(spec_common, "ROOT", str(tmp_path / "root"))

    original = (b'\x7fELF fake header\x00'
                b'/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1\x00'
                b'/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/injected-bundle/\x00'
                b'tail data\x00')
    lib = tmp_path / "libwebkit2gtk-4.1.so.0"
    lib.write_bytes(original)

    result = spec_common.patch_webkit_exec_path(
        [("libwebkit2gtk-4.1.so.0", str(lib), "BINARY")])

    patched_path = result[0][1]
    assert patched_path != str(lib), "патч не применился"
    data = open(patched_path, "rb").read()
    assert len(data) == len(original), "размер изменился — ELF сломан"
    assert b"webkit_helpers\x00" in data
    assert b"webkit_helpers/injected-bundle\x00" in data
    assert b"/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1" not in data, \
        "остался абсолютный путь: WebKit пойдёт искать helper в системе"
    assert data.endswith(b"tail data\x00"), "данные за строкой сдвинулись"


def test_webkit_exec_path_patch_skips_unrelated_binaries(monkeypatch, tmp_path):
    """Патч трогает только WebKit: остальные записи проходят как есть."""
    spec_common = _load_packaging_module("spec_common")
    monkeypatch.setattr(spec_common.sys, "platform", "linux")
    monkeypatch.setattr(spec_common, "ROOT", str(tmp_path / "root"))

    other = tmp_path / "libglib-2.0.so.0"
    other.write_bytes(b"\x7fELF /usr/lib/x86_64-linux-gnu/webkit2gtk-4.1\x00")
    entry = ("libglib-2.0.so.0", str(other), "BINARY")

    result = spec_common.patch_webkit_exec_path([entry])
    assert result == [entry], "патч изменил постороннюю библиотеку"


def test_ffmpeg_datas_skip_foreign_binaries(monkeypatch, tmp_path):
    """В Linux-сборку не должны попадать ffmpeg.exe, и наоборот.

    Каталог assets/ffmpeg хранит обе платформы сразу. Без фильтра в
    Linux-пакет укладывались 90 МБ Windows-бинарников, которые там нельзя
    запустить: find_binary требует имя без .exe и бит выполнения.
    """
    spec_common = _load_packaging_module("spec_common")
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()
    (ffmpeg_dir / "ffmpeg.exe").write_bytes(b"MZ")
    (ffmpeg_dir / "ffprobe.exe").write_bytes(b"MZ")
    (ffmpeg_dir / "ffmpeg").write_bytes(b"ELF")
    (ffmpeg_dir / "ffprobe").write_bytes(b"ELF")
    monkeypatch.setattr(spec_common, "ASSETS", str(tmp_path))

    monkeypatch.setattr(spec_common.sys, "platform", "linux")
    linux_names = [os.path.basename(src) for src, _dest in spec_common._ffmpeg_datas()]
    assert linux_names == ["ffmpeg", "ffprobe"]

    monkeypatch.setattr(spec_common.sys, "platform", "win32")
    win_names = [os.path.basename(src) for src, _dest in spec_common._ffmpeg_datas()]
    assert win_names == ["ffmpeg.exe", "ffprobe.exe"]


def test_build_linux_has_no_system_dependencies():
    """Пакеты не должны требовать GTK и WebKit от системы.

    Весь стек лежит внутри, поэтому требования только мешали бы: версии в
    дистрибутивах расходятся, а на Debian 11 и Ubuntu 20.04 WebKit старее
    2.40, и установка пакета там просто не проходила бы.

    Единственная неустранимая зависимость — glibc: её нельзя вложить, она
    неразделима с загрузчиком ld.so. Её версию dpkg-shlibdeps подставляет сам.
    """
    build_linux = _load_packaging_module("build_linux")
    assert build_linux.DEB_DEPENDS == [], \
        "DEB требует системные библиотеки, хотя несёт свои"
    assert build_linux.RPM_REQUIRES == [], \
        "RPM требует системные библиотеки, хотя несёт свои"

    with open(os.path.join(PACKAGING_DIR, "build_linux.py"), encoding="utf-8") as fh:
        text = fh.read()
    assert "shutil.which('linuxdeploy')" not in text, \
        "linuxdeploy вернулся: он раскладывает библиотеки по-своему"
    # Пустое поле Depends недопустимо в формате control, и dpkg-deb на нём падает.
    assert "if DEB_DEPENDS else ''" in text, \
        "при пустом списке в control попадёт пустое поле Depends"
    assert "AutoReqProv:    no" in text, \
        "rpmbuild выпишет требования на все вложенные библиотеки"


# ================= ГЕНЕРАЦИЯ MSI (WiX 3 и 4) =================

def _load_packaging_module(name):
    """Импортирует модуль из packaging/ (он не пакет и в sys.path не входит)."""
    sys.path.insert(0, PACKAGING_DIR)
    try:
        return __import__(name)
    finally:
        sys.path.pop(0)


@pytest.fixture()
def fake_build(tmp_path):
    """Минимальный каталог «сборки» для генератора .wxs."""
    root = tmp_path / "LocalTube"
    (root / "_internal" / "bin").mkdir(parents=True)
    (root / "LocalTube.exe").write_bytes(b"MZ")
    (root / "_internal" / "bin" / "ffmpeg.exe").write_bytes(b"MZ")
    # Дефис и точка в имени: WiX не принимает их в идентификаторах, поэтому
    # генератор обязан их вычистить.
    (root / "_internal" / "yt-dlp.version").write_text("1", encoding="utf-8")
    return root


def test_wxs_v3_uses_product_root(fake_build, tmp_path):
    """Схема WiX 3 отличается от v4 структурно, а не косметически.

    В v3 корень описания — Product, дерево каталогов растёт от TARGETDIR, и
    StandardDirectory в схеме нет вовсе.
    """
    make_wxs = _load_packaging_module("make_wxs")
    out = tmp_path / "v3.wxs"
    assert make_wxs.main(["--source", str(fake_build), "--out", str(out),
                          "--wix-version", "3"]) == 0

    xml = out.read_text(encoding="utf-8")
    assert "schemas.microsoft.com/wix/2006/wi" in xml, "не то пространство имён"
    assert "<Product " in xml, "в v3 корень описания — Product"
    assert 'Id="TARGETDIR"' in xml, "дерево каталогов должно расти от TARGETDIR"
    assert "StandardDirectory" not in xml, "StandardDirectory есть только в v4"


def test_wxs_v3_marks_components_win64(fake_build, tmp_path):
    """Без Win64 64-битный пакет ставится в Program Files (x86)."""
    make_wxs = _load_packaging_module("make_wxs")
    out = tmp_path / "v3.wxs"
    make_wxs.main(["--source", str(fake_build), "--out", str(out),
                   "--wix-version", "3", "--arch", "x64"])
    xml = out.read_text(encoding="utf-8")
    assert 'Win64="yes"' in xml, "компоненты не помечены как 64-битные"
    assert 'Id="ProgramFiles64Folder"' in xml

    out32 = tmp_path / "v3-x86.wxs"
    make_wxs.main(["--source", str(fake_build), "--out", str(out32),
                   "--wix-version", "3", "--arch", "x86"])
    xml32 = out32.read_text(encoding="utf-8")
    assert 'Win64="no"' in xml32, "для x86 Win64 должен быть no"
    assert 'Id="ProgramFilesFolder"' in xml32


def test_wxs_v3_codepages_allow_cyrillic(fake_build, tmp_path):
    """Русские строки должны проходить через light.

    При Language=1033 база MSI получает кодовую страницу 1252 без кириллицы, и
    сборка падает с LGHT0311 на имени автора и описании. Сводке при этом UTF-8
    не подходит: candle отвечает CNDL0349 и требует ANSI-страницу.
    """
    make_wxs = _load_packaging_module("make_wxs")
    out = tmp_path / "v3.wxs"
    make_wxs.main(["--source", str(fake_build), "--out", str(out),
                   "--wix-version", "3"])
    xml = out.read_text(encoding="utf-8")
    assert 'Codepage="65001"' in xml, "база MSI должна быть в UTF-8"
    assert 'SummaryCodepage="1251"' in xml, "сводке нужна ANSI-страница"
    assert 'Language="1049"' in xml
    assert 'SummaryCodepage="65001"' not in xml, \
        "UTF-8 в сводке — candle ответит CNDL0349"


def test_wxs_v4_stays_default(fake_build, tmp_path):
    """По умолчанию схема остаётся v4: её собирает CI."""
    make_wxs = _load_packaging_module("make_wxs")
    out = tmp_path / "v4.wxs"
    make_wxs.main(["--source", str(fake_build), "--out", str(out)])
    xml = out.read_text(encoding="utf-8")
    assert "wixtoolset.org/schemas/v4/wxs" in xml
    assert "<Package " in xml
    assert "<Product " not in xml, "Product — элемент схемы v3"


def test_wxs_ids_are_stable_between_runs(fake_build, tmp_path):
    """ID и GUID обязаны совпадать между сборками одной версии.

    Иначе установщик при обновлении удаляет и заново ставит все файлы, а в
    «Установке и удалении программ» появляются дубликаты.
    """
    make_wxs = _load_packaging_module("make_wxs")
    first, second = tmp_path / "a.wxs", tmp_path / "b.wxs"
    for path in (first, second):
        make_wxs.main(["--source", str(fake_build), "--out", str(path),
                       "--wix-version", "3"])
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_wix4_probe_survives_dotnet_without_sdk(monkeypatch):
    """Отсутствие .NET SDK — не ошибка, а повод перейти на WiX 3.

    Раньше функция бросала исключение, если SDK нет, и сборка MSI на этом
    заканчивалась: на машине с одним рантаймом установщик собрать было нельзя.
    """
    build_windows = _load_packaging_module("build_windows")

    monkeypatch.setattr(build_windows.shutil, "which",
                        lambda name: None if name == "wix" else "dotnet.exe")

    class _Probe:
        returncode = 0
        stdout = ""  # dotnet --list-sdks без SDK печатает пустоту

    monkeypatch.setattr(build_windows.subprocess, "run",
                        lambda *a, **kw: _Probe())
    assert build_windows._wix_command() is None


def test_wix3_dir_found_by_env(monkeypatch, tmp_path):
    """Распакованный wix314-binaries.zip нигде не регистрируется.

    Поэтому путь к нему задаётся переменной окружения, иначе собрать MSI без
    установки WiX (то есть без прав администратора) нельзя.
    """
    build_windows = _load_packaging_module("build_windows")

    for tool in ("candle.exe", "light.exe"):
        (tmp_path / tool).write_bytes(b"MZ")
    monkeypatch.setenv(build_windows.WIX3_ENV, str(tmp_path))
    monkeypatch.setattr(build_windows.shutil, "which", lambda name: None)
    assert build_windows._wix3_dir() == str(tmp_path)


def test_wix3_dir_ignores_incomplete_directory(monkeypatch, tmp_path):
    """Каталог с одним candle.exe не годится: light нужен для сборки MSI."""
    build_windows = _load_packaging_module("build_windows")

    (tmp_path / "candle.exe").write_bytes(b"MZ")
    monkeypatch.setenv(build_windows.WIX3_ENV, str(tmp_path))
    monkeypatch.setattr(build_windows.shutil, "which", lambda name: None)
    monkeypatch.delenv("WIX", raising=False)
    assert build_windows._wix3_dir() is None


def test_spec_common_puts_ffmpeg_into_bin():
    """ffmpeg должен попадать в bin: там его ищет paths.find_binary.

    Без вложенного ffmpeg загрузка падала на склейке видео с аудио, если в
    системе его нет.
    """
    sys.path.insert(0, PACKAGING_DIR)
    try:
        import spec_common
    finally:
        sys.path.pop(0)

    targets = {dest for _src, dest in spec_common._ffmpeg_datas()}
    if not targets:
        pytest.skip("ffmpeg не подготовлен в packaging/assets/ffmpeg")
    assert targets == {"bin"}, f"ffmpeg уходит не в bin: {targets}"
