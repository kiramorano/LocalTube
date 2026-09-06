# Запуск приложения на отдельном порту для браузерных проверок:
# в app.py порт 5000 задан жёстко, а рабочий сервер пользователя его занимает.
#
# Очередь принудительно ставится на паузу и уводится во временный файл: иначе
# тестовый сервер поднимает воркера и начинает по-настоящему скачивать видео из
# рабочей очереди пользователя (однажды так скачалось 39 видео).
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import app  # noqa: E402
from utils import write_json_atomic  # noqa: E402

if __name__ == '__main__':
    if os.environ.get('LT_USE_REAL_QUEUE') != '1':
        queue_path = os.path.join(tempfile.mkdtemp(prefix='lt_browser_'), 'queue.json')
        write_json_atomic(queue_path, {'paused': True, 'tasks': []})
        app.QUEUE_FILE = queue_path
        app.queue_tasks.clear()
        app.queue_paused = True
        print('Очередь изолирована: %s' % queue_path)

    if os.environ.get('LT_USE_REAL_CONFIG') != '1':
        # Проверки раздела «Хранение» сохраняют пути через /api/storage. Без
        # изоляции они перезаписали бы настоящий config.json пользователя и
        # увели его библиотеку в временную папку.
        config_path = os.path.join(tempfile.mkdtemp(prefix='lt_config_'), 'config.json')
        write_json_atomic(config_path, app.load_config())
        app.CONFIG_FILE = config_path
        print('Конфиг изолирован: %s' % config_path)

    if os.environ.get('LT_USE_REAL_USERDATA') != '1':
        # Проверки своих плейлистов создают и удаляют коллекции через
        # /api/collections. Без изоляции они писали бы в настоящий
        # userdata.json — вместе с историей и избранным пользователя.
        import userdata
        userdata_path = os.path.join(tempfile.mkdtemp(prefix='lt_userdata_'), 'userdata.json')
        userdata.USERDATA_FILE = userdata_path
        userdata.reload_from_disk()
        print('Данные пользователя изолированы: %s' % userdata_path)

    if os.environ.get('LT_USE_REAL_ACCESS') != '1':
        # Проверки раздела «Сеть» меняют PIN и тумблер доступа. Без изоляции
        # прогон отключал бы устройства, впущенные пользователем, и мог оставить
        # сервер закрытым для сети.
        import access
        access_path = os.path.join(tempfile.mkdtemp(prefix='lt_access_'), 'access.json')
        access.ACCESS_FILE = access_path
        access.reload_from_disk()
        print('Настройки доступа изолированы: %s' % access_path)

    # Признак изоляции для браузерных проверок. Скрипты, которые чистят историю,
    # избранное и скрытые каналы, требуют его наличия: запуск против рабочего
    # сервера пользователя стирал его данные молча.
    isolated = [name for name, var in (
        ('queue', 'LT_USE_REAL_QUEUE'),
        ('config', 'LT_USE_REAL_CONFIG'),
        ('userdata', 'LT_USE_REAL_USERDATA'),
        ('access', 'LT_USE_REAL_ACCESS'),
    ) if os.environ.get(var) != '1']

    @app.app.route('/api/test-mode')
    def api_test_mode():
        return {'test_server': True, 'isolated': isolated}

    port = int(os.environ.get('LT_PORT', '5004'))
    # По умолчанию только localhost. Проверки гостевого доступа поднимают сервер
    # на 0.0.0.0 (LT_HOST) и стучатся по адресу в локальной сети: с 127.0.0.1
    # любой клиент считается владельцем, и роль гостя не проверить.
    host = os.environ.get('LT_HOST', '127.0.0.1')
    app.app.run(host=host, port=port, debug=False, use_reloader=False)
