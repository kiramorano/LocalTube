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
import uuid

import paths
from logger import logger


class UserDataSaveError(Exception):
    """Не удалось сохранить пользовательские данные на диск."""

SCRIPT_DIR = paths.data_dir()
USERDATA_FILE = paths.data_path("userdata.json")

# История не должна расти бесконечно.
HISTORY_LIMIT = 500

# Свои плейлисты: названия участвуют в вёрстке сайдбара, а список видео целиком
# уходит в ответ API, поэтому оба размера ограничены.
COLLECTION_TITLE_LIMIT = 100
COLLECTION_VIDEOS_LIMIT = 1000
COLLECTIONS_LIMIT = 200

# «Смотреть позже» ведёт себя как встроенный список: создаётся при первом
# обращении, не переименовывается и не удаляется. Так кнопка на странице видео
# работает всегда, без предварительной настройки.
WATCH_LATER_ID = "watch-later"
WATCH_LATER_TITLE = "Смотреть позже"

_lock = threading.RLock()
_data = None

DEFAULTS = {
    "favorites": [],
    "history": [],
    "hidden_channels": [],
    "collections": [],
}

# Списки строк: к ним применяется общая нормализация и _set_membership.
_STRING_LISTS = ("favorites", "history", "hidden_channels")


def _empty():
    return {"favorites": [], "history": [], "hidden_channels": [],
            "collections": [], "updated_at": 0}


def _normalize(raw):
    """Приводит загруженные данные к ожидаемой структуре.

    Файл могли поправить руками или он мог остаться от старой версии, поэтому
    каждое поле проверяется отдельно, а мусор отбрасывается.
    """
    result = _empty()
    if not isinstance(raw, dict):
        return result
    for key in _STRING_LISTS:
        value = raw.get(key)
        if not isinstance(value, list):
            continue
        result[key] = _clean_ids(value, limit=HISTORY_LIMIT if key == "history" else None)
    result["collections"] = _normalize_collections(raw.get("collections"))
    updated = raw.get("updated_at")
    result["updated_at"] = updated if isinstance(updated, (int, float)) else 0
    return result


def _clean_ids(value, limit=None):
    """Оставляет непустые строки без повторов, сохраняя порядок."""
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
    return clean[:limit] if limit else clean


def _normalize_collections(value):
    """Приводит свои плейлисты к ожидаемой структуре.

    Файл могли поправить руками, а ключа collections в старых версиях не было
    вовсе. Запись без id или названия восстановить нельзя, поэтому она
    отбрасывается целиком: показать её пользователю всё равно не получится.
    """
    if not isinstance(value, list):
        return []
    result = []
    seen_ids = set()
    seen_titles = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        coll_id = item.get("id")
        title = item.get("title")
        if not isinstance(coll_id, str) or not isinstance(title, str):
            continue
        coll_id = coll_id.strip()
        title = title.strip()[:COLLECTION_TITLE_LIMIT]
        if not coll_id or not title:
            continue
        if coll_id in seen_ids or title.casefold() in seen_titles:
            continue
        seen_ids.add(coll_id)
        seen_titles.add(title.casefold())
        videos = item.get("videos")
        created = item.get("created_at")
        result.append({
            "id": coll_id,
            "title": title,
            "videos": _clean_ids(videos if isinstance(videos, list) else [],
                                 limit=COLLECTION_VIDEOS_LIMIT),
            "created_at": created if isinstance(created, (int, float)) else 0,
        })
        if len(result) >= COLLECTIONS_LIMIT:
            break
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
        # Плейлисты — список словарей, и плоская копия списка оставила бы общие
        # вложенные объекты: откат не вернул бы изменения внутри плейлиста.
        snapshot = {k: _copy_section(k, data[k]) for k in DEFAULTS}
        snapshot_updated = data["updated_at"]
        try:
            yield data
            _save_locked()
        except Exception:
            for key, value in snapshot.items():
                data[key] = value
            data["updated_at"] = snapshot_updated
            raise


def _copy_section(key, value):
    """Глубокая копия одного раздела: для плейлистов нужны копии вложенных записей."""
    if key == "collections":
        return [{**item, "videos": list(item["videos"])} for item in value]
    return list(value)


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
            "collections": _copy_section("collections", data["collections"]),
            "updated_at": data["updated_at"],
        }


def empty_state():
    """Пустые личные данные того же вида, что и get_all().

    Нужно для гостей из локальной сети: страница ждёт эти поля, но избранное,
    история и плейлисты владельца — не их дело.
    """
    return _empty()


def _set_membership(key, value, desired, limit=None):
    """Приводит наличие value в списке к desired.

    desired=None означает переключение. Явное значение нужно клиенту: он мог
    отправить запрос до того, как загрузил актуальное состояние, и слепое
    переключение сделало бы обратное задуманному.
    """
    if key not in _STRING_LISTS:
        raise ValueError(f"Раздел {key} не является списком строк")
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


# ================= Свои плейлисты =================

def _find(data, collection_id):
    for item in data["collections"]:
        if item["id"] == collection_id:
            return item
    return None


def _public(item):
    """Копия записи для выдачи наружу, чтобы вызывающий не менял хранилище."""
    return {**item, "videos": list(item["videos"])}


def _check_title(title, data, skip_id=None):
    """Проверяет название и возвращает его в очищенном виде."""
    title = (title or "").strip() if isinstance(title, str) else ""
    if not title:
        raise ValueError("Название не может быть пустым")
    if len(title) > COLLECTION_TITLE_LIMIT:
        raise ValueError(f"Название длиннее {COLLECTION_TITLE_LIMIT} символов")
    folded = title.casefold()
    # Своё название, совпадающее со встроенным списком, пользователь не отличил
    # бы от «Смотреть позже».
    if folded == WATCH_LATER_TITLE.casefold() and skip_id != WATCH_LATER_ID:
        raise ValueError(f"Название «{WATCH_LATER_TITLE}» занято встроенным списком")
    for item in data["collections"]:
        if item["id"] == skip_id:
            continue
        if item["title"].casefold() == folded:
            raise ValueError(f"Плейлист «{item['title']}» уже есть")
    return title


def get_collection(collection_id):
    """Возвращает плейлист или None."""
    with _lock:
        item = _find(_load_locked(), collection_id)
        return _public(item) if item else None


def create_collection(title, collection_id=None):
    """Создаёт свой плейлист. Возвращает созданную запись."""
    with _transaction() as data:
        clean = _check_title(title, data)
        if len(data["collections"]) >= COLLECTIONS_LIMIT:
            raise ValueError(f"Больше {COLLECTIONS_LIMIT} плейлистов не поддерживается")
        # uuid, а не название: переименование не должно менять ссылку на
        # страницу плейлиста.
        item = {
            "id": collection_id or uuid.uuid4().hex[:12],
            "title": clean,
            "videos": [],
            "created_at": time.time(),
        }
        data["collections"].append(item)
        return _public(item)


def rename_collection(collection_id, title):
    with _transaction() as data:
        item = _find(data, collection_id)
        if item is None:
            raise KeyError(collection_id)
        if collection_id == WATCH_LATER_ID:
            raise ValueError(f"«{WATCH_LATER_TITLE}» нельзя переименовать")
        item["title"] = _check_title(title, data, skip_id=collection_id)
        return _public(item)


def delete_collection(collection_id):
    with _transaction() as data:
        item = _find(data, collection_id)
        if item is None:
            raise KeyError(collection_id)
        if collection_id == WATCH_LATER_ID:
            raise ValueError(f"«{WATCH_LATER_TITLE}» нельзя удалить")
        data["collections"].remove(item)
        return True


def add_to_collection(collection_id, video_id):
    """Добавляет видео в конец плейлиста. Повторное добавление ничего не меняет."""
    video_id = (video_id or "").strip() if isinstance(video_id, str) else ""
    if not video_id:
        raise ValueError("Пустой id видео")
    with _transaction() as data:
        item = _find(data, collection_id)
        if item is None:
            raise KeyError(collection_id)
        if video_id not in item["videos"]:
            if len(item["videos"]) >= COLLECTION_VIDEOS_LIMIT:
                raise ValueError(
                    f"В плейлисте уже {COLLECTION_VIDEOS_LIMIT} видео")
            item["videos"].append(video_id)
        return _public(item)


def remove_from_collection(collection_id, video_id):
    """Убирает видео из плейлиста. Отсутствие видео ошибкой не считается."""
    with _transaction() as data:
        item = _find(data, collection_id)
        if item is None:
            raise KeyError(collection_id)
        if video_id in item["videos"]:
            item["videos"].remove(video_id)
        return _public(item)


def watch_later():
    """Возвращает встроенный список «Смотреть позже», создавая его при первом обращении."""
    with _lock:
        existing = get_collection(WATCH_LATER_ID)
        if existing is not None:
            return existing
        with _transaction() as data:
            item = {
                "id": WATCH_LATER_ID,
                "title": WATCH_LATER_TITLE,
                "videos": [],
                "created_at": time.time(),
            }
            # В начало: встроенный список удобнее держать первым в сайдбаре.
            data["collections"].insert(0, item)
            return _public(item)


def merge_from_client(payload):
    """Разово переносит данные из localStorage при первом заходе.

    Ничего не удаляет: клиентские значения объединяются с серверными, иначе
    открытие второго браузера с пустым localStorage стёрло бы всё.
    """
    incoming = _normalize(payload if isinstance(payload, dict) else {})
    added = {}
    with _lock:
        with _transaction() as data:
            # Плейлисты не переносятся: они никогда не жили в localStorage, а
            # объединять их по названию небезопасно.
            for key in _STRING_LISTS:
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
        for key in _STRING_LISTS:
            missing = [i for i in incoming[key] if i not in set(verified[key])]
            if missing:
                raise UserDataSaveError(
                    f"На диск попали не все данные ({key}: {len(missing)})"
                )
        return added, verified
