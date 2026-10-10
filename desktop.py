#!/usr/bin/env python3
"""desktop.py — запуск LocalTube как обычного оконного приложения.

Раньше единственным способом запуска был ``python app.py``: открывалась консоль,
Flask писал в неё адрес, и пользователь сам шёл в браузер. Для собранного
приложения это не годится — окно консоли выглядит как сбой, а закрыть его
означало убить сервер вместе с активными загрузками.

Здесь три отдельные задачи, и все три решаются в этом модуле.

Один экземпляр
    Второй запуск не должен поднимать второй сервер: он занял бы порт, а две
    копии, пишущие в одну очередь и один queue.json, портят данные. Замок —
    TCP-сокет на служебном порту, а не файл: файл остаётся лежать после
    аварийного завершения, и приложение потом отказывалось запускаться вовсе.

Сервер для оконного режима
    ``app.run()`` — сервер разработки Werkzeug: он однопоточный по умолчанию,
    печатает предупреждение в консоль и не рассчитан на длительную работу.
    Здесь используется waitress: он тихий, многопоточный и переносит закрытие
    окна во время отдачи видео.

Само окно
    Через pywebview, то есть системный движок: WebView2 (Edge) на Windows 10/11,
    WebKitGTK на Linux, встроенный Chromium (CEF) на Windows 7, где WebView2
    отсутствует. Собственный Chromium в остальных случаях не тащим: движок
    системы уже умеет H.264 и AAC, без которых видео с YouTube не проигрывается.
"""
import os
import socket
import sys
import threading
import time

import paths
import version
# Модуль целиком, а не только объект logger: рядом лежит LOG_FILE, путь к которому
# нужен в сообщении об ошибке запуска.
import logger as logging_setup
from logger import logger

# Порт замка: занят, пока приложение работает. Отличается от порта сервера,
# чтобы «порт занят другой программой» не путалось с «уже запущен LocalTube».
SINGLE_INSTANCE_PORT = 5051
# Сколько ждать, пока сервер начнёт отвечать, прежде чем показывать окно.
SERVER_START_TIMEOUT = 30.0
# Диапазон поиска свободного порта, если основной занят.
PORT_SEARCH_LIMIT = 20

_single_instance_socket = None


# ================= ОДИН ЭКЗЕМПЛЯР =================

def acquire_single_instance_lock():
    """Занимает замок. False — приложение уже запущено.

    Сокет намеренно не закрывается: он держится до конца работы процесса, а
    операционная система освобождает его сама, даже если процесс убили.
    """
    global _single_instance_socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Без SO_EXCLUSIVEADDRUSE Windows позволяет второму процессу занять тот же
    # адрес, и замок не работал бы вовсе. SO_REUSEADDR здесь противопоказан
    # ровно по этой причине — он разрешает именно то, что мы запрещаем.
    if sys.platform == 'win32' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        except OSError:
            # Старые сборки Windows опции не знают: замок останется чуть менее
            # строгим, но bind всё равно не даст занять порт дважды.
            pass
    try:
        sock.bind(('127.0.0.1', SINGLE_INSTANCE_PORT))
        sock.listen(1)
    except OSError:
        sock.close()
        return False
    _single_instance_socket = sock
    return True


def release_single_instance_lock():
    """Отпускает замок. Нужна тестам: иначе порт остаётся занятым до выхода."""
    global _single_instance_socket
    if _single_instance_socket is not None:
        try:
            _single_instance_socket.close()
        except OSError:
            pass
        _single_instance_socket = None


# ================= ПОРТ =================

def port_is_free(port, host='0.0.0.0'):
    """Свободен ли порт для прослушивания."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if sys.platform == 'win32' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            try:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(preferred, limit=PORT_SEARCH_LIMIT):
    """Порт для сервера: предпочтительный, иначе следующий свободный.

    Порт 5000 занимают и другие программы (на macOS — системный AirPlay), и
    раньше приложение в этом случае просто падало с «address already in use».
    """
    for candidate in range(preferred, preferred + limit):
        if port_is_free(candidate):
            return candidate
    # Ни один порт диапазона не подошёл: пусть ОС выберет любой свободный.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(('0.0.0.0', 0))
        return probe.getsockname()[1]


def wait_for_server(port, timeout=SERVER_START_TIMEOUT):
    """Ждёт, пока сервер начнёт принимать соединения.

    Окно нельзя показывать раньше: WebView2 на пустом порту рисует свою
    страницу «не удалось открыть», и она остаётся висеть, потому что повторно
    страницу никто не запрашивает.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                return True
        time.sleep(0.1)
    return False


# ================= СЕРВЕР =================

def serve(flask_app, port):
    """Поднимает waitress на всех интерфейсах.

    host='0.0.0.0' обязателен: библиотеку открывают с телефона в той же сети по
    QR-коду с PIN-кодом, и на 127.0.0.1 такая ссылка не работает.
    """
    from waitress import serve as waitress_serve

    waitress_serve(flask_app, host='0.0.0.0', port=port,
                   threads=16,
                   # Отдача видео идёт долго, а канал до телефона может встать:
                   # короткий таймаут обрывал бы просмотр на середине.
                   channel_timeout=600,
                   # Своя вывеска вместо «waitress»: по ней видно версию в логах
                   # и в ответах прокси.
                   ident=f"{version.APP_NAME}/{version.__version__}")


def start_server_thread(flask_app, port):
    """Запускает сервер в фоновом потоке.

    daemon=True намеренно: закрытие окна должно завершать приложение, не
    дожидаясь, пока waitress закончит отдавать текущие ответы.
    """
    thread = threading.Thread(target=serve, args=(flask_app, port),
                              name='localtube-server', daemon=True)
    thread.start()
    return thread


# ================= ОКНО =================

def pick_gui():
    """Движок для окна: None — пусть pywebview выбирает сам.

    На Windows 7 WebView2 нет и поставить его нельзя, поэтому там нужен
    встроенный Chromium (CEF). Проверяем не «это Windows 7», а наличие самого
    cefpython3: legacy-сборка его содержит, обычная — нет, и навязывать
    отсутствующий движок значило бы уронить запуск на ImportError.
    """
    if sys.platform == 'win32' and sys.getwindowsversion()[0] < 10:
        try:
            import cefpython3  # noqa: F401
        except ImportError:
            return None
        return 'cef'
    return None


def window_icon():
    """Путь к иконке окна или None.

    На Linux WebKitGTK берёт иконку из файла: без неё в панели задач оказывался
    безымянный серый квадрат. На Windows иконка уже вшита в exe самим
    PyInstaller, повторно передавать её не нужно.
    """
    if sys.platform == 'win32':
        return None
    for name in ('localtube.png', 'icon.png'):
        candidate = paths.resource_path('packaging', 'assets', name)
        if os.path.isfile(candidate):
            return candidate
    return None


def run_window(url, debug=False):
    """Открывает окно приложения. False — оконный движок недоступен."""
    try:
        import webview
    except ImportError:
        return False

    webview.create_window(
        version.APP_NAME,
        url,
        width=1280,
        height=800,
        # Ниже этого размера интерфейс начинает наезжать сам на себя.
        min_size=(900, 600),
        # Тёмный фон: интерфейс тёмный, и на белом фоне при старте
        # проскакивала яркая вспышка на весь экран.
        background_color='#0f0f0f',
        text_select=True,
    )

    start_kwargs = {'debug': debug, 'gui': pick_gui()}
    icon = window_icon()
    if icon:
        start_kwargs['icon'] = icon
    # private_mode=False обязателен: избранное, история просмотров и настройки
    # интерфейса лежат в localStorage, а в приватном режиме pywebview стирает
    # его при закрытии окна — все настройки пропадали после каждого выхода.
    # storage_path указывает, куда движок кладёт это хранилище: по умолчанию он
    # выбирает временный каталог, который система вправе почистить.
    start_kwargs['private_mode'] = False
    start_kwargs['storage_path'] = paths.data_path('webview')
    os.makedirs(start_kwargs['storage_path'], exist_ok=True)

    webview.start(**start_kwargs)
    return True


def open_in_browser(url):
    """Запасной путь: системный браузер, если оконный движок недоступен."""
    import webbrowser

    logger.warning(f"Оконный движок недоступен. Откройте в браузере: {url}")
    webbrowser.open(url)


# ================= ТОЧКА ВХОДА =================

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    debug = '--debug' in args
    # Режим без окна: приложение работает как обычный сервер в локальной сети.
    # Нужен для запуска на машине без графической оболочки.
    headless = '--no-window' in args or '--server' in args

    if not headless and not acquire_single_instance_lock():
        # Второй экземпляр просто открывает окно первого и уходит: молчаливый
        # выход выглядел бы как «приложение не запускается».
        open_in_browser(f"http://127.0.0.1:{_running_port()}")
        return 0

    # Импорт app здесь, а не сверху: он тяжёлый (yt-dlp, Flask, вся библиотека)
    # и до проверки замка выполнять его незачем.
    import app as app_module

    port = pick_port(app_module.SERVER_PORT)
    if port != app_module.SERVER_PORT:
        # Сообщаем приложению фактический порт: адреса для телефона, QR-код и
        # поиск в подсети собираются из него, и на старом значении ссылки вели
        # бы в никуда.
        app_module.set_server_port(port)
    _write_running_port(port)

    # Обработчик очереди должен работать и в оконном режиме: без него загрузки
    # висят в состоянии «ожидает» до первого обращения к API.
    app_module.ensure_queue_worker()

    start_server_thread(app_module.app, port)
    url = f"http://127.0.0.1:{port}"
    if not wait_for_server(port):
        # Имя файла берём у logger, а не пишем строкой: до этого здесь было
        # localtube.log, тогда как logger.py пишет в logs.txt, и подсказка
        # отправляла пользователя к несуществующему файлу.
        logger.error("Сервер не запустился за отведённое время. Подробности в логе: %s",
                     logging_setup.LOG_FILE)
        return 1

    try:
        if headless:
            logger.info("%s %s — сервер на %s",
                        version.APP_NAME, version.__version__, url)
            _wait_forever()
        elif not run_window(url, debug=debug):
            open_in_browser(url)
            _wait_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown(app_module)
    return 0


def _wait_forever():
    """Держит процесс живым, пока сервер работает в фоновом потоке."""
    while True:
        time.sleep(3600)


def _running_port_file():
    return paths.data_path('running_port')


def _write_running_port(port):
    """Запоминает порт для второго экземпляра.

    Без этого второй запуск открывал бы браузер на порту по умолчанию, тогда
    как первый экземпляр мог занять другой.
    """
    try:
        paths.ensure_data_dir()
        with open(_running_port_file(), 'w', encoding='utf-8') as f:
            f.write(str(port))
    except OSError:
        # Не критично: подсказка адреса не должна мешать запуску приложения.
        pass


def _running_port():
    try:
        with open(_running_port_file(), 'r', encoding='utf-8') as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        import access
        return access.DEFAULT_PORT


def _shutdown(app_module):
    """Закрывает внешние процессы при выходе.

    Экстрактор yt-dlp и сервер PO-токенов живут в отдельных процессах: без
    явной остановки они оставались висеть после закрытия окна, продолжая
    занимать порт 4416 и мешая следующему запуску.
    """
    try:
        app_module.shutdown_extractor()
    except Exception as e:
        logger.warning("экстрактор не остановлен: %s", e)
    try:
        import server
        server.shutdown_server()
    except Exception as e:
        logger.warning("PO-сервер не остановлен: %s", e)


if __name__ == '__main__':
    sys.exit(main())
