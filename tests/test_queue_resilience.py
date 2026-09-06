"""Устойчивость очереди: воркер не умирает, отмена не теряется, прогресс честный.

Сеть не используется: download_single_sync и build_video_map подменяются.
Каждая проверка воспроизводит конкретный сбой, найденный в рабочем коде.
"""
import os
import threading
import time
from pathlib import Path

import pytest

import download_lib
from download_lib import DownloadOutcome

from test_queue_worker import start_real_worker, wait_for, worker_env  # noqa: F401


# --- Воркер не должен умирать ---

def test_worker_survives_scan_failure(worker_env, monkeypatch):
    """Ошибка пересканирования библиотеки не должна останавливать очередь.

    build_video_map() вызывался вне try/except, и любая ошибка файловой системы
    убивала единственный поток очереди: следующие задачи навсегда оставались в
    статусе waiting, а /api/queue/add продолжал отвечать 200.
    """
    app_module = worker_env
    monkeypatch.setattr(app_module, "download_single_sync",
                        lambda urls, fmt, cb, merge_format="mp4", should_cancel=None: True)

    def boom():
        raise OSError(22, "simulated scandir failure")

    monkeypatch.setattr(app_module, "build_video_map", boom)

    first = app_module.QueueTask("scan1", ["https://youtu.be/a"], None, "Первая")
    app_module.queue_tasks.append(first)
    worker = start_real_worker(app_module)

    assert wait_for(lambda: first.status == "completed"), f"статус {first.status}"

    second = app_module.QueueTask("scan2", ["https://youtu.be/b"], None, "Вторая")
    app_module.queue_tasks.append(second)

    assert wait_for(lambda: second.status == "completed"), (
        f"воркер умер после ошибки сканирования, статус {second.status}")
    assert worker.is_alive()


@pytest.mark.real_queue_worker
def test_ensure_worker_restarts_dead_thread(app_module, queue_file, monkeypatch):
    """Упавший воркер должен подниматься заново.

    Раньше флаг _queue_worker_started оставался поднятым навсегда, и очередь
    замирала до перезапуска процесса.
    """
    monkeypatch.setattr(app_module, "_queue_worker_thread", None, raising=False)
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    monkeypatch.setattr(app_module, "_queue_worker_thread", dead, raising=False)
    monkeypatch.setattr(app_module, "process_queue", lambda: time.sleep(5))

    thread = app_module.ensure_queue_worker()

    assert thread is not dead
    assert thread.is_alive()


@pytest.mark.real_queue_worker
def test_ensure_worker_reuses_live_thread(app_module, queue_file, monkeypatch):
    monkeypatch.setattr(app_module, "process_queue", lambda: time.sleep(5))
    monkeypatch.setattr(app_module, "_queue_worker_thread", None, raising=False)

    first = app_module.ensure_queue_worker()
    second = app_module.ensure_queue_worker()

    assert first is second


# --- Отмена ---

def test_cancel_during_postprocessing_is_respected(worker_env, monkeypatch):
    """Отмена на этапе склейки не должна теряться.

    После последнего байта yt-dlp больше не вызывает хуки прогресса, поэтому
    should_cancel() не опрашивается. Успешный возврат затирал волю пользователя,
    и задача помечалась как «Готово».
    """
    app_module = worker_env
    merging = threading.Event()
    release = threading.Event()

    def fake_download(urls, fmt, cb, merge_format="mp4", should_cancel=None):
        cb(50, "Загрузка: 50%")
        merging.set()
        release.wait(10)
        return DownloadOutcome(1, 0)

    monkeypatch.setattr(app_module, "download_single_sync", fake_download)

    task = app_module.QueueTask("merge1", ["https://youtu.be/m"], None, "Склейка")
    app_module.queue_tasks.append(task)
    start_real_worker(app_module)

    assert merging.wait(5), "загрузка не началась"
    client = app_module.app.test_client()
    assert client.post("/api/queue/cancel/merge1").get_json()["was_downloading"] is True
    release.set()

    assert wait_for(lambda: task.status in ("cancelled", "completed"), timeout=5)
    assert task.status == "cancelled", "отмена во время склейки потеряна"
    assert "merge1" not in app_module.queue_cancel_requests


def test_cancel_flag_cleared_on_success(worker_env, monkeypatch):
    """Флаг отмены не должен оставаться в наборе после успешной загрузки."""
    app_module = worker_env
    monkeypatch.setattr(app_module, "download_single_sync",
                        lambda urls, fmt, cb, merge_format="mp4", should_cancel=None: DownloadOutcome(1, 0))

    app_module.queue_cancel_requests.add("leak1")
    task = app_module.QueueTask("leak1", ["https://youtu.be/x"], None, "Утечка")
    app_module.queue_tasks.append(task)
    start_real_worker(app_module)

    assert wait_for(lambda: task.status in ("completed", "cancelled"))
    assert "leak1" not in app_module.queue_cancel_requests


def test_retry_rejects_active_task(client, app_module):
    """/retry на активной задаче снимал флаг отмены и делал её неотменяемой."""
    task = app_module.QueueTask("act1", ["u"], None, "Активная")
    task.status = "downloading"
    app_module.queue_tasks.append(task)
    app_module.queue_cancel_requests.add("act1")

    res = client.post("/api/queue/retry/act1")

    assert res.status_code == 409
    assert "act1" in app_module.queue_cancel_requests, "флаг отмены сброшен"
    assert task.status == "downloading"


def test_retry_allows_failed_task(client, app_module):
    # Пауза обязательна: демон-воркеры прошлых тестов живут до конца сессии и
    # иначе успевают перевести задачу в downloading до проверки.
    app_module.queue_paused = True
    task = app_module.QueueTask("err1", ["u"], None, "Упавшая")
    task.status = "error"
    app_module.queue_tasks.append(task)

    assert client.post("/api/queue/retry/err1").status_code == 200
    assert task.status == "waiting"


def test_retry_allows_partial_task(client, app_module):
    """Частично скачанную задачу тоже надо уметь повторять.

    Со статусом completed до неё не доставали ни кнопка, ни массовый повтор,
    и дозагрузить пропущенные видео было нечем.
    """
    app_module.queue_paused = True
    task = app_module.QueueTask("part1", ["u"], None, "Частичная")
    task.status = "partial"
    app_module.queue_tasks.append(task)

    assert client.post("/api/queue/retry/part1").status_code == 200
    assert task.status == "waiting"


def test_retry_resets_position_and_metrics(client, app_module):
    """После повтора оставался номер видео и метрики прошлой попытки.

    Пользователь видел «Видео 11/79 · 1.5MiB/s» у ожидающей задачи и ждал
    докачки остатка, хотя загрузка начинается с первого видео.
    """
    app_module.queue_paused = True
    task = app_module.QueueTask("pos1", ["u1", "u2"], None, "Позиция")
    task.status = "error"
    task.current_index = 11
    task.current_url = "u2"
    task.speed = "1.50MiB/s"
    task.eta = "00:12"
    app_module.queue_tasks.append(task)

    client.post("/api/queue/retry/pos1")

    assert task.current_index == 0
    assert task.current_url == ""
    assert task.speed == ""
    assert task.eta == ""


@pytest.mark.parametrize("call", [
    lambda c: c.post("/api/queue/add", json={"urls": ["https://youtu.be/x"]}),
    lambda c: c.post("/api/queue/pause"),
    lambda c: c.post("/api/queue/resume"),
    lambda c: c.post("/api/queue/clear"),
])
def test_disk_failure_is_reported(client, app_module, monkeypatch, call):
    """Сбой записи очереди отвечал 200 «ok», и задача исчезала после перезапуска.

    write_json_atomic специально бросает JsonWriteError, но save_queue гасил
    его в лог, и все эндпоинты подтверждали успех.
    """
    def boom(*args, **kwargs):
        raise OSError("Нет места на диске")

    monkeypatch.setattr(app_module, "write_json_atomic", boom)

    res = call(client)

    assert res.status_code == 500
    assert "не сохранена" in res.get_json()["error"].lower()


def test_save_queue_reports_error(app_module, monkeypatch):
    """save_queue должен возвращать причину, а не молчать."""
    monkeypatch.setattr(app_module, "write_json_atomic",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("диск отключён")))

    assert "диск отключён" in app_module.save_queue()


def test_save_queue_returns_empty_on_success(app_module, queue_file):
    assert app_module.save_queue() == ""


def test_remove_does_not_free_hung_download(worker_env, monkeypatch):
    """«Удалить» не прерывает зависшую загрузку, только убирает её из списка.

    Кооперативная отмена читается лишь из хуков прогресса; в неотменяемом
    участке (склейка ffmpeg, сетевой запрос без таймаута) её никто не увидит.
    Воркер один, поэтому такая загрузка держит очередь — именно из-за этого
    у ffmpeg и у запроса метаданных должен быть свой предел по времени.
    """
    app_module = worker_env
    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()

    def hung_download(urls, fmt, cb, merge_format="mp4", should_cancel=None):
        # should_cancel не опрашиваем: имитируем участок без хуков прогресса.
        entered.set()
        release.wait(10)
        returned.set()
        return DownloadOutcome(1, 0)

    monkeypatch.setattr(app_module, "download_single_sync", hung_download)

    stuck = app_module.QueueTask("hung1", ["https://youtu.be/hang"], None, "Зависшая")
    app_module.queue_tasks.append(stuck)
    start_real_worker(app_module)

    assert entered.wait(5), "загрузка не началась"
    client = app_module.app.test_client()
    assert client.delete("/api/queue/remove/hung1").status_code == 200

    # Ключевое: запрос вернулся, а загрузка всё ещё внутри вызова.
    time.sleep(0.5)
    assert not returned.is_set(), (
        "тест устарел: удаление стало прерывать активную загрузку")

    release.set()
    assert returned.wait(5), "загрузка не завершилась после разблокировки"


def test_real_queue_file_is_never_used_in_tests(app_module):
    """Тесты не должны писать в настоящий queue.json пользователя.

    Демон-поток process_queue живёт до конца сессии. Когда monkeypatch
    возвращал QUEUE_FILE на место, такой поток продолжал вызывать save_queue()
    и затирал рабочую очередь на {'paused': true, 'tasks': []}: задачи
    исчезали, а загрузка не шла из-за оставшейся паузы.
    """
    real = Path(__file__).resolve().parent.parent / "queue.json"
    assert Path(app_module.QUEUE_FILE).resolve() != real.resolve(), \
        f"QUEUE_FILE указывает на рабочий файл: {app_module.QUEUE_FILE}"


def test_real_video_dir_is_never_used_in_tests():
    """Тесты не должны качать в настоящую библиотеку пользователя.

    Загрузчик берёт каталог из своего load_config, а не из app.BASE_VIDEO_DIR,
    поэтому подмена конфига в app ничего не решала: в рабочей библиотеке
    появились каталоги videos/<Автор>/vid403/_tmp_* от тестов очереди.
    """
    real = Path(__file__).resolve().parent.parent / "videos"
    used = Path(os.path.dirname(os.path.abspath(download_lib.__file__)))
    used = used / download_lib.load_config()["video_dir"]
    assert used.resolve() != real.resolve(), \
        f"загрузчик пишет в рабочую библиотеку: {used}"


def test_background_worker_is_disabled_in_tests(app_module):
    """Фоновый воркер очереди в тестах должен быть отключён.

    POST /api/queue/add вызывает ensure_queue_worker, и настоящий воркер уходит
    качать добавленное через yt-dlp. Тест уникальности id добавлял 200 задач с
    https://youtu.be/same, воркер честно шёл в сеть и оставлял ключ в
    download_lib.download_locks: поток живёт дольше теста, поэтому лок
    «всплывал» в других файлах тестов, а в рабочей библиотеке появлялись
    каталоги videos/<Автор>/vid403/_tmp_*.

    Проверяем саму заглушку, а не появление файлов: поток успевает натворить
    дел уже после проверки, и сторож по файлам был бы ненадёжным.
    """
    before = app_module._queue_worker_thread

    started = app_module.ensure_queue_worker()

    assert started is None, "ensure_queue_worker подняла настоящий поток"
    assert app_module._queue_worker_thread is before, (
        "ссылка на воркер изменилась: заглушка не действует"
    )


def test_stream_and_merge_have_time_limits():
    """У неотменяемых участков должен быть предел по времени.

    Без него зависший ffmpeg или сетевой запрос занимает единственный поток
    очереди навсегда, и отмена из интерфейса ничего не даёт.
    """
    assert download_lib.FFMPEG_TIMEOUT > 0
    assert hasattr(download_lib, "install_ffmpeg_timeout")


def test_list_starts_worker(client, app_module, monkeypatch):
    """При запуске не через `python app.py` воркер не существовал вовсе.

    Восстановленные после перезапуска задачи оставались в «Ожидание», и
    открытие раздела «Очередь» ничего не меняло.
    """
    started = []
    monkeypatch.setattr(app_module, "ensure_queue_worker", lambda: started.append(True))

    client.get("/api/queue/list")

    assert started, "/api/queue/list не поднимает воркер"


def test_stuck_download_can_be_removed(client, app_module):
    """У зависшей задачи не оставалось ни одной рабочей кнопки.

    Отмена только выставляет cancelling, а если yt-dlp завис, флаг никто не
    прочитает. Удаление активной задачи должно работать как аварийный выход.
    """
    app_module.queue_paused = True
    task = app_module.QueueTask("stuck", ["u"], None, "Зависшая")
    task.status = "downloading"
    task.cancelling = True
    app_module.queue_tasks.append(task)

    res = client.delete("/api/queue/remove/stuck")

    assert res.status_code == 200
    assert all(t.id != "stuck" for t in app_module.queue_tasks)


def test_remove_clears_flag_of_inactive_task(client, app_module):
    task = app_module.QueueTask("rm1", ["u"], None, "Ожидающая")
    app_module.queue_tasks.append(task)
    app_module.queue_cancel_requests.add("rm1")

    client.delete("/api/queue/remove/rm1")

    assert "rm1" not in app_module.queue_cancel_requests


def test_remove_sets_flag_of_active_task(client, app_module):
    """Удаление активной задачи обязано остановить загрузчик."""
    task = app_module.QueueTask("rm2", ["u"], None, "Активная")
    task.status = "downloading"
    app_module.queue_tasks.append(task)

    assert client.delete("/api/queue/remove/rm2").get_json()["cancelled_active"] is True
    assert "rm2" in app_module.queue_cancel_requests


# --- Восстановление после перезапуска ---

def test_interrupted_download_returns_to_queue(app_module, tmp_path, monkeypatch):
    """Задача в статусе downloading после перезапуска зависала навсегда.

    Ни отмена, ни повтор, ни удаление не были доступны в интерфейсе.
    """
    from utils import write_json_atomic

    # load_queue переприсваивает app.queue_tasks, поэтому паузу ставим до вызова:
    # иначе демон-воркер прошлых тестов подхватит восстановленную задачу.
    app_module.queue_paused = True
    path = tmp_path / "queue.json"
    write_json_atomic(str(path), {"paused": True, "tasks": [
        {"id": "stuck", "urls": ["u"], "format_id": None, "title": "T",
         "status": "downloading", "progress": 42,
         "speed": "1.50MiB/s", "eta": "00:12"},
    ]}, backup=False)
    monkeypatch.setattr(app_module, "QUEUE_FILE", str(path))

    original = app_module.queue_tasks
    try:
        app_module.load_queue()
        restored = [t for t in app_module.queue_tasks if t.id == "stuck"]
        assert restored, "задача не загрузилась"
        task = restored[0]
        assert task.status == "waiting"
        assert task.progress == 0
        assert "перезапуска" in task.message
        # Скорость и ETA относились к прерванной загрузке.
        assert task.speed == ""
        assert task.eta == ""
    finally:
        app_module.queue_tasks = original


# --- Отчётность ---

@pytest.mark.parametrize("outcome,status,in_message", [
    (DownloadOutcome(20, 0), "completed", "Готово"),
    # Частичный провал — отдельный статус: при completed до задачи не доставали
    # ни кнопка «Повторить», ни фильтр «С ошибками», ни массовый повтор.
    (DownloadOutcome(1, 19), "partial", "19 из 20"),
    (DownloadOutcome(0, 20), "error", "Ошибка"),
    (True, "completed", "Готово"),
    (False, "error", "Ошибка"),
])
def test_partial_failure_is_reported(worker_env, monkeypatch, outcome, status, in_message):
    """1 успех из 20 показывался как «Готово», а поле error очищалось."""
    app_module = worker_env
    monkeypatch.setattr(app_module, "download_single_sync",
                        lambda urls, fmt, cb, merge_format="mp4", should_cancel=None: outcome)

    # Ссылок столько же, сколько в outcome: сообщение считает размер задачи,
    # поэтому список из одной ссылки на 20 результатов был противоречивым.
    urls = ["https://youtu.be/x%d" % i for i in range(20)]
    task = app_module.QueueTask("rep", urls, None, "Отчёт")
    app_module.queue_tasks.append(task)
    start_real_worker(app_module)

    assert wait_for(lambda: task.status in ("completed", "error", "partial")), f"статус {task.status}"
    assert task.status == status
    assert in_message in task.message


def test_outcome_is_falsy_without_successes():
    """DownloadOutcome должен вести себя как bool: старые вызовы полагаются на это."""
    assert not DownloadOutcome(0, 5)
    assert DownloadOutcome(1, 5)
    assert DownloadOutcome(3, 0).succeeded == 3
    assert DownloadOutcome(3, 2).failed == 2


def test_outcome_carries_error_text():
    """Текст ошибки нужен очереди, чтобы показать причину вместо заглушки."""
    outcome = DownloadOutcome(0, 1, "HTTP Error 403: Forbidden")
    assert outcome.last_error == "HTTP Error 403: Forbidden"
    assert DownloadOutcome(1, 0).last_error == ""


def test_failure_reason_reaches_queue_task(worker_env, monkeypatch):
    """В очереди всегда было «Ошибка скачивания» без настоящей причины."""
    app_module = worker_env
    outcome = DownloadOutcome(0, 1, "HTTP Error 403: Forbidden")
    monkeypatch.setattr(app_module, "download_single_sync",
                        lambda urls, fmt, cb, merge_format="mp4", should_cancel=None: outcome)

    task = app_module.QueueTask("why", ["https://youtu.be/x"], None, "Причина")
    app_module.queue_tasks.append(task)
    start_real_worker(app_module)

    assert wait_for(lambda: task.status == "error"), f"статус {task.status}"
    assert "403" in task.error, task.error


def test_skipped_videos_are_reported(worker_env, monkeypatch):
    """Пропуск уже скачанного должен быть виден, а не выглядеть как загрузка."""
    app_module = worker_env
    outcome = DownloadOutcome(5, 0, "", 5)
    monkeypatch.setattr(app_module, "download_single_sync",
                        lambda urls, fmt, cb, merge_format="mp4", should_cancel=None: outcome)

    task = app_module.QueueTask("skip", ["https://youtu.be/x"], None, "Пропуск")
    app_module.queue_tasks.append(task)
    start_real_worker(app_module)

    assert wait_for(lambda: task.status == "completed"), f"статус {task.status}"
    assert "уже" in task.message.lower(), task.message


def test_add_rejects_empty_urls_with_error_code(client):
    """Отказ приходил с кодом 200, и клиент по res.ok считал его успехом."""
    res = client.post("/api/queue/add", json={"urls": []})

    assert res.status_code == 400
    assert "error" in res.get_json()


@pytest.mark.parametrize("kwargs", [
    {},
    {"json": {}},
    {"json": {"urls": []}},
    {"data": "x", "content_type": "text/plain"},
    {"json": {"urls": ["", "   ", None]}},
])
def test_add_always_answers_json(client, kwargs):
    """Запрос без Content-Type отдавал HTML-страницу 415, и клиент падал на res.json()."""
    res = client.post("/api/queue/add", **kwargs)

    assert res.status_code == 400
    assert res.content_type.startswith("application/json")
    assert "error" in res.get_json()


def test_add_accepts_single_url_as_string(client, app_module):
    res = client.post("/api/queue/add", json={"urls": "https://youtu.be/a"})

    assert res.status_code == 200
    task = next(t for t in app_module.queue_tasks if t.id == res.get_json()["task_id"])
    assert task.urls == ["https://youtu.be/a"]


def test_add_drops_blank_urls(client, app_module):
    res = client.post("/api/queue/add", json={"urls": ["https://youtu.be/a", "", "  "]})

    task = next(t for t in app_module.queue_tasks if t.id == res.get_json()["task_id"])
    assert task.urls == ["https://youtu.be/a"]


def test_add_accepts_payload_from_header_field(client, app_module):
    """Полезная нагрузка кнопки в хедере главной должна приниматься как есть.

    Поле ссылки отправляет urls, title и format_id, собранный по выбранному
    качеству. Проверяем, что задача создаётся именно с этими значениями.
    """
    res = client.post("/api/queue/add", json={
        "urls": ["https://www.youtube.com/watch?v=jNQXAC9IVRw"],
        "title": "Загрузка по ссылке",
        "format_id": "bestvideo[height<=720]+bestaudio/best",
    })

    assert res.status_code == 200
    task = next(t for t in app_module.queue_tasks if t.id == res.get_json()["task_id"])
    assert task.urls == ["https://www.youtube.com/watch?v=jNQXAC9IVRw"]
    assert task.title == "Загрузка по ссылке"
    assert task.format_id == "bestvideo[height<=720]+bestaudio/best"


def test_add_without_format_id_keeps_auto_quality(client, app_module):
    """Качество «Максимум» не передаёт format_id: качество выбирает загрузчик."""
    res = client.post("/api/queue/add", json={
        "urls": ["https://youtu.be/jNQXAC9IVRw"],
        "title": "Загрузка по ссылке",
    })

    assert res.status_code == 200
    task = next(t for t in app_module.queue_tasks if t.id == res.get_json()["task_id"])
    assert task.format_id is None, task.format_id


def test_task_ids_are_unique(client, app_module):
    """md5(time.time() + url) давал одинаковые id при быстрых добавлениях."""
    ids = [client.post("/api/queue/add", json={"urls": ["https://youtu.be/same"], "title": "x"})
           .get_json()["task_id"] for _ in range(200)]

    assert len(set(ids)) == 200


# --- Прогресс ---

def test_percent_ignores_ansi_colors():
    """yt-dlp раскрашивает _percent_str, из-за чего float() падал и прогресс был 0."""
    assert download_lib._percent_from_hook({"_percent_str": "\x1b[0;94m 45.3%\x1b[0m"}) == 45.3


def test_percent_prefers_byte_counts():
    percent = download_lib._percent_from_hook({
        "_percent_str": "\x1b[0;94m 45.3%\x1b[0m",
        "downloaded_bytes": 2_500_000, "total_bytes": 10_000_000,
    })

    assert percent == 25.0


@pytest.mark.parametrize("hook", [
    {"_percent_str": "n/a"},
    {"_percent_str": None},
    {},
    {"downloaded_bytes": 5, "total_bytes": 0},
])
def test_percent_falls_back_to_zero(hook):
    assert download_lib._percent_from_hook(hook) == 0


def test_strip_ansi_cleans_speed_and_eta():
    """Escape-последовательности уезжали в интерфейс через speed и eta задачи."""
    assert download_lib.strip_ansi("\x1b[0;32m   1.50MiB/s\x1b[0m").strip() == "1.50MiB/s"
    assert download_lib.strip_ansi("\x1b[0;33m00:12\x1b[0m") == "00:12"
    assert download_lib.strip_ansi("") == ""


def test_progress_message_survives_round_trip(worker_env, monkeypatch):
    """Строку прогресса собирает download_lib, а разбирает регуляркой app.

    Контракт между файлами неявный: достаточно поменять разделитель в одном
    месте, чтобы скорость и ETA молча перестали доходить до интерфейса.
    Здесь строка формируется настоящим хуком yt-dlp, включая ANSI-раскраску.
    """
    app_module = worker_env
    captured = []
    task = app_module.QueueTask("fmt1", ["https://youtu.be/x"], None, "Формат")

    def fake_download(urls, fmt, cb, merge_format="mp4", should_cancel=None):
        # Ровно то, что делает internal_hook в download_lib, обёрнутое в sub_cb.
        hook_status = {
            "status": "downloading",
            "downloaded_bytes": 4_530_000, "total_bytes": 10_000_000,
            "_percent_str": "\x1b[0;94m 45.3%\x1b[0m",
            "_speed_str": "\x1b[0;32m   1.50MiB/s\x1b[0m",
            "_eta_str": "\x1b[0;33m00:12\x1b[0m",
        }
        percent = download_lib._percent_from_hook(hook_status)
        speed = download_lib.strip_ansi(hook_status["_speed_str"]).strip()
        eta = download_lib.strip_ansi(hook_status["_eta_str"]).strip()
        message = f"[3/20] Загрузка: {percent:.1f}% · {speed} · ETA {eta}"
        captured.append(message)
        cb(percent, message)
        # Снимок нужен именно здесь: завершение задачи обнуляет speed и eta.
        captured.append({
            "percent": percent,
            "index": task.current_index, "total": task.total_urls,
            "speed": task.speed, "eta": task.eta,
        })
        return DownloadOutcome(1, 0)

    monkeypatch.setattr(app_module, "download_single_sync", fake_download)

    app_module.queue_tasks.append(task)
    start_real_worker(app_module)

    assert wait_for(lambda: task.status == "completed"), f"статус {task.status}"

    message, snapshot = captured
    # В сообщении не должно остаться escape-последовательностей.
    assert "\x1b" not in message
    # Процент считается из байтов, а не из раскрашенной строки.
    assert snapshot["percent"] == pytest.approx(45.3, abs=0.05)
    # app.update_progress обязан вытащить из строки все величины.
    assert (snapshot["index"], snapshot["total"]) == (3, 20)
    assert snapshot["speed"] == "1.50MiB/s"
    assert snapshot["eta"] == "00:12"


def test_merge_message_does_not_set_speed(worker_env, monkeypatch):
    """У этапа склейки нет скорости: регулярка не должна ничего подставлять."""
    app_module = worker_env

    def fake_download(urls, fmt, cb, merge_format="mp4", should_cancel=None):
        cb(50.0, "[1/1] Загрузка: 50.0% · 2.00MiB/s · ETA 00:05")
        cb(100, "[1/1] Склеивание и обработка...")
        return DownloadOutcome(1, 0)

    monkeypatch.setattr(app_module, "download_single_sync", fake_download)

    task = app_module.QueueTask("fmt2", ["https://youtu.be/y"], None, "Склейка")
    app_module.queue_tasks.append(task)
    start_real_worker(app_module)

    assert wait_for(lambda: task.status == "completed"), f"статус {task.status}"
    # Завершение задачи сбрасывает скорость: показывать 2.00MiB/s у готовой
    # загрузки нельзя.
    assert task.speed == ""
    assert task.eta == ""


def test_unavailable_video_does_not_jump_to_full_progress(monkeypatch, tmp_path):
    """Первое недоступное видео уводило прогресс всей задачи на 100%."""
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            return None

    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", FakeYDL)
    seen = []
    outcome = download_lib.download_single_sync(
        [f"https://youtu.be/v{i}" for i in range(20)], None,
        lambda p, m: seen.append(p), "mp4")

    assert seen[0] == 5.0
    assert seen[-1] == 100.0
    assert (outcome.succeeded, outcome.failed) == (0, 20)
    assert not outcome


# --- обрыв потока на середине (HTTP 403) ---

class _ForbiddenYDL:
    """yt-dlp при HTTP 403 и ignoreerrors=True не бросает исключение.

    Метаданные приходят, но склеенного файла нет: в temp-папке остаются
    только обрывок видео (.part) и целиком скачанная аудиодорожка.
    """

    info = {"id": "vid403", "title": "Ролик", "uploader": "Avocado Animations",
            "width": 1920, "height": 1080, "duration": 300}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if not download:
            return dict(self.info)
        temp = os.path.dirname(self.opts["outtmpl"])
        os.makedirs(temp, exist_ok=True)
        (Path(temp) / "video.info.json").write_text("{}", encoding="utf-8")
        (Path(temp) / "video.webp").write_bytes(b"img")
        (Path(temp) / "video.f251.webm").write_bytes(b"audio-only")
        (Path(temp) / "video.f401.mp4.part").write_bytes(b"partial")
        return dict(self.info)


def test_broken_stream_is_not_reported_as_success(monkeypatch, tmp_path):
    """Остаток аудиодорожки принимался за готовое видео.

    video.f251.webm подходит под маску расширений, поэтому переносился как
    video.webm, и задача с оборванным на 69% видеопотоком отчитывалась
    об успехе.
    """
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _ForbiddenYDL)

    outcome = download_lib.download_single_sync(["https://youtu.be/vid403"], None,
                                               lambda p, m: None, "mp4")

    assert not outcome
    assert (outcome.succeeded, outcome.failed) == (0, 1)


def test_broken_stream_leaves_nothing_on_disk(monkeypatch, tmp_path):
    """После неудачи оставались каталоги с info.json и thumbnail.jpg без видео.

    Такая папка не видна в библиотеке (скан требует video.*), то есть занимает
    место и при этом никак не отображается.
    """
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _ForbiddenYDL)

    download_lib.download_single_sync(["https://youtu.be/vid403"], None,
                                      lambda p, m: None, "mp4")

    leftovers = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert leftovers == [], f"на диске остались файлы: {leftovers}"
    assert list(tmp_path.rglob("_tmp_*")) == []


class _MetadataOnlyYDL:
    """Отдаёт метаданные без обращения к сети."""

    def __init__(self, opts):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        return {"id": "vid", "title": "Ролик", "uploader": "Канал",
                "width": 1920, "height": 1080, "duration": 300}


@pytest.fixture
def fast_retries(monkeypatch, tmp_path):
    """Загрузка без сети и без реальных пауз между попытками."""
    monkeypatch.setattr(download_lib, "load_config", lambda: {"video_dir": str(tmp_path)})
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", _MetadataOnlyYDL)
    monkeypatch.setattr(download_lib, "STREAM_RETRY_DELAY", 0)
    return monkeypatch


def test_broken_stream_is_retried(fast_retries):
    """Обрыв потока не повод терять видео: ссылки перевыдаются при повторе.

    Опция retries у yt-dlp здесь не спасает — она повторяет запрос к той же
    мёртвой ссылке googlevideo, поэтому перезапускается весь вызов.
    """
    calls = []

    def flaky(url, fmt, out_dir, pd, cb, mf, should_cancel=None, error_sink=None):
        calls.append(url)
        return len(calls) >= 3

    fast_retries.setattr(download_lib, "download_single_video_impl", flaky)
    outcome = download_lib.download_single_sync(["https://youtu.be/x"], None, lambda p, m: None)

    assert len(calls) == 3
    assert (outcome.succeeded, outcome.failed) == (1, 0)


def test_retries_are_bounded(fast_retries):
    """Число попыток ограничено: иначе задача зависла бы навсегда."""
    calls = []

    def always_fails(url, fmt, out_dir, pd, cb, mf, should_cancel=None, error_sink=None):
        calls.append(url)
        return False

    fast_retries.setattr(download_lib, "download_single_video_impl", always_fails)
    outcome = download_lib.download_single_sync(["https://youtu.be/y"], None, lambda p, m: None)

    assert len(calls) == download_lib.STREAM_RETRIES
    assert (outcome.succeeded, outcome.failed) == (0, 1)


def test_cancel_interrupts_retry_pause(fast_retries):
    """Пауза между попытками не должна игнорировать отмену."""
    fast_retries.setattr(download_lib, "STREAM_RETRY_DELAY", 30)
    fast_retries.setattr(download_lib, "download_single_video_impl",
                         lambda *a, **k: False)

    started = time.time()
    with pytest.raises(download_lib.DownloadCancelledByUser):
        download_lib.download_single_sync(["https://youtu.be/z"], None, lambda p, m: None,
                                          should_cancel=lambda: True)

    assert time.time() - started < 5


def test_retry_reports_progress_of_whole_task(fast_retries):
    """Во время повторов прогресс не должен прыгать назад к нулю."""
    fast_retries.setattr(download_lib, "download_single_video_impl",
                         lambda *a, **k: False)
    seen = []

    download_lib.download_single_sync(["https://youtu.be/a", "https://youtu.be/b"],
                                      None, lambda p, m: seen.append(p))

    assert seen == sorted(seen), f"прогресс шёл назад: {seen}"


def test_fragment_files_are_recognised():
    frag = download_lib.FORMAT_FRAGMENT_RE
    assert frag.search("video.f401.mp4")
    assert frag.search("video.f251.webm")
    assert not frag.search("video.mp4")
    assert not frag.search("My.Film.2019.mp4")


def test_network_stop_message_counts_whole_task(app_module, queue_file, monkeypatch):
    """Сообщение о частичном провале должно считать ВСЕ ссылки задачи.

    При остановке из-за недоступной сети задача прекращается на середине, и
    «Готово, но N из M не скачано» показывало M как число уже обработанных
    ссылок: 55 из 79 выглядело как «3 из 27», будто остальных видео не было.
    """
    urls = ["https://youtu.be/v%d" % i for i in range(79)]

    def fake_download(u, fmt, cb, merge_format="mp4", should_cancel=None):
        # Скачали 24, три упали по сети, остальные не тронуты.
        return DownloadOutcome(24, 3, "сеть недоступна, задача остановлена", 0)

    monkeypatch.setattr(app_module, "download_single_sync", fake_download)
    app_module.queue_tasks.clear()
    task = app_module.QueueTask("t1", urls, None, "Канал (79)")
    app_module.queue_tasks.append(task)

    app_module._process_queue_once()

    assert task.status == "partial", task.status
    assert "79" in task.message, task.message
