"""Ассеты канала: аватарка, шапка (баннер) и текстовые данные.

Шапки каналов не скачивались никогда. Причина в том, что код читал поля
`banner` / `banners`, которых у yt-dlp не существует: YouTube-экстрактор
складывает и аватарку, и баннер в общий список `thumbnails`, помечая их
идентификаторами `avatar_uncropped` и `banner_uncropped` (см. yt-dlp,
`extractor/youtube/_tab.py`, `_extract_metadata_from_tabs`). Каталог
`avas/banners/` в итоге оставался пустым, а страница канала показывала серую
заглушку вместо шапки.

Из той же причины следовали ещё два дефекта:

* аватарка выбиралась как «самая большая картинка из thumbnails», а баннер
  крупнее аватарки — на канале мог оказаться баннер вместо аватарки;
* `country` и `joined_date` читались из `channel_country` / `channel_joined`,
  которых у yt-dlp тоже нет, поэтому в сохранённых метаданных они всегда
  были пустыми строками.

Эти тесты фиксируют разбор настоящей структуры ответа yt-dlp.
"""
import json
import os

import pytest


# Список thumbnails в том виде, в каком его отдаёт YouTube-экстрактор yt-dlp:
# сначала аватарки, затем баннеры. Баннер шире аватарки — именно поэтому
# «самая большая картинка» давала баннер вместо аватарки.
YTDLP_THUMBNAILS = [
    {'url': 'https://yt3.googleusercontent.com/ava=s48-c-k', 'width': 48, 'height': 48},
    {'url': 'https://yt3.googleusercontent.com/ava=s160-c-k', 'width': 160, 'height': 160},
    {'url': 'https://yt3.googleusercontent.com/ava=s0', 'id': 'avatar_uncropped',
     'preference': 1},
    {'url': 'https://yt3.googleusercontent.com/ban=w1060-fcrop64', 'width': 1060,
     'height': 175, 'preference': -10},
    {'url': 'https://yt3.googleusercontent.com/ban=w2560-fcrop64', 'width': 2560,
     'height': 424, 'preference': -10},
    {'url': 'https://yt3.googleusercontent.com/ban=s0', 'id': 'banner_uncropped',
     'preference': -5},
]


def test_avatar_is_not_taken_from_banner(channel_assets):
    """Аватарка не должна выбираться как «самая большая картинка».

    Баннер 2560x424 крупнее любой аватарки, поэтому прежний выбор по площади
    ставил на страницу канала шапку вместо круглой аватарки.
    """
    avatar = channel_assets.pick_avatar(YTDLP_THUMBNAILS)
    assert avatar, 'аватарка не найдена в thumbnails'
    assert 'ban' not in avatar, f'вместо аватарки выбран баннер: {avatar}'


def test_avatar_prefers_uncropped(channel_assets):
    """`avatar_uncropped` — оригинал без обрезки, он нужен для крупного круга."""
    assert channel_assets.pick_avatar(YTDLP_THUMBNAILS) == \
        'https://yt3.googleusercontent.com/ava=s0'


def test_banner_is_found_in_thumbnails(channel_assets):
    """Баннер лежит в thumbnails, а не в отдельном поле.

    Поля `banner` и `banners` в выводе yt-dlp отсутствуют — из-за чтения именно
    их шапки не скачивались вообще.
    """
    banner = channel_assets.pick_banner(YTDLP_THUMBNAILS)
    assert banner, 'баннер не найден в thumbnails'
    assert 'ban' in banner, f'вместо баннера выбрана аватарка: {banner}'


def test_banner_prefers_widest_cropped_variant(channel_assets):
    """Шапка растягивается на всю ширину, нужен самый широкий обрезанный файл.

    `banner_uncropped` не подходит: это исходник 16:9, в полосе высотой 220px
    от него видна лишь центральная треть. Подробнее — в docstring pick_banner.
    """
    assert channel_assets.pick_banner(YTDLP_THUMBNAILS) == \
        'https://yt3.googleusercontent.com/ban=w2560-fcrop64'


def test_banner_detected_by_id_alone(channel_assets):
    """Одного `banner` в id достаточно: ни preference, ни размеров может не быть.

    В общем наборе у шапок есть и preference, и широкие размеры, поэтому
    распознавание по id там подменяется другими признаками. Здесь остаётся
    только id — так проверяется именно он.
    """
    thumbs = [{'url': 'https://yt3.googleusercontent.com/ban=s0', 'id': 'banner'}]
    assert channel_assets.pick_banner(thumbs) == \
        'https://yt3.googleusercontent.com/ban=s0'
    assert channel_assets.pick_avatar(thumbs) is None, \
        'шапка попала в аватарки'


def test_banner_falls_back_to_uncropped_without_sizes(channel_assets):
    """Без размеров у обрезанных вариантов берём оригинал, а не первый в списке.

    yt-dlp не всегда отдаёт width/height для обрезанных шапок. Выбор «первого
    подходящего» дал бы узкое превью 1060px, растянутое на всю ширину страницы,
    тогда как оригинал остаётся резким.
    """
    thumbs = [
        {'url': 'https://yt3.googleusercontent.com/ban=w1060-fcrop64',
         'preference': -10},
        {'url': 'https://yt3.googleusercontent.com/ban=s0',
         'id': 'banner_uncropped', 'preference': -5},
    ]
    assert channel_assets.pick_banner(thumbs) == \
        'https://yt3.googleusercontent.com/ban=s0'


def test_banner_absent_when_channel_has_none(channel_assets):
    """У части каналов шапки нет: тогда баннер не должен «находиться»."""
    only_avatars = [t for t in YTDLP_THUMBNAILS if 'ava' in t['url']]
    assert channel_assets.pick_banner(only_avatars) is None


def test_banner_detected_by_aspect_ratio(channel_assets):
    """Без id и preference шапку выдаёт соотношение сторон.

    yt-dlp расставляет метки не для всех записей, а аватарка всегда квадратная.
    """
    thumbs = [
        {'url': 'https://x/ava', 'width': 900, 'height': 900},
        {'url': 'https://x/ban', 'width': 2560, 'height': 424},
    ]
    assert channel_assets.pick_banner(thumbs) == 'https://x/ban'
    assert channel_assets.pick_avatar(thumbs) == 'https://x/ava'


def test_avatar_is_square_even_when_banner_is_bigger(channel_assets):
    """Проверка на подмену без опоры на `avatar_uncropped`.

    Раньше выбор шёл по площади, и баннер 2560x424 (1.08 Мпикс) обходил
    аватарку 900x900 (0.81 Мпикс).
    """
    thumbs = [
        {'url': 'https://x/ava', 'width': 900, 'height': 900},
        {'url': 'https://x/ban', 'width': 2560, 'height': 424, 'preference': -10},
    ]
    assert channel_assets.pick_avatar(thumbs) == 'https://x/ava'


def test_avatar_falls_back_to_largest_square(channel_assets):
    """Без `avatar_uncropped` берём самую большую квадратную картинку."""
    thumbs = [
        {'url': 'https://x/ava=s48', 'width': 48, 'height': 48},
        {'url': 'https://x/ava=s176', 'width': 176, 'height': 176},
    ]
    assert channel_assets.pick_avatar(thumbs) == 'https://x/ava=s176'


def test_fetch_channel_info_reads_real_ytdlp_fields(channel_assets, monkeypatch):
    """Разбор ответа целиком: аватар, баннер, описание, подписчики, страна.

    Раньше `fetch_channel_info` делала два запроса и оба разбирала по
    несуществующим полям. Здесь подставляется структура, которую yt-dlp
    возвращает на самом деле.
    """
    info = {
        'id': 'UCabc',
        'channel_id': 'UCabc',
        'title': 'Канал',
        'description': 'Описание канала',
        'channel_follower_count': 89600,
        'thumbnails': YTDLP_THUMBNAILS,
        'tags': ['авто'],
        'channel_is_verified': True,
        'view_count': 123456,
        'playlist_count': 250,
        'uploader_id': '@channel',
    }
    monkeypatch.setattr(channel_assets, '_extract_channel', lambda url: info)

    result = channel_assets.fetch_channel_info('https://www.youtube.com/channel/UCabc',
                                               raise_on_error=True)

    assert result['description'] == 'Описание канала'
    assert result['subscribers'] == 89600
    assert result['channel_id'] == 'UCabc'
    assert 'ava' in result['avatar']
    assert 'ban' in result['banner'], 'баннер не извлечён из thumbnails'
    assert result['verified'] is True
    assert result['tags'] == ['авто']
    assert result['view_count'] == 123456
    assert result['video_count'] == 250, 'не извлечено число видео на канале'
    assert result['handle'] == '@channel', 'не извлечён хэндл канала'


def test_fetch_channel_info_adds_about_page_fields(channel_assets, monkeypatch):
    """Страна, дата регистрации и ссылки берутся со страницы /about.

    yt-dlp этих полей не отдаёт, поэтому `country` и `joined_date` в метаданных
    всегда были пустыми. Просмотры у yt-dlp тоже отсутствуют (`view_count` для
    канала = None), а на /about они есть.
    """
    monkeypatch.setattr(channel_assets, '_extract_channel', lambda url: {
        'id': 'UCabc',
        'thumbnails': YTDLP_THUMBNAILS,
        'description': 'из yt-dlp',
        'channel_follower_count': 89600,
    })
    monkeypatch.setattr(channel_assets.channel_about, 'fetch_about', lambda url: {
        'country': 'Грузия',
        'joined_date': '2 янв. 2025 г.',
        'view_count': 421993052,
        'links': [{'title': 'Телеграм', 'url': 'https://t.me/x'}],
    })

    result = channel_assets.fetch_channel_info('https://www.youtube.com/@x')
    assert result['country'] == 'Грузия'
    assert result['joined_date'] == '2 янв. 2025 г.'
    assert result['view_count'] == 421993052
    assert result['links'] == [{'title': 'Телеграм', 'url': 'https://t.me/x'}]


def test_ytdlp_data_wins_over_about_page(channel_assets, monkeypatch):
    """Данные yt-dlp приоритетнее: /about — только дополнение.

    Разбор HTML ломается при каждом изменении вёрстки YouTube, поэтому он не
    должен затирать то, что уже пришло из поддерживаемого API.
    """
    monkeypatch.setattr(channel_assets, '_extract_channel', lambda url: {
        'id': 'UCabc',
        'thumbnails': YTDLP_THUMBNAILS,
        'description': 'из yt-dlp',
        'channel_follower_count': 89600,
        'playlist_count': 148,
    })
    monkeypatch.setattr(channel_assets.channel_about, 'fetch_about', lambda url: {
        'description': 'из HTML',
        'subscribers': 1,
        'video_count': 999,
    })

    result = channel_assets.fetch_channel_info('https://www.youtube.com/@x')
    assert result['description'] == 'из yt-dlp'
    assert result['subscribers'] == 89600
    assert result['video_count'] == 148


def test_about_page_failure_does_not_break_sync(channel_assets, monkeypatch):
    """Если /about недоступен, синхронизация продолжается.

    Капча или страница согласия — обычное дело, и терять из-за них аватар с
    шапкой нельзя.
    """
    monkeypatch.setattr(channel_assets, '_extract_channel', lambda url: {
        'id': 'UCabc', 'thumbnails': YTDLP_THUMBNAILS, 'description': 'ок',
    })

    def boom(url):
        raise RuntimeError('капча')

    monkeypatch.setattr(channel_assets.channel_about, 'fetch_about', boom)
    result = channel_assets.fetch_channel_info('https://www.youtube.com/@x')
    assert result['description'] == 'ок'
    assert result['country'] == ''
    assert 'ban' in result['banner']


def test_saved_meta_keeps_links(channel_assets, test_author):
    """Ссылки канала должны сохраняться в метаданные."""
    channel_assets.save_channel_assets(test_author, {
        'links': [{'title': 'Сайт', 'url': 'https://example.com'}],
    })
    meta = channel_assets.load_channel_meta(test_author)
    assert meta['links'] == [{'title': 'Сайт', 'url': 'https://example.com'}]


def test_video_count_sums_channel_tabs(channel_assets, monkeypatch):
    """`playlist_count` у канала означает разное в зависимости от ответа.

    Проверено на живых каналах: у `@AnataCars` ответ — плоский список видео и
    `playlist_count` = 148 (это видео), а у `@AvocadoAnimations` ответ — список
    вкладок и `playlist_count` = 2 (вкладки «Видео» и «Shorts», внутри которых
    46 и 34 записи). Без разбора вкладок на странице канала с миллионами
    подписчиков появлялось «Видео на канале: 2».
    """
    info = {
        'id': 'UCabc',
        '_type': 'playlist',
        'playlist_count': 2,
        'thumbnails': YTDLP_THUMBNAILS,
        'entries': [
            {'_type': 'playlist', 'title': 'Канал - Videos', 'playlist_count': 46},
            {'_type': 'playlist', 'title': 'Канал - Shorts', 'playlist_count': 34},
        ],
    }
    monkeypatch.setattr(channel_assets, '_extract_channel', lambda url: info)

    result = channel_assets.fetch_channel_info('https://www.youtube.com/@x')
    assert result['video_count'] == 80, 'вкладки канала не просуммированы'


def test_video_count_used_as_is_for_flat_list(channel_assets, monkeypatch):
    """Если ответ — плоский список видео, `playlist_count` уже верен."""
    info = {
        'id': 'UCabc',
        'playlist_count': 148,
        'thumbnails': YTDLP_THUMBNAILS,
        'entries': [{'_type': 'url', 'title': f'видео {i}'} for i in range(148)],
    }
    monkeypatch.setattr(channel_assets, '_extract_channel', lambda url: info)

    assert channel_assets.fetch_channel_info('https://www.youtube.com/@x')['video_count'] == 148


def test_fetch_channel_info_needs_single_request(channel_assets, monkeypatch):
    """Один запрос вместо двух.

    Второй запрос делался только ради баннера и с `extract_flat=False`, то есть
    YouTube отдавал полный список видео канала. Для картинки в шапке это
    лишние секунды и лишний трафик на каждое открытие страницы.
    """
    calls = []

    def counted(url):
        calls.append(url)
        return {'id': 'UCabc', 'thumbnails': YTDLP_THUMBNAILS, 'description': ''}

    monkeypatch.setattr(channel_assets, '_extract_channel', counted)
    channel_assets.fetch_channel_info('https://www.youtube.com/channel/UCabc')

    assert len(calls) == 1, f'запросов к YouTube: {len(calls)}, ожидался один'


def test_save_channel_assets_writes_banner_file(channel_assets, test_author, monkeypatch):
    """Баннер должен оказаться файлом в каталоге шапок."""
    saved = {}

    def fake_download(url, base_path):
        saved[url] = base_path
        name = os.path.basename(base_path) + '.jpg'
        with open(base_path + '.jpg', 'wb') as fh:
            fh.write(b'\xff\xd8\xff')
        return name

    monkeypatch.setattr(channel_assets, '_download_image', fake_download)
    channel_assets.save_channel_assets(test_author, {
        'avatar': 'https://x/ava=s0',
        'banner': 'https://x/ban=s0',
        'description': 'desc',
    })

    banner_dir_files = list(saved.values())
    assert any(channel_assets.BANNERS_DIR in path for path in banner_dir_files), \
        'баннер не сохранён в каталог шапок'
    assert channel_assets.get_banner_url(test_author), 'баннер не виден странице канала'


def test_saved_meta_keeps_extra_channel_fields(channel_assets, test_author):
    """Число видео, просмотры и галочка канала должны сохраняться.

    Раньше сохранялись только описание, подписчики и id, поэтому вкладка
    «О канале» показывала лишь количество локальных файлов.
    """
    channel_assets.save_channel_assets(test_author, {
        'description': 'desc',
        'subscribers': 1000,
        'channel_id': 'UCx',
        'video_count': 250,
        'view_count': 9000000,
        'verified': True,
        'tags': ['музыка'],
    })

    meta = channel_assets.load_channel_meta(test_author)
    assert meta['video_count'] == 250
    assert meta['view_count'] == 9000000
    assert meta['verified'] is True
    assert meta['tags'] == ['музыка']


def test_channel_page_shows_banner(client, app_module, channel_assets, monkeypatch):
    """Шапка должна попадать в разметку страницы канала.

    Файл кладём на диск по-настоящему: `get_banner_url` перебирает каталог, и с
    заглушкой проверка прошла бы и при неработающей выдаче файла.
    """
    app_module.build_video_map()
    author = next((v['author'] for v in app_module.VIDEO_MAP.values()), None)
    if not author:
        pytest.skip('в библиотеке нет видео')

    channel_assets._ensure_dirs()
    path = os.path.join(channel_assets.BANNERS_DIR,
                        channel_assets.safe_name(author) + '.jpg')
    created = not os.path.exists(path)
    if created:
        with open(path, 'wb') as fh:
            fh.write(b'\xff\xd8\xff')
    try:
        html = client.get(f'/channel/{author}').get_data(as_text=True)
        assert 'class="banner' in html, 'на странице канала нет блока шапки'
        assert channel_assets.get_banner_url(author) in html, \
            'шапка не подставлена в разметку'
    finally:
        if created and os.path.exists(path):
            os.remove(path)


def test_channel_page_serves_banner_file(client, app_module, channel_assets):
    """Маршрут выдачи шапки должен отдавать файл, а не 404."""
    app_module.build_video_map()
    author = next((v['author'] for v in app_module.VIDEO_MAP.values()), None)
    if not author:
        pytest.skip('в библиотеке нет видео')

    channel_assets._ensure_dirs()
    safe = channel_assets.safe_name(author)
    path = os.path.join(channel_assets.BANNERS_DIR, safe + '.jpg')
    created = not os.path.exists(path)
    if created:
        with open(path, 'wb') as fh:
            fh.write(b'\xff\xd8\xff')
    try:
        assert client.get(f'/channel_banner/{safe}.jpg').status_code == 200
    finally:
        if created and os.path.exists(path):
            os.remove(path)


def test_channel_page_shows_extra_channel_facts(client, app_module, channel_assets,
                                                monkeypatch):
    """Вкладка «О канале» должна показывать данные с YouTube.

    Раньше там было только число локальных файлов: просмотры, число видео на
    канале и ссылка на сам канал не сохранялись.
    """
    app_module.build_video_map()
    author = next((v['author'] for v in app_module.VIDEO_MAP.values()), None)
    if not author:
        pytest.skip('в библиотеке нет видео')

    # Значения намеренно уникальны и не встречаются в CSS страницы: иначе
    # проверка прошла бы и при потерянном поле.
    monkeypatch.setattr(channel_assets, 'load_channel_meta', lambda a: {
        'description': 'Описание',
        'subscribers': 89600,
        'video_count': 8351,
        'view_count': 9000000,
        'handle': '@handle_marker',
        'channel_url': 'https://www.youtube.com/@url_marker',
        'verified': True,
    })
    html = client.get(f'/channel/{author}').get_data(as_text=True)

    assert '>8351<' in html, 'не показано число видео на канале'
    assert '9 млн' in html, 'просмотры не отформатированы'
    assert '@handle_marker' in html, 'не показан хэндл канала'
    assert 'youtube.com/@url_marker' in html, 'нет ссылки на канал'
    # Открытая вкладка без rel=noopener получает доступ к window.opener.
    assert 'rel="noopener noreferrer"' in html, 'внешняя ссылка без rel=noopener'


def test_channel_page_shows_country_joined_and_links(client, app_module, channel_assets,
                                                     monkeypatch):
    """Страна, дата регистрации и внешние ссылки должны быть на странице."""
    app_module.build_video_map()
    author = next((v['author'] for v in app_module.VIDEO_MAP.values()), None)
    if not author:
        pytest.skip('в библиотеке нет видео')

    monkeypatch.setattr(channel_assets, 'load_channel_meta', lambda a: {
        'description': 'Описание канала',
        'country': 'Грузия',
        'joined_date': '2 янв. 2025 г.',
        'links': [
            {'title': 'Телеграм Канал', 'url': 'https://t.me/marker_one'},
            {'title': 'Мой ВПН', 'url': 'https://t.me/marker_two'},
        ],
    })
    html = client.get(f'/channel/{author}').get_data(as_text=True)

    assert 'Грузия' in html, 'не показана страна канала'
    assert '2 янв. 2025 г.' in html, 'не показана дата регистрации'
    assert 'Описание канала' in html, 'не показано описание'
    assert 'https://t.me/marker_one' in html, 'не показана первая ссылка канала'
    assert 'Телеграм Канал' in html, 'у ссылки канала нет названия'
    assert 'https://t.me/marker_two' in html, 'показана только одна ссылка из двух'


def test_channel_page_escapes_link_titles(client, app_module, channel_assets, monkeypatch):
    """Название ссылки приходит с YouTube: теги в нём не должны стать разметкой."""
    app_module.build_video_map()
    author = next((v['author'] for v in app_module.VIDEO_MAP.values()), None)
    if not author:
        pytest.skip('в библиотеке нет видео')

    monkeypatch.setattr(channel_assets, 'load_channel_meta', lambda a: {
        'links': [{'title': '<img src=x onerror=alert(1)>', 'url': 'https://example.com'}],
    })
    html = client.get(f'/channel/{author}').get_data(as_text=True)

    assert '<img src=x onerror=alert(1)>' not in html, 'название ссылки не экранировано'
    assert '&lt;img' in html, 'название ссылки потерялось'


def test_channel_page_rejects_javascript_links(client, app_module, channel_assets,
                                               monkeypatch):
    """Схема javascript: в href не должна попасть в разметку.

    Метаданные лежат в JSON на диске; правка файла вручную не должна давать
    исполняемый код на странице.
    """
    app_module.build_video_map()
    author = next((v['author'] for v in app_module.VIDEO_MAP.values()), None)
    if not author:
        pytest.skip('в библиотеке нет видео')

    monkeypatch.setattr(channel_assets, 'load_channel_meta', lambda a: {
        'links': [{'title': 'Плохая', 'url': 'javascript:alert(1)'}],
    })
    html = client.get(f'/channel/{author}').get_data(as_text=True)

    assert 'javascript:alert' not in html, 'опасная схема попала в href'


def test_stale_meta_is_resynced_once(channel_assets, test_author, monkeypatch,
                                    real_try_fetch_if_missing):
    """Метаданные от сломанного кода должны обновиться сами.

    Каналы, синхронизированные до исправления, лежат на диске со статусом
    `success`, без шапки и с пустыми полями. Проверка «success — больше не
    трогаем» защищает от бесконечных повторов, но она же навсегда оставила бы
    такие каналы без шапки. Различаем по версии схемы метаданных.
    """
    channel_assets._ensure_dirs()
    path = os.path.join(channel_assets.META_DIR,
                        channel_assets.safe_name(test_author) + '.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'description': 'desc', 'subscribers': 100, 'country': '',
                   'joined_date': '', 'sync_status': 'success',
                   'updated_at': 1.0}, fh, ensure_ascii=False)
    calls = []
    monkeypatch.setattr(channel_assets, 'sync_channel', lambda a, *args, **kw: calls.append(a))

    monkeypatch.setattr(channel_assets, 'get_banner_url', lambda author: None)
    real_try_fetch_if_missing(test_author)
    assert calls, 'канал со старой схемой метаданных не пересинхронизирован'


def test_current_meta_without_banner_is_not_resynced(channel_assets, test_author,
                                                     monkeypatch,
                                                     real_try_fetch_if_missing):
    """У части каналов шапки нет вообще: повторы должны прекратиться.

    Метаданные, записанные уже исправленным кодом, повторно не запрашиваются,
    иначе каждое открытие страницы снова дёргало бы YouTube.
    """
    channel_assets.save_channel_assets(test_author, {'description': 'desc'})
    channel_assets.update_sync_status(test_author, 'success', success=True)
    calls = []
    monkeypatch.setattr(channel_assets, 'sync_channel', lambda a, *args, **kw: calls.append(a))
    monkeypatch.setattr(channel_assets, 'get_banner_url', lambda author: None)

    real_try_fetch_if_missing(test_author)
    assert not calls, f'лишняя синхронизация канала без шапки: {calls}'


def test_saved_meta_records_schema_version(channel_assets, test_author):
    """Версия схемы пишется в метаданные, иначе повтор случится ещё раз."""
    channel_assets.save_channel_assets(test_author, {'description': 'desc'})
    meta = channel_assets.load_channel_meta(test_author)
    assert meta.get('meta_version') == channel_assets.META_VERSION


def test_banner_refresh_replaces_old_file(channel_assets, test_author, monkeypatch):
    """Новая шапка не должна оставлять рядом файл с прежним расширением.

    Иначе `get_banner_url` перебирает каталог и может вернуть устаревший .jpg
    вместо только что скачанного .webp.
    """
    channel_assets._ensure_dirs()
    safe = channel_assets.safe_name(test_author)
    stale = os.path.join(channel_assets.BANNERS_DIR, safe + '.jpg')
    with open(stale, 'wb') as fh:
        fh.write(b'old')

    def fake_download(url, base_path):
        with open(base_path + '.webp', 'wb') as fh:
            fh.write(b'new')
        return os.path.basename(base_path) + '.webp'

    monkeypatch.setattr(channel_assets, '_download_image', fake_download)
    channel_assets.save_channel_assets(test_author, {'banner': 'https://x/ban=s0'})

    assert not os.path.exists(stale), 'старый файл шапки остался рядом с новым'
    assert channel_assets.get_banner_url(test_author).endswith('.webp')
