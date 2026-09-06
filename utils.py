import io
import json
import os
import re
import shutil
import time

from logger import logger


class JsonWriteError(Exception):
    """Не удалось безопасно записать JSON-файл."""


def read_json(path, default=None, use_backup=True):
    """Читает JSON, при повреждении пробует .bak.

    Возвращает default, если файла нет или ни основной файл, ни бэкап не
    читаются. utf-8-sig: файл могли сохранить с BOM из редактора.
    """
    for candidate in ([path, path + '.bak'] if use_backup else [path]):
        if not os.path.exists(candidate):
            continue
        try:
            with open(candidate, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            if candidate != path:
                logger.warning(f"{path} повреждён, данные взяты из .bak")
            return data
        except Exception as e:
            logger.warning(f"Не удалось прочитать {candidate}: {e}")
    return default


def write_json_atomic(path, data, backup=True, indent=2):
    """Атомарно записывает JSON, сохраняя копию предыдущей версии.

    Прямая запись через open(path, 'w') обрезает файл сразу: сбой на середине
    оставляет пустой или битый JSON, а прежние данные уже потеряны. Здесь
    сначала пишется .tmp с fsync, затем os.replace подменяет файл одним
    неделимым действием.

    Бросает JsonWriteError: тихий сбой недопустим, вызывающий код должен
    узнать, что данные не сохранены.
    """
    directory = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        raise JsonWriteError(f"Нет каталога для {path}: {e}") from e

    if backup and os.path.exists(path):
        try:
            shutil.copyfile(path, path + '.bak')
        except OSError as e:
            # Отсутствие бэкапа не повод терять новые данные.
            logger.warning(f"Не удалось создать бэкап {path}: {e}")

    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            # Без fsync os.replace может отдать успех, а данные пропадут
            # при отключении питания.
            os.fsync(f.fileno())
        _replace_with_retry(tmp, path)
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise JsonWriteError(f"Не удалось записать {path}: {e}") from e


# На Windows os.replace падает с PermissionError, если целевой файл в этот
# момент открыт кем-то ещё (антивирус, поиск, открытый queue.json в редакторе).
# Файл освобождается через десятки миллисекунд, поэтому короткие повторы
# спасают запись, которая иначе теряла бы данные на ровном месте.
REPLACE_RETRIES = 5
REPLACE_DELAY = 0.05


def _replace_with_retry(tmp, path):
    for attempt in range(REPLACE_RETRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == REPLACE_RETRIES - 1:
                raise
            time.sleep(REPLACE_DELAY * (attempt + 1))


# Имена устройств Windows: файл с таким именем создать нельзя, а путь к нему
# уводит за пределы каталога (os.path.abspath('CON') -> '\\\\.\\CON').
WINDOWS_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


def safe_name(text: str) -> str:
    """Превращает имя канала или видео в безопасное имя файла.

    Пустой результат недопустим: раньше авторы вида '..', '.' и '   '
    сворачивались в пустую строку, и метаданные разных каналов писались в один
    и тот же файл вида META_DIR/.json.
    """
    if not text:
        return "unknown"
    name = re.sub(r'[\\/*?:"<>|]', "_", str(text))
    # Управляющие символы недопустимы в именах файлов на Windows.
    name = re.sub(r'[\x00-\x1f\x7f]', '_', name)
    name = name.rstrip('. ').strip()
    if not name:
        return "unknown"
    # Сравнение без расширения и регистра: 'con.txt' и 'CON' одинаково опасны.
    if name.split('.')[0].upper() in WINDOWS_RESERVED_NAMES:
        name = '_' + name
    return name

NETSCAPE_HEADER = '# Netscape HTTP Cookie File'

# YouTube отдаёт cookies входа (LOGIN_INFO, SID, SAPISID) с флагом HttpOnly.
# В Netscape-файле такая запись начинается с этого префикса: строка выглядит
# как комментарий, но yt-dlp и браузеры её читают. Отбросив её вместе с
# комментариями, мы теряли ровно те cookies, которые подтверждают вход,
# и видео с возрастным ограничением падало на «Sign in to confirm your age».
HTTPONLY_PREFIX = '#HttpOnly_'


def sanitize_netscape_cookies(text):
    """Оставляет только корректные записи Netscape-формата.

    Возвращает (текст файла, число принятых cookies). Одна битая строка
    (например, значение с переводом строки внутри) заставляла yt-dlp отвергнуть
    весь файл целиком, и авторизация пропадала для всех сайтов сразу.

    Живёт в utils, а не в app: тем же путём идёт импорт из браузера, а он
    выполняется в auth_options, которому нельзя импортировать app.
    """
    good = []
    for raw in (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = raw.rstrip('\n')
        if not line.strip():
            continue
        # Префикс снимаем до проверок и возвращаем на место при записи: иначе
        # запись авторизации выглядит комментарием и теряется.
        stripped = line.lstrip()
        httponly = stripped.startswith(HTTPONLY_PREFIX)
        if httponly:
            line = stripped[len(HTTPONLY_PREFIX):]
        elif stripped.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 7:
            continue
        domain, _flag, _path, _secure, expires, name, _value = fields
        if not domain.strip() or not name.strip():
            continue
        # expires должен быть числом, иначе http.cookiejar тоже споткнётся.
        if not expires.strip().lstrip('-').isdigit():
            continue
        good.append((HTTPONLY_PREFIX if httponly else '') + '\t'.join(fields))
    return NETSCAPE_HEADER + '\n' + '\n'.join(good) + ('\n' if good else ''), len(good)


def cookie_jar_to_netscape(jar):
    """Переводит cookiejar в Netscape-текст, склеивая рваные значения.

    jar.save() из yt-dlp пишет значение как есть, поэтому cookie с переводом
    строки внутри разрывалась на две строки, а cookie с табуляцией получала
    8 полей — yt-dlp затем терял такие записи или отвергал файл целиком.
    Значения чистятся, а не выбрасываются: терять cookies авторизации нельзя.
    """
    lines = [NETSCAPE_HEADER]
    for cookie in jar or []:
        domain = _clean_cookie_field(cookie.domain)
        expires = cookie.expires
        try:
            expires = int(float(expires or 0))
        except (TypeError, ValueError):
            expires = 0
        # has_nonstandard_attr — так HttpOnly приходит из браузера в http.cookiejar.
        httponly = False
        try:
            httponly = cookie.has_nonstandard_attr('HttpOnly')
        except AttributeError:
            httponly = False
        lines.append(('' if not httponly else HTTPONLY_PREFIX) + '\t'.join([
            domain,
            'TRUE' if domain.startswith('.') else 'FALSE',
            _clean_cookie_field(cookie.path) or '/',
            'TRUE' if cookie.secure else 'FALSE',
            str(expires),
            _clean_cookie_field(cookie.name),
            _clean_cookie_field(cookie.value),
        ]))
    return sanitize_netscape_cookies('\n'.join(lines))


def _clean_cookie_field(value):
    """Убирает табы и переводы строк, которые рвут запись на части."""
    return re.sub(r'[\t\r\n]+', ' ', str(value if value is not None else '')).strip()


class CookieStream(io.StringIO):
    """Поток cookies для yt-dlp, знающий, из какого файла он прочитан.

    yt-dlp вызывает save_cookies() при каждом close() и записывает в cookiefile
    содержимое своего jar. Если отдать ему путь, он затирает файл целиком:

    * пропадали cookies, которых не было в этом запросе (371 запись
      превращалась в 238);
    * экспорт из браузера, сделанный во время загрузки, затирался старым jar
      из памяти — пропадали LOGIN_INFO и SID.

    Но и просто выбрасывать записанное нельзя: YouTube обновляет короткоживущие
    токены (SIDCC, __Secure-1PSIDTS, __Secure-3PSIDTS, __Secure-1PSIDCC,
    __Secure-3PSIDCC), и без их сохранения авторизация протухает за считаные
    часы — видео 18+ снова падает на «Sign in to confirm your age».
    Проверено: подстановка этих пяти значений из браузера в устаревший файл
    возвращает доступ.

    Поэтому обновления вливаются в файл: значения обновляются, а записи,
    которых yt-dlp не видел, остаются на месте.
    """

    def __init__(self, text, path):
        super().__init__(text)
        self.path = path

    def flush(self):
        super().flush()
        self._merge_only()

    def close(self):
        self._merge_only()
        super().close()

    def _merge_only(self):
        """Вливает записанное yt-dlp в файл, не трогая сам поток."""
        if self.closed:
            return
        try:
            written = self.getvalue()
        except ValueError:          # поток уже закрыт
            return
        if written.strip('\x00').strip():
            merge_cookie_updates(self.path, written)

    def merge_now(self):
        """Вливает обновления в файл и готовит поток к повторному чтению.

        yt-dlp не закрывает поток и не вызывает flush: contextmanager
        YoutubeDLCookieJar.open() делает truncate(0), отдаёт поток и на выходе
        ничего не вызывает. Поэтому этот метод вызывается явно — из
        apply_cookie_updates() после работы с YoutubeDL.

        После записи поток непригоден для повторного чтения: load() читает до
        конца и позицию не возвращает, а truncate(0) при сохранении её тоже не
        сбрасывает. Повторная попытка с тем же объектом падала с
        «does not look like a Netscape format cookies file», и yt-dlp
        превращал это в CookieLoadError('failed to load cookies') — задача
        останавливалась целиком вместо повтора. Поэтому заново наполняем буфер
        текстом файла и встаём в начало.
        """
        self._merge_only()
        if self.closed:
            return
        try:
            with io.open(self.path, encoding='utf-8') as fh:
                text = fh.read()
        except OSError as exc:
            logger.warning(f'Не удалось перечитать cookies ({self.path}): {exc}')
            return
        self.seek(0)
        self.truncate(0)
        self.write(text)
        self.seek(0)


def apply_cookie_updates(opts):
    """Сохраняет обновления cookies после работы с YoutubeDL.

    Вызывать после закрытия YoutubeDL: yt-dlp записывает обновлённый jar в
    поток, но сам поток не закрывает, поэтому сигнала «готово» нет и вливать
    обновления надо явно.
    """
    stream = (opts or {}).get('cookiefile')
    if isinstance(stream, CookieStream):
        stream.merge_now()


def cookiefile_for_ydl(path):
    """Возвращает значение опции cookiefile: поток вместо пути.

    Путь отдавать нельзя — это и есть разрешение перезаписать файл целиком.
    Возвращаем None, если файла нет: yt-dlp тогда работает без cookies.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        with io.open(path, encoding='utf-8') as fh:
            return CookieStream(fh.read(), path)
    except OSError as exc:
        logger.warning(f'Не удалось прочитать cookies ({path}): {exc}')
        return None


def _parse_netscape(text):
    """Разбирает Netscape-текст в словарь (домен, путь, имя) -> поля."""
    result = {}
    for raw in (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        # truncate(0) в yt-dlp не сбрасывает позицию, поэтому в начале потока
        # остаются NUL-байты от прежней длины: их надо убрать.
        line = raw.strip('\x00')
        if not line.strip():
            continue
        stripped = line.lstrip()
        if stripped.startswith(HTTPONLY_PREFIX):
            line = stripped[len(HTTPONLY_PREFIX):]
        elif stripped.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 7:
            continue
        result[(fields[0], fields[2], fields[5])] = fields
    return result


def merge_cookie_updates(path, written):
    """Вливает обновления yt-dlp в файл, ничего не теряя.

    Обновляет значение и срок жизни у записей, которые yt-dlp переписал,
    добавляет новые и сохраняет все остальные строки файла как есть.
    """
    if not path or not os.path.exists(path):
        return
    fresh = _parse_netscape(written)
    if not fresh:
        return
    try:
        with io.open(path, encoding='utf-8') as fh:
            current = fh.read()
    except OSError as exc:
        logger.warning(f'Не удалось прочитать cookies ({path}): {exc}')
        return

    updated, out_lines = 0, []
    for raw in current.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = raw
        stripped = line.lstrip()
        httponly = stripped.startswith(HTTPONLY_PREFIX)
        body = stripped[len(HTTPONLY_PREFIX):] if httponly else line
        fields = body.split('\t')
        if len(fields) == 7 and not (not httponly and stripped.startswith('#')):
            key = (fields[0], fields[2], fields[5])
            new = fresh.pop(key, None)
            if new is not None and (new[4], new[6]) != (fields[4], fields[6]):
                fields[4], fields[6] = new[4], new[6]
                line = (HTTPONLY_PREFIX if httponly else '') + '\t'.join(fields)
                updated += 1
        out_lines.append(line)

    # Записи, которых в файле не было: YouTube завёл их в этом запросе.
    added = 0
    for fields in fresh.values():
        out_lines.append('\t'.join(fields))
        added += 1

    if not updated and not added:
        return
    text, _ = sanitize_netscape_cookies('\n'.join(out_lines))
    try:
        write_text_atomic(path, text)
    except OSError as exc:
        logger.warning(f'Не удалось обновить cookies ({path}): {exc}')
        return
    logger.info(f'cookies обновлены ({path}): '
                f'изменено {updated}, добавлено {added}')


def write_text_atomic(path, text):
    """Пишет текст через временный файл: обрыв не должен оставить огрызок."""
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    # С повторами: на Windows подмена занятого файла (cookies.txt читает yt-dlp
    # в другом потоке) падает с PermissionError, хотя через миг сработает.
    _replace_with_retry(tmp, path)


def is_tiktok_url(url) -> bool:
    """Ссылка ведёт на TikTok (сам сайт или короткий домен vm/vt).

    Нужна загрузчику: YouTube-аргументы (PO Token, player_client) TikTok-экстрактор
    не понимает, а передача их всем ссылкам ломала бы загрузку.
    """
    host = str(url or '').split('//', 1)[-1].split('/', 1)[0].split('@')[-1].lower()
    host = host.split(':')[0].removeprefix('www.')
    return host in ('tiktok.com', 'm.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com')


def is_shorts_video(info: dict) -> bool:
    if not isinstance(info, dict):
        return False
    # TikTok — лента коротких вертикальных роликов. Иногда extract_flat не
    # отдаёт размеры, поэтому одного extractor_key достаточно.
    extractor = str(info.get('extractor_key') or info.get('ie_key') or '').lower()
    webpage = str(info.get('webpage_url') or '').lower()
    if extractor.startswith('tiktok') or 'tiktok.com/' in webpage:
        return True
    if info.get('height') and info.get('width') and info['height'] > info['width']:
        return True
    title = info.get('title', '').lower()
    if '#shorts' in title or '#short' in title:
        return True
    if '/shorts/' in info.get('webpage_url', ''):
        return True
    # Короткое видео без известной ширины: условие h > w здесь недостижимо —
    # такие видео уже вернули True первым правилом. Тот же порядок проверок
    # используется в Android-клиенте (Library.kt, isShort).
    duration = info.get('duration')
    if duration and 1 <= duration <= 60 and not info.get('width'):
        return True
    return False