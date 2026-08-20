"""
po_manager.py – Управление экстрактором (Режим Cookies).
"""
import os
import logging
from typing import Dict, List, Callable

logger = logging.getLogger(__name__)
_extractor = None

def get_extractor():
    global _extractor
    if _extractor is None:
        from youtube_extractor import YouTubeExtractor
        _extractor = YouTubeExtractor()
    return _extractor

def get_po_args() -> Dict:
    # Возвращает extractor_args по настройкам (player_client + po_token)
    try:
        from auth_options import build_ydl_args
        return build_ydl_args()
    except Exception:
        return {}

def get_po_method() -> str:
    return "yt-dlp Default (Cookies Mode)"

def get_video_info(url: str, extra_args: Dict = None) -> Dict:
    return get_extractor().extract_info(url, extra_args)

def get_formats(url: str) -> List[Dict]:
    return get_extractor().get_formats(url)

def get_playlist_info(url: str) -> Dict:
    return get_extractor().get_playlist_info(url)

def download_video(url: str, output_path: str, format_id: str = None, progress_hook: Callable = None) -> bool:
    return get_extractor().download_video(url, output_path, format_id, progress_hook)

def shutdown_extractor():
    global _extractor
    if _extractor:
        _extractor = None

def is_po_available() -> bool:
    return True

def mark_po_failed():
    pass