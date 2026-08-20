#!/usr/bin/env python3
"""Серверное хранилище пользовательских данных: избранное, история, скрытые каналы.

Раньше всё это лежало в localStorage браузера: данные терялись при чистке
браузера и не были видны с других устройств. Теперь единый JSON на сервере.
"""
import contextlib
import json
import os
import shutil
import threading
import time

from logger import logger


class UserDataSaveError(Exception):
    """Не удалось сохранить пользовательские данные на диск."""

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
USERDATA_FILE = os.path.join(SCRIPT_DIR, "userdata.json")

# История не должна расти бесконечно.
HISTORY_LIMIT = 500

_lock = threading.RLock()
_data = None

DEFAULTS = {
    "favorites": [],
    "history": [],
    "hidden_channels": [],
}


def _empty():
    return {"favorites": [], "history": [], "hidden_channels": [], "updated_at": 0}


def _normalize(raw):
    """Приводит загруженные данные к ожидаемой структуре.

    Файл могли поправить руками или он мог остаться от старой версии, поэтому
    каждое поле проверяется отдельно, а мусор отбрасывается.
    """
    result = _empty()
    if not isinstance(raw, dict):
        return result
    for key in DEFAULTS:
        value = raw.get(key)
        if not isinstance(value, list):
            continue
        seen = set()
        clean = []
        for item in value:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            clean.append(item)
        result[key] = clean[:HISTORY_LIMIT] if key == "history" else clean
    updated = raw.get("updated_at")
    result["updated_at"] = updated if isinstance(updated, (int, float)) else 0
    return result


def _read_file():
    """Читает файл с диска. Возвращает None, если файла нет или он битый."""
    if not os.path.exists(USERDATA_FILE):
        return None
    try:
        # utf-8-sig: файл могли сохранить с BOM из редактора.
        with open(USERDATA_FILE, "r", encoding="utf-8-sig") as f:
            return _normalize(json.load(f))
    except Exception as e:
        logger.warning(f"userdata: не удалось прочитать {USERDATA_FILE}: {e}")
        return None


def _load_locked():
    global _data
    if _data is not None:
        return _data
    loaded = _read_file()
    if loaded is None and os.path.exists(USERDATA_FILE):
        # Файл есть, но не читается. Пробуем бэкап, прежде чем начинать с нуля.
        backup = USERDATA_FILE + ".bak"
        if os.path.exists(backup):
            try:
                with open(backup, "r", encoding="utf-8-sig") as f:
                    loaded = _normalize(json.load(f))
                logger.warning("userdata: основной файл битый, данные взяты из .bak")
            except Exception as e:
                logger.warning(f"userdata: бэкап тоже не читается: {e}")
    _data = loaded if loaded is not None else _empty()
    return _data


def _save_locked():
    """Атомарно сохраняет данные на диск.

    Бросает UserDataSaveError при неудаче: тихий сбой недопустим, потому что
    клиент по успешному ответу стирает свою копию из localStorage.
    """
    _data["updated_at"] = time.time()
    tmp = USERDATA_FILE + ".tmp"
    try:
        # Бэкап предыдущей версии — на случай, если новая запись окажется
        # неверной по смыслу (файл цел, но данные не те).
        if os.path.exists(USERDATA_FILE):
            try:
                shutil.copyfile(USERDATA_FILE, USERDATA_FILE + ".bak")
            except OSError as e:
                logger.warning(f"userdata: не удалось создать бэкап: {e}")
        # Пишем через временный файл: обрыв записи не должен оставить
        # повреждённый userdata.json.
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False, indent=2)
            f.flush()
            # fsync: без него os.replace может отдать успех, а данные
            # потеряются при отключении питания.
            os.fsync(f.fileno())
        os.replace(tmp, USERDATA_FILE)
    except Exception as e:
        logger.error(f"userdata: не удалось сохранить: {e}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise UserDataSaveError(str(e)) from e


@contextlib.contextmanager
def _transaction():
    """Изменяет данные и сохраняет их, откатывая память при сбое записи.

    Без отката состояние в памяти расходилось бы с диском: пользователь видел
    бы применённое изменение, которое исчезнет после перезапуска сервера.
    """
    with _lock:
        data = _load_locked()
        snapshot = {k: list(data[k]) for k in DEFAULTS}
        snapshot_updated = data["updated_at"]
        try:
            yield data
            _save_locked()
        except Exception:
            for key, value in snapshot.items():
                data[key] = value
            data["updated_at"] = snapshot_updated
            raise


def reload_from_disk():
    """Сбрасывает кэш в памяти (нужно тестам и после правки файла руками)."""
    global _data
    with _lock:
        _data = None


def get_all():
    with _lock:
        data = _load_locked()
        return {
            "favorites": list(data["favorites"]),
            "history": list(data["history"]),
            "hidden_channels": list(data["hidden_channels"]),
            "updated_at": data["updated_at"],
        }


def _set_membership(key, value, desired, limit=None):
    """Приводит наличие value в списке к desired.

    desired=None означает переключение. Явное значение нужно клиенту: он мог
    отправить запрос до того, как загрузил актуальное состояние, и слепое
    переключение сделало бы обратное задуманному.
    """
    value = (value or "").strip()
    if not value:
        raise ValueError("Пустое значение")
    with _transaction() as data:
        items = data[key]
        present = value in items
        target = (not present) if desired is None else bool(desired)
        if target and not present:
            items.insert(0, value)
            if limit:
                del items[limit:]
        elif present and not target:
            items.remove(value)
        return target, list(items)


def toggle_favorite(video_id, desired=None):
    """Меняет избранность видео. Возвращает (в избранном, список).

    desired=None — переключить, True/False — установить явно.
    """
    return _set_membership("favorites", video_id, desired)


def toggle_hidden_channel(author, desired=None):
    """Скрывает или показывает канал. Возвращает (скрыт, список)."""
    return _set_membership("hidden_channels", author, desired)


def mark_watched(video_id):
    """Помечает видео просмотренным, поднимая его в начало истории."""
    video_id = (video_id or "").strip()
    if not video_id:
        raise ValueError("Пустой id видео")
    with _transaction() as data:
        history = data["history"]
        if video_id in history:
            history.remove(video_id)
        history.insert(0, video_id)
        del history[HISTORY_LIMIT:]
        return list(history)


def clear(key):
    """Полностью очищает один из списков."""
    if key not in DEFAULTS:
        raise ValueError(f"Неизвестный раздел: {key}")
    with _transaction() as data:
        data[key] = []
        return []


def merge_from_client(payload):
    """Разово переносит данные из localStorage при первом заходе.

    Ничего не удаляет: клиентские значения объединяются с серверными, иначе
    открытие второго браузера с пустым localStorage стёрло бы всё.
    """
    incoming = _normalize(payload if isinstance(payload, dict) else {})
    added = {}
    with _lock:
        with _transaction() as data:
            for key in DEFAULTS:
                existing = data[key]
                known = set(existing)
                new_items = [i for i in incoming[key] if i not in known]
                added[key] = len(new_items)
                if not new_items:
                    continue
                if key == "history":
                    # История клиента новее по порядку, но серверную не теряем.
                    data[key] = (new_items + existing)[:HISTORY_LIMIT]
                else:
                    data[key] = existing + new_items

        # Клиент по успешному ответу стирает свою копию, поэтому подтверждаем
        # результат чтением с диска, а не из памяти.
        verified = _read_file()
        if verified is None:
            raise UserDataSaveError("Данные не найдены на диске после записи")
        for key in DEFAULTS:
            missing = [i for i in incoming[key] if i not in set(verified[key])]
            if missing:
                raise UserDataSaveError(
                    f"На диск попали не все данные ({key}: {len(missing)})"
                )
        return added, verified
