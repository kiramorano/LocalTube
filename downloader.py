import os
import yt_dlp
from urllib.parse import urlparse, parse_qs
import paths
from po_manager import get_po_args, get_po_method, apply_po_args
from utils import cookiefile_for_ydl, apply_cookie_updates, is_tiktok_url

PROJECT_ROOT = paths.data_dir()
COOKIES_PATH = paths.data_path("cookies.txt")

def is_playlist_url(url: str) -> bool:
    query = urlparse(url).query
    params = parse_qs(query)
    return bool(params.get('list'))

def get_format_choices(url: str, verbose=False) -> list:
    # PO Token и player_client понимает только YouTube: TikTok такие
    # extractor_args не принимает.
    po_args = {} if is_tiktok_url(url) else get_po_args()

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        # Поток, а не путь: иначе yt-dlp перезапишет cookies.txt при close().
        'cookiefile': cookiefile_for_ydl(COOKIES_PATH),
    }
    apply_po_args(ydl_opts, po_args)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        # yt-dlp при close() сохраняет cookies в поток через truncate(0) без
        # seek(0): без apply_cookie_updates поток остаётся повреждённым, и
        # последующая загрузка из него падает с «does not look like a Netscape
        # format cookies file».
        apply_cookie_updates(ydl_opts)
    except Exception as e:
        apply_cookie_updates(ydl_opts)
        print(f"Ошибка получения форматов: {e}")
        return []

    if not info or 'formats' not in info:
        return []

    formats = []
    formats.append({'type': 'auto', 'format_id': None, 'resolution': 'Авто (рекомендуемое)', 'codec': 'best'})

    seen_resolutions = set()
    for f in info.get('formats', []):
        h = f.get('height')
        if h and h >= 360:
            res_str = f"{h}p"
            if res_str not in seen_resolutions:
                formats.append({
                    'type': 'video_combo',
                    'format_id': f.get('format_id'),
                    'resolution': res_str,
                    'codec': f"{f.get('vcodec', 'h264')[:4]}",
                    'size_mb': round((f.get('filesize') or f.get('filesize_approx') or 0) / 1048576, 1)
                })
                seen_resolutions.add(res_str)
    return formats

def get_playlist_info(url: str):
    import po_manager
    return po_manager.get_playlist_info(url)