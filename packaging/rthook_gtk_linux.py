#!/usr/bin/env python3
"""rthook_gtk_linux.py — направляет вложенный GTK/WebKit на файлы бандла.

PyInstaller исполняет этот файл до основного кода приложения. Здесь
выставляются переменные окружения, по которым GTK, GLib и WebKit находят свои
модули и данные.

Одних библиотек в каталоге недостаточно: каждая часть стека ищет своё
хозяйство по отдельному пути, и путь этот компилируется в библиотеку при её
сборке. Внутри бандла файлы лежат в других местах, поэтому пути приходится
переопределять — иначе окно либо не открывается, либо остаётся без картинок,
шрифтов и защищённых соединений.

Переменные выставляются только когда рядом действительно лежит вложенный
стек: сборка без него должна продолжать работать на системном GTK.
"""
import os
import sys


def _bundle_dir():
    """Каталог с распакованным бандлом или None, если запуск из исходников."""
    if not getattr(sys, 'frozen', False):
        return None
    return getattr(sys, '_MEIPASS', None) or os.path.dirname(sys.executable)


def _setup():
    base = _bundle_dir()
    if not base or not sys.platform.startswith('linux'):
        return

    typelibs = os.path.join(base, 'gi_typelibs')
    if not os.path.isdir(typelibs):
        # Вложенного стека нет: работаем на системном GTK, ничего не меняем.
        return

    def prepend(var, value):
        """Наш путь идёт первым, системный сохраняется после него."""
        current = os.environ.get(var)
        os.environ[var] = f'{value}:{current}' if current else value

    # gi ищет описания ABI только здесь. Без этого gi.require_version падает.
    prepend('GI_TYPELIB_PATH', typelibs)

    # Загрузчик должен видеть вложенные библиотеки. Наш каталог первым:
    # системные GTK и WebKit собраны другим компилятором, и смешивать их с
    # нашими нельзя — именно на этом падала предыдущая сборка.
    prepend('LD_LIBRARY_PATH', base)

    gio_modules = os.path.join(base, 'gio_modules')
    if os.path.isdir(gio_modules):
        # Через модули GIO идут TLS-соединения: без gnutls-модуля WebKit не
        # открывает ни один https-адрес.
        os.environ['GIO_MODULE_DIR'] = gio_modules
        os.environ['GIO_EXTRA_MODULES'] = gio_modules

    pixbuf_cache = os.path.join(base, 'gdk_pixbuf', 'loaders.cache')
    if os.path.isfile(pixbuf_cache):
        # Кэш перечисляет загрузчики изображений с путями сборочной машины.
        # Перепишем пути на наши, иначе не отрисуется ни один PNG или SVG.
        fixed = os.path.join(base, 'gdk_pixbuf', 'loaders.cache.local')
        loaders_dir = os.path.join(base, 'gdk_pixbuf', 'loaders')
        if not os.path.isfile(fixed):
            try:
                with open(pixbuf_cache, encoding='utf-8') as src:
                    text = src.read()
                lines = []
                for line in text.splitlines():
                    if line.startswith('"') and '.so"' in line:
                        name = os.path.basename(line.strip().strip('"'))
                        lines.append(f'"{os.path.join(loaders_dir, name)}"')
                    else:
                        lines.append(line)
                with open(fixed, 'w', encoding='utf-8') as dst:
                    dst.write('\n'.join(lines) + '\n')
            except OSError:
                fixed = pixbuf_cache
        os.environ['GDK_PIXBUF_MODULE_FILE'] = fixed
        os.environ['GDK_PIXBUF_MODULEDIR'] = loaders_dir

    schemas = os.path.join(base, 'glib_schemas')
    if os.path.isfile(os.path.join(schemas, 'gschemas.compiled')):
        # Без схем GTK падает с «Settings schema is not installed».
        prepend('XDG_DATA_DIRS', os.path.dirname(schemas))
        os.environ['GSETTINGS_SCHEMA_DIR'] = schemas

    helpers = os.path.join(base, 'webkit_helpers')
    if os.path.isdir(helpers):
        # WebKit запускает отрисовку и сеть отдельными процессами. Путь к ним
        # вшит в библиотеку при сборке и в нашей копии заменён на относительный
        # (см. spec_common.patch_webkit_exec_path), поэтому процесс должен
        # работать из каталога бандла — иначе WebKit не найдёт helper и падает с
        # «Unable to spawn a new child process».
        #
        # WEBKIT_EXEC_PATH здесь бесполезна: её читают только сборки WebKit с
        # включённым режимом разработчика, чего в дистрибутивных пакетах нет.
        try:
            os.chdir(base)
        except OSError:
            pass

        for root, _dirs, files in os.walk(helpers):
            for name in files:
                path = os.path.join(root, name)
                if not os.access(path, os.X_OK):
                    # Бит выполнения теряется при упаковке в архив.
                    try:
                        os.chmod(path, 0o755)
                    except OSError:
                        pass

    webkit_data = os.path.join(base, 'webkit_data')
    if os.path.isdir(webkit_data):
        os.environ.setdefault('WEBKIT_INJECTED_BUNDLE_PATH', helpers)
        prepend('XDG_DATA_DIRS', webkit_data)

    certs = os.path.join(base, 'ssl_certs', 'ca-certificates.crt')
    if os.path.isfile(certs):
        # Иначе WebKit считает недоверенным каждый https-узел.
        os.environ.setdefault('SSL_CERT_FILE', certs)
        os.environ.setdefault('CA_CERTIFICATES', certs)

    fonts = os.path.join(base, 'fontconfig', 'fonts.conf')
    if os.path.isfile(fonts):
        # Сами шрифты берём системные: они у пользователя лучше. Нужна только
        # конфигурация, иначе текст рисуется без сглаживания.
        os.environ.setdefault('FONTCONFIG_FILE', fonts)
        os.environ.setdefault('FONTCONFIG_PATH', os.path.dirname(fonts))

    # Аппаратное ускорение отключаем: драйверы у пользователя свои, а наш
    # WebKit собран с другой версией Mesa — на несовпадении окно падало.
    os.environ.setdefault('WEBKIT_DISABLE_COMPOSITING_MODE', '1')
    os.environ.setdefault('WEBKIT_DISABLE_DMABUF_RENDERER', '1')

    _ensure_gl(base)


_GL_FLAG = 'LOCALTUBE_GL_FALLBACK'


def _ensure_gl(base):
    """Подключает запасные библиотеки графики, если системных нет.

    WebKit слинкован с libGL и libEGL: когда файлов нет, загрузчик не открывает
    libwebkit2gtk вовсе, и приложение падает на импорте с «undefined symbol:
    webkit_get_major_version» — библиотека осталась незагруженной, а не
    потеряла символ.

    Своя копия лежит в отдельном каталоге, а не рядом с остальными: положить её
    в общий каталог значило бы перекрыть драйвер видеокарты пользователя,
    собранный под его ядро.

    Подключить каталог простым изменением LD_LIBRARY_PATH нельзя: загрузчик
    читает эту переменную один раз при старте процесса, и правка из Python на
    него уже не влияет. Поэтому процесс перезапускается с новым окружением.
    Происходит это только там, где libGL отсутствует, — на обычном рабочем столе
    проверка ничего не делает.
    """
    gl_dir = os.path.join(base, 'gl_fallback')
    if not os.path.isdir(gl_dir):
        return
    if os.environ.get(_GL_FLAG):
        # Перезапуск уже был: второй раз ничего не даст, а зацикливаться нельзя.
        return
    if _has_system_gl():
        return

    os.environ[_GL_FLAG] = '1'
    current = os.environ.get('LD_LIBRARY_PATH')
    # В конец: если система всё же что-то предоставит, предпочтение за ней.
    os.environ['LD_LIBRARY_PATH'] = (
        f'{current}:{gl_dir}' if current else gl_dir)
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv[1:])
    except OSError:
        # Перезапуск не удался — продолжаем и позволяем упасть с внятной
        # ошибкой загрузчика, а не с молчанием.
        os.environ.pop(_GL_FLAG, None)


def _has_system_gl():
    """Есть ли в системе libGL — признак установленных драйверов.

    Смотрим файлы и кэш загрузчика, но не пробуем загрузить: загрузка
    потянула бы драйвер в процесс до того, как настроены пути.
    """
    import glob

    for pattern in ('/usr/lib/x86_64-linux-gnu/libGL.so.1',
                    '/usr/lib64/libGL.so.1',
                    '/usr/lib/libGL.so.1',
                    '/usr/lib/*-linux-gnu/libGL.so.1',
                    '/lib/x86_64-linux-gnu/libGL.so.1'):
        if glob.glob(pattern):
            return True

    # Дистрибутив мог положить библиотеку в нестандартный каталог: он известен
    # кэшу загрузчика, но не нашему списку путей.
    try:
        import subprocess
        out = subprocess.run(['/sbin/ldconfig', '-p'], capture_output=True,
                             text=True, timeout=10).stdout
        return 'libGL.so.1' in out
    except (OSError, subprocess.SubprocessError):
        return False


_setup()
