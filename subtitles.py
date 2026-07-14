"""
subtitles.py – управление субтитрами для видео.
Поддерживает:
- Скачивание субтитров с YouTube (через yt-dlp).
- Загрузку пользовательских субтитров (SRT, VTT).
- Хранение в отдельной папке, настраиваемой через config.json.
- Привязку к видео по ID (для YouTube) или по пути (для пользовательских).
"""

import os
import json
import shutil
import subprocess
from urllib.parse import quote

# Пытаемся импортировать yt-dlp (он уже есть в проекте)
try:
    import yt_dlp
except ImportError:
    print("Ошибка: yt-dlp не установлен, субтитры с YouTube недоступны.")
    yt_dlp = None

def load_config():
    """Загружает конфигурацию, чтобы получить папку для субтитров."""
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    default = {"subtitles_dir": "subtitles"}
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                if "subtitles_dir" not in cfg:
                    cfg["subtitles_dir"] = default["subtitles_dir"]
                return cfg
        except:
            return default
    return default

def get_subtitles_dir():
    """Возвращает абсолютный путь к папке субтитров, создаёт её при необходимости."""
    config = load_config()
    sub_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), config["subtitles_dir"])
    os.makedirs(sub_dir, exist_ok=True)
    return sub_dir

import re as _re

def _sanitize_component(value, fallback="unknown"):
    """БАГФИКС: очищает компонент пути (video_id, lang, source) от опасных символов —
    защита от path traversal через '../' и т.п."""
    if not value:
        return fallback
    cleaned = _re.sub(r'[^0-9A-Za-z_\-. #]', '_', str(value)).strip('. ')
    return cleaned or fallback

def get_video_subtitle_folder(video_id, video_source='youtube', create=True):
    """
    Возвращает путь к папке, где будут храниться субтитры для конкретного видео.
    Для YouTube видео используется video_id (например, ID из URL).
    Для пользовательских видео можно использовать тот же video_id (он уникален).
    """
    base = get_subtitles_dir()
    folder = os.path.join(base, _sanitize_component(video_source, 'youtube'), _sanitize_component(video_id))
    if create:
        os.makedirs(folder, exist_ok=True)
    return folder

def get_available_subtitles(video_id, video_source='youtube'):
    """
    Возвращает список доступных субтитров для видео.
    Каждый элемент: {'lang': код_языка, 'file': полный_путь, 'label': читаемое_название}
    """
    # БАГФИКС: не создаём папку при простом чтении списка — раньше при каждом
    # открытии страницы плодились пустые каталоги
    folder = get_video_subtitle_folder(video_id, video_source, create=False)
    if not os.path.isdir(folder):
        return []
    subtitles = []
    for f in os.listdir(folder):
        if f.endswith(('.vtt', '.srt')):
            # Имя файла предполагает формат: например, ru.vtt или ru.srt, либо пользовательское имя
            lang = os.path.splitext(f)[0]
            # Попробуем преобразовать код языка в читаемое название
            lang_map = {
                'ru': 'Русский', 'en': 'English', 'uk': 'Українська', 'de': 'Deutsch',
                'fr': 'Français', 'es': 'Español', 'it': 'Italiano', 'pt': 'Português',
                'pl': 'Polski', 'tr': 'Türkçe', 'zh': '中文', 'ja': '日本語'
            }
            label = lang_map.get(lang, lang)
            subtitles.append({
                'lang': lang,
                'file': os.path.join(folder, f),
                'label': label
            })
    return subtitles

def download_youtube_subtitles(video_url, video_id, lang='ru'):
    """
    Скачивает субтитры с YouTube для указанного видео.
    lang – код языка (например, 'ru', 'en'). Если не найдено, попробует автоматические.
    Возвращает True при успехе, False при ошибке.
    """
    if yt_dlp is None:
        print("yt-dlp не установлен, не могу скачать субтитры.")
        return False

    folder = get_video_subtitle_folder(video_id, 'youtube')
    # Используем yt-dlp для скачивания субтитров
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': False,   # сначала пробуем ручные
        'subtitleslangs': [lang],
        'subtitlesformat': 'vtt',
        'outtmpl': os.path.join(folder, '%(title)s.%(ext)s')
    }
    # Добавляем cookies, если есть
    cookies_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    if os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            # Проверяем, есть ли субтитры на нужном языке (ручные)
            subtitles_info = info.get('subtitles', {})
            if lang not in subtitles_info:
                # Если нет, пробуем автоматические
                ydl_opts['writeautomaticsub'] = True
                ydl_opts['writesubtitles'] = False
            # Запускаем скачивание
            with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                ydl2.download([video_url])
        # После скачивания переименуем файл в lang.<ext> для единообразия
        # БАГФИКС: сохраняем исходное расширение — раньше .srt переименовывался
        # в .vtt, и плеер не мог разобрать формат
        lang_safe = _sanitize_component(lang, 'ru')
        for f in os.listdir(folder):
            if f.endswith('.vtt') or f.endswith('.srt'):
                ext = os.path.splitext(f)[1]
                old_path = os.path.join(folder, f)
                new_path = os.path.join(folder, f"{lang_safe}{ext}")
                if old_path != new_path:
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    shutil.move(old_path, new_path)
                return True
        return False
    except Exception as e:
        print(f"Ошибка скачивания субтитров: {e}")
        return False

def upload_subtitle_file(video_id, video_source, file_obj, lang_code):
    """
    Загружает пользовательский файл субтитров (SRT или VTT) для видео.
    file_obj – объект файла из Flask (request.files).
    lang_code – код языка (например, 'ru').
    Возвращает True при успехе.
    """
    if not file_obj or not file_obj.filename:
        return False
    ext = os.path.splitext(file_obj.filename)[1].lower()
    if ext not in ['.vtt', '.srt']:
        return False
    folder = get_video_subtitle_folder(video_id, video_source)
    # Сохраняем как lang_code + расширение
    # БАГФИКС: очистка lang_code — раньше можно было передать '../..' и записать файл вне папки
    filename = f"{_sanitize_component(lang_code, 'ru')}{ext}"
    file_path = os.path.join(folder, filename)
    file_obj.save(file_path)
    return True

def delete_subtitle(video_id, video_source, lang_code):
    """Удаляет субтитры указанного языка для видео."""
    folder = get_video_subtitle_folder(video_id, video_source, create=False)
    if not os.path.isdir(folder):
        return False
    for ext in ['.vtt', '.srt']:
        file_path = os.path.join(folder, f"{_sanitize_component(lang_code, 'ru')}{ext}")
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
    return False

def get_video_id_from_metadata(video_path):
    """
    Для пользовательских видео: пытается извлечь ID из info.json в папке видео.
    Возвращает video_id (из info.json) или None.
    """
    info_file = os.path.join(os.path.dirname(video_path), "info.json")
    if os.path.exists(info_file):
        try:
            with open(info_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('id')
        except:
            pass
    return None
