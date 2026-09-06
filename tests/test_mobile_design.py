"""Мобильная вёрстка: токены, цели нажатия, нижняя навигация.

Эти проверки фиксируют то, что уже ломалось и незаметно ломается снова, потому
что страница при этом отдаётся с кодом 200:

* размер меньше 44px — палец промахивается по кнопке;
* шрифт поля меньше 16px — Safari на iOS приближает страницу при фокусе и сам
  обратно не возвращает;
* число вместо токена — радиусы и отступы разъезжаются между страницами
  (именно так в mobile.css оказались радиусы 8, 10, 12, 16, 18, 22 и 50%
  одновременно);
* забытый include навигации — на странице пропадает единственный способ
  перейти в другой раздел с телефона.

Замеры в браузере лежат в tests/browser/: здесь только то, что проверяется по
исходникам и потому работает без запущенного сервера.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(ROOT, 'templates')
STATIC_DIR = os.path.join(ROOT, 'static')

# Страницы с оформлением. Лента Shorts живёт внутри video.html и панель не
# получает намеренно: ролик занимает весь экран.
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

NAV_PARTIAL = '_mobile_nav.html'


def read_template(name):
    with open(os.path.join(TEMPLATES_DIR, name), encoding='utf-8') as fh:
        return fh.read()


def read_static(*parts):
    with open(os.path.join(STATIC_DIR, *parts), encoding='utf-8') as fh:
        return fh.read()


def strip_css_comments(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def mobile_css():
    return strip_css_comments(read_static('css', 'mobile.css'))


def ui_css():
    return strip_css_comments(read_static('css', 'ui.css'))


# --- Токены ----------------------------------------------------------------

MOBILE_TOKENS = [
    '--lt-tap',
    '--lt-safe-bottom',
    '--lt-safe-top',
    '--lt-nav-height',
    '--lt-nav-gap',
    '--lt-text-md',
    '--lt-text-xl',
    '--lt-leading',
]


@pytest.mark.parametrize('token', MOBILE_TOKENS)
def test_ui_layer_declares_mobile_tokens(token):
    """Мобильные размеры задаются токенами, а не числами по месту."""
    assert re.search(re.escape(token) + r'\s*:', ui_css()), \
        f'ui.css: не объявлен токен {token}'


def test_tap_token_is_at_least_44px():
    """44px — порог Apple HIG; браузерная проверка требует ровно его."""
    css = ui_css()
    value = re.search(r'--lt-tap\s*:\s*(\d+)px', css)
    assert value, 'ui.css: --lt-tap не задан в пикселях'
    assert int(value.group(1)) >= 44, \
        f'--lt-tap меньше 44px ({value.group(1)}px): палец будет промахиваться'


def test_safe_area_tokens_have_fallback():
    """env() без запасного значения даёт невалидную длину вне телефона.

    Без «, 0px» правило целиком отбрасывается настольным браузером: отступ
    исчезал вместе с самим свойством, а не только с вырезом.
    """
    css = ui_css()
    for token in ('--lt-safe-top', '--lt-safe-bottom',
                  '--lt-safe-left', '--lt-safe-right'):
        rule = re.search(re.escape(token) + r'\s*:\s*([^;]+);', css)
        assert rule, f'ui.css: не объявлен {token}'
        assert re.search(r'env\([^)]+,\s*0px\s*\)', rule.group(1)), \
            f'ui.css: {token} без запасного значения — правило отбросится вне телефона'


def test_mobile_css_uses_tokens_not_magic_numbers():
    """Радиусы и минимальные высоты берутся из токенов.

    Раньше в файле соседствовали радиусы 8, 10, 12, 16, 18, 22 и 50%, а
    минимальная площадь под палец была то 40px, то 44px. Числа остаются
    допустимыми там, где размер диктует не дизайн-система: превью 9/16,
    иконка 22x22, полоска-ухватка.
    """
    css = mobile_css()
    radii = re.findall(r'border-radius:\s*([^;]+);', css)
    literal = [value for value in radii
               if 'var(--lt-radius' not in value and value.strip() != '0']
    assert not literal, f'mobile.css: радиус числом вместо токена: {literal}'

    # Ограничение касается того, во что тычут пальцем. Подписи вроде .chip —
    # это span с cursor: default, им хватает своего размера.
    interactive = ('button', 'a ', 'a,', 'a:', '.control-btn', '.action-btn',
                   '.header-link', '.lt-nav-item', 'input', 'select')
    for match in re.finditer(r'([^{}]+)\{([^}]*)\}', css):
        selector, body = match.group(1).strip(), match.group(2)
        if not any(name in selector for name in interactive):
            continue
        taps = re.findall(r'min-height:\s*(\d+)px', body)
        assert not taps, \
            f'mobile.css: цель нажатия числом вместо --lt-tap в «{selector}»: {taps}'


def test_mobile_css_has_no_hardcoded_theme_colors():
    """Цвета берутся из темы: хардкод ломает светлую и стеклянные темы.

    Исключение — подложки поверх кадра видео: там фон не из темы намеренно,
    иначе иконка теряется на светлом превью.
    """
    css = mobile_css()
    # Блоки правил, где допустимы свои цвета: они лежат поверх видео.
    over_video = ('.control-btn', '.action-btn')
    for match in re.finditer(r'([^{}]+)\{([^}]*)\}', css):
        selector, body = match.group(1).strip(), match.group(2)
        if any(name in selector for name in over_video):
            continue
        bad = re.findall(r'(?:background|color)\s*:\s*(#[0-9a-fA-F]{3,6}|rgba?\([^)]*\))',
                         body)
        assert not bad, f'mobile.css: цвет мимо темы в «{selector}»: {bad}'


# --- Цели нажатия и поля ввода --------------------------------------------

def test_inputs_are_16px_on_mobile():
    """Поле меньше 16px заставляет Safari на iOS приближать страницу.

    Возврата к прежнему масштабу не происходит: пользователь остаётся на
    увеличенном, съехавшем в сторону экране. Правило должно покрывать поля
    вообще, а не перечислять их по одному.
    """
    css = mobile_css()
    rule = re.search(
        r'input:not\(\[type="range"\]\)[^{]*\{([^}]*)\}', css)
    assert rule, 'mobile.css: нет общего правила размера шрифта для полей'
    assert 'var(--lt-text-xl)' in rule.group(1), \
        'mobile.css: поля не приведены к 16px'


def test_mobile_keeps_quality_control_reachable():
    """Кнопку настроек (там выбор качества) нельзя прятать на телефоне."""
    hidden = re.findall(r'\.controls-right \.control-btn:nth-child\((\d+)\)',
                        mobile_css())
    assert '5' not in hidden, 'скрыта кнопка настроек: качество не переключить'
    assert '6' not in hidden, 'скрыта кнопка полного экрана'


def test_card_actions_are_visible_on_touch():
    """На тач-экране нет наведения: кнопки карточки должны быть видны всегда."""
    assert re.search(r'\.card-actions\s*\{[^}]*opacity:\s*1', mobile_css()), \
        'кнопки на карточках остаются прозрачными на телефоне'


def test_touch_targets_keep_visual_size_via_transparent_border():
    """Кнопки поверх превью нельзя просто увеличить: они закроют кадр.

    Площадь добирается прозрачной рамкой, поэтому background-clip обязателен —
    без него рамка закрашивается и кружок выглядит раздутым.
    """
    css = mobile_css()
    block = re.search(r'\.action-btn\s*\{([^}]*)\}', css)
    assert block, 'mobile.css: нет правил для .action-btn'
    body = block.group(1)
    assert 'var(--lt-tap)' in body, '.action-btn меньше минимальной цели'
    assert 'border: 4px solid transparent' in body, \
        '.action-btn: площадь не добрана прозрачной рамкой'
    assert 'background-clip: padding-box' in body, \
        '.action-btn: без background-clip рамка закрасится'


# --- Нижняя навигация -----------------------------------------------------

@pytest.mark.parametrize('name', [n for n in THEMED_TEMPLATES])
def test_pages_include_bottom_navigation(name):
    """Без панели на телефоне разделы доступны только через выдвижное меню."""
    assert NAV_PARTIAL in read_template(name), \
        f'{name}: не подключена нижняя навигация'


def test_shorts_feed_has_no_bottom_navigation():
    """В ленте Shorts панель закрыла бы кнопки ролика у нижнего края."""
    html = read_template('video.html')
    include_pos = html.index(NAV_PARTIAL)
    condition = html.rfind('{% if not is_short %}', 0, include_pos)
    assert condition != -1, \
        'video.html: панель подключена без условия — она попадёт в ленту Shorts'


def test_navigation_partial_has_no_inline_styles():
    """Разметка панели попадает на восемь страниц: свои стили дали бы восемь копий.

    var() здесь тоже недопустим: переменная, не объявленная шаблоном, ломает
    проверку test_css_variables_are_declared.
    """
    # Комментарии Jinja до браузера не доходят, поэтому упоминание <style> в
    # пояснении наверху файла проверку волновать не должно: смотрим разметку.
    html = re.sub(r'\{#.*?#\}', '', read_template(NAV_PARTIAL), flags=re.S)
    assert '<style' not in html, f'{NAV_PARTIAL}: инлайновые стили'
    assert 'style="' not in html, f'{NAV_PARTIAL}: инлайновый атрибут style'
    assert 'var(--' not in html, f'{NAV_PARTIAL}: var() без объявления в шаблоне'


def test_navigation_is_hidden_on_desktop_by_default():
    """Панель — мобильный элемент. На широком экране её роль у сайдбара."""
    css = mobile_css()
    base = re.search(r'\.lt-bottom-nav\s*\{([^}]*)\}', css)
    assert base, 'mobile.css: нет базового правила .lt-bottom-nav'
    assert 'display: none' in base.group(1), \
        'панель показывается на настольной вёрстке'
    # Показывается ровно внутри мобильного медиазапроса.
    mobile_block = css[css.index('@media (max-width: 600px)'):]
    assert re.search(r'\.lt-bottom-nav\s*\{[^}]*position:\s*fixed', mobile_block), \
        'панель не закрепляется у нижнего края на телефоне'


def test_navigation_reserves_space_for_content():
    """Панель перекрывала последнюю карточку каталога и кнопки в конце страницы."""
    css = mobile_css()
    assert re.search(r'#mainContent,\s*#queueContainer\s*\{[^}]*var\(--lt-nav-gap\)', css), \
        'каталог не оставляет места под панель'
    assert re.search(r'\.page-content\s*\{[^}]*padding-bottom:\s*var\(--lt-nav-gap\)', css), \
        'страница видео не оставляет места под панель'
    assert re.search(r'#toast-container\s*\{[^}]*bottom:\s*var\(--lt-nav-gap\)', css), \
        'уведомления всплывают под панелью'


def test_navigation_marks_active_section():
    """Без отметки непонятно, в каком разделе находишься."""
    css = mobile_css()
    assert re.search(r'\.lt-nav-item\.active\s*\{', css), \
        'mobile.css: активный пункт панели не выделен'
    html = read_template(NAV_PARTIAL)
    assert 'aria-current' in html, \
        f'{NAV_PARTIAL}: активный пункт не помечен для скринридера'


def test_navigation_active_state_follows_client_side_switching():
    """Разделы главной переключаются без перезагрузки.

    Отметка ставится в разметке сервером, но filterNav() меняет раздел на месте:
    без синхронизации подсветка оставалась на «Главной» после перехода в очередь.
    """
    html = read_template('index.html')
    assert re.search(r"querySelectorAll\('\.lt-nav-item'\)", html), \
        'index.html: filterNav не обновляет отметку в панели'
    assert 'data-nav-target' in html, \
        'index.html: пункты панели не связаны с разделами'


def test_index_supports_nav_query_parameter():
    """С других страниц панель ведёт на /?nav=...: параметр обязан работать."""
    html = read_template('index.html')
    assert 'URLSearchParams' in html and "get('nav')" in html, \
        'index.html: параметр ?nav= не читается, ссылки панели откроют главную'


def test_navigation_colors_come_from_theme_tokens():
    """Панель обязана перекрашиваться темой.

    У Frutiger Aero подложка светлая, а текст наследуется белый: получалось
    белое на белом (контраст 1.03). Цвета вынесены в токены, чтобы тема
    заменяла их, не переписывая раскладку.
    """
    ui = ui_css()
    for token in ('--lt-nav-bg', '--lt-nav-fg', '--lt-nav-fg-active', '--lt-nav-chip'):
        assert re.search(re.escape(token) + r'\s*:', ui), \
            f'ui.css: не объявлен токен панели {token}'
    css = mobile_css()
    assert 'var(--lt-nav-bg)' in css, 'mobile.css: подложка панели мимо токена'
    assert 'var(--lt-nav-fg)' in css, 'mobile.css: цвет пунктов мимо токена'


def test_aero_theme_overrides_navigation_colors():
    """Светлая стеклянная панель требует тёмного текста."""
    css = strip_css_comments(read_static('css', 'themes', 'frutiger-aero.css'))
    assert '--lt-nav-fg' in css, \
        'frutiger-aero.css: панель осталась с белым текстом на светлом стекле'
    assert re.search(r'\.lt-bottom-nav[^{]*\{[^}]*text-shadow:\s*none', css), \
        'frutiger-aero.css: наследуемая тень текста даёт ореол на светлой панели'


# --- Вырезы и жестовая полоса ---------------------------------------------

@pytest.mark.parametrize('name', THEMED_TEMPLATES)
def test_pages_opt_into_safe_area(name):
    """Без viewport-fit=cover env(safe-area-*) всегда равен нулю.

    Отступы под вырез и жестовую полосу в CSS есть, но браузер не сообщает их
    значения, пока страница не согласится занимать весь экран.
    """
    html = read_template(name)
    viewport = re.search(r'<meta name="viewport" content="([^"]*)"', html)
    assert viewport, f'{name}: нет мета-тега viewport'
    assert 'viewport-fit=cover' in viewport.group(1), \
        f'{name}: без viewport-fit=cover отступы под вырез не применяются'


def test_navigation_respects_gesture_bar():
    """Жестовая полоса перекрывала подписи пунктов панели."""
    css = mobile_css()
    block = re.search(r'\.lt-bottom-nav\s*\{[^}]*position:\s*fixed[^}]*\}', css)
    assert block, 'mobile.css: панель не закреплена'
    assert 'var(--lt-safe-bottom)' in block.group(0), \
        'панель не учитывает жестовую полосу телефона'


def test_sheets_clear_gesture_bar():
    """Нижняя кнопка модального окна оказывалась под жестовой полосой."""
    css = mobile_css()
    box = re.search(
        r'\.modal-content,\s*\.collection-modal-box,\s*\.dl-modal\s*\{([^}]*)\}', css)
    assert box, 'mobile.css: нет правил содержимого панели'
    padding = re.search(r'padding-bottom:\s*([^;]+);', box.group(1))
    assert padding and 'var(--lt-safe-bottom)' in padding.group(1), \
        'mobile.css: панели снизу не отступают от жестовой полосы'


def test_header_clears_notch():
    """Строка состояния накладывалась на гамбургер и поле ссылки."""
    css = mobile_css()
    block = re.search(r'(?<!\.)\bheader\s*\{([^}]*)\}', css)
    assert block, 'mobile.css: нет правил шапки для телефона'
    assert 'var(--lt-safe-top)' in block.group(1), \
        'шапка не учитывает вырез экрана'


# --- Модальные окна как панели снизу --------------------------------------

def test_modals_become_bottom_sheets():
    """Окно по центру телефона далеко от большого пальца.

    Кнопки такого окна оказываются в середине экрана, до них надо
    перехватывать телефон. Панель снизу — привычный мобильный шаблон.
    """
    css = mobile_css()
    align = re.search(r'\.modal-overlay,\s*\.collection-modal,\s*\.dl-overlay\s*\{([^}]*)\}', css)
    assert align, 'mobile.css: окна не переведены в панели снизу'
    assert 'align-items: flex-end' in align.group(1), \
        'окно не прижато к нижнему краю'
    box = re.search(
        r'\.modal-content,\s*\.collection-modal-box,\s*\.dl-modal\s*\{([^}]*)\}', css)
    assert box, 'mobile.css: нет правил содержимого панели'
    body = box.group(1)
    assert 'border-radius: var(--lt-radius-lg) var(--lt-radius-lg) 0 0' in body, \
        'у панели скруглены все углы: она выглядит обрезанной у края'
    assert 'overscroll-behavior: contain' in body, \
        'прокрутка панели пробрасывается на страницу под ней'
