#!/usr/bin/env python3
"""build_windows.py — собирает артефакты для Windows.

Один вход для всех вариантов: обычная сборка каталогом (для ZIP и MSI),
портативный один файл и MSI-установщик. Скрипт нужен, чтобы шаги не разъезжались
между локальной сборкой и CI: раньше порядок действий существовал только внутри
workflow, и собрать релиз у себя было нельзя.

Запуск:
    python packaging\\build_windows.py --targets zip,portable,msi
    python packaging\\build_windows.py --targets zip --no-ffmpeg
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import version as app_version  # noqa: E402

# Версия WiX: ставится как dotnet-инструмент. Фиксируем мажорную версию, потому
# что схема .wxs между 4 и 5 несовместима, а make_wxs генерирует схему v4.
WIX_PACKAGE = 'wix'
WIX_VERSION = '4.0.5'


def _run(cmd, **kwargs):
    print('  $', ' '.join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, **kwargs)


def _dist_dir(out_dir):
    return os.path.join(out_dir, 'dist')


def _work_dir(out_dir):
    return os.path.join(out_dir, 'build')


def fetch_ffmpeg(arch):
    """Кладёт ffmpeg в packaging/assets/ffmpeg, если его там ещё нет."""
    import fetch_ffmpeg as fetcher

    target = fetcher.TARGET_DIR
    if os.path.isdir(target) and any(
            name.startswith('ffmpeg') for name in os.listdir(target)):
        print('ffmpeg уже подготовлен, пропускаю загрузку')
        return
    fetcher.fetch('windows', arch, target)


def ensure_icons():
    """Создаёт иконки, если их нет: они не хранятся в репозитории готовыми."""
    import make_icons

    icon = os.path.join(_HERE, 'assets', 'localtube.ico')
    if os.path.isfile(icon):
        return
    make_icons.write_icons(os.path.join(_HERE, 'assets'))


def run_pyinstaller(spec_name, out_dir):
    """Запускает PyInstaller для указанного спека."""
    spec = os.path.join(_HERE, spec_name)
    _run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
          '--distpath', _dist_dir(out_dir),
          '--workpath', _work_dir(out_dir),
          spec], cwd=_ROOT)


def build_zip(out_dir, arch):
    """Архив с обычной сборкой.

    Внутрь кладётся portable.txt: распакованный ZIP ведёт себя как портативная
    версия и держит данные рядом с собой. Без маркера архив писал бы библиотеку
    в профиль пользователя, и перенос папки на другой компьютер терял данные.
    """
    app_dir = os.path.join(_dist_dir(out_dir), app_version.APP_NAME)
    if not os.path.isdir(app_dir):
        raise RuntimeError(f'нет сборки: {app_dir}')

    marker = os.path.join(app_dir, 'portable.txt')
    with open(marker, 'w', encoding='utf-8') as f:
        f.write('Данные приложения хранятся в этой папке.\n')

    out_path = os.path.join(
        out_dir, f'{app_version.APP_NAME}-windows-{arch}.zip')
    if os.path.exists(out_path):
        os.remove(out_path)

    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for current, _dirs, files in os.walk(app_dir):
            for name in sorted(files):
                full = os.path.join(current, name)
                rel = os.path.join(app_version.APP_NAME,
                                   os.path.relpath(full, app_dir))
                zf.write(full, rel)
    return out_path


def build_portable(out_dir, arch, spec_name='localtube-portable.spec'):
    """Портативный exe одним файлом.

    spec_name: имя .spec для портативной сборки. Обычно localtube-portable.spec,
    но для legacy-сборок (Windows 7) используется localtube-legacy-portable.spec,
    который включает cefpython3.
    """
    run_pyinstaller(spec_name, out_dir)
    source = os.path.join(_dist_dir(out_dir),
                          f'{app_version.APP_NAME}-portable.exe')
    if not os.path.isfile(source):
        raise RuntimeError('portable exe не собран')

    out_path = os.path.join(
        out_dir, f'{app_version.APP_NAME}-portable-windows-{arch}.exe')
    shutil.copy2(source, out_path)

    # Маркер портативности рядом с exe: сам exe его не содержит, потому что
    # paths.is_portable проверяет файл возле программы, а не внутри бандла —
    # внутри onefile всё равно временный каталог, который удаляется при выходе.
    marker = os.path.join(out_dir, 'portable.txt')
    with open(marker, 'w', encoding='utf-8') as f:
        f.write('Положите этот файл рядом с LocalTube-portable.exe,\n'
                'чтобы данные хранились в той же папке.\n')
    return out_path


# WiX 3: работает на .NET Framework, который есть в Windows из коробки, и
# запускается из распакованного архива. Нужен как запасной путь, потому что WiX 4
# ставится только через dotnet-инструмент и требует .NET SDK: на машине с одним
# рантаймом (и без прав администратора) собрать MSI иначе невозможно.
WIX3_ENV = 'WIX3_BIN'
WIX3_TOOLS = ('candle.exe', 'light.exe')


def _wix3_dir():
    """Каталог с candle.exe и light.exe или None.

    Порядок поиска: переменная окружения, PATH, стандартные каталоги установки
    WiX 3. Переменная нужна для распакованного архива wix314-binaries.zip,
    который никуда не регистрируется.
    """
    explicit = os.environ.get(WIX3_ENV)
    candidates = []
    if explicit:
        candidates.append(explicit)

    from_path = shutil.which('candle')
    if from_path:
        candidates.append(os.path.dirname(from_path))

    wix_root = os.environ.get('WIX')
    if wix_root:
        candidates.append(os.path.join(wix_root, 'bin'))

    program_files = os.environ.get('ProgramFiles(x86)') or os.environ.get('ProgramFiles')
    if program_files:
        for release in ('3.14', '3.11'):
            candidates.append(os.path.join(
                program_files, f'WiX Toolset v{release}', 'bin'))

    for directory in candidates:
        if all(os.path.isfile(os.path.join(directory, tool))
               for tool in WIX3_TOOLS):
            return directory
    return None


def _wix_command():
    """Путь к WiX 4 или None, если поставить его нельзя.

    Раньше функция бросала исключение при отсутствии .NET SDK, и сборка MSI
    заканчивалась на этом. Теперь отсутствие v4 — не ошибка: вызывающий код
    переходит на WiX 3.
    """
    existing = shutil.which('wix')
    if existing:
        return existing

    if not shutil.which('dotnet'):
        return None

    # dotnet без SDK умеет только запускать приложения: установка инструмента
    # завершится ошибкой «No .NET SDKs were found», поэтому проверяем заранее.
    try:
        probe = subprocess.run(['dotnet', '--list-sdks'],
                               capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if probe.returncode != 0 or not probe.stdout.strip():
        return None

    print('WiX не найден, устанавливаю как dotnet-инструмент')
    _run(['dotnet', 'tool', 'install', '--global',
          WIX_PACKAGE, '--version', WIX_VERSION])

    # Каталог инструментов появляется в PATH только для новых процессов,
    # поэтому в текущем сеансе путь приходится собрать вручную.
    candidate = os.path.join(os.path.expanduser('~'), '.dotnet', 'tools', 'wix.exe')
    if os.path.isfile(candidate):
        return candidate
    return shutil.which('wix')


def _build_msi_with_wix3(wix3_dir, app_dir, out_dir, out_path, arch):
    """Сборка MSI парой candle + light из WiX 3."""
    import make_wxs

    wxs_path = os.path.join(_work_dir(out_dir), 'LocalTube-v3.wxs')
    make_wxs.main(['--source', app_dir, '--out', wxs_path,
                   '--wix-version', '3', '--arch', arch])

    wixobj = os.path.join(_work_dir(out_dir), 'LocalTube-v3.wixobj')
    _run([os.path.join(wix3_dir, 'candle.exe'),
          '-arch', arch, '-nologo', '-out', wixobj, wxs_path])
    # ICE-проверки validation отключаем: они требуют установленного Windows
    # Installer SDK, а на его отсутствие light падает предупреждением-ошибкой.
    _run([os.path.join(wix3_dir, 'light.exe'),
          '-nologo', '-sval', '-out', out_path, wixobj])
    return out_path


def build_msi(out_dir, arch):
    """MSI-установщик через WiX."""
    import make_wxs

    app_dir = os.path.join(_dist_dir(out_dir), app_version.APP_NAME)
    if not os.path.isdir(app_dir):
        raise RuntimeError(f'нет сборки: {app_dir}')

    # portable.txt не должен попасть в установщик: с ним установленная версия
    # писала бы данные в Program Files, куда обычному пользователю доступа нет.
    marker = os.path.join(app_dir, 'portable.txt')
    if os.path.exists(marker):
        os.remove(marker)

    out_path = os.path.join(
        out_dir, f'{app_version.APP_NAME}-{app_version.__version__}-{arch}.msi')
    # x64 против x86: разрядность пакета должна совпадать со сборкой, иначе
    # 64-битное приложение установится в Program Files (x86).
    platform = 'x64' if arch == 'x64' else 'x86'

    wix = _wix_command()
    if wix:
        wxs_path = os.path.join(_work_dir(out_dir), 'LocalTube.wxs')
        make_wxs.main(['--source', app_dir, '--out', wxs_path])
        _run([wix, 'build', '-arch', platform, '-o', out_path, wxs_path])
        return out_path

    wix3_dir = _wix3_dir()
    if wix3_dir:
        print('WiX 4 недоступен (нужен .NET SDK), собираю через WiX 3')
        return _build_msi_with_wix3(wix3_dir, app_dir, out_dir, out_path,
                                    platform)

    raise RuntimeError(
        'нужен WiX: либо .NET SDK для WiX 4 '
        '(https://dotnet.microsoft.com/download), либо WiX 3 — распакуйте '
        'wix314-binaries.zip и укажите путь в переменной ' + WIX3_ENV)


TARGETS = ('zip', 'portable', 'msi')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Сборка LocalTube для Windows')
    parser.add_argument('--targets', default='zip,portable,msi',
                        help='Через запятую: ' + ', '.join(TARGETS))
    parser.add_argument('--arch', default='x64', choices=['x64', 'x86'])
    parser.add_argument('--out', default=os.path.join(_ROOT, 'release'))
    parser.add_argument('--spec', default='localtube.spec',
                        help='Спек для основной сборки (для legacy — '
                             'localtube-legacy.spec)')
    parser.add_argument('--no-ffmpeg', action='store_true',
                        help='Не вкладывать ffmpeg в сборку')
    args = parser.parse_args(argv)

    requested = [t.strip() for t in args.targets.split(',') if t.strip()]
    unknown = [t for t in requested if t not in TARGETS]
    if unknown:
        print(f'Неизвестные цели: {", ".join(unknown)}', file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    ensure_icons()
    if not args.no_ffmpeg:
        try:
            fetch_ffmpeg(args.arch)
        except Exception as e:
            # Сборка без вложенного ffmpeg рабочая: приложение возьмёт его из
            # PATH. Прерывать релиз из-за недоступного зеркала не стоит.
            print(f'[!] ffmpeg не вложен: {e}', file=sys.stderr)

    # Обычная сборка нужна и для ZIP, и для MSI: делаем её один раз.
    if 'zip' in requested or 'msi' in requested:
        run_pyinstaller(args.spec, args.out)

    built, failed = [], []
    # Порядок важен: ZIP добавляет portable.txt, а MSI его удаляет, поэтому MSI
    # должен собираться последним.
    for target in ('zip', 'portable', 'msi'):
        if target not in requested:
            continue
        print(f'\n=== {target} ===')
        try:
            if target == 'zip':
                built.append(build_zip(args.out, args.arch))
            elif target == 'portable':
                if args.spec == 'localtube-legacy.spec':
                    built.append(build_portable(
                        args.out, args.arch, 'localtube-legacy-portable.spec'))
                else:
                    built.append(build_portable(args.out, args.arch))
            elif target == 'msi':
                built.append(build_msi(args.out, args.arch))
        except (OSError, subprocess.CalledProcessError, RuntimeError) as e:
            print(f'[!] {target} не собран: {e}', file=sys.stderr)
            failed.append(target)

    print('\nГотово:')
    for path in built:
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f'  {os.path.basename(path)} ({size_mb:.1f} МБ)')
    if failed:
        print(f'Не собрано: {", ".join(failed)}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
