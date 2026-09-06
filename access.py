"""Доступ к серверу из локальной сети: владелец и гости.

Сервер слушает 0.0.0.0, поэтому его видит каждое устройство в сети. Раньше в
проекте не было ни одной проверки прав, и любой сосед по Wi-Fi мог удалить
видео, сменить пути хранения или выгрузить cookies аккаунта YouTube.

Владельцем считается тот, кто:
  - пришёл с самой машины (127.0.0.1 или ::1), либо
  - ввёл PIN из настроек, получив ключ устройства в cookie.

Остальным доступен только просмотр. Список разрешённого задаётся в app.py
явным перечислением: всё, что не разрешено, закрыто. При таком порядке новый
маршрут по умолчанию недоступен гостю, а не открыт по забывчивости.
"""
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import paths
from logger import logger
from utils import read_json, write_json_atomic

SCRIPT_DIR = paths.data_dir()
ACCESS_FILE = paths.data_path('access.json')

# Имя cookie с ключом устройства, впустившего себя по PIN.
TOKEN_COOKIE = 'lt_owner'
PIN_LENGTH = 6
# Ограничение перебора PIN: шесть цифр — это 10^6 вариантов, а сервер отвечает
# тысячи раз в секунду, поэтому без ограничения полный перебор занимал минуты.
MAX_PIN_ATTEMPTS = 10
ATTEMPT_WINDOW = 300.0
# Порт зашит в app.py; держим здесь, чтобы собирать ссылки для гостей.
DEFAULT_PORT = 5000
SCAN_TIMEOUT = 0.35
SCAN_WORKERS = 64
SAVED_SERVERS_LIMIT = 20

# Имя хоста или IPv4: буквы, цифры, точки, дефисы.
_HOST_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$')

_lock = threading.Lock()
_state = None

# Неудачные попытки PIN по адресу: {addr: {'count': int, 'first': monotonic}}.
# Отдельный лок, чтобы проверка попыток не ждала чтения файла настроек.
_attempts = {}
_attempts_lock = threading.Lock()


def _defaults():
    return {
        # PIN нужен, чтобы пустить со своего телефона: он в той же сети и по
        # адресу неотличим от чужого устройства.
        'pin': _new_pin(),
        # Секрет для ключей устройств. Меняется вместе с PIN, поэтому смена
        # PIN отключает все ранее впущенные устройства.
        'secret': secrets.token_hex(32),
        # Включён по умолчанию: иначе после обновления телефон в сети молча
        # перестал бы открывать видео.
        'network_enabled': True,
        'servers': [],
    }


def _new_pin():
    # secrets, а не random: PIN пускает в настройки и к cookies.
    return ''.join(secrets.choice('0123456789') for _ in range(PIN_LENGTH))


def _read_file():
    # Битый файл не должен ни ронять сервер, ни открывать доступ всем: при
    # неудаче получаем пустое и дальше подставляются значения по умолчанию.
    data = read_json(ACCESS_FILE, default={})
    return data if isinstance(data, dict) else {}


def _normalize(raw):
    base = _defaults()
    if not isinstance(raw, dict):
        return base
    pin = str(raw.get('pin') or '')
    if pin.isdigit() and len(pin) >= PIN_LENGTH:
        base['pin'] = pin
    secret = raw.get('secret')
    if isinstance(secret, str) and len(secret) >= 32:
        base['secret'] = secret
    if isinstance(raw.get('network_enabled'), bool):
        base['network_enabled'] = raw['network_enabled']
    base['servers'] = _clean_servers(raw.get('servers'))
    return base


def _clean_servers(value):
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        url = normalize_server_url(item.get('url'))
        if not url or url in seen:
            continue
        seen.add(url)
        title = item.get('title')
        result.append({'url': url,
                       'title': str(title)[:80] if title else url})
        if len(result) >= SAVED_SERVERS_LIMIT:
            break
    return result


def _load_locked():
    global _state
    if _state is None:
        raw = _read_file()
        _state = _normalize(raw)
        # Первый запуск: PIN и секрет только что созданы, их надо сохранить,
        # иначе после перезапуска ключи устройств перестанут работать.
        if raw != _state:
            _save_locked()
    return _state


def _save_locked():
    write_json_atomic(ACCESS_FILE, _state)


def reload_from_disk():
    """Сбрасывает состояние в памяти. Нужно тестам и правке файла руками."""
    global _state
    with _lock:
        _state = None


# ================= Кто владелец =================

def is_owner_address(addr):
    """Пришёл ли запрос с самой машины.

    Без адреса возвращаем False: считать такого клиента своим означало бы
    открыть доступ всем, кто спрятался за прокси.
    """
    if not addr:
        return False
    try:
        return ipaddress.ip_address(str(addr).strip()).is_loopback
    except ValueError:
        return False


# ================= PIN и ключи устройств =================

def get_pin():
    with _lock:
        return _load_locked()['pin']


def regenerate_pin():
    """Новый PIN и новый секрет: ранее впущенные устройства отключаются."""
    with _lock:
        state = _load_locked()
        state['pin'] = _new_pin()
        state['secret'] = secrets.token_hex(32)
        _save_locked()
        return state['pin']


def _expected_token(secret, pin):
    return hmac.new(secret.encode('utf-8'), pin.encode('utf-8'),
                    hashlib.sha256).hexdigest()


def _ascii_or_none(value):
    """Строка для compare_digest или None.

    hmac.compare_digest со строками требует ASCII в обоих аргументах, иначе
    бросает TypeError. И PIN, и cookie с ключом приходят от клиента, поэтому
    кириллица в поле PIN или подделанная cookie давали 500 вместо отказа: для
    гостя из сети это ломало вообще все страницы, так как проверка прав идёт в
    before_request. Сравнение с ASCII-значением всё равно не совпало бы, так
    что достаточно отсеять такое значение заранее.
    """
    if not value or not isinstance(value, str):
        return None
    return value if value.isascii() else None


def _prune_attempts_locked(now):
    """Убирает записи о попытках, у которых окно уже истекло.

    Без чистки словарь рос бы на каждый новый адрес до перезапуска сервера.
    """
    stale = [addr for addr, item in _attempts.items()
             if now - item['first'] > ATTEMPT_WINDOW]
    for addr in stale:
        del _attempts[addr]


def attempts_left(addr):
    """Сколько попыток PIN осталось у адреса. Нужно интерфейсу и тестам."""
    key = str(addr or '?')
    now = time.monotonic()
    with _attempts_lock:
        _prune_attempts_locked(now)
        item = _attempts.get(key)
        if not item:
            return MAX_PIN_ATTEMPTS
        return max(0, MAX_PIN_ATTEMPTS - item['count'])


def pin_locked_for(addr):
    """Сколько секунд адресу ждать до следующей попытки. 0 — можно пробовать."""
    key = str(addr or '?')
    now = time.monotonic()
    with _attempts_lock:
        _prune_attempts_locked(now)
        item = _attempts.get(key)
        if not item or item['count'] < MAX_PIN_ATTEMPTS:
            return 0
        left = ATTEMPT_WINDOW - (now - item['first'])
        return max(0, int(left) + 1)


def _register_failure_locked(key, now):
    item = _attempts.get(key)
    if item is None or now - item['first'] > ATTEMPT_WINDOW:
        _attempts[key] = {'count': 1, 'first': now}
    else:
        item['count'] += 1


def reset_attempts(addr=None):
    """Сбрасывает счётчик попыток: после верного PIN и в тестах."""
    with _attempts_lock:
        if addr is None:
            _attempts.clear()
        else:
            _attempts.pop(str(addr), None)


def token_for_pin(pin, addr=None):
    """Ключ устройства по верному PIN, иначе None.

    addr нужен для ограничения перебора: PIN — шесть цифр, то есть миллион
    вариантов, а без ограничения сервер отвечает тысячи раз в секунду, и полный
    перебор занимал минуты. Считаем неудачи по адресу и после MAX_PIN_ATTEMPTS
    закрываем окно на ATTEMPT_WINDOW секунд.
    """
    pin = _ascii_or_none(pin)
    if pin is None:
        return None
    pin = pin.strip()
    if not pin:
        return None

    key = str(addr or '?')
    now = time.monotonic()
    with _attempts_lock:
        _prune_attempts_locked(now)
        item = _attempts.get(key)
        # Окно исчерпано — не сравниваем вовсе, чтобы попытки не продлевали его.
        if item and item['count'] >= MAX_PIN_ATTEMPTS and now - item['first'] <= ATTEMPT_WINDOW:
            return None

    with _lock:
        state = _load_locked()
        # compare_digest, чтобы время ответа не подсказывало правильные цифры.
        matched = hmac.compare_digest(pin, state['pin'])
        token = _expected_token(state['secret'], state['pin']) if matched else None

    with _attempts_lock:
        if matched:
            _attempts.pop(key, None)
        else:
            _register_failure_locked(key, now)
    return token


def is_valid_token(token):
    token = _ascii_or_none(token)
    if token is None:
        return False
    with _lock:
        state = _load_locked()
        expected = _expected_token(state['secret'], state['pin'])
    return hmac.compare_digest(token, expected)


# ================= Тумблер доступа в сеть =================

def is_network_enabled():
    with _lock:
        return _load_locked()['network_enabled']


def set_network_enabled(value):
    with _lock:
        state = _load_locked()
        state['network_enabled'] = bool(value)
        _save_locked()
        return state['network_enabled']


# ================= Адреса своего сервера =================

def local_addresses(port=DEFAULT_PORT):
    """Адреса, по которым сервер видно из сети.

    Loopback не годится для гостя, поэтому он идёт последним и только если
    других адресов не нашлось.
    """
    found = []
    seen = set()

    def add(host):
        if not host or host in seen:
            return
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return
        if ip.is_multicast or ip.is_reserved or ip.is_link_local:
            return
        seen.add(host)
        found.append(host)

    # Адрес интерфейса, через который машина выходит в сеть. UDP-сокет ничего
    # не отправляет, поэтому работает и без интернета.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.settimeout(0.2)
        probe.connect(('8.8.8.8', 80))
        add(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()

    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            add(info[4][0])
    except OSError as e:
        logger.debug(f"Не удалось получить адреса по имени хоста: {e}")

    if not found:
        add('127.0.0.1')

    return [{'host': h, 'url': f'http://{h}:{port}'} for h in found]


def make_qr_png(url):
    """QR с адресом сервера. Картинка рисуется локально, наружу ничего не идёт."""
    import io

    import segno

    buffer = io.BytesIO()
    segno.make(url, error='m').save(buffer, kind='png', scale=6, border=2)
    return buffer.getvalue()


# ================= Чужие серверы =================

def normalize_server_url(value):
    """Приводит адрес к http://host:port или возвращает None.

    Пускаем только http и https: javascript: и file: в этом поле означали бы
    подставленную ссылку в интерфейсе.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip().rstrip('/')
    if not text:
        return None
    if '://' not in text:
        text = 'http://' + text
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(text)
        hostname = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or not hostname:
        return None
    # IPv6 проверяем отдельно: urlsplit отдаёт адрес уже без квадратных скобок,
    # а «::1» не проходил проверку имени хоста, потому что та требует начинать
    # с буквы или цифры. Поддержка IPv6 тут задумана (ниже адрес снова
    # оборачивается в скобки), но «http://[::1]:5000» отклонялся как непонятный.
    if ':' in hostname:
        try:
            ipaddress.IPv6Address(hostname)
        except ValueError:
            return None
    # Только ASCII-имена и адреса: пробелы и прочие символы дальше попадали в
    # http-запрос и роняли его InvalidURL вместо понятного отказа.
    elif not _HOST_RE.match(hostname):
        return None
    # Обращение к parts.port бросает ValueError на «:99999» и «:abc»,
    # поэтому оно внутри try.
    try:
        explicit_port = parts.port
    except ValueError:
        return None
    port = explicit_port or (443 if parts.scheme == 'https' else DEFAULT_PORT)
    host = hostname
    if ':' in host:  # IPv6
        host = f'[{host}]'
    return f'{parts.scheme}://{host}:{port}'


def saved_servers():
    with _lock:
        return [dict(item) for item in _load_locked()['servers']]


def add_server(url, title=None):
    clean = normalize_server_url(url)
    if not clean:
        raise ValueError('Непонятный адрес сервера.')
    with _lock:
        state = _load_locked()
        items = [item for item in state['servers'] if item['url'] != clean]
        if len(items) >= SAVED_SERVERS_LIMIT:
            raise ValueError(f'Больше {SAVED_SERVERS_LIMIT} серверов не поддерживается.')
        items.append({'url': clean, 'title': (str(title)[:80] if title else clean)})
        state['servers'] = items
        _save_locked()
        return dict(items[-1])


def remove_server(url):
    clean = normalize_server_url(url)
    if not clean:
        raise ValueError('Непонятный адрес сервера.')
    with _lock:
        state = _load_locked()
        before = len(state['servers'])
        state['servers'] = [i for i in state['servers'] if i['url'] != clean]
        _save_locked()
        return len(state['servers']) != before


def probe_server(url, timeout=2.0):
    """Спрашивает у чужого сервера, живой ли он и сколько у него видео."""
    clean = normalize_server_url(url)
    if not clean:
        raise ValueError('Непонятный адрес сервера.')
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(clean + '/api/network/ping', timeout=timeout) as res:
            data = json.loads(res.read().decode('utf-8'))
        if data.get('app') != 'LocalTube':
            return {'online': False, 'url': clean, 'error': 'Это не LocalTube.'}
        return {
            'online': True,
            'url': clean,
            'title': str(data.get('title') or clean)[:80],
            'videos': int(data.get('videos') or 0),
        }
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as e:
        return {'online': False, 'url': clean, 'error': str(e)[:120]}


def scan_network(port=DEFAULT_PORT, timeout=SCAN_TIMEOUT):
    """Ищет другие LocalTube в своей подсети.

    Сначала быстрая проверка открытого порта, и только для откликнувшихся —
    запрос /api/network/ping. Полный обход 254 адресов иначе занимал бы минуты.
    """
    own = [item['host'] for item in local_addresses(port)]
    candidates = []
    for host in own:
        try:
            network = ipaddress.ip_network(f'{host}/24', strict=False)
        except ValueError:
            continue
        for addr in network.hosts():
            text = str(addr)
            if text not in own and text not in candidates:
                candidates.append(text)

    def port_open(host):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            try:
                return host if sock.connect_ex((host, port)) == 0 else None
            except OSError:
                return None

    alive = []
    if candidates:
        with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
            for result in pool.map(port_open, candidates):
                if result:
                    alive.append(result)

    found = []
    for host in alive:
        info = probe_server(f'http://{host}:{port}', timeout=1.5)
        if info.get('online'):
            found.append({'url': info['url'], 'title': info.get('title') or host,
                          'videos': info.get('videos', 0)})
    return found
