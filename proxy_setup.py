#!/usr/bin/env python3
"""Настройка прокси для сетевых запросов LocalTube.

Раньше app.py просто стирал HTTP_PROXY/HTTPS_PROXY. На машине, где доступ к
YouTube идёт через локальный прокси (xray и подобные VPN-клиенты), это ломало
загрузку: yt-dlp шёл напрямую и получал ConnectionResetError(10054) на
«Unable to download API page».

Стирать переменные вообще нельзя, но и оставлять как есть тоже: запросы к
bgutil-серверу на 127.0.0.1 уходили бы через прокси. Поэтому localhost
добавляется в исключения.

Отдельная тонкость Windows: если в окружении есть NO_PROXY, но нет
HTTP(S)_PROXY, то urllib.getproxies() возвращает только «no» и полностью
игнорирует прокси из реестра. Значит адрес из реестра нужно прописать в
переменные явно.
"""

import os

# Локальные адреса всегда напрямую: bgutil-сервер и сам веб-интерфейс.
LOCAL_HOSTS = ('127.0.0.1', 'localhost', '::1')

PROXY_VARS = ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy')


def registry_proxy_url():
    """Адрес прокси из настроек Windows или ''."""
    if os.name != 'nt':
        return ''
    try:
        import winreg

        path = r'Software\Microsoft\Windows\CurrentVersion\Internet Settings'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            if not winreg.QueryValueEx(key, 'ProxyEnable')[0]:
                return ''
            server = (winreg.QueryValueEx(key, 'ProxyServer')[0] or '').strip()
    except Exception:
        return ''
    if not server:
        return ''
    # Может быть «host:port» или «http=host:port;https=host:port».
    if '=' in server:
        parts = dict(p.split('=', 1) for p in server.split(';') if '=' in p)
        server = (parts.get('https') or parts.get('http') or '').strip()
        if not server:
            return ''
    return server if '://' in server else 'http://' + server


def build_no_proxy(existing):
    """Список исключений: localhost плюс то, что уже указал пользователь."""
    hosts = list(LOCAL_HOSTS)
    for host in (h.strip() for h in (existing or '').split(',')):
        if host and host not in hosts:
            hosts.append(host)
    return ','.join(hosts)


def apply_proxy_environment(env=None):
    """Приводит переменные прокси к рабочему виду. Возвращает адрес прокси."""
    env = os.environ if env is None else env

    proxy = ''
    for name in PROXY_VARS:
        value = (env.get(name) or '').strip()
        if value:
            proxy = value if '://' in value else 'http://' + value
            break
    # Прокси из реестра сам по себе не сработает, если задан NO_PROXY.
    if not proxy:
        proxy = registry_proxy_url()

    if proxy:
        for name in ('HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy'):
            env[name] = proxy

    no_proxy = build_no_proxy(env.get('NO_PROXY') or env.get('no_proxy'))
    env['NO_PROXY'] = no_proxy
    env['no_proxy'] = no_proxy
    return proxy
