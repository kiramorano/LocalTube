"""Проверки шаблонов и темы.

Тема раньше была скопирована в каждый шаблон, копии разъезжались, и ошибки
вида «пустой href», «невидимый текст» или «нет скрипта до разметки» ловились
только глазами в браузере. Эти тесты фиксируют инварианты, за которые уже
приходилось платить регрессиями.
"""
import os
import re

import pytest

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')

# Все страницы с оформлением. channel.html рендерится только с данными канала,
# поэтому проверяем исходный текст шаблонов, а не ответы сервера.
THEMED_TEMPLATES = [
    'index.html',
    'video.html',
    'channel.html',
    'settings.html',
    'playlist.html',
    'edit.html',
    'upload.html',
    'collection.html',
]


def read_template(name):
    with open(os.path.join(TEMPLATES_DIR, name), encoding='utf-8') as fh:
        return fh.read()


def read_static(*parts):
    with open(os.path.join(STATIC_DIR, *parts), encoding='utf-8') as fh:
        return fh.read()


def strip_js_comments(js):
    """Убирает комментарии — иначе проверки цепляются за текст пояснений."""
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_theme_script_loaded_before_body(name):
    """theme.js должен быть в <head> и без defer.

    Иначе тема применяется после первой отрисовки, и пользователь светлой темы
    видит вспышку тёмного фона на каждом переходе (FOUC).
    """
    html = read_template(name)
    assert '/static/js/theme.js' in html, f'{name}: не подключён theme.js'

    script_pos = html.index('/static/js/theme.js')
    body = re.search(r'<body\b', html)
    assert body, f'{name}: нет тега body'
    assert script_pos < body.start(), f'{name}: theme.js подключён после разметки'

    tag_start = html.rindex('<script', 0, script_pos)
    tag = html[tag_start:html.index('>', script_pos)]
    assert 'defer' not in tag, f'{name}: theme.js с defer — тема применится после отрисовки'
    assert 'async' not in tag, f'{name}: theme.js с async — порядок применения темы не гарантирован'


@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_no_duplicated_theme_logic(name):
    """Логика темы должна жить только в static/js/theme.js.

    Семь копий уже разошлись в поведении: playlist.html менял обои без
    кроссфейда, а часть страниц добавляла к ссылке на обои ?w=&h= и заставляла
    браузер перекачивать их каждые 30 секунд.
    """
    scripts = '\n'.join(re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>',
                                   read_template(name), re.S))
    code = strip_js_comments(scripts)
    for dead in ('function loadThemeBackground', 'function setBackgroundImage',
                 'let activeBgLayer', "localStorage.getItem('lt_theme')",
                 "localStorage.setItem('lt_theme'"):
        assert dead not in code, f'{name}: осталась локальная копия логики темы ({dead})'


@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_theme_stylesheet_link_has_no_empty_href(name):
    """У <link> темы не должно быть href="".

    Пустой href браузер трактует как ссылку на текущую страницу и запрашивает
    HTML как стилевой файл: лишний запрос и ошибка в консоли.
    """
    html = read_template(name)
    for match in re.finditer(r'<link[^>]*id="theme-style(?:-link)?"[^>]*>', html):
        assert 'href=""' not in match.group(0), f'{name}: <link> темы с пустым href'


@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_background_layers_present(name):
    """Обои рисуются в два слоя — иначе кроссфейд подменять нечем."""
    html = read_template(name)
    assert 'id="bg-layer-1"' in html, f'{name}: нет слоя bg-layer-1'
    assert 'id="bg-layer-2"' in html, f'{name}: нет слоя bg-layer-2'


@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_no_invisible_text_from_transparent_background(name):
    """color: var(--yt-bg) недопустим: в теме frutiger-aero он равен transparent.

    Так пропадал текст активного фильтра на главной, активной вкладки в
    «Похожих видео» и выбранного пункта в меню плеера.
    """
    html = read_template(name)
    style = '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', html, re.S))
    offenders = [line.strip() for line in style.splitlines()
                 if re.search(r'(?<!-)\bcolor:\s*var\(--yt-bg\)', line)]
    assert not offenders, f'{name}: текст цвета var(--yt-bg) невидим в frutiger-aero: {offenders}'


def test_aero_theme_covers_invisible_text_cases():
    """Тема должна перекрывать «активные» элементы читаемым цветом."""
    css = read_static('css', 'themes', 'frutiger-aero.css')
    for selector in ('.chip.active', '.related-tab.active', '.settings-menu-item.active'):
        assert selector in css, f'frutiger-aero.css: не задан читаемый цвет для {selector}'


def test_aero_theme_styles_native_select_options():
    """<option> рисует система и наследует белый цвет от select.

    Без явного цвета раскрытый список в этой теме был белым на белом. Раньше
    правило прописывали вручную и только на двух страницах из семи.
    """
    css = read_static('css', 'themes', 'frutiger-aero.css')
    assert re.search(r'\[data-theme="frutiger-aero"\]\s+option', css), \
        'frutiger-aero.css: нет правила для option'


def test_aero_theme_has_no_dead_body_background_rules():
    """Обои живут на слоях, а не на body.

    Правила background-size / position / attachment на body ничего не делали:
    картинка туда не попадает. Мёртвый код вводит в заблуждение при правках.
    """
    css = read_static('css', 'themes', 'frutiger-aero.css')
    body_blocks = re.findall(r'\[data-theme="frutiger-aero"\]\s+body\s*\{([^}]*)\}', css)
    for block in body_blocks:
        for dead in ('background-size', 'background-attachment', 'background-repeat', 'background-image'):
            assert dead not in block, f'frutiger-aero.css: мёртвое правило {dead} на body'


def test_aero_theme_keeps_search_pill_geometry():
    """Поле поиска, выбор качества и кнопка склеены в одну «пилюлю».

    Общее правило темы задаёт полям border-radius: 40px по кругу, из-за чего
    склейка распадалась на три отдельные плашки. Геометрия должна
    восстанавливаться явно.
    """
    css = read_static('css', 'themes', 'frutiger-aero.css')
    assert '.search-container .url-input' in css, 'frutiger-aero.css: не восстановлен радиус поля поиска'
    assert '.search-container .download-btn' in css, 'frutiger-aero.css: не восстановлен радиус кнопки поиска'


def test_aero_theme_does_not_force_font_on_everything():
    """`* { font-family: ... !important }` ломает моноширинные и иконочные шрифты."""
    css = read_static('css', 'themes', 'frutiger-aero.css')
    assert not re.search(r'\[data-theme="frutiger-aero"\]\s*\*\s*\{[^}]*font-family[^}]*!important', css), \
        'frutiger-aero.css: шрифт навязан всем элементам через * !important'


def test_fonts_css_selector_matches_root_element():
    """Селектор `[data-theme] html` не совпадает никогда: атрибут на самом html."""
    css = read_static('css', 'fonts.css')
    assert '[data-theme="frutiger-aero"] html' not in css, \
        'fonts.css: селектор [data-theme] html не совпадает ни с чем'
    assert 'html[data-theme="frutiger-aero"]' in css, \
        'fonts.css: шрифт темы не привязан к корневому элементу'


def test_theme_js_does_not_bust_wallpaper_cache():
    """Обои весят ~2 МБ; ?w=&h= делали ссылку уникальной и обнуляли кэш."""
    js = strip_js_comments(read_static('js', 'theme.js'))
    assert '?w=' not in js, 'theme.js: в ссылке на обои остался cache-buster'
    assert 'innerWidth' not in js, 'theme.js: размер окна не должен попадать в ссылку на обои'


def test_theme_js_validates_stored_theme():
    """Мусор в localStorage не должен приводить к запросу постороннего файла стилей."""
    js = strip_js_comments(read_static('js', 'theme.js'))
    assert 'THEMES.indexOf' in js, 'theme.js: значение темы из localStorage не проверяется'


def test_video_page_loads_mobile_script():
    """У страницы видео тот же сайдбар-драйвер, но mobile.js там не подключался,
    поэтому закрытие по Escape работало на всех страницах, кроме неё."""
    html = read_template('video.html')
    assert 'id="sidebarDrawer"' in html
    assert '/static/js/mobile.js' in html, 'video.html: не подключён mobile.js'


def test_aero_button_rule_excludes_channel_tabs():
    """Вкладки канала — это <button>, поэтому общее правило кнопок в теме
    добавляло им рамку 1px и font-weight 500. Вкладки становились шире, полоса
    вкладок перестала прокручиваться до конца, и последняя вкладка («О канале»)
    оставалась подрезанной у правого края на мобильном."""
    css = read_static('css', 'themes', 'frutiger-aero.css')
    assert '[data-theme="frutiger-aero"] button:not(.tab)' in css, (
        'общее правило кнопок снова затрагивает вкладки канала'
    )
    # Голого селектора кнопки без исключения быть не должно.
    assert not re.search(r'\[data-theme="frutiger-aero"\]\s+button\s*[,{]', css), (
        'найден селектор button без :not(.tab)'
    )


def test_channel_tab_styles_stay_in_template():
    """Оформление вкладок задаёт channel.html; тема не должна его перебивать,
    иначе ширины вкладок разъезжаются между темами."""
    html = read_template('channel.html')
    assert '.tab {' in html, 'в channel.html нет собственных стилей вкладок'
    assert 'scrollIntoView' in html, 'потеряна прокрутка активной вкладки в видимую область'


def test_sidebar_toggle_is_svg_in_templates():
    """Кнопка меню — это <svg>. Фиксируем это, потому что от типа элемента
    зависит способ программной активации в mobile.js."""
    for name in ('index.html', 'video.html'):
        html = read_template(name)
        marker = 'id="sidebarToggle"'
        assert marker in html, f'{name}: не найдена кнопка сайдбара'
        tag_start = html.rfind('<', 0, html.index(marker))
        assert html[tag_start:tag_start + 5] == '<svg ', (
            f'{name}: тип элемента кнопки меню изменился, проверить mobile.js'
        )


def test_mobile_js_does_not_call_click_on_svg():
    """У SVGElement нет метода click() (он есть только у HTMLElement), поэтому
    toggle.click() падал с TypeError и меню не открывалось с клавиатуры."""
    js = strip_js_comments(read_static('js', 'mobile.js'))
    assert '.click()' not in js, (
        'mobile.js: .click() не работает на <svg>, нужен dispatchEvent'
    )
    assert 'dispatchEvent' in js, 'mobile.js: нет программной отправки click'
    assert "MouseEvent('click'" in js or 'MouseEvent("click"' in js, (
        'mobile.js: событие click должно создаваться как MouseEvent'
    )
    assert 'bubbles: true' in js, (
        'mobile.js: событие должно всплывать, иначе обработчик шаблона его не увидит'
    )


def test_mobile_js_keeps_aria_expanded_in_sync():
    """Сайдбар переключает разметка страницы, поэтому состояние для скринридера
    нужно отслеживать по классу, а не по клику."""
    js = strip_js_comments(read_static('js', 'mobile.js'))
    assert 'aria-expanded' in js, 'mobile.js: не выставляется aria-expanded'
    assert 'MutationObserver' in js, 'mobile.js: aria-expanded не синхронизируется'


def test_list_view_class_has_styles():
    """toggleView() навешивает .list-view; без правил кнопка вида ничего не делала."""
    html = read_template('index.html')
    assert 'list-view' in html
    style = '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', html, re.S))
    assert '.video-grid.list-view' in style, 'index.html: у .list-view нет стилей'
