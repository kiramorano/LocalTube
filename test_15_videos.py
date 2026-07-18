#!/usr/bin/env python3
import yt_dlp
import os

TEST_URLS = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=9bZkp7q19f0",
    "https://www.youtube.com/watch?v=kJQP7kiw5Fk",
    "https://www.youtube.com/watch?v=YQHsXMglC9A",
    "https://www.youtube.com/watch?v=JGwWNGJdvx8",
    "https://www.youtube.com/watch?v=OPf0YbXqDm0",
    "https://www.youtube.com/watch?v=fRh_vgS2dFE",
    "https://www.youtube.com/watch?v=RB-RcX5DS5A",
    "https://www.youtube.com/watch?v=CevxZvSJLk8",
    "https://www.youtube.com/watch?v=HhjHYkPQ8F0",
    "https://www.youtube.com/watch?v=eqZ8WJdL0sA",
    "https://www.youtube.com/watch?v=7wtfhZwyrcc",
    "https://www.youtube.com/watch?v=QYh6mYIJG2Y",
    "https://www.youtube.com/watch?v=9f06QZ0PUu0",
    "https://www.youtube.com/watch?v=1SBybP4ZybE",
]

def test_video(url):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'ignoreerrors': True,
    }
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = "cookies.txt"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or not info.get('id'):
            print(f"❌ {url} - yt-dlp не вернул информацию о видео")
            return False
        print(f"✅ {url} - успешно")
        return True
    except Exception as e:
        print(f"❌ {url} - ошибка: {str(e)[:100]}")
        return False

if __name__ == "__main__":
    print("Проверка 15 случайных видео...\n")
    success = 0
    for i, url in enumerate(TEST_URLS, 1):
        print(f"{i}. {url}")
        if test_video(url):
            success += 1
        print()
    print(f"Успешно: {success}/{len(TEST_URLS)}")
