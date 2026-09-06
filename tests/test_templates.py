"""Шаблоны, Jinja-фильтры и целостность клиентского JS.

Эти проверки ловят класс ошибок, из-за которых страница отдаётся с кодом 200,
но интерфейс не работает: пропавшая JS-функция, незарегистрированный фильтр,
неэкранированные данные.
"""
import os
import re

import pytest

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
TEMPLATE_FILES = sorted(f for f in os.listdir(TEMPLATES_DIR) if f.endswith(".html"))


@pytest.mark.parametrize("name", TEMPLATE_FILES)
def test_template_compiles(app_module, name):
    app_module.app.jinja_env.get_template(name)


@pytest.mark.parametrize("raw,expected", [
    ("20260812", "12.08.2026"),
    ("2026-08-12", "12.08.2026"),
    ("", ""),
    (None, ""),
    ("мусор", "мусор"),
])
def test_human_date(app_module, raw, expected):
    assert app_module.app.jinja_env.filters["human_date"](raw) == expected


@pytest.mark.parametrize("seconds,expected", [
    (70, "1:10"),
    (94, "1:34"),
    (3723, "1:02:03"),
    (59, "0:59"),
    # 0 и мусор означают "длительность неизвестна": плашку показывать нечего.
    (0, ""),
    (None, ""),
    ("", ""),
    ("abc", ""),
])
def test_human_duration(app_module, seconds, expected):
    assert app_module.app.jinja_env.filters["human_duration"](seconds) == expected


def read_template(name):
    with open(os.path.join(TEMPLATES_DIR, name), encoding="utf-8") as f:
        return f.read()


def read_static(*parts):
    """Читает файл из static/: общие слои стилей и скриптов."""
    root = os.path.dirname(TEMPLATES_DIR)
    with open(os.path.join(root, "static", *parts), encoding="utf-8") as f:
        return f.read()


def template_env():
    """Jinja с теми же фильтрами и переменными, что даёт приложение.

    Без фильтра перевода шаблон вообще не собирается («No filter named t»), а
    без ui_lang в контексте пропадает атрибут lang у <html>. Заводить их в
    каждом тесте порознь значило бы ловить эту ошибку по очереди.
    """
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    # Русский — язык исходных строк, поэтому перевод здесь тождественный.
    env.filters["t"] = lambda text: text
    env.globals["ui_lang"] = "ru"
    env.globals["ui_languages"] = [{"code": "ru", "label": "Русский"},
                                   {"code": "en", "label": "English"}]
    return env


@pytest.mark.parametrize("name", TEMPLATE_FILES)
def test_no_calls_to_undefined_local_functions(name):
    """Каждая функция, вызванная из onclick/onchange, должна быть объявлена.

    Именно так возник баг с пропавшей escapeHtml: очередь падала с ReferenceError,
    хотя страница отдавалась успешно.
    """
    html = read_template(name)
    declared = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", html))
    declared |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", html))
    declared |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function", html))
    # Обработчики часто вешают на window, чтобы они были видны из inline-атрибутов.
    declared |= set(re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=", html))

    # Берём только вызовы верхнего уровня: obj.method() — не наша забота.
    handlers = re.findall(r'on(?:click|change|input|submit|load|error)="([^"]+)"', html)
    called = set()
    for handler in handlers:
        called.update(re.findall(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(", handler))

    js_keywords = {"if", "return", "typeof", "for", "while", "switch", "catch", "function", "new", "await"}
    missing = {
        fn for fn in called - declared - js_keywords
        if not fn[0].isupper() and fn not in {"this", "window", "document", "event"}
    }

    assert not missing, f"{name}: вызываются необъявленные функции {sorted(missing)}"


@pytest.mark.parametrize("name", TEMPLATE_FILES)
def test_no_leftover_userdata_state_variables(name):
    """После переноса данных на сервер не должно остаться забытых ссылок.

    Переменные переименованы (history -> watchHistory), поэтому старое имя в
    коде означало бы необъявленную переменную и ReferenceError.
    """
    html = read_template(name)
    # Вырезаем строковые литералы: 'lt_history' и data.history — легальны.
    code = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"|`[^`]*`", "''", html)
    # Обращения вида data.history / window.history тоже допустимы.
    bare_history = re.findall(r"(?<![\w.$])history\s*(?:\.|\[|=[^=])", code)
    assert not bare_history, (
        f"{name}: осталось обращение к переменной history "
        f"({len(bare_history)} шт.), она переименована в watchHistory")


def test_index_waits_for_userdata_before_writing():
    """Клики по избранному обязаны дождаться загрузки данных.

    Иначе список пуст, клиент решает «добавляю», а сервер по актуальному
    состоянию делает обратное.
    """
    html = read_template("index.html")
    assert "userDataReady" in html
    # Обе функции записи должны ждать готовности данных.
    for fn in ("toggleFav", "toggleHideChannel"):
        start = html.index(f"async function {fn}(")
        body = html[start:start + 400]
        assert "await userDataReady" in body, f"{fn} не ждёт userDataReady"


def test_index_sends_explicit_state_not_toggle():
    """Клиент передаёт желаемое состояние, а не команду переключения."""
    html = read_template("index.html")
    assert "active: shouldBeFavorite" in html
    assert "hidden: shouldHide" in html


def test_index_renders_userdata_inline():
    """Данные должны приходить вместе со страницей, а не отдельным запросом.

    Иначе избранное и фильтр скрытых каналов применяются с задержкой, и
    карточки скрытых каналов успевают мигнуть.
    """
    html = read_template("index.html")
    assert "favorites|default([])|tojson" in html
    assert "watch_history|default([])|tojson" in html
    assert "hidden_channels|default([])|tojson" in html
    # Никакой маскировки контента быть не должно: данные уже есть.
    assert "userdata-loading" not in html


def test_index_does_not_wipe_inline_data_on_fetch_error():
    """Сбой фонового запроса не должен обнулять уже отрендеренные данные."""
    html = read_template("index.html")
    start = html.index("async function loadUserData(")
    # Границей берём начало следующей функции, а не окно фиксированной длины:
    # любая вставка внутрь loadUserData выталкивала проверяемую строку наружу,
    # и тест падал на нетронутой логике.
    end = html.index("async function loadSidebarCollections(", start)
    body = html[start:end]
    assert "local.favorites.length" in body, "пустая локальная копия затрёт данные страницы"


def test_settings_has_userdata_controls():
    """В настройках должны быть кнопки очистки: эндпоинт без UI бесполезен."""
    html = read_template("settings.html")
    # Каждый раздел должен быть очищаемым через API.
    for section in ("history", "favorites", "hidden_channels"):
        assert f"clearSection('{section}'" in html, f"нет очистки раздела {section}"
    # Кнопка должна существовать в разметке и иметь обработчик.
    for btn in ("clearHistory", "clearFavorites", "clearHidden"):
        assert f'id="{btn}"' in html, f"нет кнопки {btn}"
        assert f"$('{btn}').addEventListener" in html, f"кнопка {btn} без обработчика"
    assert "/api/userdata/clear/" in html
    # Очистка необратима — обязательно подтверждение.
    assert "confirm(" in html


def test_settings_has_browser_cookie_export():
    """Кнопка экспорта cookies из браузера и выбор браузера.

    Эндпоинт /api/cookies/from-browser существовал, но не вызывался ниоткуда:
    единственным способом были ручная вставка текста, а cookies нужны для видео
    с ограничением по возрасту.
    """
    html = read_template("settings.html")
    for element in ("cookieBrowser", "importFromBrowser"):
        assert f'id="{element}"' in html, f"нет элемента {element}"
    assert "$('importFromBrowser').addEventListener" in html, "кнопка без обработчика"
    assert "/api/cookies/from-browser" in html
    # Список браузеров должен приходить с сервера, а не быть захардкожен:
    # иначе в нём окажутся браузеры, которых нет в системе.
    assert "/api/cookies/browsers" in html
    assert "loadBrowsers" in html


def test_settings_browser_list_is_not_hardcoded():
    """Захардкоженный список повторил бы ошибку с несуществующими браузерами."""
    html = read_template("settings.html")
    select = html.split('id="cookieBrowser"', 1)[1].split("</select>", 1)[0]

    for browser in ("firefox", "chrome", "edge", "opera"):
        assert f'value="{browser}"' not in select, \
            f"браузер {browser} захардкожен в разметке"


def test_settings_browser_import_reports_errors():
    """Chrome/Edge часто падают на DPAPI — пользователь должен видеть причину."""
    html = read_template("settings.html")
    body = html.split("$('importFromBrowser').addEventListener", 1)[1].split("loadBrowsers();", 1)[0]

    assert "data.error" in body, "ошибка сервера не показывается"
    assert "$('status').textContent" in body
    # Кнопку нужно блокировать: чтение профиля занимает секунды.
    assert "disabled = true" in body and "disabled = false" in body


def test_queue_template_escapes_user_data():
    html = read_template("index.html")
    assert "function escapeHtml" in html
    # Заголовок и ссылки приходят с YouTube и обязаны экранироваться.
    assert "escapeHtml(task.title)" in html
    assert "escapeHtml(task.current_url)" in html


def test_queue_template_has_cancel_and_priority_controls():
    html = read_template("index.html")
    assert "cancelQueueTask" in html
    assert "setQueuePriority" in html
    assert 'value="cancelled"' in html


def test_channel_template_has_sync_panel():
    html = read_template("channel.html")
    for marker in ("syncStatus", "syncButton", "startChannelSync", "loadSyncStatus"):
        assert marker in html


def test_channel_template_uses_date_filters():
    html = read_template("channel.html")
    assert "human_date" in html
    assert "human_duration" in html


@pytest.mark.parametrize("page", ["/", "/settings"])
def test_pages_render(client, page):
    assert client.get(page).status_code == 200


# --- Переменные CSS -------------------------------------------------------

# Переменные, приходящие из внешних файлов стилей, а не из самого шаблона.
EXTERNAL_CSS_VARS = {"--yt-sidebar-width"}


@pytest.mark.parametrize("name", TEMPLATE_FILES)
def test_css_variables_are_declared(name):
    """var(--x) без объявления давал прозрачные карточки очереди.

    Не считаем ошибкой var(--x, fallback) и переменные, которые ставит JS
    через setProperty: у них значение появляется в рантайме.
    """
    html = read_template(name)
    # Только использования без значения по умолчанию.
    used = set(re.findall(r"var\((--[\w-]+)\s*\)", html))
    declared = set(re.findall(r"(--[\w-]+)\s*:", html))
    declared |= set(re.findall(r"setProperty\(\s*['\"](--[\w-]+)", html))
    missing = sorted(used - declared - EXTERNAL_CSS_VARS)
    assert not missing, f"{name}: переменные используются, но не объявлены: {missing}"


def test_index_declares_card_bg_for_both_themes():
    """Карточки очереди были невидимы: --yt-card-bg не объявлялась ни в одной теме."""
    html = read_template("index.html")
    for theme in ('data-theme="dark"', 'data-theme="light"'):
        block = html.split(theme, 1)[1].split("}", 1)[0]
        assert "--yt-card-bg" in block, f"--yt-card-bg отсутствует в теме {theme}"


def test_index_pins_sidebar_on_wide_screens():
    """Сайдбар стоял на left:-240px всегда, поэтому пункт «Очередь» не кликался."""
    html = read_template("index.html")
    assert re.search(r"@media\s*\(min-width:\s*\d+px\)\s*\{[^}]*\.sidebar-drawer\s*\{\s*left:\s*0", html)


def test_index_drops_sidebar_offset_when_sidebar_hidden():
    """В диапазоне 601–999px слева оставалась пустая полоса 240px."""
    html = read_template("index.html")
    pin = re.search(r"@media\s*\(min-width:\s*(\d+)px\)\s*\{[^}]*\.sidebar-drawer\s*\{\s*left:\s*0", html)
    reset = re.search(
        r"@media\s*\(max-width:\s*(\d+)px\)\s*\{\s*#mainContent,\s*#queueContainer\s*\{\s*margin-left:\s*0",
        html,
    )
    assert reset, "нет сброса отступа для узких экранов"
    # Диапазоны должны стыковаться, иначе останется щель без сайдбара и с отступом.
    assert int(reset.group(1)) == int(pin.group(1)) - 1


# Шаблоны с боковой панелью.
SIDEBAR_TEMPLATES = ["index.html", "video.html", "playlist.html", "upload.html", "edit.html"]


@pytest.mark.parametrize("name", SIDEBAR_TEMPLATES)
def test_templates_have_no_local_sidebar_toggle(name):
    """Переключение панели должно быть только в общем mobile.js.

    Пять шаблонов держали одинаковую копию `classList.toggle('active')`, и
    CSS-часть разъехалась: закрепление на широких экранах добавили только в
    index.html. В итоге на десктопе кнопка лишь включала затемняющий оверлей, а
    панель не сворачивалась. Вторая копия обработчика вдобавок отменяла первую.
    """
    html = read_template(name)
    assert "function toggleSidebar" not in html, \
        f"{name}: локальная копия переключения панели"
    assert not re.search(r"sidebarToggle\s*\.\s*addEventListener", html), \
        f"{name}: обработчик кнопки навешивается в шаблоне, а не в mobile.js"


@pytest.mark.parametrize("name", SIDEBAR_TEMPLATES)
def test_sidebar_templates_load_shared_script(name):
    """Без mobile.js кнопка панели вообще перестаёт работать."""
    html = read_template(name)
    assert "/static/js/mobile.js" in html, f"{name}: не подключён mobile.js"


def test_collapsed_state_lives_on_root_element():
    """Класс свёрнутости висит на <html>, а не на самой панели.

    Инлайновые стили шаблона подключаются до ui.css, и правило
    `.sidebar-drawer { left: 0 }` внутри @media (min-width: 1000px) перебивало
    бы `.sidebar-drawer.active`. Селектор от корня документа этого не допускает.
    """
    css = read_static("css", "ui.css")
    assert ":root.sidebar-collapsed .sidebar-drawer" in css, \
        "в ui.css нет правила сворачивания закреплённой панели"
    js = read_static("js", "mobile.js")
    assert "documentElement" in js and "sidebar-collapsed" in js, \
        "mobile.js не ставит класс состояния на <html>"


def test_pinned_sidebar_has_no_overlay():
    """Закреплённая панель ничего не перекрывает — затемнять фон незачем.

    Правило в index.html стояло до `.sidebar-overlay.active` при равной
    специфичности и потому проигрывало: на десктопе экран темнел.
    """
    css = read_static("css", "ui.css")
    block = re.search(r"@media\s*\(min-width:\s*1000px\)\s*\{(.+?)\n\}", css, re.S)
    assert block, "в ui.css нет медиазапроса закрепления панели"
    assert ".sidebar-overlay.active" in block.group(1), \
        "оверлей не погашен для закреплённой панели"


def test_collapsed_sidebar_frees_content_space():
    """Контент должен занимать место свёрнутой панели.

    margin-left задан инлайн в разметке, поэтому без !important правило не
    применяется и слева остаётся пустая полоса 240px.
    """
    css = read_static("css", "ui.css")
    block = re.search(r":root\.sidebar-collapsed\s+#mainContent[^}]*\}", css)
    assert block, "нет сброса отступа контента при свёрнутой панели"
    assert "!important" in block.group(0), \
        "инлайновый margin-left перебьёт правило без !important"


def test_queue_polling_skips_hidden_queue():
    """Опрос очереди раз в 3 секунды шёл даже на других разделах."""
    html = read_template("index.html")
    body = html.split("function startQueuePolling()", 1)[1].split("\n        }", 1)[0]
    assert "currentNav !== 'queue'" in body
    assert "document.hidden" in body


def test_queue_polling_started_once():
    html = read_template("index.html")
    assert html.count("startQueuePolling();") == 1


def test_remove_queue_task_checks_response():
    """Ошибка удаления показывалась как «Задача удалена»."""
    html = read_template("index.html")
    body = html.split("function removeQueueTask(", 1)[1].split("\n        }", 1)[0]
    assert "res.ok" in body


@pytest.mark.parametrize("fn", ["pauseQueue", "resumeQueue", "clearQueue"])
def test_queue_toolbar_checks_response(fn):
    """pause/resume/clear показывали успех даже при ошибке сервера.

    fetch отклоняется только на сетевом сбое, поэтому 500 попадал в then.
    """
    html = read_template("index.html")
    body = html.split(f"function {fn}(", 1)[1].split("\n        }", 1)[0]
    # Все три переведены на общий помощник, который проверяет res.ok.
    assert "queueAction(" in body, f"{fn} не проверяет ответ сервера"
    helper = html.split("function queueAction(", 1)[1].split("\n        }", 1)[0]
    assert "res.ok" in helper


def test_retry_failed_checks_each_response():
    """«Повторить ошибки» отчитывался об успехе, даже если сервер отверг всё."""
    html = read_template("index.html")
    body = html.split("function retryFailedQueueTasks(", 1)[1].split("\n        }", 1)[0]
    assert "res.ok" in body
    # Частичные задачи тоже нужно повторять.
    assert "'partial'" in body


def test_partial_status_is_rendered():
    """Частичный провал показывался как «Завершено» без кнопки повтора."""
    html = read_template("index.html")
    render = html.split("function renderQueue(", 1)[1].split("\n        function ", 1)[0]
    assert "partial:" in render, "нет метки статуса partial"
    assert "'partial'" in render, "partial не попадает в фильтр/кнопки"


def test_stuck_task_can_be_removed_from_ui():
    """У задачи в downloading не было ни «Отменить» (после отмены), ни «Удалить»."""
    html = read_template("index.html")
    render = html.split("function renderQueue(", 1)[1].split("\n        function ", 1)[0]
    actions = render.split('queue-item-actions', 1)[1]
    # Кнопка удаления больше не завязана на статус задачи.
    assert "task.status !== 'downloading' ? `<button onclick=\"removeQueueTask" not in actions
    assert "removeQueueTask" in actions


def test_queue_hides_main_content():
    """Очередь уезжала на высоту экрана вниз, и пользователь видел пустоту.

    Скрывались только внутренние блоки <main>, а сам <main> с min-height 100vh
    оставался в потоке документа.
    """
    html = read_template("index.html")
    body = html.split("function filterNav(", 1)[1].split("\n        function ", 1)[0]
    assert "mainContent" in body, "видимость <main> не переключается"
    branch = body.split("if (nav === 'queue')", 1)[1].split("} else {", 1)[0]
    assert "mainContent" in branch and "'none'" in branch, \
        "<main> не скрывается при показе очереди"


def test_paused_queue_is_announced():
    """Пауза упоминалась мелким серым текстом, и остановленная очередь
    выглядела как сломанная загрузка."""
    html = read_template("index.html")
    assert 'id="queuePausedBanner"' in html, "нет заметного предупреждения о паузе"
    assert ".queue-paused-banner" in html, "у предупреждения нет стилей"
    render = html.split("function renderQueue(", 1)[1].split("\n        function ", 1)[0]
    assert "queuePausedBanner" in render, "предупреждение не привязано к состоянию очереди"
    banner = render.split("queuePausedBanner", 1)[1][:400]
    # Показываем только когда есть что загружать: иначе баннер висел бы всегда.
    assert "waiting" in banner and "downloading" in banner, \
        "предупреждение не учитывает наличие незавершённых задач"


def test_removing_active_task_asks_first():
    """Удаление активной задачи теряет прогресс, поэтому спрашиваем."""
    html = read_template("index.html")
    body = html.split("function removeQueueTask(", 1)[1].split("\n        function ", 1)[0]
    code = re.sub(r"//.*", "", body)
    assert "confirm(" in code, "активная задача удаляется без подтверждения"
    assert "'downloading'" in code, "подтверждение не привязано к активной загрузке"
    # Обещать прерывание нельзя: в неотменяемом участке поток догрузит видео.
    assert "прерв" in code, "пользователя не предупреждают о судьбе загрузки"


def test_toast_count_is_limited():
    """Красные тосты копились без предела, пока сервер недоступен."""
    html = read_template("index.html")
    body = html.split("function showToast(", 1)[1].split("\n        function ", 1)[0]
    assert "TOAST_LIMIT" in body
    # Проверяем именно ранний выход: одного присваивания dataset.msg мало,
    # без сравнения с текстом дубли всё равно наслаиваются.
    assert re.search(r"dataset\.msg\s*===\s*msg[^\n]*return", body), \
        "повторные одинаковые тосты не отсекаются"


def test_priority_select_survives_polling():
    """Список приоритета закрывался сам через 3 секунды: список перерисовывался."""
    html = read_template("index.html")
    render = html.split("function renderQueue(", 1)[1].split("\n        function ", 1)[0]
    assert "queue-priority-select" in render.split("container.innerHTML", 1)[0], \
        "нет защиты от перерисовки во время выбора приоритета"


def test_queue_position_only_while_downloading():
    """У ожидающей задачи оставалось «Видео 11/79» из прошлой попытки."""
    html = read_template("index.html")
    render = html.split("function renderQueue(", 1)[1].split("\n        function ", 1)[0]
    position_line = next(ln for ln in render.splitlines() if "const position" in ln)
    tail = render.split("const position", 1)[1].split(";", 1)[0]
    assert "downloading" in position_line + tail


# --- Модалка выбора видео на странице канала ------------------------------

def test_channel_has_download_picker():
    html = read_template("channel.html")
    for marker in ("dlOverlay", "dlQuality", "dlFormat", "dlSelectAll", "dlSelectNone", "dlConfirm"):
        assert marker in html, f"нет элемента {marker}"


@pytest.mark.parametrize("quality", ["2160", "1440", "1080", "720", "480", "360"])
def test_channel_picker_offers_resolutions(quality):
    html = read_template("channel.html")
    assert f'value="{quality}"' in html


@pytest.mark.parametrize("container", ["mp4", "mkv", "webm"])
def test_channel_picker_offers_containers(container):
    html = read_template("channel.html")
    assert f'value="{container}"' in html


def test_channel_picker_builds_height_selector():
    """format_id конкретного видео нельзя переиспользовать для всей пачки."""
    html = read_template("channel.html")
    body = html.split("function buildFormatSelector(", 1)[1].split("\n    }", 1)[0]
    assert "bestvideo[height<=${quality}]+bestaudio/best" in body
    assert "bestaudio/best" in body


def test_channel_picker_opens_instead_of_direct_queue():
    """Раньше вся пачка уходила в очередь без выбора."""
    html = read_template("channel.html")
    body = html.split("async function fetchRemainingVideos(", 1)[1].split("\n    }", 1)[0]
    assert "dlOpen(videos)" in body
    assert "/api/queue/add" not in body


def test_channel_picker_escapes_titles():
    """Названия приходят с YouTube, поэтому только textContent."""
    html = read_template("channel.html")
    body = html.split("function dlRender(", 1)[1].split("\n    }", 1)[0]
    # Комментарии выкидываем: слово innerHTML упоминается в пояснении.
    code = re.sub(r"//.*", "", body)
    assert "innerHTML" not in code
    assert "textContent" in code


def test_player_requests_qualities_by_video_id():
    """Меню качества спрашивает список по идентификатору видео.

    Раньше в запрос уходил локальный путь /media/..., yt-dlp отвечал «is not a
    valid URL», и меню всегда показывало «Нет доступных форматов». Теперь список
    отдаёт сам сервер по /api/quality/<id>.
    """
    html = read_template("video.html")
    body = html.split("/api/quality/", 1)[1].split("catch", 1)[0]
    code = re.sub(r"//.*", "", body)
    assert "QUALITY_VIDEO_ID" in code, "идентификатор видео не передаётся"
    assert "video_url" not in code, "в запрос по-прежнему уходит локальный путь"


def test_player_quality_switch_changes_source():
    """Выбор качества обязан переключать файл, а не только менять подпись.

    Прежняя кнопка показывала «Перезагрузите страницу для применения» и ничего
    не делала: пересобранных файлов тогда просто не было.
    """
    html = read_template("video.html")
    code = re.sub(r"//.*", "", html)
    assert "selectQuality" not in code, "остался неработающий переключатель качества"
    body = code.split("function applyQuality", 1)[1].split("\n            }", 1)[0]
    assert "video.src" in body, "источник видео не переключается"


def test_index_has_url_download_controls():
    """На главной обязаны быть поле ссылки и кнопка загрузки.

    Разметку однажды потеряли при переписывании главной страницы: CSS для
    .url-input и .download-btn остался, а самого поля не было — скачать видео
    по ссылке через интерфейс стало нечем.
    """
    html = read_template("index.html")
    assert 'id="urlInput"' in html, "нет поля ввода ссылки"
    assert 'id="downloadBtn"' in html, "нет кнопки загрузки"
    assert 'class="header-center"' in html, "в хедере нет блока с полем"
    assert "function startDownload(" in html, "нет обработчика загрузки"
    assert "/api/queue/add" in html, "кнопка ни к чему не обращается"


def test_index_download_button_is_wired():
    """Кнопка и поле должны быть связаны с обработчиком.

    Осиротевшая функция уже была: addToQueue существовала, но её никто не
    вызывал, поэтому кнопки в интерфейсе не работали бы вовсе.
    """
    html = read_template("index.html")
    assert re.search(r'id="downloadBtn"[^>]*onclick="startDownload\(\)"', html), \
        "кнопка не вызывает startDownload"
    # Enter в поле тоже должен запускать загрузку.
    listener = html.split("getElementById('urlInput')?.addEventListener", 1)
    assert len(listener) == 2, "нет обработчика клавиш для поля ссылки"
    handler = listener[1][:300]
    assert "startDownload()" in handler, "Enter не запускает загрузку"
    assert "'Enter'" in handler, "загрузка привязана не к Enter"


def test_index_validates_url_before_queue():
    """Мусор не должен уходить в очередь: ошибку показываем сразу."""
    html = read_template("index.html")
    body = html.split("async function startDownload(", 1)[1].split("\n        }", 1)[0]
    code = re.sub(r"//.*", "", body)
    assert "isSupportedVideoUrl" in code, "ссылка не проверяется"
    assert "buildFormatSelector" in code, "качество не учитывается"
    assert "function isSupportedVideoUrl(" in html, "нет функции проверки ссылки"


def test_index_accepts_youtube_and_tiktok_urls():
    """Клиентская проверка не должна отбрасывать поддерживаемый TikTok."""
    html = read_template("index.html")
    assert "TikTok" in html
    assert "vm.tiktok.com" in html
    assert "vt.tiktok.com" in html
    assert "parts[0].startsWith('@')" in html
    assert "TikTok отдаёт единый поток" in html
    assert "buildFormatSelector(quality, url)" in html


def test_index_url_field_survives_mobile_width():
    """На узком экране поле ссылки должно оставаться доступным.

    В мобильной версии .header-center скрывался целиком (display: none), и на
    телефоне скачать видео по ссылке было невозможно.
    """
    html = read_template("index.html")
    media = html.split("@media (max-width: 760px)", 1)
    assert len(media) == 2, "нет мобильного блока стилей"
    rules = media[1].split("}", 20)
    mobile_css = "}".join(rules[:12])
    assert not re.search(r"\.header-center\s*\{[^}]*display:\s*none", mobile_css), \
        "поле ссылки снова скрыто на мобильной ширине"


def test_index_has_no_direct_download_leftovers():
    """Прямое скачивание не делаем: не должно остаться ни кнопки, ни стилей."""
    html = read_template("index.html")
    assert "direct-btn" not in html, "остался стиль кнопки прямого скачивания"
    assert "directDownload" not in html, "остался обработчик прямого скачивания"


def test_index_links_to_upload_page():
    """Страница /upload существовала, но попасть на неё из интерфейса было нельзя."""
    html = read_template("index.html")
    assert 'href="/upload"' in html, "в навигации нет ссылки на загрузку своего файла"


# ================= Разделы настроек =================

# Разделы страницы настроек: значение вкладки и обязательный заголовок.
SETTINGS_TABS = (("profile", "Профиль"), ("storage", "Хранение"),
                 ("download", "Загрузка"), ("network", "Сеть"))


def test_settings_has_three_sections():
    """Настройки разделены на Профиль, Хранение, Загрузку и Сеть.

    Раньше это была одна простыня из четырёх секций, причём «Обслуживание»
    (плагины) стояло отдельно от «Загрузки с YouTube», хотя относится к ней.
    """
    html = read_template("settings.html")
    for tab, title in SETTINGS_TABS:
        assert f'data-tab="{tab}"' in html, f"нет вкладки {tab}"
        assert title in html, f"нет заголовка раздела {title}"


def test_settings_tabs_have_panels():
    """Каждой кнопке раздела должна соответствовать панель с содержимым."""
    html = read_template("settings.html")
    for tab, _ in SETTINGS_TABS:
        assert f'id="panel-{tab}"' in html, f"нет панели для раздела {tab}"


def test_settings_tab_switching_is_wired():
    """Переключение разделов должно работать без перезагрузки страницы.

    Проверяем именно навешивание обработчика: наличие функции showTab ни о чём
    не говорит, если её никто не вызывает по клику. Разметка без обработчика
    выглядит рабочей, но кнопки не переключают разделы.
    """
    html = read_template("settings.html")
    assert "function showTab(" in html, "нет функции переключения разделов"
    listener = re.search(
        r"querySelectorAll\(['\"]\.tab-btn['\"]\)[\s\S]{0,240}?"
        r"addEventListener\(\s*['\"]click['\"][\s\S]{0,120}?showTab\(",
        html)
    assert listener, "клик по кнопке раздела не вызывает showTab"


def test_settings_storage_has_all_path_fields():
    """Раздел «Хранение» должен позволять задать все пути.

    Баннеры, метаданные каналов и свои видео раньше были зашиты в коде и
    настройке не поддавались вовсе.
    """
    html = read_template("settings.html")
    for field in ("video_dir", "avatars_dir", "banners_dir", "meta_dir",
                  "playlists_dir", "subtitles_dir", "uservideos_dir"):
        assert f'data-path="{field}"' in html, f"нет поля для {field}"


def test_settings_storage_calls_api():
    """Пути должны сохраняться на сервер: localStorage тут бесполезен."""
    html = read_template("settings.html")
    assert "/api/storage" in html, "нет обращения к /api/storage"
    assert "function loadStorage(" in html, "пути не загружаются с сервера"
    # Объявление функции содержит 'loadStorage(' само, поэтому ищем вызов
    # отдельной строкой: без него поля остались бы пустыми при открытии.
    calls = re.findall(r"^\s*loadStorage\(\);\s*$", html, re.M)
    assert calls, "загрузка путей объявлена, но не вызывается"


def test_settings_storage_reports_errors():
    """Недоступный путь — частый случай (нет диска, нет прав).

    Пользователь должен видеть причину, иначе решит, что кнопка не работает.
    """
    html = read_template("settings.html")
    body = html.split("async function saveStorage(", 1)
    assert len(body) == 2, "нет функции сохранения путей"
    code = body[1].split("\n        }", 1)[0]
    assert "data.error" in code, "ошибка сервера не показывается"
    assert "res.ok" in code, "код ответа не проверяется"


def test_settings_storage_shows_resolved_paths():
    """Относительный 'videos' не объясняет, где лежат файлы."""
    html = read_template("settings.html")
    assert "resolved" in html, "абсолютные пути не показываются"


def test_settings_keeps_maintenance_in_download_section():
    """Плагины и статус — часть загрузки, а не отдельный раздел.

    Проверяем, что кнопки обслуживания попали именно в панель «Загрузка».
    """
    html = read_template("settings.html")
    panel = html.split('id="panel-download"', 1)
    assert len(panel) == 2, "нет панели раздела «Загрузка»"
    # Панель кончается там, где начинается скрипт: секций внутри несколько,
    # поэтому резать по первому </section> нельзя.
    body = panel[1].split("<script", 1)[0]
    for control in ("authCheck", "authRefresh", "cookieBrowser", "importFromBrowser"):
        assert control in body, f"{control} вне раздела «Загрузка»"
    # Управление профилем не должно оказаться в разделе загрузки.
    assert 'id="username"' not in body, "поле профиля попало в раздел «Загрузка»"


# ===== Свои плейлисты (UI) =====


def render_video_page(is_short, is_owner=True):
    """Собирает страницу видео с минимальным контекстом.

    Нужен, чтобы проверять итоговый HTML, а не текст шаблона: ветки
    {% if is_short %} вложены друг в друга и разбор строками ошибается.
    """
    env = template_env()
    env.globals["url_for"] = lambda endpoint, **kw: "/" + endpoint + "/" + str(kw.get("filename", ""))
    template = env.get_template("video.html")
    return template.render(
        folder="f", author="a", meta={"title": "T", "uploader": "a"},
        video_url="/media/x.mp4", mime_type="video/mp4", video_id="abc123",
        author_avatar=None, subtitles=[], related=[], description="",
        theme="dark", config={}, is_short=is_short,
        shorts_feed=[{"id": "s1", "title": "S", "author": "a", "size_mb": 1, "url": "s.mp4"}],
        collection_id="", collection_order=[], is_owner=is_owner,
    )


def test_video_page_has_save_to_collection_button():
    """Кнопка сохранения нужна на обычной странице видео."""
    html = read_template("video.html")
    assert 'id="saveToCollectionBtn"' in html, "нет кнопки сохранения в плейлист"
    assert "openCollectionModal" in html, "кнопка ни к чему не привязана"


def test_video_page_save_button_is_outside_shorts_branch():
    """Кнопка должна быть в ветке обычного видео, а не только в Shorts.

    Раньше блок случайно попал внутрь {% if is_short %} и на обычных
    страницах кнопки не было вообще.
    """
    # Рендерим обе ветки: разбор текста шаблона путается во вложенных {% if %}.
    normal = render_video_page(is_short=False)
    shorts = render_video_page(is_short=True)
    assert 'id="saveToCollectionBtn"' in normal, (
        "кнопки сохранения нет на обычной странице видео"
    )
    assert "short-save-btn" in shorts, "в ленте Shorts нет кнопок сохранения"
    # Окно выбора нужно в обоих режимах, иначе кнопка ничего не откроет.
    for name, html in (("обычное видео", normal), ("Shorts", shorts)):
        assert 'id="collectionModal"' in html, f"{name}: нет окна выбора плейлиста"


def test_video_page_shorts_have_their_own_save_buttons():
    """В ленте Shorts у каждого ролика своя кнопка со своим id."""
    html = read_template("video.html")
    assert "short-save-btn" in html, "нет кнопки сохранения в ленте Shorts"
    assert 'data-video-id="{{ s.id }}"' in html, (
        "кнопка Shorts не передаёт id ролика, сохранялось бы не то видео"
    )


def test_video_page_modal_markup_precedes_script_usage():
    """Окно выбора плейлиста должно существовать к моменту getElementById.

    Разметка после </script> давала null и кнопка молча не работала.
    """
    html = read_template("video.html")
    # Ищем именно вызов, а не подстроку: опечатка в имени метода дала бы
    # ReferenceError, а проверка на вхождение её бы не заметила.
    call = re.search(r"document\.body\.insertAdjacentHTML\(\s*'beforeend'", html)
    assert call, "разметка окна не вставляется вызовом insertAdjacentHTML"
    lookup = html.find("getElementById('collectionModal')")
    assert lookup != -1, "скрипт не ищет окно по id"
    assert call.start() < lookup, "элемент ищется раньше, чем создаётся"
    # В самой вставляемой разметке должны быть все части окна.
    inserted = html[call.end():html.find("`);", call.end())]
    for part in ('id="collectionModal"', 'id="collectionList"', 'id="collectionCreate"'):
        assert part in inserted, f"вставляемая разметка без {part}"


def test_video_page_modal_has_all_controls():
    """Создание, «Смотреть позже», закрытие и место для ошибок."""
    html = read_template("video.html")
    for control in ("collectionList", "collectionNewTitle", "collectionCreate",
                    "watchLaterBtn", "collectionModalClose", "collectionModalStatus"):
        assert control in html, f"в окне нет {control}"


def test_video_page_renders_collection_titles_as_text():
    """Название плейлиста задаёт пользователь: кавычка не должна ломать разметку."""
    html = read_template("video.html")
    block = html.split("function renderCollections", 1)
    assert len(block) == 2, "нет отрисовки списка плейлистов"
    body = block[1].split("async function", 1)[0]
    assert "textContent" in body, "название вставляется без экранирования"
    assert "innerHTML" not in body, "innerHTML с названием от пользователя"


def test_video_page_reverts_checkbox_on_error():
    """Если сервер отказал, галочка не должна врать о состоянии."""
    html = read_template("video.html")
    body = html.split("async function toggleInCollection", 1)[1].split("\n        }", 1)[0]
    assert "box.checked = !wanted" in body, "галочка не возвращается после ошибки"


def test_index_sidebar_lists_collections():
    """Плейлисты и кнопка создания есть в боковом меню главной."""
    html = read_template("index.html")
    assert 'id="sidebarCollections"' in html, "нет места под список плейлистов"
    assert 'id="createCollectionBtn"' in html, "нет кнопки создания плейлиста"
    assert "loadSidebarCollections();" in html, "список не загружается при открытии"


def test_index_sidebar_collections_use_text_content():
    """Название плейлиста в меню - тоже текст, не HTML."""
    html = read_template("index.html")
    body = html.split("async function loadSidebarCollections", 1)[1].split("document.getElementById('createCollectionBtn')", 1)[0]
    assert "label.textContent" in body, "название вставляется без экранирования"


def test_collection_page_has_actions():
    """На странице плейлиста: просмотр, переименование, удаление, снятие видео."""
    html = read_template("collection.html")
    for control in ("playAllBtn", "renameBtn", "deleteBtn", "data-remove", "videoList"):
        assert control in html, f"на странице плейлиста нет {control}"


def test_collection_page_hides_edit_for_built_in():
    """«Смотреть позже» нельзя переименовать или удалить."""
    html = read_template("collection.html")
    assert "built_in_id" in html, "встроенный плейлист не отличается от своих"
    guard = html.split("collection.id != built_in_id", 1)
    assert len(guard) == 2, "нет проверки на встроенный плейлист"
    body = guard[1].split("{% endif %}", 1)[0]
    assert "renameBtn" in body and "deleteBtn" in body, (
        "кнопки правки не спрятаны для встроенного плейлиста"
    )


def test_collection_page_remove_button_stops_navigation():
    """Кнопка стоит внутри ссылки: без preventDefault был бы переход на видео."""
    html = read_template("collection.html")
    body = html.split("data-remove]", 1)[1].split("function renumber", 1)[0]
    assert "preventDefault" in body, "клик по кнопке уводил бы со страницы"


def test_video_page_plays_playlist_in_order():
    """Кнопка «Смотреть» ведёт по плейлисту: нужен переход после конца видео.

    Параметр ?collection= уже добавлялся в ссылку, но никто его не читал и
    следующее видео не включалось.
    """
    html = read_template("video.html")
    assert "collection_order" in html, "порядок видео не приходит на страницу"
    assert "addEventListener('ended'" in html, "нет перехода после конца видео"
    body = html.split("PLAYLIST_ORDER.indexOf", 1)
    assert len(body) == 2, "текущее видео не ищется в списке"
    tail = body[1].split("// ===== Сохранение", 1)[0]
    assert "at + 1" in tail, "следующее видео не выбирается"
    assert "collection=" in tail, "параметр плейлиста теряется при переходе"


def test_video_page_playlist_strip_is_built_as_text():
    """Подпись плейлиста собирается через textContent, без вставки HTML."""
    html = read_template("video.html")
    tail = html.split("id = 'playlistStrip'", 1)[1].split("// ===== Сохранение", 1)[0]
    assert "info.textContent" in tail, "подпись вставляется без экранирования"
    assert "innerHTML" not in tail, "innerHTML в блоке плейлиста"


def test_watch_route_always_passes_playlist_vars(app_module):
    """Без этих переменных шаблон падает на tojson от Undefined.

    Проверено на практике: рендер без collection_id обрывался TypeError.
    """
    import inspect

    source = inspect.getsource(app_module.watch)
    for name in ("collection_id=", "collection_order="):
        assert name in source, f"роут /watch не передаёт {name}"


CLOSING_SCRIPT_TAG = "</" + "script>"


@pytest.mark.parametrize("name", TEMPLATE_FILES)
def test_inline_script_bodies_have_no_literal_closing_tag(name):
    """Закрывающий тег скрипта в тексте кода обрывает скрипт прямо там.

    Реальный случай: комментарий, где этот тег был написан словами, закончил
    блок раньше времени. Весь остаток кода попал на страницу как текст, кнопка
    молча перестала работать, и в консоли не было ни одной ошибки.
    """
    html = read_template(name)
    for match in re.finditer(r"<script(?![^>]*\ssrc=)[^>]*>", html):
        start = match.end()
        end = html.find(CLOSING_SCRIPT_TAG, start)
        assert end != -1, f"{name}: незакрытый блок скрипта"
        # Браузер закрывает блок на первом же таком теге, поэтому сравнивать
        # надо не «есть ли тег в теле» (он и есть граница), а стоит ли граница
        # там, где мы её задумали: перед ней должен идти отступ, а не код.
        line = html[html.rfind("\n", 0, end) + 1:end]
        assert line.strip() == "", (
            f"{name}: блок скрипта обрывается посреди кода на строке "
            f"{html[:end].count(chr(10)) + 1}: {line.strip()[:60]!r}"
        )


def test_collection_page_uses_user_media_for_own_videos():
    """Превью /api/thumbnail есть только у видео с YouTube."""
    html = read_template("collection.html")
    assert "/usermedia/" in html, "для своих видео нет пути к превью"
    assert "/api/thumbnail/" in html, "для видео с YouTube нет превью"


# ================= Раздел «Сеть» и гостевой режим =================

def render_index_page(is_owner):
    """Собирает главную с минимальным контекстом."""
    env = template_env()
    env.globals["url_for"] = lambda endpoint, **kw: (
        "/watch/" + str(kw.get("vid_id", "")) if endpoint == "watch"
        else "/" + endpoint + "/" + str(kw.get("filename", ""))
    )
    return env.get_template("index.html").render(
        all_videos=[{"id": "v1", "title": "T", "author": "a", "size_mb": 1,
                     "thumb": None, "folder": "f", "author_avatar": None,
                     "duration": 0}],
        shorts=[], authors=[{"name": "a", "avatar": None}], playlists=[],
        user_videos=[], hidden_channels=[], favorites=[], watch_history=[],
        is_owner=is_owner,
    )


def render_channel_page(is_owner):
    """Собирает страницу канала с минимальным контекстом."""
    env = template_env()
    env.filters["human_date"] = lambda v: v or ""
    env.filters["human_duration"] = lambda v: ""
    return env.get_template("channel.html").render(
        author="a", author_avatar=None, banner_url=None,
        videos=[], playlists=[], authors=[], is_hidden=False,
        total_videos=0, total_shorts=0, channel_url="https://x",
        description="", subscribers="", country="", joined_date="",
        sync_status={"status": "never"}, is_owner=is_owner,
    )


# ===== Языки аудиодорожек и субтитров =====


def download_panel():
    """Разметка раздела «Загрузка» без остальной страницы.

    Панель кончается там, где начинается скрипт: секций внутри несколько,
    поэтому резать по первому </section> нельзя.
    """
    html = read_template("settings.html")
    parts = html.split('id="panel-download"', 1)
    assert len(parts) == 2, "нет панели раздела «Загрузка»"
    return parts[1].split("<script", 1)[0]


def test_settings_download_has_language_controls():
    """Выбор языка озвучки и субтитров живёт в разделе «Загрузка».

    Раньше язык аудиодорожки выбрать было нельзя вовсе, а язык субтитров
    вводился текстовым полем на странице каждого видео по одному разу.
    """
    panel = download_panel()
    for element in ("audioLangs", "subtitlesEnabled", "subtitleLangs", "subtitlesAuto"):
        assert f'id="{element}"' in panel, f"нет элемента {element} в разделе «Загрузка»"


def test_settings_language_lists_allow_multiple():
    """Языков может быть несколько: приоритет дорожек и набор субтитров."""
    panel = download_panel()
    for element in ("audioLangs", "subtitleLangs"):
        block = panel.split(f'id="{element}"', 1)[1][:200]
        assert "multiple" in block, f"{element} не позволяет выбрать несколько языков"


def test_settings_language_options_come_from_server():
    """Список языков не должен дублироваться в шаблоне.

    Две копии разъезжаются: в настройках оказывался бы язык, которого не знает
    ни загрузчик, ни подписи дорожек.
    """
    html = read_template("settings.html")
    assert "/api/download/prefs" in html, "нет обращения к настройкам загрузки"
    assert "data.languages" in html, "список языков не берётся с сервера"
    panel = download_panel()
    assert '<option value="ru"' not in panel, "язык зашит в разметку"


def test_settings_download_prefs_are_loaded_and_saved():
    """Значения должны и читаться при открытии, и уходить на сервер."""
    html = read_template("settings.html")
    assert "async function loadDownloadPrefs(" in html, "настройки загрузки не читаются"
    assert re.search(r"^\s*loadDownloadPrefs\(\);\s*$", html, re.M), \
        "чтение объявлено, но не вызывается"
    save = html.split("async function saveDownloadPrefs(", 1)
    assert len(save) == 2, "нет функции сохранения настроек загрузки"
    code = save[1].split("\n        }", 1)[0]
    assert "method:'POST'" in code.replace(" ", "") or "method: 'POST'" in code, \
        "настройки не отправляются на сервер"


def test_settings_download_prefs_saved_by_main_button():
    """Кнопка «Сохранить настройки» одна: отдельная кнопка тут только запутает."""
    html = read_template("settings.html")
    handler = html.split("$('save').addEventListener", 1)
    assert len(handler) == 2, "нет обработчика кнопки сохранения"
    assert "saveDownloadPrefs(" in handler[1][:800], \
        "кнопка сохранения не сохраняет языки"


def test_settings_download_prefs_report_errors():
    """Недопустимый код языка сервер отвергает: причину надо показать."""
    html = read_template("settings.html")
    code = html.split("async function saveDownloadPrefs(", 1)[1].split("\n        }", 1)[0]
    assert "error" in code, "ошибка сервера не показывается"


def test_settings_has_network_section():
    """Раздел «Сеть» должен показывать адреса, PIN и тумблер доступа."""
    html = read_template("settings.html")
    for element in ("netAddresses", "netPin", "netEnabled", "netShowQr",
                    "netRegenPin", "netServers", "netScan", "netAddServer"):
        assert f'id="{element}"' in html, f"нет элемента {element}"


def test_settings_network_calls_api():
    """Каждая кнопка раздела должна обращаться к своему эндпоинту."""
    html = read_template("settings.html")
    for url in ("/api/network/info", "/api/network/qr", "/api/network/enabled",
                "/api/network/pin/regenerate", "/api/network/servers",
                "/api/network/check", "/api/network/scan"):
        assert url in html, f"раздел «Сеть» не обращается к {url}"


def test_settings_network_controls_are_wired():
    """Разметка без обработчика — мёртвая кнопка."""
    html = read_template("settings.html")
    for element in ("netEnabled", "netShowQr", "netRegenPin", "netAddServer", "netScan"):
        assert f"$('{element}').addEventListener" in html, f"{element} без обработчика"


def test_settings_network_reverts_toggle_on_error():
    """Если сервер не принял тумблер, галочка не должна остаться сдвинутой."""
    html = read_template("settings.html")
    start = html.index("$('netEnabled').addEventListener")
    body = html[start:html.index("$('netShowQr')", start)]
    assert "event.target.checked = !enabled" in body, (
        "интерфейс покажет состояние, которого на сервере нет"
    )


def test_settings_network_renders_addresses_as_text():
    """Адреса и названия серверов вставляем текстом, а не разметкой."""
    html = read_template("settings.html")
    start = html.index("function renderServers(")
    body = html[start:html.index("async function loadNetwork(", start)]
    assert "textContent" in body, "названия серверов вставляются как разметка"
    assert "innerHTML" not in body, "в списке серверов есть innerHTML"


def test_settings_pin_change_asks_confirmation():
    """Смена PIN отключает устройства — без подтверждения это ловушка."""
    html = read_template("settings.html")
    start = html.index("$('netRegenPin').addEventListener")
    body = html[start:start + 700]
    assert "confirm(" in body, "PIN меняется без подтверждения"


def test_index_marks_owner_flag():
    """Страница должна знать роль: от неё зависит показ кнопок владельца."""
    assert "IS_OWNER = true" in render_index_page(is_owner=True)
    assert "IS_OWNER = false" in render_index_page(is_owner=False)


def test_index_hides_owner_controls_from_guest():
    """Гостю не нужны поле загрузки, очередь, настройки и плейлисты."""
    guest = render_index_page(is_owner=False)
    owner = render_index_page(is_owner=True)
    for element in ('id="urlInput"', 'id="downloadBtn"', 'data-nav="queue"',
                    'href="/upload"', 'id="createCollectionBtn"',
                    'id="sidebarCollections"', 'id="hiddenChannelsList"'):
        assert element in owner, f"у владельца пропал {element}"
        assert element not in guest, f"гость видит {element}"


def test_index_offers_guest_search_and_unlock():
    """Взамен гость получает поиск по библиотеке и вход по PIN."""
    guest = render_index_page(is_owner=False)
    assert 'id="searchInput"' in guest, "гостю нечем искать видео"
    assert 'id="guestUnlockBtn"' in guest, "гость не может войти по PIN"
    assert "/api/network/unlock" in guest, "кнопка входа ни к чему не привязана"


def test_index_search_field_is_used_by_filter():
    """Поле поиска должно влиять на фильтр, иначе оно декоративное."""
    html = read_template("index.html")
    start = html.index("function applyFilters(")
    body = html[start:start + 900]
    assert "searchInput" in body, "фильтр не читает поле поиска"


def test_guest_keeps_own_data_locally():
    """Гость ведёт своё избранное у себя: данные владельца не трогаются."""
    html = read_template("index.html")
    start = html.index("async function loadUserData(")
    body = html[start:html.index("async function loadSidebarCollections(", start)]
    assert "if (!IS_OWNER)" in body, "гость пойдёт за данными владельца"
    assert "GUEST_FAV_KEY" in body, "гостевое избранное негде хранить"


def test_guest_writes_only_to_own_storage_keys():
    """Гость не должен писать в ключи владельца.

    Именно так и обнаружился дефект: гость складывал избранное в lt_favorites, а
    перенос старых данных отправлял этот ключ на сервер при первом входе по PIN —
    избранное гостя оказывалось у владельца.
    """
    html = read_template("index.html")
    start = html.index("function saveUserDataLocally(")
    body = html[start:html.index("async function pushUserData(", start)]
    guest_branch = body[body.index("if (!IS_OWNER)"):body.index("return;")]
    for owner_key in ("'lt_favorites'", "'lt_history'", "'lt_hidden_channels'"):
        assert owner_key not in guest_branch, f"гость пишет в ключ владельца {owner_key}"
    assert "GUEST_FAV_KEY" in guest_branch and "GUEST_HISTORY_KEY" in guest_branch, (
        "гостю некуда сохранить своё избранное"
    )


def test_guest_storage_keys_differ_from_owner():
    """Ключи гостя и владельца не должны совпадать."""
    html = read_template("index.html")
    for line in html.splitlines():
        if "GUEST_FAV_KEY =" in line:
            assert "'lt_favorites'" not in line, "ключ гостя совпал с ключом владельца"
        if "GUEST_HISTORY_KEY =" in line:
            assert "'lt_history'" not in line, "ключ гостя совпал с ключом владельца"


def test_video_page_guest_history_uses_own_key():
    """История гостя на странице видео — тоже в отдельном ключе."""
    html = read_template("video.html")
    start = html.index("function markCurrentVideoWatched(")
    body = html[start:start + 1000]
    guest_branch = body[body.index("if (!IS_OWNER)"):]
    assert "lt_guest_history" in guest_branch, "гость пишет историю в ключ владельца"
    assert "setItem('lt_history'" not in guest_branch


def test_video_page_guest_cannot_hide_channels():
    """Скрытие каналов — настройка владельца, у гостя она не должна срабатывать."""
    html = read_template("video.html")
    start = html.index("async function toggleHideChannel(")
    body = html[start:start + 400]
    assert "if (!IS_OWNER) return;" in body, (
        "при сбое запроса список владельца перезапишется из браузера гостя"
    )


def test_video_page_hides_owner_controls_from_guest():
    """На странице видео гостю нечего скрывать, править и качать."""
    guest = render_video_page(is_short=False, is_owner=False)
    owner = render_video_page(is_short=False, is_owner=True)
    for element in ('id="hideChannelBtn"', 'id="saveToCollectionBtn"',
                    'id="downloadAudioBtn"', 'class="download-file-btn"'):
        assert element in owner, f"у владельца пропал {element}"
        assert element not in guest, f"гость видит {element}"


def test_video_page_hides_shorts_save_button_from_guest():
    # Ищем именно разметку кнопки: само имя класса встречается ещё и в
    # querySelectorAll, поэтому проверка по подстроке класса всегда проходила бы.
    button = 'class="short-btn short-save-btn"'
    assert button in render_video_page(is_short=True, is_owner=True)
    assert button not in render_video_page(is_short=True, is_owner=False), (
        "гость видит кнопку сохранения в Shorts"
    )


def test_video_page_guest_does_not_write_owner_history():
    """Просмотр гостя не должен уходить в историю владельца."""
    guest = render_video_page(is_short=False, is_owner=False)
    assert "IS_OWNER = false" in guest
    html = read_template("video.html")
    start = html.index("function markCurrentVideoWatched(")
    body = html[start:start + 900]
    assert "if (!IS_OWNER)" in body, "гость пишет в историю владельца"


def test_channel_page_hides_owner_controls_from_guest():
    """Обновление канала качает файлы: гостю панель недоступна."""
    guest = render_channel_page(is_owner=False)
    owner = render_channel_page(is_owner=True)
    for element in ('id="syncButton"', 'id="downloadRemaining"',
                    'id="hideChannelBtn"', 'href="/settings"'):
        assert element in owner, f"у владельца пропал {element}"
        assert element not in guest, f"гость видит {element}"


def test_channel_sync_code_survives_missing_panel():
    """Скрытая панель не должна ронять остальной скрипт страницы."""
    html = read_template("channel.html")
    start = html.index("function renderSyncStatus(")
    body = html[start:html.index("async function loadSyncStatus(", start)]
    assert "if (!statusEl" in body, "рендер статуса упадёт без панели"
    assert "getElementById('syncButton')?" in html or "if (!button) return" in body, (
        "обработчик кнопки синхронизации упадёт без кнопки"
    )


MOBILE_CSS_LINK = "/static/css/mobile.css"


@pytest.mark.parametrize("name", TEMPLATE_FILES)
def test_mobile_css_is_loaded_after_inline_styles(name):
    """mobile.css должна подключаться после инлайновых <style> шаблона.

    Правила в шаблоне и в mobile.css имеют одинаковую специфичность, поэтому
    побеждает последний. Когда ссылка стояла перед <style>, мобильные правила
    молча проигрывали: кнопки плеера оставались 38x34 вместо 40x40, поле языка
    субтитров — 80px вместо всей ширины, а сетка блоков на странице видео
    получала двойной отступ и разъезжалась.
    """
    html = read_template(name)
    if MOBILE_CSS_LINK not in html:
        pytest.skip(f"{name} не подключает mobile.css")
    link_pos = html.index(MOBILE_CSS_LINK)
    # Инлайновые <style> в <head>: только они конкурируют с mobile.css.
    head = html[:html.index("</head>")] if "</head>" in html else html
    style_positions = [m.start() for m in re.finditer(r"<style>", head)]
    late = [pos for pos in style_positions if pos > link_pos]
    assert not late, (
        f"{name}: <style> идёт после mobile.css — мобильные правила будут перебиты"
    )


@pytest.mark.parametrize("name", TEMPLATE_FILES)
def test_mobile_css_has_no_hardcoded_theme_colors(name):
    """На мобильной вёрстке нельзя подменять цвета темы хардкодом."""
    css_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "css", "mobile.css"
    )
    with open(css_path, encoding="utf-8") as fh:
        css = fh.read()
    # var(--yt-card-bg, #1f1f1f) в светлой теме делал блоки тёмными: fallback
    # срабатывал там, где переменная не объявлена шаблоном.
    bad = re.findall(r"var\(\s*--yt-[\w-]+\s*,\s*#[0-9a-fA-F]{3,6}\s*\)", css)
    assert not bad, f"mobile.css: цветной fallback ломает светлую тему: {bad}"


def test_mobile_keeps_quality_control_reachable():
    """Кнопку настроек (там выбор качества) нельзя прятать на телефоне.

    Раньше media-запрос скрывал первые три кнопки справа, и на 360px из ряда
    выпадали и «картинка в картинке», и настройки — качество на телефоне было
    не переключить вовсе.
    """
    css_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "css", "mobile.css"
    )
    with open(css_path, encoding="utf-8") as fh:
        css = fh.read()
    hidden = re.findall(r"\.controls-right \.control-btn:nth-child\((\d+)\)", css)
    # settingsBtn — пятая кнопка, fullscreenBtn — шестая.
    assert "5" not in hidden, "скрыта кнопка настроек: качество не переключить"
    assert "6" not in hidden, "скрыта кнопка полного экрана"


def test_mobile_card_actions_are_visible_on_touch():
    """На тач-экране кнопки карточки должны быть видны без наведения.

    При opacity: 0 «в избранное» и «копировать ссылку» были недостижимы с
    телефона: hover там не воспроизводится.
    """
    css_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "css", "mobile.css"
    )
    with open(css_path, encoding="utf-8") as fh:
        css = fh.read()
    assert re.search(r"\.card-actions\s*\{[^}]*opacity:\s*1", css), (
        "кнопки на карточках остаются прозрачными на телефоне"
    )
