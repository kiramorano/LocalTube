"""
youtube_extractor.py – Универсальный извлекатель видео.
"""
import os
import yt_dlp
import logging
import traceback

logger = logging.getLogger(__name__)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
COOKIES_PATH = os.path.join(PROJECT_ROOT, 'cookies.txt')

class YouTubeExtractor:
    def _get_ydl_opts(self, extra_args: dict = None) -> dict:
        from po_manager import get_po_args
        
        opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'extract_flat': 'in_playlist',
            'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
            'socket_timeout': 30,
            'retries': 5,
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
        }

        po_args = get_po_args()
        if po_args:
            opts.update(po_args)

        if extra_args:
            opts.update(extra_args)
        return opts

    def extract_info(self, url: str, extra_args: dict = None) -> dict:
        opts = self._get_ydl_opts(extra_args)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info if info is not None else {}
        except Exception as e:
            logger.error(f"Ошибка экстракции: {e}\n{traceback.format_exc()}")
            return {}

    def get_formats(self, url: str) -> list:
        info = self.extract_info(url, {'extract_flat': False})
        if not info: 
            return []
        
        formats = []
        seen = set()
        for f in info.get('formats', []):
            h = f.get('height')
            if h and h >= 360 and h not in seen:
                formats.append({
                    'format_id': f.get('format_id'),
                    'resolution': f"{h}p",
                    'ext': f.get('ext'),
                    'filesize': f.get('filesize') or f.get('filesize_approx', 0)
                })
                seen.add(h)
        
        return sorted(formats, key=lambda x: int(x['resolution'][:-1]), reverse=True)

    def get_playlist_info(self, url: str) -> dict:
        info = self.extract_info(url, {'extract_flat': 'in_playlist'})
        if not info: 
            return {}
            
        entries = info.get('entries', [info])
        videos = []
        for entry in entries:
            if entry:
                video_url = entry.get('url') or entry.get('webpage_url')
                if not video_url and entry.get('id'):
                    video_url = f"https://www.youtube.com/watch?v={entry.get('id')}"
                
                if video_url:
                    videos.append({
                        'id': entry.get('id'),
                        'title': entry.get('title'),
                        'url': video_url,
                        'duration': entry.get('duration')
                    })
        
        return {
            'is_playlist': 'entries' in info, 
            'title': info.get('title'), 
            'videos': videos, 
            'count': len(videos)
        }

    def download_video(self, url, output_path, format_id, progress_hook):
        opts = self._get_ydl_opts({'extract_flat': False})
        
        if format_id and '+' not in format_id:
            final_format = f"{format_id}+bestaudio/best"
        else:
            final_format = format_id or 'bestvideo+bestaudio/best'
            
        opts.update({
            'format': final_format,
            'outtmpl': output_path,
            'progress_hooks': [progress_hook] if progress_hook else [],
        })
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
                return True
        except Exception as e:
            logger.error(f"Ошибка скачивания: {e}")
            return False

    def shutdown(self):
        pass