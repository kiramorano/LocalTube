# diagnostic.py
import os
import sys
import shutil

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
USER_VIDEOS_ROOT = "uservideos"
BASE_VIDEO_DIR = "videos"
AVATARS_DIR = "avas"

print("=" * 60)
print("ДИАГНОСТИКА ПОЛЬЗОВАТЕЛЬСКИХ ВИДЕО")
print("=" * 60)

# 1. Проверка папок
print("\n1. СУЩЕСТВУЮЩИЕ ПАПКИ:")
for folder in [USER_VIDEOS_ROOT, BASE_VIDEO_DIR, AVATARS_DIR]:
    path = os.path.join(PROJECT_DIR, folder)
    exists = os.path.exists(path)
    print(f"   {folder}: {'есть' if exists else 'НЕТ'}")
    if exists:
        print(f"      содержимое: {os.listdir(path) if os.listdir(path) else 'пусто'}")

# 2. Проверка прав записи в корне
print("\n2. ПРАВА ЗАПИСИ В КОРНЕ ПРОЕКТА:")
test_file = os.path.join(PROJECT_DIR, "test_write.tmp")
try:
    with open(test_file, 'w') as f:
        f.write("test")
    os.remove(test_file)
    print("   ✅ можно создавать временные файлы")
except:
    print("   ❌ НЕЛЬЗЯ создавать временные файлы (ошибка прав)")

# 3. Поиск пользовательских видео
print("\n3. ПОИСК ПОЛЬЗОВАТЕЛЬСКИХ ВИДЕО (uservideos):")
user_videos_dir = os.path.join(PROJECT_DIR, USER_VIDEOS_ROOT)
if os.path.exists(user_videos_dir):
    for user in os.listdir(user_videos_dir):
        user_path = os.path.join(user_videos_dir, user)
        if not os.path.isdir(user_path):
            continue
        print(f"   Пользователь: {user}")
        for vid_folder in os.listdir(user_path):
            vid_path = os.path.join(user_path, vid_folder)
            if not os.path.isdir(vid_path):
                continue
            info_file = os.path.join(vid_path, "info.json")
            video_file = None
            for ext in ['.mp4', '.mkv', '.webm', '.avi', '.mov']:
                cand = os.path.join(vid_path, f"video{ext}")
                if os.path.exists(cand):
                    video_file = cand
                    break
            print(f"      Видео ID: {vid_folder}")
            print(f"         info.json: {'есть' if os.path.exists(info_file) else 'НЕТ'}")
            print(f"         video.mp4: {'есть' if video_file else 'НЕТ'}")
            if video_file:
                size = round(os.path.getsize(video_file) / (1024*1024), 2)
                print(f"         размер: {size} МБ")
            if os.path.exists(info_file):
                try:
                    import json
                    with open(info_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    print(f"         автор: {data.get('author')}")
                    print(f"         название: {data.get('title')}")
                except Exception as e:
                    print(f"         ошибка чтения info.json: {e}")
else:
    print("   Папка uservideos не существует")

# 4. Тестирование маршрута /usermedia (имитация)
print("\n4. ТЕСТИРОВАНИЕ МАРШРУТА /usermedia:")
if os.path.exists(user_videos_dir):
    for user in os.listdir(user_videos_dir):
        user_path = os.path.join(user_videos_dir, user)
        if not os.path.isdir(user_path):
            continue
        for vid_folder in os.listdir(user_path):
            vid_path = os.path.join(user_path, vid_folder)
            if not os.path.isdir(vid_path):
                continue
            video_file = None
            for ext in ['.mp4', '.mkv', '.webm', '.avi', '.mov']:
                cand = os.path.join(vid_path, f"video{ext}")
                if os.path.exists(cand):
                    video_file = cand
                    break
            if video_file:
                # Относительный путь, который должен быть в URL
                rel_path = os.path.relpath(video_file, start=user_videos_dir).replace('\\', '/')
                print(f"   Если запросить /usermedia/{rel_path}, файл должен отдаться")
                print(f"   Полный путь: {video_file}")
                print(f"   Существует? {os.path.exists(video_file)}")
                break  # достаточно одного
            break
        break

# 5. Проверка сериализации в USER_VIDEO_MAP (через get_all_user_videos из user_videos)
print("\n5. ПРОВЕРКА ФУНКЦИИ get_all_user_videos():")
try:
    sys.path.insert(0, PROJECT_DIR)
    from user_videos import get_all_user_videos
    all_vids = get_all_user_videos()
    print(f"   Найдено: {len(all_vids)} видео")
    for v in all_vids:
        print(f"   ID: {v.get('id')}, автор: {v.get('author')}, путь: {v.get('video_path')}")
        # Проверяем, можно ли получить URL
        if v.get('video_path'):
            rel = os.path.relpath(v['video_path'], start=os.path.join(PROJECT_DIR, USER_VIDEOS_ROOT)).replace('\\', '/')
            url = f"/usermedia/{rel}"
            print(f"      URL: {url}")
            print(f"      файл существует: {os.path.exists(v['video_path'])}")
except Exception as e:
    print(f"   ОШИБКА: {e}")

print("\n" + "=" * 60)
print("Диагностика завершена. Скопируйте этот вывод в чат.")