import os
import yt_dlp
from urllib.parse import urlparse, parse_qs
from po_manager import get_po_args, get_po_method

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
COOKIES_PATH = os.path.join(PROJECT_ROOT, "cookies.txt")

def is_playlist_url(url: str) -> bool:
    query = urlparse(url).query
    params = parse_qs(query)
    return bool(params.get('list'))

def get_format_choices(url: str, verbose=False) -> list:
    po_args = get_po_args()
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
    }
    ydl_opts.update(po_args)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
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
    except Exception as e:
        print(f"Ошибка получения форматов: {e}")
        return []

def get_playlist_info(url: str):
    import po_manager
    return po_manager.get_playlist_info(url)