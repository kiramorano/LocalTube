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
        meta = os.path.join(channel_assets.META_DIR,
                            channel_assets.safe_name(author) + ".json")
        for path in (
            meta,
            # Атомарная запись оставляет .bak и может оставить .tmp: без их
            # удаления следующий тест прочитает данные предыдущего.
            meta + ".bak",
            meta + ".tmp",
            os.path.join(channel_assets.CHANNEL_ASSETS_DIR, channel_assets.safe_name(author) + ".jpg"),
        ):
            if os.path.exists(path):
                os.remove(path)

    cleanup()
    yield author
    cleanup()
    with channel_assets._fetch_lock:
        channel_assets._fetching.discard(author)
