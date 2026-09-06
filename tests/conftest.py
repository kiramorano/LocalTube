"""Общие фикстуры для тестов LocalTube.

Все тесты работают без обращения к сети. Реальные данные пользователя
(queue.json, avas/meta/*.json) изолируются: очередь пишется во временный файл,
метаданные тестовых каналов удаляются после прогона.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


@pytest.fixture(scope="session", autouse=True)
def _protect_real_queue_file(tmp_path_factory):
    """Уводит QUEUE_FILE во временный файл на весь прогон.

    Фикстура queue_file подменяла путь только на время одного теста, а тесты
    воркера оставляют демон-поток process_queue, который живёт до конца сессии.
    После восстановления monkeypatch такой поток продолжал вызывать save_queue()
    и писал уже в НАСТОЯЩИЙ queue.json пользователя, затирая его на
    {'paused': true, 'tasks': []}: очередь исчезала, а загрузка не шла, потому
    что оставалась пауза. Session-scope и autouse: подмена действует всегда,
    даже если конкретный тест не просил фикстуру queue_file.
    """
    import app as app_module

    safe = tmp_path_factory.mktemp("queue_guard") / "queue.json"
    app_module.QUEUE_FILE = str(safe)
    return str(safe)


@pytest.fixture(scope="session", autouse=True)
def _protect_real_cookies_file(tmp_path_factory):
    """Уводит COOKIES_PATH во временный файл на весь прогон.

    cookies.txt — дамп браузера пользователя, заново его так просто не собрать.
    Тест импорта cookies из браузера подменял путь только в app, а запись идёт
    ещё и из auth_options, и настоящий файл (172 КБ, 1256 записей) оказался
    затёрт тремя тестовыми записями. Session-scope и autouse: подмена
    действует всегда, во всех модулях, которые пишут этот файл.

    Копия настоящего файла кладётся во временный: тестам, которые читают
    cookies, содержимое остаётся доступным.
    """
    import shutil

    import app as app_module
    import auth_options
    import channel_assets
    import download_lib
    import downloader
    import worker
    import youtube_extractor

    safe = str(tmp_path_factory.mktemp("cookies_guard") / "cookies.txt")
    real = auth_options.COOKIES_PATH
    if os.path.exists(real):
        shutil.copyfile(real, safe)
    # Каждый модуль держит свой COOKIES_PATH, подменять нужно во всех: любой
    # непокрытый модуль пишет в настоящий файл. Список проверяется тестом
    # test_every_module_with_cookies_path_is_protected.
    for module in (app_module, auth_options, channel_assets, download_lib,
                   downloader, worker, youtube_extractor):
        module.COOKIES_PATH = safe
    return safe


@pytest.fixture(scope="session", autouse=True)
def _protect_real_userdata_file(tmp_path_factory):
    """Уводит USERDATA_FILE во временный файл на весь прогон.

    userdata.json хранит избранное, историю и свои плейлисты пользователя.
    Изоляция была только в фикстуре store из test_userdata.py, то есть в тестах,
    которые её явно просят. Любой другой тест, дошедший до эндпоинта
    /api/userdata*, писал в НАСТОЯЩИЙ файл. Session-scope и autouse: подмена
    действует всегда.

    Копия настоящего файла кладётся во временный: тестам, которые читают
    существующие данные, содержимое остаётся доступным.
    """
    import shutil

    import userdata

    safe = str(tmp_path_factory.mktemp("userdata_guard") / "userdata.json")
    real = userdata.USERDATA_FILE
    if os.path.exists(real):
        shutil.copyfile(real, safe)
    userdata.USERDATA_FILE = safe
    userdata.reload_from_disk()
    return safe


@pytest.fixture(scope="session", autouse=True)
def _protect_real_config_file(tmp_path_factory):
    """Уводит CONFIG_FILE во временный файл на весь прогон.

    config.json хранит пути библиотеки, настройки авторизации YouTube и языковые
    дорожки. Изоляция была только в фикстурах отдельных файлов тестов, поэтому
    любой другой тест, дошедший до сохранения настроек, писал в рабочий файл
    пользователя: так в него попали разделы «youtube_auth» и «downloads» с
    тестовыми значениями.

    Копия настоящего файла кладётся во временный: тестам, которые читают пути
    библиотеки, содержимое остаётся доступным. Список модулей проверяется тестом
    test_every_module_with_config_file_is_protected — каждый держит свою копию
    пути, и непокрытый модуль снова писал бы в настоящий файл.
    """
    import shutil

    import app as app_module
    import auth_options
    import download_prefs
    import worker

    safe = str(tmp_path_factory.mktemp("config_guard") / "config.json")
    real = auth_options.CONFIG_FILE
    if os.path.exists(real):
        shutil.copyfile(real, safe)
    for module in (app_module, auth_options, download_prefs, worker):
        module.CONFIG_FILE = safe
    return safe


@pytest.fixture(scope="session", autouse=True)
def _protect_real_access_file(tmp_path_factory):
    """Уводит ACCESS_FILE во временный файл на весь прогон.

    access.json хранит PIN доступа из локальной сети и секрет для ключей
    устройств. Тесты меняют и PIN, и тумблер доступа: без изоляции прогон
    отключал бы уже впущенные устройства пользователя и мог оставить сервер
    закрытым для сети.
    """
    import access

    safe = str(tmp_path_factory.mktemp("access_guard") / "access.json")
    access.ACCESS_FILE = safe
    access.reload_from_disk()
    return safe


@pytest.fixture(autouse=True)
def real_try_fetch_if_missing(monkeypatch):
    """Запрещает фоновую догрузку данных канала во всех тестах.

    Открытие /channel/<author> поднимает поток try_fetch_if_missing, который
    идёт в YouTube и пишет статус в реальные avas/meta/*.json. Поток живёт
    дольше самого теста, поэтому загрязнение проявлялось в произвольном месте
    прогона и выглядело как чужая ошибка.

    Возвращает исходную функцию: тесты самой догрузки вызывают её напрямую.
    """
    import channel_assets

    original = channel_assets.try_fetch_if_missing
    monkeypatch.setattr(channel_assets, "try_fetch_if_missing", lambda author: None)
    return original


@pytest.fixture(scope="session", autouse=True)
def _protect_real_video_dir(tmp_path_factory):
    """Уводит каталог загрузки из настоящей библиотеки во временный.

    Вторая линия обороны к _no_background_queue_worker: если задача всё-таки
    дойдёт до загрузчика, файлы лягут во временную папку, а не в библиотеку
    пользователя. Так там уже появились каталоги videos/<Автор>/vid403/_tmp_*.

    Подменяем именно load_config в download_lib: тесты, которым нужен свой
    каталог, переопределяют его через monkeypatch поверх этой фикстуры.
    Оригинал остаётся доступен как download_lib._real_load_config — его читают
    тесты, сверяющие пути между модулями.
    """
    import download_lib

    tmp_videos = tmp_path_factory.mktemp("videos_guard")
    original = download_lib.load_config
    download_lib._real_load_config = original
    download_lib.load_config = lambda: {**original(), "video_dir": str(tmp_videos)}
    yield str(tmp_videos)
    download_lib.load_config = original
    del download_lib._real_load_config


@pytest.fixture(autouse=True)
def _no_background_queue_worker(monkeypatch, request):
    """Запрещает фоновый воркер очереди во всех тестах.

    POST /api/queue/add вызывает ensure_queue_worker, и настоящий воркер уходит
    качать добавленное через настоящий yt-dlp. Тест уникальности id добавлял 200
    задач с адресом https://youtu.be/same — воркер честно шёл в сеть и оставлял
    ключ в download_lib.download_locks, потому что поток живёт дольше самого
    теста. Дальше это выглядело как чужая ошибка: лок, снятый в другом файле
    тестов, и каталоги _tmp_* в рабочей библиотеке.

    Тесты воркера запускают process_queue напрямую через start_real_worker,
    поэтому им эта заглушка не мешает. Тестам самой ensure_queue_worker нужна
    настоящая функция: они помечаются @pytest.mark.real_queue_worker.
    """
    import app as app_module

    if request.node.get_closest_marker("real_queue_worker"):
        return
    monkeypatch.setattr(app_module, "ensure_queue_worker", lambda: None)


@pytest.fixture(autouse=True)
def _isolate_channel_meta(tmp_path_factory, monkeypatch):
    """Уводит запись метаданных каналов во временный каталог.

    Эндпоинты синхронизации пишут статус в avas/meta/*.json по реальному имени
    автора. Без изоляции прогон тестов оставлял в рабочих файлах статус
    checking, из-за которого кнопка обновления канала блокировалась.

    Чтение остаётся рабочим: если файла нет во временном каталоге, берём копию
    из настоящего.
    """
    import shutil
    import channel_assets

    real_meta = channel_assets.META_DIR
    tmp_meta = tmp_path_factory.mktemp("meta")
    if os.path.isdir(real_meta):
        for name in os.listdir(real_meta):
            if name.endswith(".json"):
                shutil.copyfile(os.path.join(real_meta, name),
                                os.path.join(str(tmp_meta), name))
    monkeypatch.setattr(channel_assets, "META_DIR", str(tmp_meta))
    yield str(tmp_meta)


@pytest.fixture(scope="session")
def app_module():
    import app as app_module
    return app_module


@pytest.fixture(scope="session")
def channel_assets():
    import channel_assets
    return channel_assets


@pytest.fixture
def queue_file(tmp_path, app_module, monkeypatch):
    """Подменяет queue.json временным файлом и очищает состояние очереди.

    Тесты воркера запускают process_queue как демон-поток, который живёт до
    конца сессии. Ставим очередь на паузу, чтобы такой поток не подхватывал
    задачи следующих тестов.
    """
    path = tmp_path / "queue.json"
    monkeypatch.setattr(app_module, "QUEUE_FILE", str(path))
    monkeypatch.setattr(app_module, "queue_tasks", [], raising=False)
    monkeypatch.setattr(app_module, "queue_paused", False, raising=False)
    app_module.queue_cancel_requests.clear()
    yield path
    # Пауза на выходе: демон-воркер из тестов process_queue не должен
    # подхватывать задачи следующего теста.
    app_module.queue_paused = True
    app_module.queue_tasks.clear()
    app_module.queue_cancel_requests.clear()


@pytest.fixture
def client(app_module, queue_file):
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


@pytest.fixture
def test_author(channel_assets):
    """Имя тестового канала; его метаданные удаляются после теста."""
    author = "__localtube_test_channel__"

    def cleanup():
        safe = channel_assets.safe_name(author)
        meta = os.path.join(channel_assets.META_DIR, safe + ".json")
        paths = [
            meta,
            # Атомарная запись оставляет .bak и может оставить .tmp: без их
            # удаления следующий тест прочитает данные предыдущего.
            meta + ".bak",
            meta + ".tmp",
        ]
        # Картинки: расширение зависит от content-type, поэтому перечисляем все
        # возможные. Раньше чистился только avas/<автор>.jpg, и проверка шапок
        # оставляла файл в настоящем каталоге пользователя.
        for directory in (channel_assets.CHANNEL_ASSETS_DIR, channel_assets.BANNERS_DIR):
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                paths.append(os.path.join(directory, safe + ext))
        for path in paths:
            if os.path.exists(path):
                os.remove(path)

    cleanup()
    yield author
    cleanup()
    with channel_assets._fetch_lock:
        channel_assets._fetching.discard(author)
