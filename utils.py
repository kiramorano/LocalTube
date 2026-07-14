import re

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