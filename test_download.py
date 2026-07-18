# test_download.py — проверяет работу yt-dlp отдельно
import yt_dlp

def check_video(url):
    ydl_opts = {
        'quiet': False,
        # Если есть cookies.txt, раскомментируй строку:
        # 'cookiefile': 'cookies.txt',
        'extractor_args': {'youtube': {'player_client': ['android']}},
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'socket_timeout': 30,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            raise RuntimeError("yt-dlp не вернул информацию о видео")
        print("\n✅ Успешно!")
        print(f"Название: {info.get('title')}")
        print(f"Автор: {info.get('uploader')}")
        print(f"Длительность: {info.get('duration')} сек")
        print("Форматы доступны, можно скачивать.")
        return True
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        print("\nСоветы:")
        print("- Установи / обнови yt-dlp: pip install --upgrade yt-dlp")
        print("- Если ошибка сети, добавь cookies (экспортируй из браузера и раскомментируй 'cookiefile')")
        print("- Попробуй использовать VPN/прокси")
        return False


def main():
    url = input("Вставьте ссылку на YouTube: ").strip()
    if not url:
        print("Ошибка: ссылка не указана")
        return 1
    return 0 if check_video(url) else 1


if __name__ == "__main__":
    raise SystemExit(main())
