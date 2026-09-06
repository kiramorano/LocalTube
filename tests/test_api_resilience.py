"""Проверки живучести API.

Здесь зафиксированы отказы, которые уже случались: запрос без Content-Type
валил маршрут с 415 и HTML-страницей вместо JSON, превью без файла отдавало 500,
а имя темы уходило прямо в путь на диске.
"""
import ast
import json
import os
import re

import pytest

import app as app_module


@pytest.fixture()
def client():
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as test_client:
        yield test_client


# Маршруты, которые читают тело запроса. request.json на запросе без
# Content-Type: application/json поднимает 415 и отдаёт HTML, на котором
# клиентский res.json() падает с SyntaxError вместо понятной ошибки.
JSON_ROUTES = [
    ('/api/formats', 'POST'),
    ('/api/direct_download', 'POST'),
    ('/api/playlist/info', 'POST'),
    ('/api/cookies/from-browser', 'POST'),
    ('/api/cookies/import', 'POST'),
    ('/api/userdata/hidden-channel', 'POST'),
    ('/api/thumbnails/generate', 'POST'),
    ('/api/convert/some-id', 'POST'),
]


@pytest.mark.parametrize('path,method', JSON_ROUTES)
def test_routes_answer_json_without_content_type(client, path, method):
    """Ответ должен быть JSON даже на мусорное тело без Content-Type."""
    response = client.open(path, method=method, data='not json at all')
    assert response.status_code != 415, f'{path}: 415 вместо разбора тела'
    assert response.is_json, f'{path}: отдан не JSON ({response.content_type})'


@pytest.mark.parametrize('path,method', JSON_ROUTES)
def test_routes_answer_json_on_empty_body(client, path, method):
    """Пустое тело — тоже не повод падать с HTML-страницей."""
    response = client.open(path, method=method)
    assert response.status_code != 415, f'{path}: 415 на пустом теле'
    assert response.is_json, f'{path}: отдан не JSON ({response.content_type})'


def test_thumbnail_of_unknown_video_returns_image(client):
    """Раньше здесь отдавался несуществующий static/images/lazy_placeholder.gif.

    send_file на отсутствующем пути поднимал ошибку, поэтому каждое видео без
    превью давало ошибку в консоли браузера, а предзагрузка превью на главной
    заваливала лог.
    """
    response = client.get('/api/thumbnail/no-such-video-id')
    assert response.status_code == 200
    assert response.mimetype == 'image/gif'
    # Отдаём валидный GIF, а не пустое тело: пустой ответ браузер рисует
    # «сломанной картинкой».
    assert response.data.startswith(b'GIF89a')


def test_thumbnail_placeholder_is_cacheable(client):
    """Заглушка запрашивается на каждую карточку — без кэша это лишние запросы."""
    response = client.get('/api/thumbnail/no-such-video-id')
    assert 'max-age' in response.headers.get('Cache-Control', '')


def test_theme_backgrounds_rejects_unknown_theme(client):
    """Имя темы попадает в путь на диске, поэтому список тем закрытый."""
    response = client.get('/api/theme-backgrounds/dark')
    assert response.status_code == 200
    assert response.get_json() == []


def test_theme_backgrounds_are_sorted(client):
    """os.listdir отдаёт порядок файловой системы.

    Из-за этого разные страницы получали список в разном порядке, и переход
    между страницами менял обои при неизменном наборе файлов.
    """
    images = client.get('/api/theme-backgrounds/frutiger-aero').get_json()
    assert images == sorted(images)


def test_theme_backgrounds_only_lists_images(client):
    """В каталог темы легко попасть постороннему файлу; отдавать его незачем."""
    images = client.get('/api/theme-backgrounds/frutiger-aero').get_json()
    assert all(name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) for name in images)


def test_dead_frutiger_endpoint_removed(client):
    """/api/frutiger/backgrounds не использовался ни одной страницей."""
    assert client.get('/api/frutiger/backgrounds').status_code == 404


def test_temp_upload_paths_are_unique():
    """Временный файл назывался temp_video.mp4 в корне проекта.

    Две одновременные загрузки писали в один файл, и первая получала чужое
    видео.
    """
    first = app_module._temp_upload_path('video', 'clip.mp4')
    second = app_module._temp_upload_path('video', 'clip.mp4')
    assert first != second
    assert first.endswith('.mp4') and second.endswith('.mp4')


def test_temp_upload_path_survives_missing_filename():
    """filename может быть None — os.path.splitext на None падает с TypeError."""
    path = app_module._temp_upload_path('video', None)
    assert os.path.basename(path).startswith('video_')


def test_temp_upload_path_stays_inside_temp_dir():
    """Имя файла приходит от клиента, поэтому расширение чистим."""
    path = app_module._temp_upload_path('video', 'clip.mp4/../../../evil.exe')
    resolved = os.path.realpath(path)
    assert resolved.startswith(os.path.realpath(app_module.TEMP_UPLOAD_DIR))


def test_queue_task_ids_are_unique():
    """id считался как md5(time.time() + url)[:8].

    Разрешение таймера на Windows грубое, поэтому два быстрых добавления одной
    ссылки давали одинаковый id, а он — ключ для отмены и приоритета.
    """
    with app_module.queue_lock:
        ids = {app_module._new_task_id_locked() for _ in range(200)}
    assert len(ids) == 200


def test_queue_list_reports_pause_state(client):
    """Пауза читается под тем же локом, что и список задач.

    Раньше флаг писался без лока, а читался под ним: запись могла попасть между
    чтением и записью файла, и после перезапуска пауза пропадала.
    """
    try:
        assert client.post('/api/queue/pause').status_code == 200
        assert client.get('/api/queue/list').get_json()['paused'] is True
    finally:
        client.post('/api/queue/resume')
    assert client.get('/api/queue/list').get_json()['paused'] is False


def test_cookies_import_rejects_empty_payload(client):
    """Пустой импорт затирал рабочие cookies."""
    response = client.post('/api/cookies/import',
                           data=json.dumps({'text': '   '}),
                           content_type='application/json')
    assert response.status_code == 400
    assert response.is_json


def test_cookies_import_keeps_existing_file_on_garbage(client, tmp_path, monkeypatch):
    """Мусорный импорт не должен затирать рабочий файл cookies.

    Ветка Netscape писала файл напрямую через open(...,'w'), в обход проверки на
    «ни одной cookie не распознано», поэтому вставка мусора обнуляла авторизацию.
    """
    cookies_path = tmp_path / 'cookies.txt'
    cookies_path.write_text('# Netscape HTTP Cookie File\nkeep-me', encoding='utf-8')
    monkeypatch.setattr(app_module, 'COOKIES_PATH', str(cookies_path))

    response = client.post('/api/cookies/import',
                           data=json.dumps({'text': 'это не cookies'}),
                           content_type='application/json')
    assert response.status_code == 400
    assert 'keep-me' in cookies_path.read_text(encoding='utf-8')


def test_api_errors_are_json(client):
    """На /api/... ошибка должна приходить в JSON.

    По умолчанию Flask отдаёт HTML, и клиентский res.json() падал с SyntaxError
    вместо показа причины — в интерфейсе это выглядело как «ничего не произошло».
    """
    response = client.get('/api/no-such-endpoint')
    assert response.status_code == 404
    assert response.is_json
    assert 'error' in response.get_json()


def test_page_errors_stay_html(client):
    """Обычные страницы должны и дальше отдавать HTML-страницу ошибки."""
    response = client.get('/no-such-page')
    assert response.status_code == 404
    assert not response.is_json


def test_progress_save_is_throttled(monkeypatch):
    """save_queue на каждый тик прогресса — это запись файла раз в секунду.

    write_json_atomic пишет временный файл, копию .bak и делает fsync, а
    прогресс приходит от yt-dlp примерно раз в секунду на каждую загрузку.
    """
    calls = []
    monkeypatch.setattr(app_module, 'save_queue', lambda: calls.append(1) or '')
    monkeypatch.setattr(app_module, '_last_progress_save', app_module.time.monotonic())

    for _ in range(20):
        app_module.save_queue_progress()
    assert calls == [], 'прогресс сохраняется без троттлинга'

    # По истечении интервала запись обязана произойти: иначе прогресс не
    # доживёт до перезапуска вообще.
    monkeypatch.setattr(app_module, '_last_progress_save',
                        app_module.time.monotonic() - app_module.PROGRESS_SAVE_INTERVAL - 1)
    app_module.save_queue_progress()
    assert calls == [1]


def test_video_info_reads_bom_file(tmp_path):
    """info.json с BOM: с encoding='utf-8' json.load падал, метаданные терялись."""
    (tmp_path / 'info.json').write_text(
        json.dumps({'title': 'С BOM', 'id': 'abc'}), encoding='utf-8-sig')
    meta = app_module.read_video_info(str(tmp_path))
    assert meta.get('title') == 'С BOM'


def test_video_info_survives_broken_json(tmp_path):
    """Битый info.json не должен ронять страницу видео."""
    (tmp_path / 'info.json').write_text('{ это не json', encoding='utf-8')
    assert app_module.read_video_info(str(tmp_path)) == {}


def test_video_info_ignores_non_dict_json(tmp_path):
    """info.json со списком на верхнем уровне раньше приводил к AttributeError
    на первом же meta.get()."""
    (tmp_path / 'info.json').write_text('[1, 2, 3]', encoding='utf-8')
    assert app_module.read_video_info(str(tmp_path)) == {}


# ===================== ОЧИСТКА ФЛАГОВ ОТМЕНЫ =====================

def test_queue_clear_drops_cancel_flags(client):
    """Флаги отмены завершённых задач оставались в queue_cancel_requests
    навсегда: набор рос всю жизнь процесса и сужал пространство новых id
    (_new_task_id_locked исключает занятые в нём значения)."""
    task = app_module.QueueTask('cleartest', ['https://example.com/x'], 'best', 'x')
    task.status = 'error'
    with app_module.queue_lock:
        app_module.queue_tasks.append(task)
        app_module.queue_cancel_requests.add(task.id)
        app_module.queue_cancel_requests.add('ghost-id')
    try:
        response = client.post('/api/queue/clear')
        assert response.status_code == 200
        with app_module.queue_lock:
            # Задача была завершённой, значит удалена вместе со своим флагом.
            assert task.id not in app_module.queue_cancel_requests
            # Флаг задачи, которой вообще нет в списке, тоже мусор.
            assert 'ghost-id' not in app_module.queue_cancel_requests
    finally:
        with app_module.queue_lock:
            app_module.queue_tasks[:] = [
                t for t in app_module.queue_tasks if t.id != task.id]
            app_module.queue_cancel_requests.difference_update({task.id, 'ghost-id'})


def test_queue_clear_keeps_flags_of_live_tasks(client):
    """Активную отменяемую задачу очистка списка не трогает, поэтому её флаг
    отмены должен остаться — иначе загрузка перестала бы прерываться."""
    active = app_module.QueueTask('livetest', ['https://example.com/live'], 'best', 'live')
    active.status = 'downloading'
    with app_module.queue_lock:
        app_module.queue_tasks.append(active)
        app_module.queue_cancel_requests.add(active.id)
    try:
        assert client.post('/api/queue/clear').status_code == 200
        with app_module.queue_lock:
            assert active.id in app_module.queue_cancel_requests
    finally:
        with app_module.queue_lock:
            app_module.queue_tasks[:] = [
                t for t in app_module.queue_tasks if t.id != active.id]
            app_module.queue_cancel_requests.discard(active.id)


# ===================== СМЕНА ПАПОК ХРАНЕНИЯ =====================

def test_apply_storage_paths_invalidates_scan_cache(monkeypatch, tmp_path):
    """Кэш сканирования ключуется путём папки и хранит отметку свежести. После
    смены папки ensure_video_map отдавал прежнюю библиотеку, пока не истечёт
    окно свежести, — пользователь менял папку и видел старый список."""
    with app_module._scan_cache_lock:
        app_module._scan_cache['C:/old/path'] = ('fingerprint', 'v', 'm', 'id', {})
    monkeypatch.setattr(app_module, '_map_built_at', app_module.time.time())

    app_module.apply_storage_paths()

    with app_module._scan_cache_lock:
        assert app_module._scan_cache == {}, 'кэш старой папки не сброшен'
    assert app_module._map_built_at == 0.0, 'отметка свежести карты не сброшена'


# ===================== COOKIES: ОШИБКИ ФАЙЛОВОЙ СИСТЕМЫ =====================

def test_cookies_status_survives_missing_file(client, monkeypatch):
    """os.path.exists + getsize + getmtime — три обращения к диску. Файл могли
    удалить между ними, и getmtime падал с FileNotFoundError."""
    def boom(_path):
        raise FileNotFoundError('исчез между проверками')
    monkeypatch.setattr(app_module.os, 'stat', boom)
    response = client.get('/api/cookies/status')
    assert response.status_code == 200
    assert response.get_json()['exists'] is False


def test_cookies_get_reports_error_as_json(client, monkeypatch):
    """Занятый или недоступный файл должен давать JSON, а не HTML-страницу 500."""
    def boom(_path):
        raise PermissionError('файл занят')
    monkeypatch.setattr(app_module.os, 'stat', boom)
    response = client.get('/api/cookies')
    assert response.status_code == 500
    assert 'error' in response.get_json()


def test_cookies_delete_reports_locked_file(client, monkeypatch):
    """На Windows открытый yt-dlp файл не удаляется: PermissionError без
    обработки превращался в 500 с HTML вместо понятного ответа."""
    def boom(_path):
        raise PermissionError('файл занят другим процессом')
    monkeypatch.setattr(app_module.os, 'remove', boom)
    response = client.delete('/api/cookies')
    assert response.status_code == 500
    assert 'error' in response.get_json()


def test_cookies_delete_missing_file_is_not_error(client, monkeypatch):
    """Удалять уже нечего — для DELETE это успех по смыслу операции."""
    def boom(_path):
        raise FileNotFoundError('нет файла')
    monkeypatch.setattr(app_module.os, 'remove', boom)
    response = client.delete('/api/cookies')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'not_found'


# ===================== МЁРТВЫЙ КОД =====================

def test_app_has_no_unused_imports():
    """signal, traceback и shutil импортировались, но не использовались."""
    for name in ('signal', 'traceback', 'shutil'):
        assert not hasattr(app_module, name), f'{name} импортируется, но не нужен'


def test_app_has_no_dead_progress_data():
    """progress_data в app.py присваивался один раз и никогда не читался:
    прогресс живёт в задачах очереди, а download_lib получает свой словарь
    параметром."""
    assert not hasattr(app_module, 'progress_data')


# ===================== СТРАНИЦА КАНАЛА: ЛИШНИЕ ОБХОДЫ ДИСКА =====================

def test_channel_page_uses_cached_thumbnails(client, monkeypatch):
    """Страница канала звала find_file на каждое видео, то есть делала os.listdir
    по числу видео автора, хотя build_video_map уже сохранил имя превью в
    thumb_file. На канале с 81 видео это давало 83 обхода папок вместо 3.
    """
    app_module.build_video_map()
    counts = {}
    for video in app_module.VIDEO_MAP.values():
        counts[video['author']] = counts.get(video['author'], 0) + 1
    if not counts:
        pytest.skip('в библиотеке нет видео')
    author = max(counts, key=counts.get)
    total = counts[author]
    if total < 3:
        pytest.skip('нужен автор хотя бы с тремя видео')

    # Прогрев: первый запрос может достраивать карту библиотеки.
    client.get('/channel/' + author)

    real_listdir = os.listdir
    calls = []

    def counting_listdir(path):
        calls.append(path)
        return real_listdir(path)

    monkeypatch.setattr(app_module.os, 'listdir', counting_listdir)
    response = client.get('/channel/' + author)
    assert response.status_code == 200
    # Порог с запасом: важно, что число обходов не растёт вместе с числом видео.
    assert len(calls) < total, (
        f'обходов папок {len(calls)} при {total} видео: превью снова читаются с диска'
    )


def test_channel_thumbnails_match_disk_scan():
    """Кэш обязан давать то же имя превью, что и обход папки: иначе оптимизация
    молча ломает картинки на странице канала."""
    app_module.build_video_map()
    checked = 0
    for video in app_module.VIDEO_MAP.values():
        folder = os.path.join(app_module.BASE_VIDEO_DIR, video['author'], video['folder'])
        from_disk = app_module.find_file(folder, ['.jpg', '.png', '.webp'])
        cached = video.get('thumb_file')
        if cached is None and 'thumb_file' not in video:
            cached = from_disk
        assert cached == from_disk, f"{video['folder']}: кэш {cached!r} против диска {from_disk!r}"
        checked += 1
    if not checked:
        pytest.skip('в библиотеке нет видео')


# ===================== ГОЛЫЕ EXCEPT =====================

def test_no_bare_except_in_project_modules():
    """`except:` перехватывает KeyboardInterrupt и SystemExit, поэтому Ctrl+C
    во время чтения конфига или работы ffmpeg молча игнорировался, а настоящие
    ошибки (битый JSON, отсутствующий ffmpeg) исчезали без следа в логе."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for name in sorted(os.listdir(project_dir)):
        if not name.endswith('.py'):
            continue
        path = os.path.join(project_dir, name)
        with open(path, 'r', encoding='utf-8') as handle:
            for number, line in enumerate(handle, 1):
                # Именно голый except, а не `except Exception:`.
                if re.match(r'^\s*except\s*:', line):
                    offenders.append(f'{name}:{number}')
    assert not offenders, 'голый except: ' + ', '.join(offenders)


def test_ast_confirms_no_bare_handlers():
    """Проверка регуляркой может пропустить нестандартное форматирование,
    поэтому дополнительно смотрим дерево разбора."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for name in sorted(os.listdir(project_dir)):
        if not name.endswith('.py'):
            continue
        path = os.path.join(project_dir, name)
        with open(path, 'r', encoding='utf-8') as handle:
            try:
                tree = ast.parse(handle.read())
            except SyntaxError as e:
                offenders.append(f'{name}: не разбирается ({e})')
                continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                offenders.append(f'{name}:{node.lineno}')
    assert not offenders, 'голые обработчики: ' + ', '.join(offenders)
