#!/usr/bin/env python3
"""download_prefs.py — настройки загрузки: языки аудиодорожек и субтитров.

Раньше выбора не было вовсе: yt-dlp брал аудиодорожку по умолчанию (у видео с
несколькими озвучками это язык оригинала, а не тот, что нужен), а субтитры
приходилось качать вручную, по одному языку, кнопкой на странице видео.

Модуль отделён от download_lib, потому что настройки нужны трём сторонам:
эндпоинту настроек в app.py, загрузчику download_lib.py и разделу интерфейса.
Хранение — в config.json, ключ "downloads", рядом с путями к библиотеке:
download_lib.py читает конфиг сам, отдельным load_config, и передать ему
настройки из app.py нечем.
"""

import os
import re
import threading

import paths
from logger import logger
from utils import read_json, write_json_atomic

SCRIPT_DIR = paths.data_dir()
CONFIG_FILE = paths.data_path("config.json")

# Сериализует read-modify-write config.json: файл общий с путями хранения и
# настройками авторизации, одновременная запись потеряла бы часть значений.
_config_lock = threading.RLock()

# Ключ в config.json.
CONFIG_SECTION = "downloads"

# Значения по умолчанию повторяют прежнее поведение: язык аудио не задан
# (скачивается дорожка по умолчанию), субтитры выключены. Иначе обновление
# программы начало бы тянуть лишние файлы без спроса пользователя.
DEFAULTS = {
    "audio_langs": [],          # приоритет языков аудиодорожки, пусто = как решит YouTube
    "subtitles_enabled": False,  # качать ли субтитры вместе с видео
    "subtitle_langs": ["ru"],    # какие языки субтитров качать
    "subtitles_auto": True,      # брать ли автоматические, если ручных нет
}

# Языки для выпадающих списков. Порядок — по вероятности использования, а не по
# алфавиту: русский и английский нужны почти всегда.
LANGUAGES = (
    ("ru", "Русский"),
    ("en", "English"),
    ("uk", "Українська"),
    ("be", "Беларуская"),
    ("kk", "Қазақша"),
    ("de", "Deutsch"),
    ("fr", "Français"),
    ("es", "Español"),
    ("pt", "Português"),
    ("pt-BR", "Português (Brasil)"),
    ("it", "Italiano"),
    ("pl", "Polski"),
    ("tr", "Türkçe"),
    ("ar", "العربية"),
    ("hi", "हिन्दी"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("zh", "中文"),
)

# Код языка уходит в имя файла субтитров и в фильтр формата yt-dlp. Строка вида
# '../../evil' увела бы запись за пределы папки, а пробел внутри фильтра ломает
# разбор селектора. Разрешаем только то, чем YouTube действительно пользуется:
# ru, en, pt-BR, zh-Hans.
LANG_RE = re.compile(r'^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$')

# Селекторы единого потока: у TikTok видео и звук идут вместе, и фильтр языка
# сделал бы формат недостижимым («Requested format is not available»).
_SINGLE_STREAM = ('best', 'worst')


def _clean_langs(value):
    """Приводит список языков к нормальному виду.

    Принимает и список, и строку «ru, en»: поле интерфейса присылает строку,
    а API — список.

    Возвращает (список, ошибка), где ошибка — пара (шаблон, значение). Шаблон
    отделён от значения, потому что текст ошибки переводится: строку с уже
    подставленным кодом языка в словаре не найти.
    """
    if value is None:
        return [], None
    if isinstance(value, str):
        parts = value.split(',')
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        # Число или словарь: осмысленно истолковать нечего.
        return [], ("Неверный список языков: {value}", repr(value))
    result = []
    for part in parts:
        code = str(part).strip()
        if not code:
            continue
        if not LANG_RE.match(code):
            return [], ("Недопустимый код языка: {value}", repr(code))
        # Повтор в списке означал бы повторную загрузку того же файла.
        if code not in result:
            result.append(code)
    return result, None


def _read_section():
    cfg = read_json(CONFIG_FILE, default=None)
    if not isinstance(cfg, dict):
        return {}
    section = cfg.get(CONFIG_SECTION)
    return section if isinstance(section, dict) else {}


def get_prefs():
    """Текущие настройки загрузки, всегда полным набором ключей.

    Битый конфиг и значения неверного типа (правка руками) не должны ронять
    загрузку: непонятное значение заменяется значением по умолчанию.
    """
    prefs = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    section = _read_section()
    for key in ("audio_langs", "subtitle_langs"):
        if key not in section:
            continue
        langs, error = _clean_langs(section[key])
        if error:
            # Правка руками положила в ключ невесть что: берём значение по
            # умолчанию, но загрузку не роняем.
            logger.warning(f"Настройка {key} в config.json испорчена: "
                           f"{error[0].format(value=error[1])}")
            continue
        # Пустой список — осмысленное значение: «язык не важен».
        prefs[key] = langs
    for key in ("subtitles_enabled", "subtitles_auto"):
        if key in section:
            prefs[key] = bool(section[key])
    return prefs


def save_prefs(data):
    """Сохраняет присланные настройки. Возвращает True или {'error': ...}.

    Пишет только известные ключи: мусор из запроса в конфиг попадать не должен.
    Остальные разделы config.json (пути, авторизация) сохраняются.
    """
    if not isinstance(data, dict):
        return {"error": "Ожидался объект с настройками"}

    updates = {}
    for key in ("audio_langs", "subtitle_langs"):
        if key in data:
            langs, error = _clean_langs(data[key])
            if error:
                # Шаблон и значение отдаём порознь: вызывающий переводит текст.
                return {"error": error[0], "value": error[1]}
            updates[key] = langs
    for key in ("subtitles_enabled", "subtitles_auto"):
        if key in data:
            updates[key] = bool(data[key])

    if not updates:
        return True

    try:
        with _config_lock:
            cfg = read_json(CONFIG_FILE, default={})
            if not isinstance(cfg, dict):
                cfg = {}
            section = dict(_read_section())
            section.update(updates)
            cfg[CONFIG_SECTION] = section
            write_json_atomic(CONFIG_FILE, cfg)
        return True
    except Exception as e:
        return {"error": str(e)}


def languages_for_ui():
    """Список языков в виде, готовом для JSON."""
    return [{"code": code, "label": label} for code, label in LANGUAGES]


def audio_format_selector(selector, langs):
    """Добавляет к селектору формата приоритет языка аудиодорожки.

    yt-dlp умеет фильтровать форматы по полю language, но точного совпадения у
    YouTube часто нет: дорожка приходит как ru-RU или en-US. Поэтому оператор
    ^= (начинается с), а не =.

    Исходный селектор остаётся последним запасом: у большинства видео дорожка
    одна и вообще без языка, и без запаса не скачалось бы ничего.
    """
    if not selector or not langs:
        return selector
    # Единый поток: фильтровать нечего, аудио отдельным форматом не существует.
    if selector.split('/')[0].strip() in _SINGLE_STREAM:
        return selector

    variants = []
    for lang in langs:
        # Фильтр вешается на аудиочасть: у видеопотока поля language нет.
        variant = re.sub(r'\b(bestaudio|worstaudio)\b',
                         lambda m: f"{m.group(1)}[language^={lang}]",
                         selector.split('/')[0])
        if variant not in variants:
            variants.append(variant)
    variants.append(selector)
    return '/'.join(variants)


def apply_subtitle_opts(opts, prefs=None):
    """Вливает в опции yt-dlp скачивание субтитров.

    При выключенной настройке опции не появляются вовсе: yt-dlp по умолчанию
    субтитры не качает, и лишние ключи только сбивали бы с толку при отладке.
    """
    if prefs is None:
        prefs = get_prefs()
    if not prefs.get("subtitles_enabled"):
        return opts
    langs = prefs.get("subtitle_langs") or []
    if not langs:
        # Включённые субтитры без языков качать нечего.
        return opts
    opts['writesubtitles'] = True
    opts['writeautomaticsub'] = bool(prefs.get("subtitles_auto"))
    opts['subtitleslangs'] = list(langs)
    opts['subtitlesformat'] = 'vtt/srt/best'
    return opts
