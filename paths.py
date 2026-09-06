"""paths.py — где лежат файлы приложения.

Раньше каждый модуль считал корень проекта сам:
``os.path.dirname(os.path.abspath(__file__))``. Пока приложение запускали как
``python app.py``, это работало: исходники и данные лежали в одной папке. Для
собранных версий такое допущение ломается сразу в двух местах.

Во-первых, под PyInstaller ``__file__`` указывает внутрь распакованного
бандла (``sys._MEIPASS``), а в onefile это ещё и временный каталог, который
удаляется при выходе: библиотека, cookies и история пропадали бы после каждого
закрытия окна. Во-вторых, MSI, DEB и RPM ставят приложение в каталог только для
чтения (``C:\\Program Files``, ``/usr/lib``), поэтому писать рядом с
исполняемым файлом нельзя вообще.

Отсюда разделение на два корня:

``resource_dir()``
    Только чтение: шаблоны, статика, локали, исходники плагинов yt-dlp.
    В собранной версии это каталог бандла.

``data_dir()``
    Запись: config.json, cookies.txt, queue.json, userdata.json, access.json,
    логи, кэш картинок и сама библиотека видео.

Куда именно смотрит ``data_dir()``, зависит от режима сборки:

* портативная версия (portable.exe, AppImage, распакованный архив) держит
  данные рядом с собой — такую папку можно носить на флешке;
* установленная версия (MSI, DEB, RPM) пишет в профиль пользователя;
* ``LOCALTUBE_DATA_DIR`` перекрывает выбор в любом случае.

Портативность определяется файлом-маркером ``portable.txt`` рядом с
исполняемым файлом, а не догадками об имени каталога: сборщик кладёт маркер
явно, и поведение не зависит от того, куда пользователь распаковал архив.
"""
import os
import sys

# Имя каталога с данными в профиле пользователя и переменная-перекрытие.
APP_DIR_NAME = "LocalTube"
DATA_DIR_ENV = "LOCALTUBE_DATA_DIR"
# Маркер портативного режима: кладётся рядом с исполняемым файлом при сборке.
PORTABLE_MARKER = "portable.txt"

# Каталог исходников. Для запуска из репозитория он же и корень проекта.
_SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))


def is_frozen():
    """Собранная версия (PyInstaller), а не запуск из исходников."""
    return bool(getattr(sys, "frozen", False))


def resource_dir():
    """Каталог с файлами только для чтения.

    Под PyInstaller это ``sys._MEIPASS``: и в onedir, и в onefile шаблоны со
    статикой лежат именно там, а не рядом с exe.
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return _SOURCE_DIR


def app_dir():
    """Каталог рядом с исполняемым файлом.

    Для собранной версии — папка с exe (в onefile это не распакованный бандл, а
    место, откуда программу запустили), для исходников — корень проекта. Здесь
    ищется маркер портативного режима и вложенный ffmpeg.
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return _SOURCE_DIR


def is_portable():
    """Портативный режим: данные лежат рядом с приложением."""
    if os.environ.get(DATA_DIR_ENV):
        # Явно заданный каталог данных — это уже не портативный режим, а
        # ручное управление, и спрашивать про маркер незачем.
        return False
    if not is_frozen():
        # Запуск из исходников ведёт себя как раньше: всё в корне проекта.
        return True
    return os.path.exists(os.path.join(app_dir(), PORTABLE_MARKER))


def _user_data_dir():
    """Каталог данных в профиле пользователя, по правилам платформы."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if not base:
            # Обе переменные пусты только в сильно урезанном окружении;
            # домашний каталог есть всегда.
            base = os.path.expanduser("~")
        return os.path.join(base, APP_DIR_NAME)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                            APP_DIR_NAME)
    # Linux и прочие Unix: XDG_DATA_HOME, иначе ~/.local/share.
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"),
                                                           ".local", "share")
    return os.path.join(base, APP_DIR_NAME.lower())


def data_dir():
    """Каталог для записи: настройки, служебные JSON, логи, библиотека."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if is_portable():
        return app_dir()
    return _user_data_dir()


def ensure_data_dir():
    """Создаёт каталог данных и возвращает путь к нему."""
    path = data_dir()
    os.makedirs(path, exist_ok=True)
    return path


def data_path(*parts):
    """Путь внутри каталога данных."""
    return os.path.join(data_dir(), *parts)


def resource_path(*parts):
    """Путь внутри каталога ресурсов."""
    return os.path.join(resource_dir(), *parts)


def user_path(value, base=None):
    """Абсолютный путь к папке хранения из настроек.

    Относительные значения считаются от каталога данных, абсолютные
    (``D:/видео``) возвращаются как есть. Раньше эту роль играл
    ``os.path.join(SCRIPT_DIR, value)`` в app.py, из-за чего библиотека
    оказывалась внутри бандла.
    """
    root = base or data_dir()
    if not value:
        return root
    expanded = os.path.expanduser(str(value))
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(root, expanded)


# ================= ВНЕШНИЕ ПРОГРАММЫ =================
# ffmpeg вызывался по имени, то есть только из PATH. В портативной сборке и на
# свежей системе его там нет, и загрузка падала на склейке видео с аудио уже
# после скачивания. Поэтому сначала ищем копию внутри пакета.

def _binary_names(name):
    if sys.platform == "win32":
        return (name + ".exe", name)
    return (name,)


def _bundled_candidates(name):
    """Места, куда сборщик кладёт вложенные бинарники."""
    roots = [
        os.path.join(app_dir(), "bin"),
        app_dir(),
    ]
    if is_frozen():
        # onefile распаковывает данные в _MEIPASS, onedir держит их в _internal:
        # оба варианта ищем через resource_dir.
        roots.insert(0, os.path.join(resource_dir(), "bin"))
        roots.insert(1, resource_dir())
    for root in roots:
        for filename in _binary_names(name):
            yield os.path.join(root, filename)


def find_binary(name):
    """Путь к внешней программе: сначала вложенная копия, потом PATH.

    Возвращает None, если программы нет нигде: вызывающий код сам решает, что
    показать пользователю.
    """
    import shutil

    for candidate in _bundled_candidates(name):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which(name)


def ffmpeg_path():
    """Путь к ffmpeg; имя как есть, если найти не удалось.

    Возврат имени, а не None, оставляет прежнее поведение вызовов
    ``subprocess.run(['ffmpeg', ...])``: ошибка будет той же самой, что и
    раньше, а не TypeError на None.
    """
    return find_binary("ffmpeg") or "ffmpeg"


def ffprobe_path():
    """Путь к ffprobe; имя как есть, если найти не удалось."""
    return find_binary("ffprobe") or "ffprobe"


def ffmpeg_dir():
    """Каталог с ffmpeg — для параметра ffmpeg_location у yt-dlp.

    yt-dlp принимает каталог и сам находит в нём ffmpeg с ffprobe. Без этого
    postprocessor искал их только в PATH и падал на склейке.
    """
    found = find_binary("ffmpeg")
    if found and os.path.isabs(found):
        return os.path.dirname(found)
    return None
