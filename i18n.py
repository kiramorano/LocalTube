#!/usr/bin/env python3
"""i18n.py — перевод интерфейса на русский и английский.

Ключ перевода — сама русская строка, как msgid в gettext. Технические ключи
(settings.title) заманчивее выглядят, но при опечатке дают пустое место или
саму строку ключа на экране; здесь же непереведённая строка остаётся русской,
то есть читаемой.

Язык хранится в cookie, а не в localStorage: страницы собирает сервер, и к
моменту работы клиентского кода разметка уже отдана — переключение через
localStorage означало бы мигание русского текста при каждом заходе.
"""

import os
import threading

import paths
from logger import logger
from utils import read_json

SCRIPT_DIR = paths.resource_dir()
# Словари переводов только читаются, поэтому это ресурс: в собранной версии они
# лежат внутри бандла, а не в каталоге данных пользователя.
LOCALES_DIR = paths.resource_path("locales")

# Порядок важен: первый язык — по умолчанию.
LANGUAGES = ("ru", "en")
DEFAULT_LANG = LANGUAGES[0]

# Подписи для выбора языка: каждый язык называется на самом себе, иначе выбрать
# язык из непонятного интерфейса тяжело.
LANGUAGE_LABELS = {"ru": "Русский", "en": "English"}

# Имя cookie с выбранным языком.
LANG_COOKIE = "lt_lang"
# Год: язык — редко меняемая настройка, спрашивать заново каждую сессию незачем.
LANG_COOKIE_MAX_AGE = 365 * 24 * 60 * 60

_cache = {}
_cache_lock = threading.Lock()


def normalize_lang(value):
    """Приводит код языка к поддерживаемому.

    Мусор в cookie, регистр (EN) и региональный код (en-US) не должны приводить
    к пустому интерфейсу.
    """
    if not isinstance(value, str):
        return DEFAULT_LANG
    code = value.strip().lower().replace('_', '-')
    if code in LANGUAGES:
        return code
    base = code.split('-')[0]
    return base if base in LANGUAGES else DEFAULT_LANG


def load_dictionary(lang):
    """Словарь переводов для языка. Читается с диска один раз.

    Словарь нужен на каждый запрос страницы: без кэша это чтение файла на
    каждое открытие любой страницы.
    """
    lang = normalize_lang(lang)
    if lang == DEFAULT_LANG:
        # Русский — язык исходных строк, словарь ему не нужен.
        return {}
    with _cache_lock:
        cached = _cache.get(lang)
    if cached is not None:
        return cached

    path = os.path.join(LOCALES_DIR, f"{lang}.json")
    data = read_json(path, default=None)
    if not isinstance(data, dict):
        logger.warning(f"Словарь переводов {path} не прочитан, интерфейс останется русским")
        data = {}
    # Значения нестрокового типа сломали бы шаблон: пропускаем их, а не падаем.
    clean = {str(k): v for k, v in data.items() if isinstance(v, str) and v.strip()}
    with _cache_lock:
        _cache[lang] = clean
    return clean


def reload_dictionaries():
    """Сбрасывает кэш словарей: нужно тестам и правке словаря на ходу."""
    with _cache_lock:
        _cache.clear()


def translate(text, lang):
    """Переводит строку. Неизвестная строка остаётся как есть.

    Отступы по краям сохраняются: в HTML текст почти всегда идёт с ними, и
    обрезка ломала бы расстановку пробелов между словом и соседним тегом.
    """
    if not isinstance(text, str):
        # Число из шаблона переводить нечего.
        return text
    lang = normalize_lang(lang)
    if lang == DEFAULT_LANG:
        return text
    key = text.strip()
    if not key:
        return text
    value = load_dictionary(lang).get(key)
    if value is None:
        return text
    # Возвращаем перевод с теми же отступами, что были у исходной строки.
    start = text[:len(text) - len(text.lstrip())]
    end = text[len(text.rstrip()):]
    return f"{start}{value}{end}"


def languages_for_ui():
    """Список языков для выпадающего поля настроек."""
    return [{"code": code, "label": LANGUAGE_LABELS.get(code, code)} for code in LANGUAGES]
