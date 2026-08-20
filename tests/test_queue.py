"""Очередь загрузок: модель задачи, сохранение, API управления."""
import json
import re

import pytest


def test_empty_queue_list(client):
    res = client.get("/api/queue/list")
    assert res.status_code == 200
    body = res.get_json()
    assert body["tasks"] == []
    assert body["paused"] is False


def test_task_dict_contains_progress_fields(app_module):
    task = app_module.QueueTask("t1", ["https://youtu.be/a", "https://youtu.be/b"], None, "Пачка", "mp4")
    payload = task.to_dict()
    for field in ("current_url", "current_index", "total_urls", "speed", "eta", "attempts", "priority"):
        assert field in payload
    assert payload["total_urls"] == 2


def test_task_dict_roundtrip(app_module):
    task = app_module.QueueTask("t1", ["u1", "u2"], None, "Заголовок")
    task.status = "error"
    task.attempts = 3
    task.speed = "1.20MiB/s"
    task.eta = "00:42"
    task.current_index = 2
    task.priority = "high"

    restored = app_module.QueueTask.from_dict(task.to_dict())

    assert restored.attempts == 3
    assert (restored.speed, restored.eta) == ("1.20MiB/s", "00:42")
    assert restored.current_index == 2
    assert restored.priority == "high"


def test_interrupted_download_becomes_waiting(app_module):
    task = app_module.QueueTask.from_dict({"id": "x", "urls": ["u"], "status": "downloading", "progress": 55})
    assert task.status == "waiting"
    assert task.progress == 0


def test_unknown_priority_falls_back_to_normal(app_module):
    task = app_module.QueueTask("t", ["u"], None, "T", "mp4", "bogus")
    assert task.priority == "normal"


def test_pause_and_resume_persisted(client, app_module, queue_file):
    assert client.post("/api/queue/pause").get_json()["paused"] is True
    assert json.loads(queue_file.read_text(encoding="utf-8"))["paused"] is True
    assert client.get("/api/queue/list").get_json()["paused"] is True

    assert client.post("/api/queue/resume").get_json()["paused"] is False
    assert json.loads(queue_file.read_text(encoding="utf-8"))["paused"] is False


def test_paused_survives_reload(app_module, queue_file):
    app_module.queue_paused = True
    app_module.save_queue()
    app_module.queue_paused = False

    app_module.load_queue()

    assert app_module.queue_paused is True


def test_legacy_list_format_is_read(app_module, queue_file):
    queue_file.write_text(json.dumps([{
        "id": "old1", "urls": ["https://youtu.be/old"], "title": "Старый формат",
        "status": "error", "progress": 0, "message": "", "error": "boom",
    }]), encoding="utf-8")

    app_module.load_queue()

    assert [t.id for t in app_module.queue_tasks] == ["old1"]
    assert app_module.queue_tasks[0].attempts == 0
    assert app_module.queue_tasks[0].priority == "normal"


def test_retry_resets_task(client, app_module):
    task = app_module.QueueTask("r1", ["u"], None, "Ошибка")
    task.status = "error"
    task.error = "boom"
    app_module.queue_tasks.append(task)

    assert client.post("/api/queue/retry/r1").status_code == 200
    assert task.status == "waiting"
    assert task.error == ""


def test_retry_missing_task_returns_404(client):
    assert client.post("/api/queue/retry/does-not-exist").status_code == 404


def test_clear_keeps_active_and_waiting(client, app_module):
    statuses = {"a": "waiting", "b": "downloading", "c": "completed", "d": "error", "e": "cancelled"}
    for task_id, status in statuses.items():
        task = app_module.QueueTask(task_id, ["u"], None, task_id)
        task.status = status
        app_module.queue_tasks.append(task)

    client.post("/api/queue/clear")

    assert sorted(t.id for t in app_module.queue_tasks) == ["a", "b"]


def test_remove_deletes_task(client, app_module):
    app_module.queue_tasks.append(app_module.QueueTask("a", ["u"], None, "A"))
    res = client.delete("/api/queue/remove/a")
    assert res.get_json()["cancelled_active"] is False
    assert app_module.queue_tasks == []


def test_add_rejects_empty_urls(client):
    assert "error" in client.post("/api/queue/add", json={"urls": []}).get_json()


def test_add_creates_task_with_fields(client, app_module):
    res = client.post("/api/queue/add", json={
        "urls": ["https://youtu.be/x", "https://youtu.be/y"],
        "title": "Две ссылки", "merge_format": "mkv", "priority": "high",
    })
    task_id = res.get_json()["task_id"]
    task = next(t for t in app_module.queue_tasks if t.id == task_id)

    assert task.total_urls == 2
    assert task.merge_format == "mkv"
    assert task.priority == "high"

    listed = client.get("/api/queue/list").get_json()["tasks"][-1]
    for key in ("speed", "eta", "attempts", "current_index", "total_urls", "priority", "cancelling"):
        assert key in listed


@pytest.mark.parametrize("message,index,total,speed,eta", [
    ("[2/7] Загрузка: 43.5% · 1.66MiB/s · ETA 00:31", "2", "7", "1.66MiB/s", "00:31"),
    ("[1/1] Загрузка: 100% · 9.10MiB/s · ETA 00:00", "1", "1", "9.10MiB/s", "00:00"),
])
def test_progress_message_parsing(message, index, total, speed, eta):
    position = re.match(r"\[(\d+)/(\d+)\]\s+", message)
    metrics = re.search(r"·\s*([^·]+?)\s*·\s*ETA\s*(.+)$", message)

    assert position.group(1, 2) == (index, total)
    assert metrics.group(1) == speed
    assert metrics.group(2) == eta


def test_progress_message_without_metrics_is_safe():
    plain = "Склеивание и обработка..."
    assert re.match(r"\[(\d+)/(\d+)\]\s+", plain) is None
    assert re.search(r"·\s*([^·]+?)\s*·\s*ETA\s*(.+)$", plain) is None
