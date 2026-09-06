"""Тесты доступа из локальной сети: владелец против гостя.

Сервер слушает 0.0.0.0, поэтому его видит вся сеть. Владельцем считается тот,
кто пришёл с самой машины (127.0.0.1) либо ввёл PIN. Всем остальным доступен
только просмотр: ни скачивания, ни удаления, ни настроек, ни личных данных.

Проверок много намеренно: раньше в проекте не было ни одной проверки прав, и
любой в сети мог выгрузить cookies аккаунта YouTube.
"""
import json

import pytest

import access
import userdata as userdata_module


@pytest.fixture
def net(tmp_path, monkeypatch):
    """Изолированные настройки доступа во временном файле."""
    monkeypatch.setattr(access, "ACCESS_FILE", str(tmp_path / "access.json"))
    access.reload_from_disk()
    yield access
    access.reload_from_disk()


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Изолированные личные данные."""
    monkeypatch.setattr(userdata_module, "USERDATA_FILE",
                        str(tmp_path / "userdata.json"))
    userdata_module.reload_from_disk()
    yield userdata_module
    userdata_module.reload_from_disk()


@pytest.fixture
def guest(client, net):
    """Клиент, приходящий с чужого адреса в сети."""
    client.environ_base["REMOTE_ADDR"] = "192.168.0.55"
    return client


@pytest.fixture
def owner(client, net):
    """Клиент с самой машины: владелец."""
    client.environ_base["REMOTE_ADDR"] = "127.0.0.1"
    return client


# ================= Кто владелец =================

def test_loopback_is_owner(net):
    for addr in ("127.0.0.1", "::1", "127.0.0.5"):
        assert net.is_owner_address(addr), f"{addr} должен быть владельцем"


def test_lan_address_is_not_owner(net):
    for addr in ("192.168.0.55", "10.0.0.3", "172.16.5.9", "8.8.8.8"):
        assert not net.is_owner_address(addr), f"{addr} не должен быть владельцем"


def test_missing_address_is_not_owner(net):
    """Без адреса нельзя считать клиента своим: это открыло бы доступ всем."""
    assert not net.is_owner_address(None)
    assert not net.is_owner_address("")


# ================= PIN =================

def test_pin_is_generated_and_stable(net):
    pin = net.get_pin()
    assert len(pin) >= 6, f"слишком короткий PIN: {pin}"
    assert pin.isdigit(), "PIN должен состоять из цифр"
    assert net.get_pin() == pin, "PIN меняется между вызовами"


def test_pin_survives_reload(net):
    pin = net.get_pin()
    net.reload_from_disk()
    assert net.get_pin() == pin, "PIN не сохранился на диск"


def test_regenerate_pin_changes_it(net):
    old = net.get_pin()
    new = net.regenerate_pin()
    assert new != old, "PIN не изменился"
    assert net.get_pin() == new


def test_token_for_correct_pin(net):
    token = net.token_for_pin(net.get_pin())
    assert token, "верный PIN не дал ключа"
    assert net.is_valid_token(token), "выданный ключ не признаётся"


def test_wrong_pin_gives_no_token(net):
    assert net.token_for_pin("000000") is None
    assert net.token_for_pin("") is None
    assert net.token_for_pin(None) is None


def test_token_dies_after_pin_change(net):
    """Смена PIN должна отключать выданные ранее устройства."""
    token = net.token_for_pin(net.get_pin())
    net.regenerate_pin()
    assert not net.is_valid_token(token), "старый ключ всё ещё работает"


def test_garbage_token_is_rejected(net):
    for value in (None, "", "abc", "0" * 64):
        assert not net.is_valid_token(value), f"принят мусорный ключ: {value!r}"


def test_pin_change_rotates_secret(net, monkeypatch):
    """Ключи должны меняться даже при выпадении того же PIN.

    Ключ считается от секрета и PIN. Если секрет не менять, повторно выпавший
    PIN вернул бы к жизни ключи устройств, которые владелец уже отключил.
    Шесть цифр — это миллион вариантов, повтор редкий, но возможный.
    """
    old_token = net.token_for_pin(net.get_pin())
    fixed = net.get_pin()
    monkeypatch.setattr(net, "_new_pin", lambda: fixed)
    assert net.regenerate_pin() == fixed, "проверка бессмысленна: PIN изменился"
    assert not net.is_valid_token(old_token), (
        "старый ключ ожил вместе с повторившимся PIN"
    )


# ================= Тумблер доступа в сеть =================

def test_network_access_is_on_by_default(net):
    """Иначе после обновления телефон в сети перестал бы работать молча."""
    assert net.is_network_enabled() is True


def test_network_access_can_be_turned_off(net):
    net.set_network_enabled(False)
    assert net.is_network_enabled() is False
    net.reload_from_disk()
    assert net.is_network_enabled() is False, "тумблер не сохранился"


def test_disabled_network_blocks_guest(guest, net):
    net.set_network_enabled(False)
    res = guest.get("/")
    assert res.status_code == 403, "гость прошёл при выключенном доступе"


def test_disabled_network_still_allows_owner(owner, net):
    net.set_network_enabled(False)
    assert owner.get("/").status_code == 200, "владельца заблокировали"


# ================= Гостю закрыто всё опасное =================

# Здесь перечислены запросы, каждый из которых раньше был доступен любому
# устройству в сети. Формат: (метод, путь, тело).
DANGEROUS = [
    ("POST", "/api/queue/add", {"urls": ["https://youtu.be/x"]}),
    ("POST", "/api/queue/pause", None),
    ("POST", "/api/queue/resume", None),
    ("POST", "/api/queue/clear", None),
    ("GET", "/api/queue/list", None),
    ("DELETE", "/api/queue/remove/1", None),
    ("POST", "/api/queue/cancel/1", None),
    ("POST", "/api/queue/priority/1", {"priority": "high"}),
    ("POST", "/api/queue/retry/1", None),
    ("GET", "/api/cookies", None),
    ("DELETE", "/api/cookies", None),
    ("GET", "/api/cookies/status", None),
    ("POST", "/api/cookies/import", {"text": "x"}),
    ("GET", "/api/cookies/browsers", None),
    ("POST", "/api/cookies/from-browser", {"browser": "chrome"}),
    ("GET", "/api/storage", None),
    ("POST", "/api/storage", {"video_dir": "videos"}),
    # Языковые дорожки и субтитры: настройки владельца, гость их не меняет.
    ("GET", "/api/download/prefs", None),
    ("POST", "/api/download/prefs", {"audio_langs": ["ru"]}),
    ("GET", "/api/auth/options", None),
    ("POST", "/api/auth/options", {"player_client": "web"}),
    ("POST", "/api/auth/ensure", None),
    ("GET", "/api/auth/status", None),
    ("POST", "/api/avatars/download_all", None),
    ("POST", "/api/thumbnails/generate", None),
    ("POST", "/api/direct_download", {"url": "https://youtu.be/x"}),
    ("POST", "/api/formats", {"url": "https://youtu.be/x"}),
    ("POST", "/api/playlist/info", {"url": "https://youtu.be/x"}),
    ("POST", "/api/user_video/upload", None),
    ("POST", "/api/user_video/edit/abc", None),
    ("POST", "/api/user_video/delete/abc", None),
    ("GET", "/api/userdata", None),
    ("POST", "/api/userdata/favorite/abc", {"active": True}),
    ("POST", "/api/userdata/watched/abc", None),
    ("POST", "/api/userdata/hidden-channel", {"author": "a", "hidden": True}),
    ("POST", "/api/userdata/clear/history", None),
    ("POST", "/api/userdata/migrate", {"favorites": []}),
    ("GET", "/api/collections", None),
    ("POST", "/api/collections", {"title": "x"}),
    ("PATCH", "/api/collections/abc", {"title": "y"}),
    ("DELETE", "/api/collections/abc", None),
    ("POST", "/api/collections/abc/videos", {"video_id": "v"}),
    ("DELETE", "/api/collections/abc/videos/v", None),
    ("POST", "/api/channel/a/sync", None),
    ("POST", "/api/channel/a/remaining", None),
    ("POST", "/api/convert/abc", {"quality": "720p"}),
    ("POST", "/api/subtitles/download/abc", None),
    ("POST", "/api/subtitles/upload/abc", None),
    ("DELETE", "/api/subtitles/abc/ru", None),
    ("POST", "/api/subtitles/download_all", None),
    ("GET", "/api/audio/download/abc", None),
    ("GET", "/settings", None),
    ("GET", "/upload", None),
    ("GET", "/edit/abc", None),
    ("GET", "/collection/watch-later", None),
    # Раздел «Сеть»: гость не должен ни читать PIN, ни трогать доступ.
    ("GET", "/api/network/info", None),
    ("POST", "/api/network/enabled", {"enabled": False}),
    ("POST", "/api/network/pin/regenerate", None),
    ("GET", "/api/network/qr", None),
    ("POST", "/api/network/scan", None),
]


@pytest.mark.parametrize("method,path,payload", DANGEROUS,
                         ids=[f"{m} {p}" for m, p, _ in DANGEROUS])
def test_guest_cannot_touch_dangerous_routes(guest, method, path, payload):
    res = guest.open(path, method=method, json=payload)
    assert res.status_code == 403, (
        f"{method} {path} доступен гостю (код {res.status_code})"
    )


def test_guest_gets_no_pin_in_error(guest):
    """Отказ не должен раскрывать PIN: иначе гость просто его прочитает."""
    pin = access.get_pin()
    res = guest.get("/api/network/info")
    assert pin not in res.get_data(as_text=True)


# ================= Гостю разрешён просмотр =================

ALLOWED = [
    ("GET", "/"),
    ("GET", "/api/catalog"),
    ("GET", "/api/search?q=x"),
    ("GET", "/api/theme-backgrounds/frutiger-aero"),
]


@pytest.mark.parametrize("method,path", ALLOWED, ids=[p for _, p in ALLOWED])
def test_guest_can_browse(guest, method, path):
    res = guest.open(path, method=method)
    assert res.status_code == 200, f"{method} {path} закрыт гостю"


def test_guest_can_open_video_page(guest, hidden_setup):
    """Страница просмотра — основное, зачем гость и заходит."""
    res = guest.get("/watch/open1")
    assert res.status_code == 200, f"страница видео закрыта гостю: {res.status_code}"


def test_owner_keeps_full_access(owner):
    """Владелец не должен ничего потерять."""
    for path in ("/", "/settings", "/upload", "/api/userdata", "/api/collections",
                 "/api/queue/list", "/api/network/info"):
        assert owner.get(path).status_code == 200, f"{path} закрыт владельцу"


# ================= Вход по PIN =================

def test_guest_becomes_owner_with_pin(guest, net):
    res = guest.post("/api/network/unlock", json={"pin": net.get_pin()})
    assert res.status_code == 200, res.get_data(as_text=True)
    # Ключ приходит в cookie, чтобы работали и страницы, а не только API.
    assert res.status_code == 200
    assert guest.get("/api/userdata").status_code == 200, "PIN не дал доступа"
    assert guest.get("/settings").status_code == 200


def test_wrong_pin_does_not_unlock(guest):
    res = guest.post("/api/network/unlock", json={"pin": "000000"})
    assert res.status_code == 403
    assert guest.get("/api/userdata").status_code == 403


def test_unlock_survives_next_request(guest, net):
    guest.post("/api/network/unlock", json={"pin": net.get_pin()})
    for _ in range(3):
        assert guest.get("/api/collections").status_code == 200


def test_lock_returns_guest_rights(guest, net):
    guest.post("/api/network/unlock", json={"pin": net.get_pin()})
    assert guest.get("/api/userdata").status_code == 200
    guest.post("/api/network/lock")
    assert guest.get("/api/userdata").status_code == 403, "выход не сработал"


# ================= Скрытые каналы недоступны гостю =================

@pytest.fixture
def hidden_setup(app_module, store, monkeypatch):
    """Один скрытый канал и один обычный."""
    monkeypatch.setattr(app_module, "VIDEO_MAP", {
        "open1": {"id": "open1", "author": "Открытый", "folder": "f1",
                  "filename": "v.mp4", "title": "Видно", "size_mb": 1,
                  "is_short": False, "thumb_file": None},
        "secret1": {"id": "secret1", "author": "Тайный", "folder": "f2",
                    "filename": "v.mp4", "title": "Секрет", "size_mb": 1,
                    "is_short": False, "thumb_file": None},
    })
    # ensure_video_map иначе пересканирует библиотеку и вернёт настоящие видео.
    monkeypatch.setattr(app_module, "ensure_video_map", lambda: None)
    monkeypatch.setattr(app_module, "build_video_map", lambda: None)
    monkeypatch.setattr(app_module, "build_user_video_map", lambda: None)
    monkeypatch.setattr(app_module, "build_playlist_map", lambda: None)
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {})
    store.toggle_hidden_channel("Тайный", True)
    return app_module


@pytest.fixture
def media_files(app_module, tmp_path, monkeypatch):
    """Настоящие файлы на диске под временными путями раздачи.

    Без них send_from_directory отвечает 404 сам, и проверка фильтра прошла бы
    даже при полностью снятой защите.
    """
    videos = tmp_path / "videos"
    avatars = tmp_path / "avas"
    for author, folder in (("Открытый", "f1"), ("Тайный", "f2")):
        directory = videos / author / folder
        directory.mkdir(parents=True)
        (directory / "v.mp4").write_bytes(b"video")
        avatars.mkdir(exist_ok=True)
        (avatars / f"{author}.jpg").write_bytes(b"jpeg")
    monkeypatch.setattr(app_module, "BASE_VIDEO_DIR", str(videos))
    monkeypatch.setattr(app_module, "AVATARS_DIR", str(avatars))
    return {"videos": videos, "avatars": avatars}


def test_guest_catalog_hides_hidden_channel(guest, hidden_setup):
    data = guest.get("/api/catalog").get_json()
    ids = [v["id"] for v in data.get("videos", [])]
    assert "open1" in ids
    assert "secret1" not in ids, "видео скрытого канала попало в каталог гостя"


def test_guest_cannot_bypass_with_include_hidden(guest, hidden_setup):
    """include_hidden=1 не должен быть лазейкой для гостя."""
    data = guest.get("/api/catalog?include_hidden=1").get_json()
    ids = [v["id"] for v in data.get("videos", [])]
    assert "secret1" not in ids, "include_hidden открыл гостю скрытый канал"


def test_guest_search_hides_hidden_channel(guest, hidden_setup):
    data = guest.get("/api/search?q=Секрет&include_hidden=1").get_json()
    ids = [v["id"] for v in (data.get("videos") or data.get("results") or [])]
    assert "secret1" not in ids, "поиск выдал гостю скрытое видео"


def test_guest_cannot_open_hidden_video_page(guest, hidden_setup):
    """Прямая ссылка на видео скрытого канала должна давать отказ."""
    assert guest.get("/watch/secret1").status_code == 404
    assert guest.get("/watch/open1").status_code != 404


def test_guest_cannot_open_hidden_channel_page(guest, hidden_setup):
    assert guest.get("/channel/Тайный").status_code == 404
    assert guest.get("/channel/Открытый").status_code == 200


def test_guest_cannot_read_hidden_video_json(guest, hidden_setup):
    assert guest.get("/api/video/secret1").status_code == 404
    assert guest.get("/api/video/open1").status_code == 200


def test_guest_cannot_fetch_hidden_media_file(guest, hidden_setup, media_files):
    """Файл раздаётся по угадываемому пути — фильтр нужен и здесь.

    Иначе гость забирает видео скрытого канала мимо страниц. Файлы кладём на
    диск по-настоящему: без них send_from_directory отвечает 404 сам, и проверка
    прошла бы даже без всякого фильтра.
    """
    assert guest.get("/media/Открытый/f1/v.mp4").status_code == 200, (
        "обычный файл не отдаётся, проверка ничего не значит"
    )
    res = guest.get("/media/Тайный/f2/v.mp4")
    assert res.status_code in (403, 404), (
        f"файл скрытого канала отдан гостю (код {res.status_code})"
    )


def test_owner_still_gets_hidden_media_file(owner, hidden_setup, media_files):
    """Владельцу его же файл отдаётся: скрытие включил он сам."""
    assert owner.get("/media/Тайный/f2/v.mp4").status_code == 200


def test_guest_cannot_fetch_hidden_avatar(guest, hidden_setup, media_files):
    """Аватарка называется по имени канала — её тоже надо закрывать."""
    assert guest.get("/avatars/Открытый.jpg").status_code == 200, (
        "обычная аватарка не отдаётся, проверка ничего не значит"
    )
    res = guest.get("/avatars/Тайный.jpg")
    assert res.status_code in (403, 404), (
        f"аватарка скрытого канала отдана гостю (код {res.status_code})"
    )


def test_owner_still_gets_hidden_avatar(owner, hidden_setup, media_files):
    assert owner.get("/avatars/Тайный.jpg").status_code == 200


def test_guest_cannot_fetch_hidden_thumbnail(guest, hidden_setup):
    res = guest.get("/api/thumbnail/secret1")
    assert res.status_code in (403, 404), "превью скрытого видео отдано гостю"


def test_owner_still_sees_hidden_channel_directly(owner, hidden_setup):
    """Владельцу скрытие мешать не должно: он сам его включил."""
    assert owner.get("/channel/Тайный").status_code == 200
    assert owner.get("/api/video/secret1").status_code == 200
    data = owner.get("/api/catalog?include_hidden=1").get_json()
    ids = [v["id"] for v in data.get("videos", [])]
    assert "secret1" in ids, "владелец потерял доступ к скрытому каналу"


# ================= Личные данные не текут гостю =================

def test_guest_index_has_no_personal_data(guest, app_module, store, monkeypatch):
    """История и избранное приезжают в разметке главной — гостю нужны пустые."""
    monkeypatch.setattr(app_module, "VIDEO_MAP", {})
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {})
    store.toggle_favorite("secret_fav", True)
    store.mark_watched("secret_hist")

    html = guest.get("/").get_data(as_text=True)
    assert "secret_fav" not in html, "избранное владельца попало на страницу гостя"
    assert "secret_hist" not in html, "история владельца попала на страницу гостя"


def test_owner_index_has_personal_data(owner, app_module, store, monkeypatch):
    monkeypatch.setattr(app_module, "VIDEO_MAP", {})
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {})
    store.toggle_favorite("my_fav", True)

    html = owner.get("/").get_data(as_text=True)
    assert "my_fav" in html, "владелец потерял своё избранное"


def test_guest_page_knows_it_is_guest(guest, app_module, monkeypatch):
    """Шаблону нужен признак роли, чтобы спрятать кнопки действий."""
    monkeypatch.setattr(app_module, "VIDEO_MAP", {})
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {})
    html = guest.get("/").get_data(as_text=True)
    assert "IS_OWNER = false" in html, "страница не знает, что зашёл гость"


def test_owner_page_knows_it_is_owner(owner, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "VIDEO_MAP", {})
    monkeypatch.setattr(app_module, "USER_VIDEO_MAP", {})
    html = owner.get("/").get_data(as_text=True)
    assert "IS_OWNER = true" in html


# ================= Сведения о своём сервере =================

def test_network_info_lists_addresses(owner):
    data = owner.get("/api/network/info").get_json()
    assert data["port"] == 5000
    assert isinstance(data["addresses"], list)
    assert data["addresses"], "не нашлось ни одного адреса"
    for item in data["addresses"]:
        assert item["url"].startswith("http://"), item
    assert "pin" in data, "владельцу нужен PIN, чтобы его продиктовать"
    assert data["enabled"] is True


def test_network_info_has_no_loopback_only(owner):
    """127.0.0.1 бесполезен для гостя: нужен адрес в сети."""
    data = owner.get("/api/network/info").get_json()
    hosts = [item["host"] for item in data["addresses"]]
    assert any(not h.startswith("127.") for h in hosts), f"только loopback: {hosts}"


def test_qr_returns_png(owner):
    res = owner.get("/api/network/qr")
    assert res.status_code == 200
    assert res.mimetype == "image/png", res.mimetype
    assert res.get_data()[:8] == b"\x89PNG\r\n\x1a\n", "это не PNG"


def test_toggle_network_via_api(owner, net):
    assert owner.post("/api/network/enabled", json={"enabled": False}).status_code == 200
    assert net.is_network_enabled() is False
    assert owner.post("/api/network/enabled", json={"enabled": True}).status_code == 200
    assert net.is_network_enabled() is True


def test_regenerate_pin_via_api(owner, net):
    old = net.get_pin()
    res = owner.post("/api/network/pin/regenerate")
    assert res.status_code == 200
    assert res.get_json()["pin"] != old


def test_bad_payload_for_enabled(owner):
    for payload in ({}, {"enabled": "да"}, None):
        res = owner.post("/api/network/enabled", json=payload)
        assert res.status_code == 400, f"принято тело {payload!r}"


# ================= Подключение к чужому серверу =================

def test_remote_check_reports_unreachable(owner):
    """Недоступный адрес — понятный отказ, а не пятисотка."""
    res = owner.post("/api/network/check", json={"url": "http://127.0.0.1:1"})
    assert res.status_code == 200, res.get_data(as_text=True)
    assert res.get_json()["online"] is False


def test_remote_check_rejects_garbage(owner):
    for value in ("", "не ссылка", "ftp://x", None, "http://имя с пробелом"):
        res = owner.post("/api/network/check", json={"url": value})
        assert res.status_code == 400, f"принят адрес {value!r}"


def test_remote_check_finds_own_server(owner, app_module):
    """Проверка связи должна работать против настоящего сервера LocalTube."""
    res = owner.get("/api/network/ping")
    assert res.status_code == 200
    data = res.get_json()
    assert data["app"] == "LocalTube", data


def test_ping_is_open_to_guests(guest):
    """Иначе автопоиск с чужого устройства не найдёт сервер."""
    assert guest.get("/api/network/ping").status_code == 200


def test_ping_does_not_leak_anything(guest):
    """В ответе не должно быть ни PIN, ни путей, ни личных данных."""
    text = guest.get("/api/network/ping").get_data(as_text=True)
    pin = access.get_pin()
    assert pin not in text
    for word in ("cookies", "C:\\", "favorites", "history"):
        assert word not in text, f"ping выдаёт лишнее: {word}"


def test_saved_servers_roundtrip(owner):
    res = owner.post("/api/network/servers", json={"url": "http://192.168.0.7:5000",
                                                   "title": "Ноутбук"})
    assert res.status_code == 200, res.get_data(as_text=True)
    items = owner.get("/api/network/servers").get_json()["servers"]
    assert any(s["url"] == "http://192.168.0.7:5000" for s in items), items

    owner.delete("/api/network/servers", json={"url": "http://192.168.0.7:5000"})
    items = owner.get("/api/network/servers").get_json()["servers"]
    assert not any(s["url"] == "http://192.168.0.7:5000" for s in items)


def test_saved_servers_reject_bad_url(owner):
    # Имя без точек не проверяем: в локальной сети машины так и называются
    # (DESKTOP-88R3R6I), это допустимый адрес.
    for value in ("", "javascript:alert(1)", "http://хост с пробелом",
                  "ftp://192.168.0.5", "http://192.168.0.5:99999", None):
        res = owner.post("/api/network/servers", json={"url": value})
        assert res.status_code == 400, f"принят адрес {value!r}"


def test_saved_servers_accept_plain_hostname(owner):
    """Имя машины без схемы должно работать: так адрес и диктуют вслух."""
    res = owner.post("/api/network/servers", json={"url": "192.168.0.31"})
    assert res.status_code == 200, res.get_data(as_text=True)
    assert res.get_json()["server"]["url"] == "http://192.168.0.31:5000"


def test_scan_returns_list(owner, monkeypatch):
    """Автопоиск не должен зависеть от того, что реально есть в сети."""
    monkeypatch.setattr(access, "scan_network", lambda *a, **kw: [
        {"url": "http://192.168.0.9:5000", "title": "DESKTOP", "videos": 3},
    ])
    res = owner.post("/api/network/scan")
    assert res.status_code == 200
    assert res.get_json()["servers"][0]["url"] == "http://192.168.0.9:5000"


# ================= Файл настроек доступа =================

def test_access_file_is_written(net, tmp_path):
    net.regenerate_pin()
    with open(net.ACCESS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "pin" in data
    assert data.get("network_enabled") is True


def test_broken_access_file_does_not_break_server(net):
    """Битый файл не должен открывать доступ всем и не должен ронять сервер."""
    with open(net.ACCESS_FILE, "w", encoding="utf-8") as f:
        f.write("{это не json")
    net.reload_from_disk()
    assert net.get_pin(), "PIN не восстановился"
    assert net.is_network_enabled() is True


def test_pin_is_not_stored_in_plain_text(net):
    """PIN лежит не сырьём — по ключу устройства он не должен восстанавливаться."""
    pin = net.get_pin()
    token = net.token_for_pin(pin)
    assert pin not in token, "ключ устройства содержит сам PIN"
    assert len(token) >= 32, f"слишком короткий ключ: {len(token)}"


# ================= Не-ASCII во внешнем вводе =================

def test_non_ascii_pin_is_rejected_not_crashing(net):
    """hmac.compare_digest со строками требует ASCII в обоих аргументах, иначе
    бросает TypeError. PIN приходит от клиента, поэтому кириллица в поле давала
    500 вместо «Неверный PIN»."""
    for pin in ("абвгде", "１２３４５６", "ﬁ", "pin\u00a0", "🔑🔑🔑🔑🔑🔑"):
        assert net.token_for_pin(pin) is None, f"не-ASCII PIN принят: {pin!r}"


def test_non_ascii_token_is_rejected_not_crashing(net):
    """Cookie с ключом подделывает кто угодно. Не-ASCII значение роняло
    is_valid_token, а она вызывается в before_request — то есть 500 приходил на
    любую страницу, а не только на API."""
    for token in ("ключ", "ﬁ", "токен" * 10, "\u2028\u2029"):
        assert net.is_valid_token(token) is False, f"не-ASCII ключ принят: {token!r}"


def test_non_ascii_pin_gives_403_not_500(guest, net):
    """Проверка через HTTP: ответ должен быть понятным отказом."""
    net.reset_attempts()
    res = guest.post("/api/network/unlock", json={"pin": "абвгде"})
    assert res.status_code == 403, f"ожидали 403, получили {res.status_code}"
    assert "error" in res.get_json()


def test_forged_non_ascii_cookie_does_not_break_pages(guest, net):
    """Гость из сети с подделанной cookie должен видеть страницу, а не 500."""
    guest.set_cookie("lt_owner", "ключ-устройства")
    res = guest.get("/")
    assert res.status_code == 200, f"страница упала с {res.status_code}"


# ================= Ограничение перебора PIN =================

def test_pin_attempts_are_limited(guest, net):
    """PIN — шесть цифр, то есть 10^6 вариантов, а сервер отвечает тысячи раз в
    секунду: без ограничения полный перебор занимал минуты."""
    net.reset_attempts()
    codes = []
    for i in range(net.MAX_PIN_ATTEMPTS + 5):
        res = guest.post("/api/network/unlock", json={"pin": f"{i:06d}"})
        codes.append(res.status_code)
    assert codes.count(403) == net.MAX_PIN_ATTEMPTS, (
        f"сравнений было {codes.count(403)}, ждали {net.MAX_PIN_ATTEMPTS}"
    )
    assert codes[-1] == 429, "после исчерпания попыток должен быть 429"


def test_correct_pin_blocked_while_window_is_closed(guest, net):
    """Пока окно закрыто, не принимается даже верный PIN: иначе ограничение
    обходилось бы вперемешку с угадыванием."""
    net.reset_attempts()
    for i in range(net.MAX_PIN_ATTEMPTS):
        guest.post("/api/network/unlock", json={"pin": f"{i:06d}"})
    res = guest.post("/api/network/unlock", json={"pin": net.get_pin()})
    assert res.status_code == 429
    assert res.get_json().get("retry_after", 0) > 0, "не сказано, сколько ждать"


def test_attempts_are_counted_per_address(client, net):
    """Перебор с одного адреса не должен запирать остальные устройства."""
    net.reset_attempts()
    client.environ_base["REMOTE_ADDR"] = "192.168.0.55"
    for i in range(net.MAX_PIN_ATTEMPTS + 2):
        client.post("/api/network/unlock", json={"pin": f"{i:06d}"})
    client.environ_base["REMOTE_ADDR"] = "192.168.0.56"
    res = client.post("/api/network/unlock", json={"pin": net.get_pin()})
    assert res.status_code == 200, "заперт чужой адрес"


def test_successful_unlock_resets_attempts(guest, net):
    """Владелец, опечатавшийся пару раз, не должен копить счётчик."""
    net.reset_attempts()
    for i in range(net.MAX_PIN_ATTEMPTS - 1):
        guest.post("/api/network/unlock", json={"pin": f"{i:06d}"})
    assert net.attempts_left("192.168.0.55") == 1
    res = guest.post("/api/network/unlock", json={"pin": net.get_pin()})
    assert res.status_code == 200
    assert net.attempts_left("192.168.0.55") == net.MAX_PIN_ATTEMPTS


def test_attempts_window_expires(guest, net, monkeypatch):
    """Окно не вечное: через ATTEMPT_WINDOW попытки снова доступны."""
    net.reset_attempts()
    for i in range(net.MAX_PIN_ATTEMPTS):
        guest.post("/api/network/unlock", json={"pin": f"{i:06d}"})
    assert net.pin_locked_for("192.168.0.55") > 0

    # Двигаем время вперёд, а не спим: тест должен быть быстрым.
    real_monotonic = net.time.monotonic
    shift = net.ATTEMPT_WINDOW + 1
    monkeypatch.setattr(net.time, "monotonic", lambda: real_monotonic() + shift)
    assert net.pin_locked_for("192.168.0.55") == 0, "окно не истекло"
    res = guest.post("/api/network/unlock", json={"pin": net.get_pin()})
    assert res.status_code == 200


def test_attempts_store_does_not_grow_forever(net, monkeypatch):
    """Записи о попытках чистятся, иначе словарь рос бы на каждый новый адрес
    до перезапуска сервера."""
    net.reset_attempts()
    for i in range(50):
        net.token_for_pin("000000", f"10.0.0.{i}")
    assert len(net._attempts) == 50

    real_monotonic = net.time.monotonic
    shift = net.ATTEMPT_WINDOW + 1
    monkeypatch.setattr(net.time, "monotonic", lambda: real_monotonic() + shift)
    net.token_for_pin("000000", "10.0.1.1")
    assert len(net._attempts) == 1, f"осталось записей: {len(net._attempts)}"


# ================= IPv6 в адресах серверов =================

def test_ipv6_server_url_is_accepted(net):
    """Поддержка IPv6 тут задумана (адрес оборачивается в квадратные скобки), но
    проверка имени хоста требовала начинать с буквы или цифры, а «::1» начинается
    с двоеточия — адрес отклонялся как непонятный."""
    assert net.normalize_server_url("http://[::1]:5000") == "http://[::1]:5000"
    assert net.normalize_server_url("http://[fe80::1]:5000") == "http://[fe80::1]:5000"
    assert net.normalize_server_url("[::1]") == "http://[::1]:5000"


def test_broken_ipv6_is_still_rejected(net):
    """Проверка адреса не должна превратиться в «пропускаем всё с двоеточием»."""
    for value in ("http://[gggg::1]:80", "http://[::1", "http://[]:80",
                  "http://[1:2:3:4:5:6:7:8:9]:80"):
        assert net.normalize_server_url(value) is None, f"принят мусор: {value}"


def test_dangerous_schemes_are_rejected(net):
    """Адрес попадает в link.href в настройках: javascript: означал бы
    исполнение кода по клику владельца."""
    for value in ("javascript:alert(1)", "JavaScript:alert(1)",
                  "data:text/html,<script>alert(1)</script>",
                  "file:///etc/passwd", "vbscript:msgbox(1)",
                  "  javascript:alert(1)  "):
        assert net.normalize_server_url(value) is None, f"принята схема: {value}"


# ================= Секреты не должны попадать в репозиторий =================

def test_secret_files_are_ignored_by_git():
    """PIN и секрет ключей устройств не должны уезжать в публичный репозиторий.

    access.json перечислен в .gitignore, но копию тех же данных легко получить
    под другим именем: рядом лежал localhost.bak с побайтово тем же содержимым,
    и обычный git add -A утащил бы его в коммит. Проверяем именно .gitignore, а
    не текущий рабочий каталог: файл создаётся заново на каждой машине.
    """
    import os
    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Файлов может не быть на диске: --no-index проверяет только правила.
    # Имена идут аргументами, а не через --stdin: с text=True на Windows перевод
    # строки превращается в \r\n, и git не находит правило для «access.json\r».
    candidates = ["access.json", "access.json.bak", "localhost.bak",
                  "cookies.txt", "userdata.json", "userdata.json.bak",
                  "queue.json", "config.json"]
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--"] + candidates,
            cwd=root, text=True, capture_output=True)
    except OSError:
        pytest.skip("git недоступен")
    if result.returncode == 128:
        pytest.skip(f"git не смог проверить правила: {result.stderr.strip()}")
    ignored = set(result.stdout.split())
    missing = [name for name in candidates if name not in ignored]
    assert not missing, f".gitignore не закрывает: {missing}"
