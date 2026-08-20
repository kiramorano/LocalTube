"""End-to-end проверка отмены: реальный воркер очереди с подменённой загрузкой.

Сеть не используется: download_single_sync заменяется на медленную заглушку,
которая опрашивает should_cancel так же, как настоящий progress hook yt-dlp.
"""
import threading
import time

import pytest

import download_lib


@pytest.fixture
def worker_env(app_module, queue_file, monkeypatch):
    """Готовит окружение для запуска настоящего process_queue.

    build_video_map отключается: он сканирует реальную библиотеку после каждой
    задачи и замедляет тест. Задачи получают уникальные id, поэтому оставшиеся
    от предыдущего теста демон-потоки не мешают.
    """
    monkeypatch.setattr(app_module, "build_video_map", lambda: None)
    app_module.queue_tasks.clear()
    app_module.queue_cancel_requests.clear()
    app_module.queue_paused = False
    yield app_module
    # Убираем задачи, чтобы «вечные» воркеры прошлых тестов ничего не подхватили.
    app_module.queue_paused = True
    app_module.queue_tasks.clear()
    app_module.queue_cancel_requests.clear()


def start_real_worker(app_module):
    """Запускает настоящий process_queue как демон-поток.

    Это важно: тест должен проверять рабочий код, а не его копию в тесте.
    process_queue — бесконечный цикл, поэтому поток демонский и просто
    остаётся ждать задач после проверки.
    """
    thread = threading.Thread(target=app_module.process_queue, daemon=True)
    thread.start()
    return thread


def wait_for(predicate, timeout=8.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_cancel_stops_running_download(worker_env, monkeypatch):
    """Отмена должна прервать активную загрузку, а не дожидаться её конца."""
    app_module = worker_env
    started = threading.Event()

    def slow_download(urls, format_id, cb, merge_format="mp4", should_cancel=None):
        started.set()
        # Имитируем длинную загрузку с регулярной проверкой отмены (~4 с).
        for _ in range(200):
            if should_cancel and should_cancel():
                raise download_lib.DownloadCancelledByUser("cancelled")
            time.sleep(0.02)
        return True

    # process_queue вызывает имя, импортированное в app, поэтому патчим там.
    monkeypatch.setattr(app_module, "download_single_sync", slow_download)

    task = app_module.QueueTask("e2e", ["https://youtu.be/slow"], None, "Долгое видео")
    app_module.queue_tasks.append(task)
    start_real_worker(app_module)

    assert started.wait(5), "загрузка не началась"
    client = app_module.app.test_client()
    cancelled_at = time.time()
    assert client.post("/api/queue/cancel/e2e").get_json()["was_downloading"] is True

    assert wait_for(lambda: task.status == "cancelled", timeout=5), f"статус остался {task.status}"
    # Заглушка длится ~4 с; отмена обязана сработать заметно раньше.
    assert time.time() - cancelled_at < 2.5
    assert "e2e" not in app_module.queue_cancel_requests
    assert task.message == "Отменено пользователем"


def test_download_completes_without_cancel(worker_env, monkeypatch):
    app_module = worker_env
    monkeypatch.setattr(
        app_module, "download_single_sync",
        lambda urls, format_id, cb, merge_format="mp4", should_cancel=None: True,
    )

    task = app_module.QueueTask("ok", ["https://youtu.be/fast"], None, "Быстрое видео")
    app_module.queue_tasks.append(task)
    start_real_worker(app_module)

    assert wait_for(lambda: task.status == "completed"), f"статус остался {task.status}"


def test_failed_download_marked_as_error(worker_env, monkeypatch):
    app_module = worker_env
    monkeypatch.setattr(
        app_module, "download_single_sync",
        lambda urls, format_id, cb, merge_format="mp4", should_cancel=None: False,
    )

    task = app_module.QueueTask("bad", ["https://youtu.be/gone"], None, "Недоступное видео")
    app_module.queue_tasks.append(task)
    start_real_worker(app_module)

    assert wait_for(lambda: task.status == "error"), f"статус остался {task.status}"


def test_high_priority_task_runs_first(worker_env, monkeypatch):
    app_module = worker_env
    order = []
    gate = threading.Event()

    def track(urls, format_id, cb, merge_format="mp4", should_cancel=None):
        order.append(urls[0])
        gate.set()
        return True

    monkeypatch.setattr(app_module, "download_single_sync", track)

    # Обычная задача добавлена раньше, но срочная должна взяться первой.
    app_module.queue_tasks.append(app_module.QueueTask("n", ["normal"], None, "Обычная"))
    app_module.queue_tasks.append(app_module.QueueTask("h", ["urgent"], None, "Срочная", "mp4", "high"))

    start_real_worker(app_module)

    assert gate.wait(5), "ни одна задача не запустилась"
    assert order[0] == "urgent"


def test_paused_queue_does_not_start_tasks(worker_env, monkeypatch):
    app_module = worker_env
    calls = []
    monkeypatch.setattr(
        app_module, "download_single_sync",
        lambda urls, format_id, cb, merge_format="mp4", should_cancel=None: calls.append(urls) or True,
    )
    app_module.queue_paused = True

    task = app_module.QueueTask("p", ["https://youtu.be/x"], None, "На паузе")
    app_module.queue_tasks.append(task)
    start_real_worker(app_module)
    time.sleep(1.0)

    assert calls == []
    assert task.status == "waiting"
