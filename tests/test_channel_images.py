"""Скрипт download_avatars.py: аватарка не должна подменяться шапкой канала.

Скрипт выбирал «самую большую картинку» из общего списка `thumbnails`, но
YouTube-экстрактор yt-dlp складывает туда и аватарку, и шапку канала. Шапка
2560x424 (1.08 Мпикс) крупнее аватарки 900x900 (0.81 Мпикс), поэтому в каталог
`avas/` попадала широкая полоса вместо круглой аватарки. На диске так и
оказались файлы 2560x424 у двух каналов из трёх.

Логика выбора теперь общая с channel_assets, чтобы дефект не разъезжался по
двум копиям.
"""
import io
import os
from PIL import Image

import pytest


# Список в том виде, в каком его отдаёт YouTube-экстрактор: аватарки и шапки
# вперемешку, шапка помечена preference = -10.
MIXED_THUMBNAILS = [
    {'url': 'https://x/ava=s48-c-k', 'width': 48, 'height': 48},
    {'url': 'https://x/ava=s900', 'width': 900, 'height': 900},
    {'url': 'https://x/ban=w2560', 'width': 2560, 'height': 424, 'preference': -10},
    {'url': 'https://x/ban=s0', 'id': 'banner_uncropped', 'preference': -5},
]


@pytest.fixture
def avatars_script():
    import download_avatars
    return download_avatars


def test_avatar_script_does_not_pick_banner(avatars_script, monkeypatch):
    """Скрипт обязан вернуть аватарку, а не шапку канала."""
    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            return {'thumbnails': MIXED_THUMBNAILS}

    monkeypatch.setattr(avatars_script.yt_dlp, 'YoutubeDL', FakeYDL)
    url = avatars_script._fetch_avatar_from_channel_url('https://youtube.com/@x', 'Автор')
    assert url, 'аватарка не найдена'
    assert 'ban' not in url, f'вместо аватарки выбрана шапка канала: {url}'


def test_avatar_script_shares_logic_with_channel_assets(avatars_script):
    """Выбор аватарки должен быть один на весь проект.

    Две независимые копии «возьми самую большую картинку» уже разъехались:
    channel_assets исправлен, а скрипт продолжал класть шапки в avas/.
    """
    import channel_assets
    assert avatars_script.pick_avatar is channel_assets.pick_avatar, \
        'скрипт держит свою копию выбора аватарки'


def test_saved_avatar_is_square(tmp_path, channel_assets, test_author, monkeypatch):
    """Файл в каталоге аватарок должен быть примерно квадратным.

    Проверка на реальном файле: широкую полосу 2560x424 в кружке аватарки
    браузер обрежет до середины шапки, и понять, что картинка неверная, по
    одному только URL нельзя.
    """
    banner = Image.new('RGB', (2560, 424), (10, 20, 30))
    avatar = Image.new('RGB', (900, 900), (200, 100, 50))
    files = {'https://x/ban=s0': banner, 'https://x/ava=s0': avatar}

    def fake_download(url, base_path):
        buf = io.BytesIO()
        files[url].save(buf, format='JPEG')
        with open(base_path + '.jpg', 'wb') as fh:
            fh.write(buf.getvalue())
        return os.path.basename(base_path) + '.jpg'

    monkeypatch.setattr(channel_assets, '_download_image', fake_download)
    channel_assets.save_channel_assets(test_author, {
        'avatar': 'https://x/ava=s0',
        'banner': 'https://x/ban=s0',
    })

    path = os.path.join(channel_assets.CHANNEL_ASSETS_DIR,
                        channel_assets.safe_name(test_author) + '.jpg')
    assert os.path.exists(path), 'аватарка не сохранена'
    with Image.open(path) as img:
        ratio = img.width / img.height
    assert 0.8 <= ratio <= 1.25, f'в каталоге аватарок лежит не аватарка: {img.size}'


def test_saved_banner_is_wide(channel_assets, test_author, monkeypatch):
    """Файл в каталоге шапок должен быть широким.

    `banner_uncropped` отдаёт необрезанный исходник 4096x2304 (16:9): в полосе
    высотой 220px от него видна только центральная треть, лица и текст на
    шапке уезжают за край. Нужен вариант, обрезанный под шапку.
    """
    wide = Image.new('RGB', (2560, 424), (0, 0, 0))
    tall = Image.new('RGB', (4096, 2304), (0, 0, 0))
    files = {'https://x/ban=w2560': wide, 'https://x/ban=s0': tall}

    def fake_download(url, base_path):
        buf = io.BytesIO()
        files[url].save(buf, format='JPEG')
        with open(base_path + '.jpg', 'wb') as fh:
            fh.write(buf.getvalue())
        return os.path.basename(base_path) + '.jpg'

    monkeypatch.setattr(channel_assets, '_download_image', fake_download)
    channel_assets.save_channel_assets(test_author, {
        'banner': channel_assets.pick_banner(MIXED_THUMBNAILS),
    })

    path = os.path.join(channel_assets.BANNERS_DIR,
                        channel_assets.safe_name(test_author) + '.jpg')
    assert os.path.exists(path), 'шапка не сохранена'
    with Image.open(path) as img:
        ratio = img.width / img.height
    assert ratio >= 3, f'шапка не обрезана под полосу: {img.size}, ratio={ratio:.2f}'


def test_banner_prefers_cropped_wide_variant(channel_assets):
    """Для шапки нужен широкий обрезанный вариант, а не 16:9 исходник."""
    assert channel_assets.pick_banner(MIXED_THUMBNAILS) == 'https://x/ban=w2560'


def test_banner_uncropped_used_when_no_cropped_variant(channel_assets):
    """Если обрезанного варианта нет, исходник лучше пустой шапки."""
    only_uncropped = [
        {'url': 'https://x/ava=s900', 'width': 900, 'height': 900},
        {'url': 'https://x/ban=s0', 'id': 'banner_uncropped', 'preference': -5},
    ]
    assert channel_assets.pick_banner(only_uncropped) == 'https://x/ban=s0'
