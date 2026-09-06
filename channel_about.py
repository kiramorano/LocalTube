"""Разбор страницы «О канале» YouTube: страна, дата регистрации, ссылки.

Зачем отдельный модуль. yt-dlp не отдаёт для канала ни страну, ни дату
регистрации, ни список внешних ссылок: полей `channel_country`,
`channel_joined`, `channel_created` в его выводе нет вообще. Код читал именно
их, поэтому `country` и `joined_date` в сохранённых метаданных всегда
оставались пустыми строками.

Всё это лежит в `aboutChannelViewModel` внутри `ytInitialData` на странице
`https://www.youtube.com/@канал/about`. Структура (сокращённо):

    aboutChannelViewModel:
        description: "текст описания"
        country: "Грузия"
        subscriberCountText: "90,3 тыс. подписчиков"
        viewCountText: "421 993 052 просмотра"
        videoCountText: "148 видео"
        joinedDateText: {content: "Дата регистрации: 2 янв. 2025 г."}
        canonicalChannelUrl: "http://www.youtube.com/@AnataCars"
        links: [{channelExternalLinkViewModel: {
                    title: {content: "Телеграм Канал"},
                    link: {content: "t.me/...", commandRuns: [{onTap: {
                        innertubeCommand: {urlEndpoint: {url: "...redirect?q=..."}}}}]}}}]

Разбор HTML отделён от сетевого запроса (`parse_about` против `fetch_about`),
чтобы его можно было проверять без обращения к YouTube.
"""
import json
import logging
import re
from urllib.parse import parse_qs, unquote, urlparse

try:
    import requests
except ImportError:  # pragma: no cover - requests есть в requirements
    requests = None

logger = logging.getLogger(__name__)

# ytInitialData объявляется в inline-скрипте. Ищем от «{» до конца скрипта:
# внутри JSON встречаются любые символы, поэтому нежадный поиск до `;</script>`.
_YT_DATA_RE = re.compile(r'ytInitialData\s*=\s*(\{.*?\})\s*;?\s*</script>', re.S)

# «90,3 тыс. подписчиков», «3,09 млн подписчиков», «1234 подписчика».
_MULTIPLIERS = (
    ('млрд', 1_000_000_000),
    ('billion', 1_000_000_000),
    ('млн', 1_000_000),
    ('million', 1_000_000),
    ('тыс', 1_000),
    ('thousand', 1_000),
    ('k', 1_000),
)


def _find_view_model(node):
    """Ищет aboutChannelViewModel в дереве ytInitialData.

    Обходим дерево, а не идём по фиксированному пути: YouTube меняет вложенность
    (панель «О канале» переезжала между tabRenderer и engagementPanel), и жёсткий
    путь ломается при каждой такой правке.
    """
    if isinstance(node, dict):
        model = node.get('aboutChannelViewModel')
        if isinstance(model, dict):
            return model
        for value in node.values():
            found = _find_view_model(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_view_model(value)
            if found is not None:
                return found
    return None


def _text(value):
    """Достаёт строку из поля, которое бывает и строкой, и {'content': ...}."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        content = value.get('content') or value.get('simpleText')
        if isinstance(content, str):
            return content.strip()
    return ''


def parse_count(text):
    """«421 993 052 просмотра» -> 421993052, «90,3 тыс.» -> 90300.

    Пробел здесь бывает неразрывным (\xa0) и «узким неразрывным» (\u202f):
    YouTube использует их как разделитель разрядов, и обычный split по ' ' их
    не убирает.
    """
    text = str(text or '').replace('\xa0', ' ').replace('\u202f', ' ').strip()
    if not text:
        return None
    lowered = text.lower()
    number = re.search(r'\d[\d\s.,]*', lowered)
    if not number:
        return None
    raw = number.group(0).strip()
    for suffix, factor in _MULTIPLIERS:
        if suffix in lowered:
            # У сокращений дробная часть отделяется запятой или точкой:
            # «3,09 млн» и «3.09M» — одно и то же число.
            digits = raw.replace(' ', '').replace(',', '.')
            try:
                return int(round(float(digits) * factor))
            except ValueError:
                return None
    # Полное число: разделители разрядов — пробелы, запятые или точки.
    digits = re.sub(r'[^\d]', '', raw)
    return int(digits) if digits else None


def _clean_joined(text):
    """«Дата регистрации: 2 янв. 2025 г.» -> «2 янв. 2025 г.».

    Подпись убираем: на странице канала значение стоит в плитке с заголовком
    «Регистрация», и дубль подписи там лишний.
    """
    text = _text(text)
    if not text:
        return ''
    # Отрезаем всё до первого двоеточия — так же работает и англоязычный
    # вариант «Joined: Jan 2, 2025».
    if ':' in text:
        text = text.split(':', 1)[1]
    return text.strip()


def _resolve_link(url):
    """Разворачивает /redirect?...&q=<адрес> в настоящий адрес.

    Ссылка через редирект YouTube привязана к redir_token и в чужом браузере
    может не открыться. Схемы кроме http(s) отбрасываем: `javascript:` в href
    выполнился бы на странице пользователя.
    """
    url = str(url or '').strip()
    if not url:
        return None
    if '/redirect' in url:
        query = parse_qs(urlparse(url).query)
        target = (query.get('q') or query.get('u') or [None])[0]
        if target:
            url = unquote(target)
    if not re.match(r'https?://', url, re.I):
        return None
    return url


def _parse_links(links):
    """Собирает внешние ссылки канала: [{'title': ..., 'url': ...}]."""
    result = []
    if not isinstance(links, list):
        return result
    for item in links:
        if not isinstance(item, dict):
            continue
        model = item.get('channelExternalLinkViewModel')
        if not isinstance(model, dict):
            continue
        title = _text(model.get('title'))
        link = model.get('link')
        url = None
        if isinstance(link, dict):
            for run in link.get('commandRuns') or []:
                if not isinstance(run, dict):
                    continue
                endpoint = (((run.get('onTap') or {}).get('innertubeCommand') or {})
                            .get('urlEndpoint') or {})
                url = _resolve_link(endpoint.get('url'))
                if url:
                    break
            if not url:
                # Без commandRuns остаётся только видимый текст: он бывает
                # обрезанным («t.me/...»), но лучше, чем ничего.
                url = _resolve_link('https://' + _text(link).lstrip('/'))
        if url:
            result.append({'title': title or url, 'url': url})
    return result


def parse_about(html):
    """Разбирает HTML страницы /about. Возвращает {} если данных нет.

    Пустой результат — нормальная ситуация: YouTube отдаёт страницу согласия
    или капчу, и синхронизация канала не должна из-за этого падать.
    """
    if not html:
        return {}
    match = _YT_DATA_RE.search(html)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except (ValueError, TypeError):
        return {}
    model = _find_view_model(data)
    if not model:
        return {}

    canonical = _text(model.get('canonicalChannelUrl'))
    if canonical.startswith('http://'):
        # YouTube отдаёт http, но браузер всё равно уйдёт на https.
        canonical = 'https://' + canonical[len('http://'):]

    return {
        'description': model.get('description') if isinstance(model.get('description'), str) else '',
        'country': _text(model.get('country')),
        'joined_date': _clean_joined(model.get('joinedDateText')),
        'subscribers': parse_count(_text(model.get('subscriberCountText'))),
        'view_count': parse_count(_text(model.get('viewCountText'))),
        'video_count': parse_count(_text(model.get('videoCountText'))),
        'channel_url': canonical,
        'channel_id': _text(model.get('channelId')),
        'links': _parse_links(model.get('links')),
    }


def fetch_about(channel_url, timeout=20):
    """Скачивает и разбирает страницу «О канале». Возвращает {} при ошибке."""
    if requests is None or not channel_url:
        return {}
    url = channel_url.rstrip('/')
    if not url.endswith('/about'):
        url += '/about'
    try:
        resp = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            # Без Accept-Language YouTube отдаёт страницу на языке по IP, и
            # подпись «Дата регистрации» приходит на случайном языке.
            'Accept-Language': 'ru,en;q=0.9',
        }, timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"channel_about: {url} вернул {resp.status_code}")
            return {}
        return parse_about(resp.text)
    except Exception as e:
        logger.warning(f"channel_about: ошибка запроса {url}: {e}")
        return {}
