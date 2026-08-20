import json
import os
import re
import shutil

from logger import logger


class JsonWriteError(Exception):
    """Не удалось безопасно записать JSON-файл."""


def read_json(path, default=None, use_backup=True):
    """Читает JSON, при повреждении пробует .bak.

    Возвращает default, если файла нет или ни основной файл, ни бэкап не
    читаются. utf-8-sig: файл могли сохранить с BOM из редактора.
    """
    for candidate in ([path, path + '.bak'] if use_backup else [path]):
        if not os.path.exists(candidate):
            continue
        try:
            with open(candidate, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            if candidate != path:
                logger.warning(f"{path} повреждён, данные взяты из .bak")
            return data
        except Exception as e:
            logger.warning(f"Не удалось прочитать {candidate}: {e}")
    return default


def write_json_atomic(path, data, backup=True, indent=2):
    """Атомарно записывает JSON, сохраняя копию предыдущей версии.

    Прямая запись через open(path, 'w') обрезает файл сразу: сбой на середине
    оставляет пустой или битый JSON, а прежние данные уже потеряны. Здесь
    сначала пишется .tmp с fsync, затем os.replace подменяет файл одним
    неделимым действием.

    Бросает JsonWriteError: тихий сбой недопустим, вызывающий код должен
    узнать, что данные не сохранены.
    """
    directory = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        raise JsonWriteError(f"Нет каталога для {path}: {e}") from e

    if backup and os.path.exists(path):
        try:
            shutil.copyfile(path, path + '.bak')
        except OSError as e:
            # Отсутствие бэкапа не повод терять новые данные.
            logger.warning(f"Не удалось создать бэкап {path}: {e}")

    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            # Без fsync os.replace может отдать успех, а данные пропадут
            # при отключении питания.
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise JsonWriteError(f"Не удалось записать {path}: {e}") from e


def safe_name(text: str) -> str:
    if not text:
        return "unknown"
    name = re.sub(r'[\\/*?:"<>|]', "_", text)
    name = name.rstrip('. ')
    return name.strip()

def is_shorts_video(info: dict) -> bool:
    if not isinstance(info, dict):
        return False
    if info.get('height') and info.get('width') and info['height'] > info['width']:
        return True
    title = info.get('title', '').lower()
    if '#shorts' in title or '#short' in title:
        return True
    if '/shorts/' in info.get('webpage_url', ''):
        return True
    duration = info.get('duration')
    if duration and duration <= 60 and (info.get('height', 0) > info.get('width', 0)):
        return True
    return False