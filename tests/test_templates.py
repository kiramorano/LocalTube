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
    body = html[start:start + 1600]
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
