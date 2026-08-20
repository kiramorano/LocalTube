"""Отмена загрузок и приоритеты задач в очереди."""
import os

import pytest

import download_lib


def make_task(app_module, task_id, status="waiting", priority="normal"):
    task = app_module.QueueTask(task_id, ["https://youtu.be/" + task_id], None, task_id, "mp4", priority)
    task.status = status
    app_module.queue_tasks.append(task)
    return task


# --- API отмены ---

def test_cancel_waiting_task_marks_cancelled(client, app_module):
    task = make_task(app_module, "w1")

    res = client.post("/api/queue/cancel/w1")

    assert res.status_code == 200
    assert res.get_json()["was_downloading"] is False
    assert task.status == "cancelled"
    assert task.progress == 0
    # Ожидающую задачу отменять через загрузчик не нужно.
    assert "w1" not in app_module.queue_cancel_requests


def test_cancel_active_task_requests_interrupt(client, app_module):
    task = make_task(app_module, "d1", status="downloading")

    res = client.post("/api/queue/cancel/d1")

    assert res.get_json()["was_downloading"] is True
    # Статус меняет воркер после фактической остановки, а не эндпоинт.
    assert task.status == "downloading"
    assert "d1" in app_module.queue_cancel_requests
    assert task.message == "Отмена загрузки..."


def test_cancel_missing_task_returns_404(client):
    assert client.post("/api/queue/cancel/nope").status_code == 404


@pytest.mark.parametrize("status", ["completed", "error", "cancelled"])
def test_cancel_finished_task_returns_409(client, app_module, status):
    make_task(app_module, "f1", status=status)
    assert client.post("/api/queue/cancel/f1").status_code == 409


def test_remove_active_task_also_cancels_download(client, app_module):
    make_task(app_module, "d2", status="downloading")

    res = client.delete("/api/queue/remove/d2")

    assert res.get_json()["cancelled_active"] is True
    assert "d2" in app_module.queue_cancel_requests
    assert app_module.queue_tasks == []


def test_cancelled_task_can_be_retried(client, app_module):
    task = make_task(app_module, "c1", status="downloading")
    client.post("/api/queue/cancel/c1")
    task.status = "cancelled"

    assert client.post("/api/queue/retry/c1").status_code == 200
    assert task.status == "waiting"
    # Повтор должен снять прежний запрос отмены, иначе загрузка сорвётся сразу.
    assert "c1" not in app_module.queue_cancel_requests


def test_list_reports_cancelling_flag(client, app_module):
    make_task(app_module, "d3", status="downloading")
    client.post("/api/queue/cancel/d3")

    listed = {t["id"]: t for t in client.get("/api/queue/list").get_json()["tasks"]}

    assert listed["d3"]["cancelling"] is True


# --- API приоритетов ---

def test_set_priority(client, app_module):
    task = make_task(app_module, "p1")

    res = client.post("/api/queue/priority/p1", json={"priority": "high"})

    assert res.status_code == 200
    assert task.priority == "high"


def test_invalid_priority_rejected(client, app_module):
    task = make_task(app_module, "p2")

    res = client.post("/api/queue/priority/p2", json={"priority": "urgent"})

    assert res.status_code == 400
    assert task.priority == "normal"


def test_priority_for_missing_task_returns_404(client):
    assert client.post("/api/queue/priority/nope", json={"priority": "high"}).status_code == 404


def test_priority_persisted(client, app_module, queue_file):
    make_task(app_module, "p3")
    client.post("/api/queue/priority/p3", json={"priority": "low"})

    app_module.queue_tasks.clear()
    app_module.load_queue()

    assert app_module.queue_tasks[0].priority == "low"


# --- порядок выборки задач воркером ---

def pick_next(app_module):
    """Повторяет логику выбора задачи из process_queue."""
    waiting = [t for t in app_module.queue_tasks if t.status == "waiting"]
    if not waiting:
        return None
    return min(waiting, key=lambda t: app_module.PRIORITY_ORDER.get(t.priority, 1))


def test_high_priority_task_goes_first(app_module, queue_file):
    make_task(app_module, "first")
    make_task(app_module, "urgent", priority="high")

    assert pick_next(app_module).id == "urgent"


def test_low_priority_task_goes_last(app_module, queue_file):
    make_task(app_module, "low1", priority="low")
    make_task(app_module, "normal1")

    assert pick_next(app_module).id == "normal1"


def test_same_priority_keeps_insertion_order(app_module, queue_file):
    make_task(app_module, "a")
    make_task(app_module, "b")

    assert pick_next(app_module).id == "a"


def test_cancelled_tasks_are_not_picked(app_module, queue_file):
    make_task(app_module, "x", status="cancelled")

    assert pick_next(app_module) is None


# --- поведение загрузчика при отмене ---

def test_download_single_sync_raises_on_cancel():
    with pytest.raises(download_lib.DownloadCancelledByUser):
        download_lib.download_single_sync(
            ["https://youtu.be/whatever"], None, lambda p, m: None,
            should_cancel=lambda: True,
        )


def test_download_single_video_impl_cancels_before_network(tmp_path):
    output_dir = tmp_path / "video_dir"
    output_dir.mkdir()

    with pytest.raises(download_lib.DownloadCancelledByUser):
        download_lib.download_single_video_impl(
            "https://youtu.be/cancel-me", None, str(output_dir), None,
            lambda p, m: None, "mp4", should_cancel=lambda: True,
        )

    # Незавершённая загрузка не должна оставлять temp-каталоги.
    assert list(output_dir.iterdir()) == []


def test_download_releases_lock_after_cancel(tmp_path):
    url = "https://youtu.be/lock-check"
    output_dir = tmp_path / "locked"
    output_dir.mkdir()

    with pytest.raises(download_lib.DownloadCancelledByUser):
        download_lib.download_single_video_impl(
            url, None, str(output_dir), None, lambda p, m: None, "mp4",
            should_cancel=lambda: True,
        )

    # Иначе повторная загрузка того же URL молча завершилась бы "успехом".
    assert url not in download_lib.download_locks


class FakeYDL:
    """Заглушка yt_dlp.YoutubeDL, которая дёргает progress_hooks как настоящая."""

    instances = []

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        hook = self.opts['progress_hooks'][0]
        # Несколько тиков прогресса: отмена должна прилететь посреди загрузки.
        for percent in (10, 30, 60, 90):
            hook({'status': 'downloading', '_percent_str': f'{percent}%',
                  '_speed_str': '1.0MiB/s', '_eta_str': '00:10'})
        hook({'status': 'finished'})
        return {'id': 'abc', 'title': 'T'}


def test_progress_hook_aborts_mid_download(tmp_path, monkeypatch):
    """Отмена во время скачивания должна прерывать его через progress hook.

    Именно этот путь используется в реальной загрузке: yt-dlp вызывает хук,
    а хук поднимает DownloadCancelled.
    """
    FakeYDL.instances.clear()
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", FakeYDL)

    ticks = {"n": 0}

    def cancel_after_first_tick():
        # Первый вызов — до сети, отмены ещё нет; дальше пользователь нажал «Отменить».
        ticks["n"] += 1
        return ticks["n"] > 1

    output_dir = tmp_path / "vid"
    output_dir.mkdir()

    with pytest.raises(download_lib.DownloadCancelledByUser):
        download_lib.download_single_video_impl(
            "https://youtu.be/mid", None, str(output_dir), None,
            lambda p, m: None, "mp4", should_cancel=cancel_after_first_tick,
        )

    # Загрузка реально началась (yt-dlp был создан) и прервалась до конца.
    assert FakeYDL.instances, "yt-dlp не был вызван — отмена сработала слишком рано"
    assert list(output_dir.iterdir()) == []


def test_download_finishes_when_not_cancelled(tmp_path, monkeypatch):
    """Контрольный случай: без отмены тот же путь доходит до конца."""
    FakeYDL.instances.clear()
    monkeypatch.setattr(download_lib.yt_dlp, "YoutubeDL", FakeYDL)

    output_dir = tmp_path / "vid2"
    output_dir.mkdir()
    messages = []

    # Файлов заглушка не создаёт, поэтому итог False, но исключения быть не должно.
    result = download_lib.download_single_video_impl(
        "https://youtu.be/ok", None, str(output_dir), None,
        lambda p, m: messages.append(m), "mp4", should_cancel=lambda: False,
    )

    assert result is False
    assert any("ETA" in m for m in messages), messages


def test_cleanup_empty_dir_removes_only_empty(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    full = tmp_path / "full"
    full.mkdir()
    (full / "video.mp4").write_text("data", encoding="utf-8")

    download_lib.cleanup_empty_dir(str(empty))
    download_lib.cleanup_empty_dir(str(full))

    assert not empty.exists()
    assert full.exists()


def test_progress_dict_reports_cancelled_status(tmp_path):
    progress = {}
    output_dir = tmp_path / "vid"
    output_dir.mkdir()

    with pytest.raises(download_lib.DownloadCancelledByUser):
        download_lib.download_single_video_impl(
            "https://youtu.be/progress", None, str(output_dir), progress,
            lambda p, m: None, "mp4", should_cancel=lambda: True,
        )

    assert progress["status"] == "cancelled"
