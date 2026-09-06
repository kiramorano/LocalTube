"""Тесты локализации интерфейса: русский и английский.

Раньше все подписи были вписаны в шаблоны по-русски, поэтому английский язык
означал бы правку девяти файлов вручную и вторую копию каждой страницы.

Ключ перевода — сама русская строка (как msgid в gettext). Так ничего не
теряется при опечатке в ключе: непереведённая строка показывается по-русски, а
не пустым местом или технической строкой вида settings.title.

Главное, что проверяют эти тесты: словарь и шаблоны не расходятся. Строка,
пропущенная в словаре, выглядит рабочей в русском интерфейсе и всплывает
русским текстом посреди английского.
"""
import json
import os
import re

import pytest

import i18n

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "templates")


def read_template(name):
    with open(os.path.join(TEMPLATES_DIR, name), encoding="utf-8") as f:
        return f.read()


# ================= Языки =================

def test_supported_languages_are_russian_and_english():
    assert i18n.LANGUAGES == ("ru", "en")


def test_default_language_is_russian():
    """Проект писался по-русски: смена языка по умолчанию удивила бы."""
    assert i18n.DEFAULT_LANG == "ru"


def test_unknown_language_falls_back_to_default():
    """Мусор в cookie не должен приводить к пустому интерфейсу."""
    assert i18n.normalize_lang("de") == "ru"
    assert i18n.normalize_lang("") == "ru"
    assert i18n.normalize_lang(None) == "ru"
    assert i18n.normalize_lang("EN") == "en", "регистр не учитывается"
    assert i18n.normalize_lang("en-US") == "en", "региональный код не распознан"


# ================= Перевод строк =================

def test_russian_returns_source_string():
    """Для русского словарь не нужен: ключ и есть перевод."""
    assert i18n.translate("Настройки", "ru") == "Настройки"


def test_english_uses_dictionary():
    assert i18n.translate("Настройки", "en") == "Settings"


def test_missing_key_returns_source_string():
    """Пропущенная строка показывается по-русски, а не пустым местом."""
    assert i18n.translate("Такой строки нет в словаре", "en") == "Такой строки нет в словаре"


def test_translate_keeps_whitespace_around_text():
    """В HTML текст часто идёт с отступами: их нельзя терять при переводе."""
    assert i18n.translate("  Настройки\n", "en") == "  Settings\n"


def test_translate_handles_non_string():
    """Число из шаблона переводить нечего, но падать нельзя."""
    assert i18n.translate(None, "en") is None
    assert i18n.translate(5, "en") == 5


# ================= Словарь =================

def test_dictionary_is_valid_json():
    data = i18n.load_dictionary("en")
    assert isinstance(data, dict) and data, "словарь пуст"


def test_dictionary_values_are_strings():
    for key, value in i18n.load_dictionary("en").items():
        assert isinstance(value, str), f"перевод {key!r} не строка"


def test_dictionary_has_no_empty_translations():
    """Пустой перевод хуже отсутствующего: строка исчезает из интерфейса."""
    empty = [k for k, v in i18n.load_dictionary("en").items() if not v.strip()]
    assert not empty, f"пустые переводы: {empty[:5]}"


def test_dictionary_has_no_russian_left():
    """Русский текст в английском словаре — незамеченный пропуск."""
    left = [k for k, v in i18n.load_dictionary("en").items()
            if re.search(r"[А-Яа-яЁё]", v)]
    assert not left, f"не переведено: {left[:5]}"


def test_dictionary_keys_are_russian():
    """Ключ — русская строка. Технический ключ (settings.title) — ошибка."""
    wrong = [k for k in i18n.load_dictionary("en") if not re.search(r"[А-Яа-яЁё]", k)]
    assert not wrong, f"ключи не на русском: {wrong[:5]}"


def test_dictionary_keys_are_trimmed():
    """Пробелы обрезаются при поиске: ключ с ними никогда не совпадёт."""
    untrimmed = [k for k in i18n.load_dictionary("en") if k != k.strip()]
    assert not untrimmed, f"ключи с пробелами по краям: {untrimmed[:5]}"


def test_dictionary_is_cached(monkeypatch):
    """Словарь читается на каждый запрос страницы: без кэша это лишний ввод-вывод."""
    i18n.load_dictionary("en")
    calls = []
    original = i18n.read_json
    monkeypatch.setattr(i18n, "read_json", lambda *a, **kw: calls.append(1) or original(*a, **kw))
    i18n.load_dictionary("en")
    assert not calls, "словарь читается с диска повторно"


# ================= Пометка строк в шаблонах =================

TEMPLATE_FILES = tuple(sorted(f for f in os.listdir(TEMPLATES_DIR) if f.endswith(".html")))


@pytest.mark.parametrize("name", TEMPLATE_FILES)
def test_templates_use_translation_filter(name):
    """В шаблоне не должно остаться русского текста без фильтра перевода.

    Проверяем видимый текст между тегами: именно он попадает на экран. Без
    фильтра строка останется русской при выборе английского языка.
    """
    html = read_template(name)
    # Комментарии (в том числе jinja) в интерфейс не попадают.
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"\{#.*?#\}", "", html, flags=re.S)
    # <script> и <style> проверяются отдельным тестом: там свои правила.
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
    html = re.sub(r"<style\b.*?</style>", "", html, flags=re.S)

    missed = []
    for text in re.findall(r">([^<>]*[А-Яа-яЁё][^<>]*)<", html):
        # Уже помеченная строка: {{ 'Текст'|t }} или {{ ... }} с переводом.
        if "|t" in text or "{{" in text:
            continue
        missed.append(text.strip())
    assert not missed, f"{name}: текст без перевода: {missed[:5]}"


@pytest.mark.parametrize("name", TEMPLATE_FILES)
def test_template_attributes_are_translated(name):
    """Подсказки и placeholder читает и пользователь, и скринридер."""
    html = read_template(name)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"\{#.*?#\}", "", html, flags=re.S)
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)

    missed = re.findall(
        r'(?:placeholder|title|aria-label|alt)="([^"{}]*[А-Яа-яЁё][^"{}]*)"', html)
    assert not missed, f"{name}: атрибут без перевода: {missed[:5]}"


@pytest.mark.parametrize("name", TEMPLATE_FILES)
def test_template_strings_exist_in_dictionary(name):
    """Каждая помеченная строка должна быть в английском словаре."""
    html = read_template(name)
    dictionary = i18n.load_dictionary("en")
    missing = []
    for quote in ("'", '"'):
        for text in re.findall(r"\{\{\s*%s([^%s]+)%s\s*\|\s*t\b" % (quote, quote, quote), html):
            if re.search(r"[А-Яа-яЁё]", text) and text.strip() not in dictionary:
                missing.append(text.strip())
    assert not missing, f"{name}: нет в словаре: {missing[:5]}"


# ================= Клиентский слой =================

def test_client_dictionary_is_served(client):
    res = client.get("/api/i18n/en")
    assert res.status_code == 200
    data = res.get_json()
    assert data["lang"] == "en"
    assert data["strings"]["Настройки"] == "Settings"


def test_client_dictionary_rejects_unknown_language(client):
    res = client.get("/api/i18n/de")
    assert res.status_code == 404


def test_language_cookie_switches_pages(client):
    """Язык хранится в cookie: страницы отдаёт сервер, localStorage поздно."""
    client.set_cookie("lt_lang", "en", domain="localhost")
    body = client.get("/settings").get_data(as_text=True)
    assert "Settings" in body
    assert "Настройки</h1>" not in body


def test_default_language_keeps_russian(client):
    body = client.get("/settings").get_data(as_text=True)
    assert "Настройки" in body


def test_language_api_saves_choice(client):
    res = client.post("/api/language", json={"lang": "en"})
    assert res.status_code == 200
    assert "lt_lang=en" in res.headers.get("Set-Cookie", "")


def test_language_api_rejects_unknown(client):
    res = client.post("/api/language", json={"lang": "de"})
    assert res.status_code == 400


@pytest.mark.parametrize("path", ("/", "/settings", "/upload"))
def test_html_lang_attribute_follows_choice(client, path):
    """lang у <html> нужен скринридеру и переносам слов.

    Проверяются все страницы: атрибут задаётся в каждом шаблоне отдельно, и
    зашитый lang="ru" на одной странице скринридер уводил бы на русские правила
    чтения английского текста.
    """
    client.set_cookie("lt_lang", "en", domain="localhost")
    body = client.get(path).get_data(as_text=True)
    assert '<html lang="en"' in body, f"{path}: атрибут lang не отражает выбор"


# ================= Вкладка «Язык» в настройках =================

def test_settings_has_language_tab():
    html = read_template("settings.html")
    assert 'data-tab="language"' in html, "нет вкладки «Язык»"
    assert 'id="panel-language"' in html, "нет панели вкладки «Язык»"


def test_language_tab_offers_both_languages(client):
    """Список строится циклом по языкам сервера, поэтому проверяем готовый HTML.

    Разметка с зашитыми <option> разъехалась бы с i18n.LANGUAGES: язык, который
    сервер не знает, попал бы в выбор и не сохранялся.
    """
    body = client.get("/settings").get_data(as_text=True)
    panel = body.split('id="panel-language"', 1)
    assert len(panel) == 2, "нет панели «Язык»"
    block = panel[1].split("</select>", 1)[0]
    for code, label in ((l["code"], l["label"]) for l in i18n.languages_for_ui()):
        assert f'value="{code}"' in block, f"нет выбора языка {code}"
        # Язык называется на самом себе: выбрать его из непонятного интерфейса
        # иначе тяжело.
        assert label in block, f"нет подписи языка {code}"


def test_language_choice_calls_api():
    """Выбор языка должен уходить на сервер: страницы рендерит он."""
    html = read_template("settings.html")
    assert "/api/language" in html, "выбор языка не сохраняется на сервере"


def test_language_selector_is_wired():
    """Выбор языка должен применяться сразу, без общей кнопки сохранения."""
    html = read_template("settings.html")
    assert "$('uiLang').addEventListener" in html, "выбор языка без обработчика"
    # Обработчик должен быть безусловным: подвешенный за проверку другого
    # элемента он молча не срабатывает, и язык не переключается.
    line = next(ln for ln in html.splitlines() if "$('uiLang').addEventListener" in ln)
    assert line.strip().startswith("$('uiLang')"), \
        f"обработчик выбора языка навешивается по условию: {line.strip()[:90]}"
    assert "/api/language" in html, "язык не сохраняется на сервере"


# ================= Клиентские строки =================

JS_FILES = ("i18n.js", "mobile.js", "theme.js")


def read_static(*parts):
    root = os.path.dirname(TEMPLATES_DIR)
    with open(os.path.join(root, "static", *parts), encoding="utf-8") as f:
        return f.read()


def test_client_layer_exists():
    """Часть подписей появляется уже в браузере: очередь, статусы, ошибки."""
    js = read_static("js", "i18n.js")
    assert "window.LocalTubeI18n" in js, "нет клиентского слоя перевода"
    assert "/api/i18n/" in js, "словарь не запрашивается с сервера"


def test_client_layer_falls_back_to_source():
    """Пропущенная строка должна остаться русской, а не исчезнуть."""
    js = read_static("js", "i18n.js")
    assert "if (!value) return text;" in js, "нет запаса на отсутствующий перевод"


def untranslated_strings(code):
    """Русские литералы клиентского кода, которые не идут через t().

    Не считаются пропуском:
      * строки внутри console.* — они попадают в консоль разработчика, а не на
        экран, и перевод там только мешает искать причину;
      * сравнения (=== 'Показать') — перевод сломал бы условие, такие места
        переписаны на сравнение по данным, а не по подписи.
    """
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    missed = []
    for match in re.finditer(
            r"""(['"`])((?:[^'"`\\]|\\.)*[А-Яа-яЁё](?:[^'"`\\]|\\.)*)\1""", code):
        before = code[max(0, match.start() - 40):match.start()]
        if re.search(r"\bt\(\s*$", before):
            continue
        if re.search(r"console\.(log|warn|error|debug|info)\(\s*$", before):
            continue
        missed.append(match.group(2))
    return missed


@pytest.mark.parametrize("name", tuple(sorted(
    f for f in os.listdir(os.path.join(os.path.dirname(TEMPLATES_DIR), "static", "js"))
    if f.endswith(".js"))))
def test_scripts_translate_visible_strings(name):
    """Русский текст в скрипте должен идти через функцию перевода.

    Строка, попадающая в textContent или innerHTML напрямую, останется русской
    при выборе английского языка.
    """
    js = read_static("js", name)
    assert not untranslated_strings(js), \
        f"{name}: строка без перевода: {untranslated_strings(js)[:5]}"


def test_templates_scripts_translate_visible_strings():
    """То же для скриптов внутри шаблонов: там строк больше всего."""
    missed = {}
    for name in TEMPLATE_FILES:
        html = read_template(name)
        found = []
        for code in re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.S):
            found.extend(untranslated_strings(code))
        if found:
            missed[name] = found[:3]
    assert not missed, f"строки без перевода: {missed}"


def test_client_strings_exist_in_dictionary():
    """Каждая строка из клиентского кода должна быть в английском словаре."""
    dictionary = i18n.load_dictionary("en")
    missing = set()
    sources = [read_static("js", f) for f in os.listdir(
        os.path.join(os.path.dirname(TEMPLATES_DIR), "static", "js")) if f.endswith(".js")]
    sources += [read_template(n) for n in TEMPLATE_FILES]
    for code in sources:
        for match in re.finditer(
                r"""\bt\((['"])((?:[^'"\\]|\\.)*[А-Яа-яЁё](?:[^'"\\]|\\.)*)\1""", code):
            text = match.group(2).replace("\\'", "'").replace('\\"', '"').strip()
            if text not in dictionary:
                missing.add(text)
    assert not missing, f"нет в словаре: {sorted(missing)[:8]}"


@pytest.mark.parametrize("name", TEMPLATE_FILES)
def test_templates_load_client_layer(name):
    """Скрипт перевода нужен на каждой странице, где есть свой код."""
    html = read_template(name)
    if not html.lstrip().startswith(("<!DOCTYPE", "<html")):
        # Включаемый фрагмент (_mobile_nav.html) своего <head> не имеет:
        # скрипты подключает страница, которая его вставляет.
        pytest.skip("фрагмент, а не страница")
    assert "/static/js/i18n.js" in html, f"{name}: не подключён клиентский перевод"
    # Порядок важен: t() должна существовать до кода, который её вызывает.
    assert html.index("/static/js/i18n.js") < html.index("/static/js/theme.js"), \
        f"{name}: перевод подключён после темы"


def test_client_dictionary_is_ready_before_first_paint():
    """Словарь должен быть на месте до первой отрисовки подписей.

    Запрос словаря по сети успевал завершиться позже, чем скрипты страницы
    рисовали шапку: имя «Гость» оставалось русским на английском интерфейсе.
    Словарь на английском встраивается в саму страницу, поэтому t() отвечает
    правильно с первого вызова, а сетевой запрос остаётся только запасным путём.
    """
    js = read_static("js", "i18n.js")
    assert "LT_I18N" in js, "словарь со страницы не используется"
    # Проверяем не наличие имени, а порядок: словарь со страницы читается до
    # сетевого запроса. Иначе запрос остаётся основным путём, и первая
    # отрисовка снова обгоняет перевод.
    embedded = js.index("strings = window.LT_I18N")
    request = js.index("fetch('/api/i18n/")
    assert embedded < request, "словарь со страницы читается после сетевого запроса"
    # Между чтением словаря и запросом должен быть выход: иначе запрос уйдёт
    # всё равно, и смысла во встроенном словаре нет.
    assert "return ready;" in js[embedded:request], \
        "после встроенного словаря код всё равно идёт в сеть"
    # Условие перед чтением должно опираться на сам словарь. Отвязанное условие
    # (например, всегда ложное) оставляет сетевой запрос основным путём, и
    # проверки на порядок строк этого не видят.
    guard = js[:embedded].rsplit("if (", 1)[-1].split(")", 1)[0]
    assert "window.LT_I18N" in guard, \
        f"встроенный словарь читается по условию, не связанному с ним: if ({guard})"


def test_page_embeds_dictionary_for_english(client):
    """На английской странице словарь приходит вместе с разметкой."""
    client.set_cookie("lt_lang", "en", domain="localhost")
    html = client.get("/upload").data.decode("utf-8")
    assert "LT_I18N" in html, "страница не отдаёт словарь клиентскому слою"
    assert "Guest" in html, "перевод не попал в встроенный словарь"


def test_page_skips_dictionary_for_russian(client):
    """Русской странице словарь не нужен: это лишние килобайты в каждом ответе."""
    client.set_cookie("lt_lang", "ru", domain="localhost")
    html = client.get("/upload").data.decode("utf-8")
    assert "LT_I18N" not in html, "русской странице словарь не нужен"


@pytest.mark.parametrize("path", ("/", "/settings", "/upload"))
def test_language_switch_survives_template_reuse(client, path):
    """Второй запрос на другом языке должен переводиться, а не повторять первый.

    Jinja вычисляет постоянные выражения один раз при компиляции шаблона:
    {{ 'Профиль'|t }} — аргумент постоянный, поэтому результат фильтра
    запекался в скомпилированный шаблон. Язык первого открытия страницы после
    старта сервера оставался на ней навсегда: страницы, впервые открытые на
    русском, не переводились никогда, а открытые сразу на английском — не
    возвращались к русскому.
    """
    client.set_cookie("lt_lang", "ru", domain="localhost")
    first = client.get(path).data.decode("utf-8")
    client.set_cookie("lt_lang", "en", domain="localhost")
    second = client.get(path).data.decode("utf-8")

    # Сравниваем только видимую разметку: во встроенном словаре русские ключи
    # есть всегда, и по всей странице их не отличить от непереведённого текста.
    def visible(html):
        html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.S)
        return re.sub(r"<!--.*?-->", "", html, flags=re.S)

    russian_first = len(re.findall(r"[А-Яа-яЁё]{3,}", visible(first)))
    russian_second = len(re.findall(r"[А-Яа-яЁё]{3,}", visible(second)))
    assert russian_first > 0, f"{path}: русская страница без русского текста"
    assert russian_second < russian_first, (
        f"{path}: перевод не применился ко второму запросу "
        f"(русских слов было {russian_first}, стало {russian_second})")


@pytest.mark.parametrize("path", ("/", "/settings", "/upload"))
def test_pages_vary_by_cookie(client, path):
    """Страница зависит от cookie языка, и браузер должен об этом знать.

    Без заголовка Vary браузер отдавал из кэша страницу, отрисованную до смены
    языка: /upload переводился (его открывали впервые), а уже посещённые
    /settings и главная оставались русскими до принудительного обновления.
    """
    res = client.get(path)
    assert res.status_code == 200
    vary = res.headers.get("Vary", "")
    assert "Cookie" in vary, f"{path}: нет Vary: Cookie (получено {vary!r})"


# ================= Серверные сообщения =================

def test_api_errors_are_translated(client):
    """Текст ошибки показывается в интерфейсе: он тоже должен переводиться."""
    client.set_cookie("lt_lang", "en", domain="localhost")
    res = client.post("/api/download/prefs", json={"subtitle_langs": ["../evil"]})
    assert res.status_code == 400
    assert not re.search(r"[А-Яа-яЁё]", res.get_json()["error"]), res.get_json()["error"]
