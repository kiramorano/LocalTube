#!/usr/bin/env python3
"""spec_common.py — общая часть PyInstaller-спеков.

Спеков три (обычная сборка, портативная одним файлом, legacy для Windows 7), и
списки данных, скрытых импортов и исключений у них совпадают. Держать три копии
одного списка — верный способ получить сборку, где в одном варианте забыли
шаблоны, а в другом — локали, поэтому вся общая часть лежит здесь.

Модуль импортируется из .spec-файлов, которые PyInstaller выполняет как обычный
Python, поэтому здесь нет ничего специфичного для PyInstaller, кроме
``collect_all``.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, 'packaging', 'assets')

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Модули проекта, которые PyInstaller не находит сам: часть подключается как
# blueprints через init(), часть импортируется по имени внутри функций.
HIDDEN_PROJECT_MODULES = [
    'access', 'audio_language', 'auth_options', 'channel_assets',
    'custom_quality', 'desktop', 'download_avatars', 'download_lib',
    'download_prefs', 'download_thumbnails', 'download_video', 'downloader',
    'i18n', 'logger', 'paths', 'po_manager', 'proc', 'proxy_setup', 'server',
    'subtitles', 'userdata', 'user_videos', 'utils', 'version',
    'youtube_extractor',
]

# Пакеты, которые тянутся динамически и потому не видны анализатору импортов.
HIDDEN_THIRD_PARTY = [
    # waitress поднимает сервер в оконном режиме.
    'waitress', 'waitress.server', 'waitress.task',
    # segno рисует QR-код для доступа с телефона.
    'segno',
    # Flask выбирает JSON-провайдер и планировщик маршрутов на ходу.
    'jinja2.ext', 'werkzeug.middleware.proxy_fix',
    # pywebview на Linux использует GTK и WebKit через GObject Introspection,
    # но импорты делаются динамически — PyInstaller их не видит.
    'gi', 'gi.repository',
    'gi.repository.Gtk', 'gi.repository.GObject',
    'gi.repository.Gdk', 'gi.repository.WebKit2',
    'gi.repository.Gio', 'gi.repository.GLib',
]

# Крупные пакеты, не нужные приложению. Без исключений PyInstaller тащит их
# целиком, если они просто установлены в окружении сборки: tkinter добавляет
# несколько мегабайт и dll, которых на машине пользователя может не быть, а
# pytest с numpy утраивают размер архива.
EXCLUDES = [
    'tkinter', 'test', 'unittest', 'pytest', '_pytest', 'numpy', 'pandas',
    'matplotlib', 'scipy', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    'IPython', 'notebook', 'sphinx', 'setuptools', 'pip', 'wheel',
]


def collect_datas(include_ffmpeg=True):
    """Файлы, которые должны попасть в сборку.

    Шаблоны и статику приходится перечислять явно: приложение обращается к ним
    через ``paths.resource_path``, а не через импорт, поэтому анализатор
    PyInstaller их не видит и в сборку они не попадали — интерфейс отдавался
    как TemplateNotFound.
    """
    datas = [
        (os.path.join(ROOT, 'templates'), 'templates'),
        (os.path.join(ROOT, 'static'), 'static'),
    ]

    # Локали: i18n читает их с диска по имени файла.
    locales = os.path.join(ROOT, 'locales')
    if os.path.isdir(locales):
        datas.append((locales, 'locales'))

    # Плагины PO Token. В каталог данных приложение раскладывает их само при
    # первом запуске (auth_options.ensure_plugins), но исходники нужны как
    # образец, если пользователь их удалит.
    plugins = os.path.join(ROOT, 'yt_dlp_plugins')
    if os.path.isdir(plugins):
        datas.append((plugins, 'yt_dlp_plugins'))

    # config.json в .gitignore: в чистом клоне его нет, приложение создаёт файл
    # с настройками по умолчанию при первом запуске.
    config = os.path.join(ROOT, 'config.json')
    if os.path.isfile(config):
        datas.append((config, '.'))

    # Иконка нужна внутри сборки: на Linux окно берёт её файлом, а не из
    # ресурсов исполняемого файла, как на Windows.
    icon_png = os.path.join(ASSETS, 'localtube.png')
    if os.path.isfile(icon_png):
        datas.append((icon_png, os.path.join('packaging', 'assets')))

    if include_ffmpeg:
        datas.extend(_ffmpeg_datas())

    return datas


def _ffmpeg_datas():
    """Вложенный ffmpeg, если сборщик его подготовил.

    ffmpeg кладётся в ``packaging/assets/ffmpeg`` до запуска PyInstaller (в CI
    это делает отдельный шаг). Без него загрузка с YouTube падала на склейке
    видео с аудио: yt-dlp скачивал два потока и не мог их объединить, потому что
    ffmpeg не установлен в системе. Файлы идут в подкаталог ``bin``, где их ищет
    ``paths.find_binary``.
    """
    ffmpeg_dir = os.path.join(ASSETS, 'ffmpeg')
    if not os.path.isdir(ffmpeg_dir):
        return []

    # Каталог может содержать сборки под обе платформы: скачивать их удобно
    # заранее, а вот в пакет должны попасть только свои. Иначе в Linux-сборку
    # укладывались ffmpeg.exe и ffprobe.exe — 90 МБ, которые там невозможно
    # запустить (paths.find_binary требует бит выполнения и имя без .exe).
    want_exe = sys.platform == 'win32'
    found = []
    for name in sorted(os.listdir(ffmpeg_dir)):
        full = os.path.join(ffmpeg_dir, name)
        if not os.path.isfile(full):
            continue
        if name.lower().endswith('.exe') != want_exe:
            continue
        found.append((full, 'bin'))
    return found


# ================= ПОЛНЫЙ БАНДЛ GTK/WEBKIT ДЛЯ LINUX =================
#
# Приложение несёт в себе весь графический стек: GTK, WebKitGTK, GLib и всё, на
# что они опираются. Так собранный пакет запускается там, где нет ни GTK, ни
# WebKit, — а именно этого требует обещание «работает в любом дистрибутиве».
#
# Половинчатый вариант не годится и был причиной падения: если положить внутрь
# libstdc++ сборочной машины, но окно рисовать системным WebKit, то системная
# библиотека линкуется с нашей и падает —
#   `GLIBCXX_3.4.26' not found (required by libwebkit2gtk-4.1.so.0)
# Поэтому либо всё системное, либо всё своё. Здесь выбрано второе.
#
# Что вложить нельзя:
#   * glibc (libc, libm, libpthread, libdl, librt) — неразделима с загрузчиком
#     ld.so, который выбирает система. Её версия на сборочной машине становится
#     минимальным требованием: Ubuntu 22.04 даёт glibc 2.35, что покрывает
#     Ubuntu 22.04+, Debian 12+, Fedora 36+, Arch, openSUSE 15.5+.
#   * libGL/libEGL/libgbm/libdrm — драйверы видеокарты пользователя. Своя копия
#     не совпала бы с ядром и ломала бы ускорение.
LINUX_BUNDLE_LIBS = (
    # C++ и вспомогательные: WebKit требует новый GLIBCXX, поэтому свой.
    'libstdc++.so.6',
    'libgcc_s.so.1',
    # GLib — фундамент всего стека.
    'libglib-2.0.so.0',
    'libgobject-2.0.so.0',
    'libgio-2.0.so.0',
    'libgmodule-2.0.so.0',
    'libgthread-2.0.so.0',
    'libgirepository-1.0.so.1',
    'libffi.so',
    'libpcre2-8.so.0',
    'libpcre.so.3',
    # GTK и отрисовка.
    'libgtk-3.so.0',
    'libgdk-3.so.0',
    'libgdk_pixbuf-2.0.so.0',
    'libatk-1.0.so.0',
    'libatk-bridge-2.0.so.0',
    'libatspi.so.0',
    'libcairo.so.2',
    'libcairo-gobject.so.2',
    'libcairo-script-interpreter.so.2',
    'libpango-1.0.so.0',
    'libpangocairo-1.0.so.0',
    'libpangoft2-1.0.so.0',
    'libharfbuzz.so.0',
    'libharfbuzz-subset.so.0',
    'libfribidi.so.0',
    'libthai.so.0',
    'libdatrie.so.1',
    'libgraphite2.so.3',
    'libfontconfig.so.1',
    'libfreetype.so.6',
    'libpixman-1.so.0',
    'libepoxy.so.0',
    'librsvg-2.so.2',
    # WebKit и JavaScriptCore — сердце окна.
    'libwebkit2gtk-4.1.so.0',
    'libwebkit2gtk-4.0.so.37',
    'libjavascriptcoregtk-4.1.so.0',
    'libjavascriptcoregtk-4.0.so.18',
    # Сеть и криптография для WebKit.
    'libsoup-3.0.so.0',
    'libsoup-2.4.so.1',
    'libsoup-gnome-2.4.so.1',
    'libnghttp2.so.14',
    'libpsl.so.5',
    'libgnutls.so.30',
    'libhogweed.so.6',
    'libnettle.so.8',
    'libgmp.so.10',
    'libtasn1.so.6',
    'libidn2.so.0',
    'libunistring.so.2',
    'libp11-kit.so.0',
    'libbrotlidec.so.1',
    'libbrotlicommon.so.1',
    'libssl.so',
    'libcrypto.so',
    # Мультимедиа: без GStreamer в WebKit не играет видео.
    'libgstreamer-1.0.so.0',
    'libgstbase-1.0.so.0',
    'libgstapp-1.0.so.0',
    'libgstaudio-1.0.so.0',
    'libgstvideo-1.0.so.0',
    'libgstpbutils-1.0.so.0',
    'libgstgl-1.0.so.0',
    'libgsttag-1.0.so.0',
    'libgstfft-1.0.so.0',
    'libgstriff-1.0.so.0',
    'libgstcodecparsers-1.0.so.0',
    'libgsttranscoder-1.0.so.0',
    'liborc-0.4.so.0',
    # Кодеки и изображения.
    'libjpeg.so.8',
    'libpng16.so.16',
    'libwebp.so.7',
    'libwebpdemux.so.2',
    'libwebpmux.so.3',
    'libtiff.so.5',
    'libopenjp2.so.7',
    'libjbig.so.0',
    'libwoff2dec.so.1.0.2',
    'libwoff2common.so.1.0.2',
    'libsharpyuv.so.0',
    # Сжатие.
    'libz.so.1',
    'liblzma.so.5',
    'libzstd.so.1',
    'libbz2.so.1',
    # Системные службы, к которым обращается GTK.
    'libdbus-1.so.3',
    'libdbus-glib-1.so.2',
    'libsystemd.so.0',
    'libselinux.so.1',
    'libmount.so.1',
    'libblkid.so.1',
    'libuuid.so.1',
    'libcap.so.2',
    'liblber-2.5.so.0',
    'libldap-2.5.so.0',
    'libsasl2.so.2',
    'libgssapi_krb5.so.2',
    'libkrb5.so.3',
    'libk5crypto.so.3',
    'libkrb5support.so.0',
    'libcom_err.so.2',
    'libkeyutils.so.1',
    'libtirpc.so.3',
    # X11 и Wayland: сами протоколы, без драйверов.
    'libX11.so.6',
    'libX11-xcb.so.1',
    'libXext.so.6',
    'libXrender.so.1',
    'libXi.so.6',
    'libXfixes.so.3',
    'libXcomposite.so.1',
    'libXdamage.so.1',
    'libXrandr.so.2',
    'libXcursor.so.1',
    'libXinerama.so.1',
    'libXtst.so.6',
    'libxcb.so.1',
    'libxcb-render.so.0',
    'libxcb-shm.so.0',
    'libxcb-glx.so.0',
    'libxcb-dri2.so.0',
    'libxcb-dri3.so.0',
    'libxcb-present.so.0',
    'libxcb-sync.so.1',
    'libxcb-xfixes.so.0',
    'libxcb-randr.so.0',
    'libxcb-shape.so.0',
    'libxcb-keysyms.so.1',
    'libxshmfence.so.1',
    'libxkbcommon.so.0',
    'libwayland-client.so.0',
    'libwayland-cursor.so.0',
    'libwayland-egl.so.1',
    'libwayland-server.so.0',
    'libXau.so.6',
    'libXdmcp.so.6',
    'libbsd.so.0',
    'libmd.so.0',
    'libenchant-2.so.2',
    'libhyphen.so.0',
    'libnotify.so.4',
    'libsecret-1.so.0',
    'libmanette-0.2.so.0',
    'libgudev-1.0.so.0',
    'libicui18n.so.70',
    'libicuuc.so.70',
    'libicudata.so.70',
    'libxslt.so.1',
    'libxml2.so.2',
    'libsqlite3.so.0',
    'libtdb.so.1',
    'libavif.so.13',
    'libaom.so.3',
    'libdav1d.so.5',
    'libde265.so.0',
    'libx265.so.199',
    'libnuma.so.1',
    'libyuv.so.0',
    'libgcrypt.so.20',
    'libgpg-error.so.0',
    'liblcms2.so.2',
    'libjson-glib-1.0.so.0',
    'libproxy.so.1',
    'libduktape.so.207',
)

# Библиотеки, которые остаются системными при любом раскладе.
LINUX_NEVER_BUNDLE = (
    # glibc: неразделима с ld.so, версию выбирает система.
    'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2', 'librt.so.1',
    'libresolv.so.2', 'libnsl.so', 'libutil.so.1', 'libcrypt.so',
    'ld-linux-x86-64.so.2', 'libanl.so.1', 'libthread_db.so.1',
    # Драйверы видеокарты: рядом с основными библиотеками их быть не должно,
    # иначе наш экземпляр перекроет драйвер пользователя. Копия всё же нужна —
    # WebKit слинкован с libGL и без файла просто не загружается, — но она
    # уходит в отдельный каталог и подключается лишь когда системной нет,
    # см. ``collect_gl_fallback``.
    'libGL.so', 'libGLX.so', 'libGLdispatch.so', 'libOpenGL.so',
    'libEGL.so', 'libGLESv2.so', 'libgbm.so', 'libdrm.so',
    'libglapi.so', 'libgallium', 'libvulkan.so',
)

# Библиотеки графики для запасного каталога. Порядок важен: при подключении
# вручную каждая следующая опирается на предыдущие.
LINUX_GL_FALLBACK = (
    'libGLdispatch.so.0',
    'libglapi.so.0',
    'libdrm.so.2',
    'libgbm.so.1',
    'libGLX.so.0',
    'libGL.so.1',
    'libEGL.so.1',
    'libGLESv2.so.2',
)


def collect_gl_fallback():
    """Запасные копии библиотек графики.

    WebKit слинкован с libGL, libEGL, libdrm и libgbm: без этих файлов
    загрузчик не открывает libwebkit2gtk вовсе, и приложение падает с
    ``undefined symbol: webkit_get_major_version`` — библиотека осталась
    незагруженной, а не потеряла символ.

    При этом положить их рядом с остальными нельзя: наш экземпляр оказался бы
    первым в поиске и перекрыл бы драйвер видеокарты пользователя. Поэтому копии
    уходят в отдельный каталог, который подключается только если в системе своих
    нет (см. rthook_gtk_linux.py).

    Каталог прописывается в RPATH копий: иначе, подключённые в обход обычного
    поиска, они не нашли бы собственные зависимости.
    """
    if not sys.platform.startswith('linux'):
        return []

    import glob
    import shutil
    import subprocess

    stage = os.path.join(ROOT, 'build', 'gl_fallback')
    os.makedirs(stage, exist_ok=True)

    found = []
    for name in LINUX_GL_FALLBACK:
        src = None
        for d in _LIB_DIRS:
            hits = glob.glob(os.path.join(d, name))
            if hits:
                src = os.path.realpath(hits[0])
                break
        if not src:
            continue
        dst = os.path.join(stage, name)
        shutil.copy2(src, dst)
        os.chmod(dst, 0o755)
        # $ORIGIN — сам каталог, $ORIGIN/.. — основной бандл: часть
        # зависимостей (libwayland, libexpat) лежит там.
        subprocess.run(['patchelf', '--set-rpath', '$ORIGIN:$ORIGIN/..', dst],
                       capture_output=True)
        found.append((f'gl_fallback/{name}', dst, 'BINARY'))

    print(f'[spec_common] запасных библиотек графики: {len(found)}')
    return found


def _is_never_bundled(name):
    return any(name.startswith(prefix) for prefix in LINUX_NEVER_BUNDLE)


# Каталог с helper-процессами внутри бандла. Имя короткое не случайно: оно
# записывается поверх вшитого пути в libwebkit2gtk, а туда влезает не больше
# байт, чем занимала исходная строка.
WEBKIT_HELPER_DIR = 'webkit_helpers'


def patch_webkit_exec_path(binaries):
    """Переписывает вшитый в WebKit путь к helper-процессам на относительный.

    WebKit рисует страницу и ведёт сеть отдельными процессами и запускает их по
    пути, зафиксированному при его сборке:
        /usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/WebKitNetworkProcess
    В системе пользователя этого каталога нет, и окно падает с
        Unable to spawn a new child process: Failed to spawn child process
    Переменная ``WEBKIT_EXEC_PATH`` не спасает: её читают только сборки с
    включённым режимом разработчика, а в дистрибутивных пакетах его нет — строки
    с таким именем в библиотеке попросту отсутствуют.

    Поэтому строка правится в нашей копии библиотеки. Заменяем её на
    относительный путь: абсолютный записать нельзя, так как каталог установки
    заранее неизвестен (DEB кладёт в /usr/lib, AppImage монтируется в /tmp со
    случайным именем), а места в строке ровно столько, сколько было. Остаток
    забиваем нулями — так строка и заканчивается для загрузчика.

    Относительный путь считается от текущего каталога, поэтому перед запуском
    окна процесс переходит в каталог бандла (см. rthook_gtk_linux.py).
    """
    if not sys.platform.startswith('linux'):
        return binaries

    import re

    stage = os.path.join(ROOT, 'build', 'webkit_patched')
    os.makedirs(stage, exist_ok=True)
    # Каталог WebKit в разных дистрибутивах называется по-разному, поэтому ищем
    # по образцу, а не по готовому списку путей.
    pattern = re.compile(
        rb'/usr/(?:lib|lib64|libexec|lib/[^\0]{1,40}?)/webkit2gtk-4\.[01]'
        rb'(/injected-bundle)?/?(?=\0)')

    patched = []
    for item in binaries:
        dest, src = item[0], item[1]
        name = os.path.basename(dest.replace('\\', '/'))
        if not name.startswith(('libwebkit2gtk-', 'libjavascriptcoregtk-')):
            patched.append(item)
            continue
        try:
            with open(src, 'rb') as fh:
                data = fh.read()
        except OSError:
            patched.append(item)
            continue

        hits = 0

        def _replace(match):
            nonlocal hits
            hits += 1
            suffix = match.group(1) or b''
            new = WEBKIT_HELPER_DIR.encode() + suffix
            # Строка обязана быть не длиннее исходной: следом в файле лежат
            # другие данные, сдвигать их нельзя.
            return new.ljust(len(match.group(0)), b'\0')

        data = pattern.sub(_replace, data)
        if not hits:
            patched.append(item)
            continue

        out = os.path.join(stage, name)
        with open(out, 'wb') as fh:
            fh.write(data)
        os.chmod(out, 0o755)
        print(f'[spec_common] путь helper-процессов в {name}: заменён '
              f'({hits} вхождений)')
        patched.append((item[0], out) + tuple(item[2:]))

    return patched


def collect_gtk_stack():
    """Собирает GTK, WebKit и их зависимости для вложения в приложение.

    Идёт от корневых библиотек и рекурсивно обходит их зависимости через
    ``ldd``: перечислять полный список руками бессмысленно — он различается
    между дистрибутивами и версиями, а забытая библиотека проявится только у
    пользователя.

    Возвращает записи TOC ``(dest, src, 'BINARY')``, а не пары ``(src, dest)``:
    загрузчик ищет библиотеку по имени вроде ``libfoo.so.0``, тогда как на диске
    лежит ``libfoo.so.0.1.2``, и имя внутри бандла нужно задать явно.
    """
    if not sys.platform.startswith('linux'):
        return []

    import glob
    import subprocess

    roots = []
    for pattern in ('libwebkit2gtk-4.1.so.0', 'libwebkit2gtk-4.0.so.37',
                    'libgtk-3.so.0', 'libgdk-3.so.0', 'librsvg-2.so.2',
                    'libgirepository-1.0.so.1'):
        for d in _LIB_DIRS:
            found = glob.glob(os.path.join(d, pattern))
            if found:
                roots.append(found[0])
                break

    if not roots:
        print('[spec_common] GTK/WebKit не найдены — окно будет искать их в системе')
        return []

    # Модули и helper-процессы кладутся в свои подкаталоги другими функциями, но
    # их зависимости нужно обойти здесь. Иначе, например, TLS-модуль GIO окажется
    # в сборке без libgnutls, и WebKit не откроет ни один https-адрес.
    deps_only = {os.path.realpath(p) for p in _module_paths()}

    # Обход в ширину: ldd выводит и косвенные зависимости, но полагаться на это
    # нельзя — у части библиотек он их не раскрывает.
    seen, queue, result = {}, list(roots) + sorted(deps_only), []
    while queue:
        lib = queue.pop()
        real = os.path.realpath(lib)
        if real in seen:
            continue
        seen[real] = True
        name = os.path.basename(lib)
        if not _is_never_bundled(name) and real not in deps_only:
            result.append((real, name))
        try:
            out = subprocess.run(['ldd', real], capture_output=True, text=True,
                                 timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for line in out.splitlines():
            parts = line.split(' => ')
            if len(parts) != 2:
                continue
            dep = parts[1].strip().split(' (')[0]
            if not dep or not os.path.isfile(dep):
                continue
            dep_name = os.path.basename(dep)
            if _is_never_bundled(dep_name):
                continue
            if os.path.realpath(dep) not in seen:
                queue.append(dep)

    # Загрузчик ищет библиотеку по её SONAME, а не по имени файла: в записи
    # зависимости стоит `libwebkit2gtk-4.1.so.0`, тогда как на диске лежит
    # `libwebkit2gtk-4.1.so.0.19.7`, а рядом ещё симлинк для сборки. Класть все
    # три имени — значит трижды скопировать 90 МБ, поэтому берём только SONAME.
    uniq = {}
    for src, dest in result:
        uniq[_soname(src) or dest] = src
    total = sum(os.path.getsize(s) for s in uniq.values() if os.path.isfile(s))
    print(f'[spec_common] в бандл GTK/WebKit: {len(uniq)} библиотек, '
          f'{total / 1024 / 1024:.0f} МБ')
    return [(dest, src, 'BINARY') for dest, src in sorted(uniq.items())]


def _soname(path):
    """SONAME библиотеки — имя, по которому её найдёт загрузчик."""
    import re
    import subprocess

    try:
        out = subprocess.run(['objdump', '-p', path], capture_output=True,
                             text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'^\s*SONAME\s+(\S+)', out, re.MULTILINE)
    return match.group(1) if match else None


_LIB_DIRS = (
    '/usr/lib/x86_64-linux-gnu',
    '/usr/lib64',
    '/usr/lib',
    '/lib/x86_64-linux-gnu',
)


def _module_paths():
    """Подгружаемые модули и helper-процессы WebKit.

    Сами они укладываются в отдельные каталоги, но их зависимости должны попасть
    в общий бандл: модуль TLS без libgnutls бесполезен, а helper-процесс WebKit
    без своих библиотек не запустится и окно останется пустым.
    """
    import glob

    paths = []
    for pattern in ('gio/modules/*.so', 'gdk-pixbuf-2.0/*/loaders/*.so',
                    'webkit2gtk-4.1/*', 'webkit2gtk-4.0/*'):
        for d in _LIB_DIRS:
            hits = glob.glob(os.path.join(d, pattern))
            if hits:
                paths.extend(p for p in hits if os.path.isfile(p))
                break
    return paths


def collect_gtk_support_files():
    """Файлы, без которых вложенный GTK не работает.

    Библиотек недостаточно: GTK и WebKit подгружают модули и данные с диска, и
    каждый из них ищется по своему пути. Без них окно либо не открывается, либо
    остаётся без картинок и шрифтов.
    """
    if not sys.platform.startswith('linux'):
        return []

    import glob
    found = []

    # Typelib: описания ABI для gi. Без них gi.require_version падает сразу.
    for d in ('/usr/lib/x86_64-linux-gnu/girepository-1.0',
              '/usr/lib64/girepository-1.0', '/usr/lib/girepository-1.0'):
        if not os.path.isdir(d):
            continue
        for f in glob.glob(os.path.join(d, '*.typelib')):
            found.append((f, 'gi_typelibs'))
        break

    # Модули GIO: через них идут TLS-соединения и настройки. Без gnutls-модуля
    # WebKit не открывает https.
    for d in ('/usr/lib/x86_64-linux-gnu/gio/modules',
              '/usr/lib64/gio/modules', '/usr/lib/gio/modules'):
        if os.path.isdir(d):
            for f in glob.glob(os.path.join(d, '*.so')):
                found.append((f, 'gio_modules'))
            break

    # Загрузчики gdk-pixbuf: без них не отображается ни один PNG или SVG.
    for pattern in ('/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/*/loaders/*.so',
                    '/usr/lib64/gdk-pixbuf-2.0/*/loaders/*.so'):
        for f in glob.glob(pattern):
            found.append((f, 'gdk_pixbuf/loaders'))
    for pattern in ('/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/*/loaders.cache',
                    '/usr/lib64/gdk-pixbuf-2.0/*/loaders.cache'):
        for f in glob.glob(pattern):
            found.append((f, 'gdk_pixbuf'))

    # Схемы GSettings в скомпилированном виде: GTK читает их при старте и без
    # них падает с «Settings schema not installed».
    for d in ('/usr/share/glib-2.0/schemas',):
        cache = os.path.join(d, 'gschemas.compiled')
        if os.path.isfile(cache):
            found.append((cache, 'glib_schemas'))

    # Данные WebKit: локали и словари переносов.
    for d in ('/usr/share/webkit2gtk-4.1', '/usr/share/webkit2gtk-4.0'):
        if os.path.isdir(d):
            for root, _dirs, files in os.walk(d):
                rel = os.path.relpath(root, d)
                for fn in files:
                    dest = os.path.join('webkit_data',
                                        '' if rel == '.' else rel)
                    found.append((os.path.join(root, fn), dest))
            break

    # Сертификаты: без них WebKit считает недоверенным каждый https-узел.
    for ca in ('/etc/ssl/certs/ca-certificates.crt',
               '/etc/pki/tls/certs/ca-bundle.crt'):
        if os.path.isfile(ca):
            found.append((ca, 'ssl_certs'))
            break

    # Тема значков и настройки шрифтов: иначе интерфейс без иконок, а текст
    # отрисовывается без сглаживания.
    if os.path.isfile('/usr/share/icons/Adwaita/index.theme'):
        found.append(('/usr/share/icons/Adwaita/index.theme',
                      'icons/Adwaita'))
    for d in ('/etc/fonts',):
        if os.path.isdir(d):
            for root, _dirs, files in os.walk(d):
                rel = os.path.relpath(root, d)
                for fn in files:
                    if fn.endswith(('.conf', '.dtd')):
                        found.append((os.path.join(root, fn),
                                      os.path.join('fontconfig',
                                                   '' if rel == '.' else rel)))

    print(f'[spec_common] в бандл файлов поддержки GTK: {len(found)}')
    # Записи TOC ``(dest, src, 'DATA')``: списки a.datas после Analysis уже
    # нормализованы, и пары ``(src, dest)`` в них не принимаются.
    return [(os.path.join(dest, os.path.basename(src)), src, 'DATA')
            for src, dest in found]


def collect_webkit_helpers():
    """Вспомогательные процессы WebKit.

    WebKit запускает отрисовку и сеть отдельными процессами
    (WebKitWebProcess, WebKitNetworkProcess). Это исполняемые файлы, а не
    библиотеки: PyInstaller их не видит, и без них окно открывается пустым —
    страница никогда не загружается.
    """
    if not sys.platform.startswith('linux'):
        return []

    import glob
    # MiniBrowser — демонстрационный браузер из состава WebKitGTK. Приложению
    # не нужен, а весит заметно.
    skip = {'MiniBrowser'}
    found = []
    for pattern in ('/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/*',
                    '/usr/lib/x86_64-linux-gnu/webkit2gtk-4.0/*',
                    '/usr/lib64/webkit2gtk-4.1/*',
                    '/usr/libexec/webkit2gtk-4.1/*'):
        for path in glob.glob(pattern):
            if os.path.basename(path) in skip:
                continue
            if os.path.isfile(path):
                found.append((path, 'webkit_helpers'))
            elif os.path.isdir(path):
                for root, _dirs, files in os.walk(path):
                    rel = os.path.relpath(root, os.path.dirname(path))
                    for fn in files:
                        found.append((os.path.join(root, fn),
                                      os.path.join('webkit_helpers', rel)))
        if found:
            break
    print(f'[spec_common] в бандл helper-процессов WebKit: {len(found)}')
    # BINARY, а не DATA: PyInstaller правит таким файлам RPATH, и без этого
    # helper-процесс искал бы библиотеки в системе, а не рядом с собой.
    return [(os.path.join(dest, os.path.basename(src)), src, 'BINARY')
            for src, dest in found]


def collect_hidden_imports():
    """Скрытые импорты вместе с зависимостями yt-dlp."""
    from PyInstaller.utils.hooks import collect_submodules

    third_party = list(HIDDEN_THIRD_PARTY)
    # gi.repository нужен только на Linux (WebKit через GObject Introspection);
    # на Windows используется cefpython3, а pywebview там работает иначе.
    if sys.platform != 'win32':
        hidden = list(HIDDEN_PROJECT_MODULES) + third_party
    else:
        hidden = list(HIDDEN_PROJECT_MODULES) + [p for p in third_party
                                                  if not p.startswith('gi')]
    # yt-dlp находит экстракторы по имени модуля во время работы, поэтому все
    # подмодули надо перечислить: иначе в сборке отсутствовал бы экстрактор
    # YouTube, хотя сам yt-dlp на месте.
    hidden += collect_submodules('yt_dlp')
    return hidden


def collect_binaries():
    """Бинарные зависимости yt-dlp (их немного, но они есть).

    GTK и WebKit собираются отдельно, уже после Analysis, см.
    ``collect_gtk_stack``: хуки PyInstaller дополняют списки после сбора, и
    добавленное ими иначе не попало бы под обработку.
    """
    from PyInstaller.utils.hooks import collect_dynamic_libs

    return collect_dynamic_libs('yt_dlp')


def runtime_hooks():
    """Хуки, исполняемые до кода приложения.

    Вложенный GTK не находит свои модули сам: пути к ним вшиты в библиотеки при
    сборке и указывают на каталоги дистрибутива. Хук переводит их на файлы
    бандла до первого импорта gi.
    """
    if not sys.platform.startswith('linux'):
        return []
    hook = os.path.join(ROOT, 'packaging', 'rthook_gtk_linux.py')
    return [hook] if os.path.isfile(hook) else []


def icon_path():
    """Иконка для исполняемого файла или None.

    Windows берёт .ico из ресурсов exe. На Linux PyInstaller иконку в файл не
    вшивает вовсе, поэтому передавать её там бессмысленно.
    """
    if sys.platform != 'win32':
        return None
    candidate = os.path.join(ASSETS, 'localtube.ico')
    return candidate if os.path.isfile(candidate) else None


def version_file():
    """Путь к файлу с версией для ресурсов Windows или None.

    Без этого файла в свойствах exe пусто, а SmartScreen и антивирусы относятся
    к безымянным исполняемым файлам заметно хуже.
    """
    if sys.platform != 'win32':
        return None
    import version as app_version

    path = os.path.join(ROOT, 'build', 'file_version_info.txt')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    major, minor, patch = app_version.version_tuple()[:3]
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', '{app_version.APP_AUTHOR}'),
         StringStruct('FileDescription', '{app_version.APP_DESCRIPTION}'),
         StringStruct('FileVersion', '{app_version.__version__}'),
         StringStruct('InternalName', '{app_version.APP_NAME}'),
         StringStruct('OriginalFilename', '{app_version.APP_NAME}.exe'),
         StringStruct('ProductName', '{app_version.APP_NAME}'),
         StringStruct('ProductVersion', '{app_version.__version__}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


def entry_script():
    """Точка входа: оконная оболочка, а не app.py.

    app.py поднимает сервер разработки Werkzeug и печатает адрес в консоль.
    desktop.py открывает настоящее окно и держит сервер в фоне, поэтому именно
    он и есть входной файл собранного приложения.
    """
    return os.path.join(ROOT, 'desktop.py')
