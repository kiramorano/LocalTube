"""Дизайн-система и темы оформления.

Раньше «тема» означала только набор цветов, скопированный inline в каждый
шаблон: радиусы, отступы, тени и состояния кнопок жили в восьми копиях и
разъезжались между страницами. Отсюда ощущение незаконченного продукта.

Эти тесты фиксируют контракт: общий слой оформления подключается всем
страницам, а каждая тема обязана объявить полный набор токенов. Без этого
страница открывается с кодом 200, но выглядит сломанной — например настройки
теряют фон и текст, потому что используют второе семейство переменных.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(ROOT, 'templates')
STATIC_DIR = os.path.join(ROOT, 'static')

# Страницы с оформлением: те же, что и в test_theme_ui.py.
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

# Темы, выбираемые пользователем. dark и light остаются: библиотека уже
# существует, и менять оформление у тех, кто его выбрал, нельзя.
SELECTABLE_THEMES = ['dark', 'light', 'midnight', 'glass', 'frutiger-aero']

# Темы с собственным файлом стилей.
THEME_STYLESHEETS = {
    'midnight': 'midnight.css',
    'glass': 'glass.css',
    'frutiger-aero': 'frutiger-aero.css',
}

# Токены разметки страниц (--yt-*). Их использует index/video/channel и т.д.
YT_TOKENS = [
    '--yt-bg',
    '--yt-bg-solid',
    '--yt-spec-text-primary',
    '--yt-spec-text-secondary',
    '--yt-spec-border',
    '--yt-spec-icon-inactive',
    '--yt-button-bg',
    '--yt-button-hover',
    '--yt-card-bg',
    '--yt-modal-bg',
    '--yt-search-bg',
]

# Второе семейство: его использует settings.html. Тема, объявившая только
# --yt-*, оставляла страницу настроек без фона и цвета текста.
SETTINGS_TOKENS = ['--bg', '--text', '--muted', '--border', '--card', '--button']


def read_template(name):
    with open(os.path.join(TEMPLATES_DIR, name), encoding='utf-8') as fh:
        return fh.read()


def read_static(*parts):
    with open(os.path.join(STATIC_DIR, *parts), encoding='utf-8') as fh:
        return fh.read()


def strip_css_comments(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


# --- Общий слой оформления -------------------------------------------------

@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_pages_load_shared_ui_layer(name):
    """Оформление кнопок, карточек и полей должно быть общим для всех страниц."""
    html = read_template(name)
    assert '/static/css/ui.css' in html, f'{name}: не подключён общий слой ui.css'


@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_ui_layer_wins_over_inline_styles(name):
    """ui.css идёт после инлайновых стилей, иначе страница его перебивает.

    Специфичность правил одинаковая, поэтому побеждает тот, кто объявлен
    последним. Раньше по этой же причине mobile.css пришлось ставить в конец.

    Сравниваем только со стилями внутри <head>: у video.html есть отдельный
    блок для ленты Shorts прямо в разметке, и он к оформлению не относится.
    """
    html = read_template(name)
    head = html[:html.index('</head>')]
    ui_pos = head.index('/static/css/ui.css')
    style_pos = head.rindex('</style>')
    assert ui_pos > style_pos, f'{name}: ui.css подключён до инлайновых стилей'


@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_mobile_css_stays_last(name):
    """mobile.css должен остаться последним: он правит вёрстку под телефон."""
    html = read_template(name)
    assert '/static/css/mobile.css' in html, f'{name}: не подключён mobile.css'
    assert html.index('/static/css/mobile.css') > html.index('/static/css/ui.css'), \
        f'{name}: ui.css перебивает мобильные правила'


def test_ui_layer_defines_design_tokens():
    """Радиусы, отступы и тени задаются токенами, а не числами по месту."""
    css = strip_css_comments(read_static('css', 'ui.css'))
    for token in ('--lt-radius-sm', '--lt-radius-md', '--lt-radius-lg',
                  '--lt-shadow-1', '--lt-shadow-2', '--lt-accent',
                  '--lt-transition'):
        assert re.search(re.escape(token) + r'\s*:', css), \
            f'ui.css: не объявлен токен {token}'


def test_ui_layer_has_visible_focus_ring():
    """Без видимого фокуса интерфейсом нельзя пользоваться с клавиатуры."""
    css = strip_css_comments(read_static('css', 'ui.css'))
    assert ':focus-visible' in css, 'ui.css: нет стиля фокуса для клавиатуры'
    assert 'outline' in css, 'ui.css: фокус не рисуется контуром'


def test_ui_layer_respects_reduced_motion():
    """Анимации должны отключаться по системной настройке."""
    css = strip_css_comments(read_static('css', 'ui.css'))
    assert 'prefers-reduced-motion' in css, \
        'ui.css: анимации не отключаются при prefers-reduced-motion'


def test_ui_layer_keeps_search_pill_geometry():
    """Общий радиус не должен разбивать склейку поля поиска на три плашки.

    Склейку оформляет шаблон, поэтому общий слой обязан её не трогать:
    переопределить не получается — у :not() специфичность выше, и браузер
    показывал скруглённый стык вместо прямого.
    """
    css = strip_css_comments(read_static('css', 'ui.css'))
    radius_rules = re.findall(r'([^{}]*)\{[^}]*border-radius[^}]*\}', css)
    for selector in radius_rules:
        # :focus-visible скругляет только контур фокуса, геометрию склейки он
        # не меняет — само поле остаётся прежней формы.
        if ':focus-visible' in selector or 'search-container' in selector:
            continue
        if 'button' in selector and 'search-container' not in selector:
            assert ':not(.download-btn)' in selector, \
                f'ui.css: правило радиуса ломает кнопку поиска: {selector.strip()}'
        if re.search(r'(^|\s)input', selector) and 'search-container' not in selector:
            assert ':not(.url-input)' in selector, \
                f'ui.css: правило радиуса ломает поле поиска: {selector.strip()}'
        if re.search(r'(^|,|\s)select', selector) and 'search-container' not in selector:
            assert ':not(.url-quality)' in selector, \
                f'ui.css: правило радиуса ломает выбор качества: {selector.strip()}'


def test_ui_layer_does_not_force_font_on_everything():
    """`* { font-family: ... !important }` ломает моноширинные и иконочные шрифты."""
    css = strip_css_comments(read_static('css', 'ui.css'))
    assert not re.search(r'\*\s*\{[^}]*font-family[^}]*!important', css), \
        'ui.css: шрифт навязан всем элементам через * !important'


# --- Единая реализация темы ------------------------------------------------

@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_pages_use_shared_theme_script(name):
    """Тему подключает только static/js/theme.js.

    collection.html держал свою копию: путь к файлу стилей был зашит под
    frutiger-aero, поэтому midnight и glass открывались там как тёмная тема.
    """
    html = read_template(name)
    assert '/static/js/theme.js' in html, f'{name}: не подключён theme.js'
    script_pos = html.index('/static/js/theme.js')
    body = re.search(r'<body\b', html)
    assert body, f'{name}: нет тега body'
    assert script_pos < body.start(), \
        f'{name}: theme.js подключён после разметки, тема встанет после отрисовки'


@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_pages_have_no_local_theme_copy(name):
    """Копия логики темы в шаблоне не знает про новые темы.

    Проверяем именно инлайновый код: локальная реализация отставала от общей и
    подключала чужой файл стилей.
    """
    scripts = '\n'.join(re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>',
                                   read_template(name), re.S))
    code = re.sub(r'^\s*//.*$', '', re.sub(r'/\*.*?\*/', '', scripts, flags=re.S), flags=re.M)
    for dead in ('function loadThemeBackground', 'function setBackgroundImage',
                 'activeBgLayer', "localStorage.getItem('lt_theme')",
                 "localStorage.setItem('lt_theme'",
                 'themes/frutiger-aero.css'):
        assert dead not in code, \
            f'{name}: осталась локальная копия логики темы ({dead})'


@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_pages_do_not_hardcode_theme_font(name):
    """Шрифт темы задаёт fonts.css по атрибуту data-theme.

    Присвоение documentElement.style.fontFamily из шаблона перебивало таблицу
    стилей инлайновым значением, и новая тема не могла сменить шрифт.
    """
    html = read_template(name)
    assert 'documentElement.style.fontFamily' not in html, \
        f'{name}: шрифт темы навязан инлайново вместо fonts.css'


@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_theme_stylesheet_wins_over_inline_styles(name):
    """Файл темы должен идти после инлайновых стилей.

    Специфичность :root[data-theme] одинаковая, поэтому побеждает объявленный
    последним. На video/channel/settings/collection ссылка стояла в начале
    <head>, а шаблон ниже заново объявлял токены aero — файл темы не
    применялся. theme.js обязан идти после самой ссылки: иначе
    applyStylesheet не находит элемент и не ставит href.
    """
    html = read_template(name)
    head = html[:html.index('</head>')]
    link = re.search(r'<link[^>]*id="theme-style(?:-link)?"[^>]*>', head)
    assert link, f'{name}: нет <link> файла темы'
    style_pos = head.rindex('</style>')
    assert link.start() > style_pos, \
        f'{name}: файл темы подключён до инлайновых стилей, токены шаблона его перебивают'
    script_pos = head.index('/static/js/theme.js')
    assert script_pos > link.start(), \
        f'{name}: theme.js раньше <link> темы, applyStylesheet не найдёт элемент'


# --- Набор тем -------------------------------------------------------------

def test_theme_js_offers_all_themes():
    js = read_static('js', 'theme.js')
    listed = re.search(r'THEMES\s*=\s*\[(.*?)\]', js, re.S)
    assert listed, 'theme.js: не найден список тем'
    names = re.findall(r"'([\w-]+)'", listed.group(1))
    assert names == SELECTABLE_THEMES, f'theme.js: список тем {names}'


def test_theme_js_maps_every_theme_to_its_stylesheet():
    """Путь к стилю темы не должен быть зашит под одну тему.

    Раньше applyStylesheet знал только frutiger-aero.css, поэтому новая тема
    получала оформление без своего файла и выглядела как тёмная.
    """
    js = read_static('js', 'theme.js')
    for theme, filename in THEME_STYLESHEETS.items():
        assert filename in js, f'theme.js: не указан файл стилей {filename}'
        assert theme in js, f'theme.js: тема {theme} не упомянута'


@pytest.mark.parametrize('theme,filename', sorted(THEME_STYLESHEETS.items()))
def test_theme_file_declares_all_tokens(theme, filename):
    """Тема обязана объявить оба семейства токенов.

    Пропуск --bg/--text оставлял страницу настроек без фона: она использует
    другое семейство переменных, чем каталог.
    """
    css = strip_css_comments(read_static('css', 'themes', filename))
    block = re.search(r':root\[data-theme="' + re.escape(theme) + r'"\]\s*\{(.*?)\}',
                      css, re.S)
    assert block, f'{filename}: нет блока токенов для темы {theme}'
    declared = set(re.findall(r'(--[\w-]+)\s*:', block.group(1)))
    missing = [t for t in YT_TOKENS + SETTINGS_TOKENS if t not in declared]
    assert not missing, f'{filename}: не объявлены токены {missing}'


@pytest.mark.parametrize('theme,filename', sorted(THEME_STYLESHEETS.items()))
def test_theme_file_scopes_rules_to_itself(theme, filename):
    """Тема не должна менять оформление других тем.

    Правило без селектора темы применялось бы всегда, потому что файл
    подключён к тому же #theme-style.
    """
    css = strip_css_comments(read_static('css', 'themes', filename))
    body_rules = re.findall(r'(^|\})\s*(body|header|\.video-card)\s*\{', css)
    assert not body_rules, \
        f'{filename}: правила вне области темы: {[r[1] for r in body_rules]}'


@pytest.mark.parametrize('theme', ['midnight', 'glass'])
def test_new_themes_are_offered_in_settings(theme):
    html = read_template('settings.html')
    assert f'value="{theme}"' in html, f'settings.html: нет выбора темы {theme}'


def test_settings_theme_select_lists_every_theme():
    """Выбор темы в настройках — единственный способ её сменить."""
    html = read_template('settings.html')
    select = html.split('<select id="theme"', 1)[1].split('</select>', 1)[0]
    offered = re.findall(r'value="([\w-]+)"', select)
    assert offered == SELECTABLE_THEMES, f'settings.html: предлагаются {offered}'


def test_glass_theme_has_translucent_panels():
    """Смысл стеклянной темы — размытые полупрозрачные панели."""
    css = strip_css_comments(read_static('css', 'themes', 'glass.css'))
    assert 'backdrop-filter' in css, 'glass.css: нет размытия панелей'
    assert '-webkit-backdrop-filter' in css, 'glass.css: нет префикса для WebKit'


def test_glass_theme_keeps_opaque_menus():
    """Сквозь меню не должно просвечивать содержимое страницы.

    В frutiger-aero это уже приводило к нечитаемым настройкам плеера, поэтому
    панели там сделаны почти непрозрачными.
    """
    css = strip_css_comments(read_static('css', 'themes', 'glass.css'))
    modal = re.search(r'--yt-modal-bg\s*:\s*([^;]+);', css)
    assert modal, 'glass.css: не задан фон панелей'
    alpha = re.search(r'rgba\([^)]*,\s*([\d.]+)\s*\)', modal.group(1))
    assert alpha is None or float(alpha.group(1)) >= 0.9, \
        f'glass.css: панели слишком прозрачные ({modal.group(1).strip()})'


def test_midnight_theme_is_opaque():
    """Премиальная тёмная тема — без прозрачного фона и без обоев."""
    css = strip_css_comments(read_static('css', 'themes', 'midnight.css'))
    block = re.search(r':root\[data-theme="midnight"\]\s*\{(.*?)\}', css, re.S)
    assert block, 'midnight.css: нет блока токенов'
    bg = re.search(r'--yt-bg\s*:\s*([^;]+);', block.group(1))
    assert bg and 'transparent' not in bg.group(1), \
        'midnight.css: фон не должен быть прозрачным'


def test_only_aero_theme_declares_wallpapers(app_module):
    """Обои есть только у Frutiger Aero: остальные темы их не запрашивают."""
    assert app_module.THEMES_WITH_BACKGROUNDS == ('frutiger-aero',)
    for theme in ('midnight', 'glass'):
        assert app_module.app.test_client().get(
            f'/api/theme-backgrounds/{theme}').get_json() == []


@pytest.mark.parametrize('theme', ['midnight', 'glass'])
def test_new_theme_text_is_not_transparent(theme):
    """color: var(--yt-bg) невидим, если фон темы прозрачный.

    У новых тем фон непрозрачный, поэтому важнее другое: --yt-bg-solid обязан
    остаться непрозрачным, его используют как цвет текста на инверсии.
    """
    filename = THEME_STYLESHEETS[theme]
    css = strip_css_comments(read_static('css', 'themes', filename))
    solid = re.search(r'--yt-bg-solid\s*:\s*([^;]+);', css)
    assert solid, f'{filename}: не объявлен --yt-bg-solid'
    assert 'transparent' not in solid.group(1), \
        f'{filename}: --yt-bg-solid прозрачен, текст на инверсии исчезнет'


def test_channel_links_use_link_token():
    """Ссылки на странице канала берут цвет из токена --link.

    #3ea6ff на белом фоне светлой темы даёт контраст 2,6:1 — ниже порога
    WCAG AA (4,5:1) для текста.
    """
    css = strip_css_comments(read_template('channel.html'))
    for selector in ('.about a', '.about-links a'):
        rule = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css)
        assert rule, f'в channel.html нет правила {selector}'
        assert '--link' in rule.group(1), \
            f'{selector}: цвет ссылки зашит вместо var(--link)'
    light = re.search(r':root\[data-theme="light"\]\s*\{([^}]*)\}', css)
    assert light and '--link' in light.group(1), \
        'светлая тема не переопределяет --link'


def test_channel_facts_use_theme_tokens():
    """Плитки «О канале» не должны зашивать цвета.

    Иначе в midnight, glass и aero блок выглядит чужеродным.
    """
    css = strip_css_comments(read_template('channel.html'))
    for selector in ('.fact', '.fact-label', '.tag'):
        rule = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css)
        assert rule, f'в channel.html нет правила {selector}'
        assert 'var(--' in rule.group(1), \
            f'{selector}: цвета зашиты вместо токенов темы'
