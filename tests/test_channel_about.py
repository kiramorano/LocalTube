"""Страна, дата регистрации, ссылки и просмотры канала со страницы /about.

yt-dlp этих полей не отдаёт: `channel_country`, `channel_joined`,
`channel_created` в его выводе отсутствуют (проверено grep по исходникам
2026.08.19), поэтому в сохранённых метаданных `country` и `joined_date` всегда
оставались пустыми строками. Всё это есть в `aboutChannelViewModel` внутри
`ytInitialData` на странице `https://www.youtube.com/@канал/about`.

Разбор HTML вынесен в отдельный модуль, чтобы его можно было проверять без
сети: сетевой запрос делает только `fetch_about`.
"""
import json

import pytest


# Срез настоящего ответа YouTube: только те поля, которые нам нужны. Полная
# структура — в docstring channel_about.parse_about.
ABOUT_VIEW_MODEL = {
    'description': 'ОРИГИНАЛЫ ТУТ\n\nИстории из автомобильного мира',
    'country': 'Грузия',
    'subscriberCountText': '90,3 тыс. подписчиков',
    'viewCountText': '421 993 052 просмотра',
    'videoCountText': '148 видео',
    'joinedDateText': {'content': 'Дата регистрации: 2 янв. 2025 г.'},
    'canonicalChannelUrl': 'http://www.youtube.com/@AnataCars',
    'displayCanonicalChannelUrl': 'www.youtube.com/@AnataCars',
    'channelId': 'UC9cXUuij6hlppu3Jrk_flmA',
    'links': [
        {'channelExternalLinkViewModel': {
            'title': {'content': 'Телеграм Канал'},
            'link': {'content': 't.me/ mWDpbGAVpJRjMzIy', 'commandRuns': [
                {'onTap': {'innertubeCommand': {'urlEndpoint': {
                    'url': 'https://www.youtube.com/redirect?event=channel_description'
                           '&redir_token=QUM4Zm9r&q=https%3A%2F%2Ft.me%2F%2BmWDpbGAVpJRjMzIy',
                }}}},
            ]},
        }},
        {'channelExternalLinkViewModel': {
            'title': {'content': 'Сайт'},
            'link': {'content': 'example.com', 'commandRuns': [
                {'onTap': {'innertubeCommand': {'urlEndpoint': {
                    'url': 'https://example.com/blog',
                }}}},
            ]},
        }},
    ],
}


def make_page(view_model):
    """Собирает HTML-страницу с ytInitialData вокруг переданной модели."""
    data = {'contents': {'twoColumnBrowseResultsRenderer': {'tabs': [
        {'tabRenderer': {'content': {'sectionListRenderer': {'contents': [
            {'itemSectionRenderer': {'contents': [
                {'aboutChannelRenderer': {'metadata': {
                    'aboutChannelViewModel': view_model}}},
            ]}},
        ]}}}},
    ]}}}
    return ('<html><body><script>var ytInitialData = '
            + json.dumps(data, ensure_ascii=False)
            + ';</script></body></html>')


@pytest.fixture
def about():
    import channel_about
    return channel_about


def test_parse_country(about):
    """Страна канала: yt-dlp её не отдаёт, а пользователь просил показывать."""
    assert about.parse_about(make_page(ABOUT_VIEW_MODEL))['country'] == 'Грузия'


def test_parse_joined_date(about):
    """Дата регистрации приходит строкой с подписью — подпись убираем.

    «Дата регистрации: 2 янв. 2025 г.» на странице канала выводится в плитке с
    заголовком «Регистрация», и дубль подписи там лишний.
    """
    assert about.parse_about(make_page(ABOUT_VIEW_MODEL))['joined_date'] == '2 янв. 2025 г.'


def test_parse_view_count(about):
    """Просмотры: «421 993 052 просмотра» -> число.

    Отдавать строку нельзя: страница канала форматирует число сама
    (фильтр compact_count), иначе в плитке будет каша из двух форматов.
    """
    assert about.parse_about(make_page(ABOUT_VIEW_MODEL))['view_count'] == 421993052


def test_parse_video_count(about):
    """«148 видео» -> 148."""
    assert about.parse_about(make_page(ABOUT_VIEW_MODEL))['video_count'] == 148


def test_parse_subscribers(about):
    """«90,3 тыс. подписчиков» -> 90300."""
    assert about.parse_about(make_page(ABOUT_VIEW_MODEL))['subscribers'] == 90300


def test_parse_links_resolve_redirect(about):
    """Ссылки канала должны быть настоящими, а не редиректами YouTube.

    YouTube оборачивает внешние ссылки в /redirect?...&q=<url>. Такой адрес
    привязан к токену и в чужом браузере может не открыться, поэтому берём
    параметр q.
    """
    links = about.parse_about(make_page(ABOUT_VIEW_MODEL))['links']
    assert len(links) == 2
    assert links[0]['title'] == 'Телеграм Канал'
    assert links[0]['url'] == 'https://t.me/+mWDpbGAVpJRjMzIy', \
        'редирект YouTube не развёрнут в настоящий адрес'
    # Прямая ссылка без редиректа остаётся как есть.
    assert links[1]['url'] == 'https://example.com/blog'


def test_parse_links_reject_non_http(about):
    """Схемы кроме http(s) в разметку не попадают.

    `javascript:` в href — исполняемый код на странице пользователя.
    """
    vm = json.loads(json.dumps(ABOUT_VIEW_MODEL, ensure_ascii=False))
    vm['links'][1]['channelExternalLinkViewModel']['link']['commandRuns'][0][
        'onTap']['innertubeCommand']['urlEndpoint']['url'] = 'javascript:alert(1)'
    links = about.parse_about(make_page(vm))['links']
    assert all(link['url'].startswith('http') for link in links), \
        f'опасная схема просочилась: {links}'


def test_parse_canonical_url(about):
    """Ссылка на канал: http из ответа приводим к https."""
    result = about.parse_about(make_page(ABOUT_VIEW_MODEL))
    assert result['channel_url'] == 'https://www.youtube.com/@AnataCars'


def test_parse_handles_missing_fields(about):
    """У части каналов страны и ссылок нет: разбор не должен падать."""
    result = about.parse_about(make_page({'description': 'только описание'}))
    assert result['description'] == 'только описание'
    assert result['country'] == ''
    assert result['joined_date'] == ''
    assert result['links'] == []


def test_parse_broken_page_returns_empty(about):
    """Битая страница (капча, редирект на согласие) не должна ронять синхронизацию."""
    assert about.parse_about('<html>no data here</html>') == {}
    assert about.parse_about('') == {}


def test_parse_ignores_html_in_description(about):
    """Описание вставляется в разметку — теги внутри не должны стать разметкой."""
    vm = dict(ABOUT_VIEW_MODEL, description='<script>alert(1)</script>')
    result = about.parse_about(make_page(vm))
    # Экранирование — забота шаблона, но модуль обязан вернуть текст как есть,
    # без «починки», иначе двойное экранирование испортит обычные описания.
    assert result['description'] == '<script>alert(1)</script>'
