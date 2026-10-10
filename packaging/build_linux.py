#!/usr/bin/env python3
"""build_linux.py — собирает DEB, RPM, AppImage и tar.gz из готовой сборки.

Скрипт запускается после PyInstaller и работает с каталогом ``dist/LocalTube``.
Он не собирает приложение сам: PyInstaller должен вызываться отдельно, чтобы
одну и ту же сборку можно было упаковать во все форматы без повторной сборки.

Раскладка внутри пакетов подчиняется FHS, а не удобству: приложение целиком
кладётся в ``/usr/lib/localtube`` (это не библиотеки, но и не исполняемые файлы
для прямого запуска — именно так поступают Firefox и Chrome), а в ``/usr/bin``
идёт символьная ссылка. Иконки и ``.desktop`` — в ``/usr/share``, иначе рабочий
стол не покажет приложение в меню.

Каталог установки только для чтения, поэтому данные приложение пишет в
``~/.local/share/localtube`` — этим занимается ``paths.data_dir``.

Запуск:
    python3 packaging/build_linux.py --source dist/LocalTube --formats deb,rpm,appimage,targz
"""
import argparse
import gzip
import os
import shutil
import stat
import subprocess
import sys
import tarfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import version as app_version  # noqa: E402

PKG_NAME = 'localtube'
INSTALL_ROOT = f'/usr/lib/{PKG_NAME}'
ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)

# Зависимостей уровня системы у пакета нет: GTK, WebKitGTK, GObject-биндинги и
# всё, на что они опираются, лежат внутри (см. spec_common.collect_gtk_stack).
# Приложение запускается и там, где графический стек не установлен вовсе.
#
# Требовать WebKit от системы было бы и лишним, и вредным: версии в
# дистрибутивах расходятся, а pywebview 6 работает только с 2.40+, где есть
# webkit_web_view_evaluate_javascript. На Debian 11 и Ubuntu 20.04 WebKit
# старее, и установка пакета там просто не проходила бы.
#
# Остаётся только glibc: её вложить нельзя, она неразделима с загрузчиком
# ld.so. Версия сборочной машины (Ubuntu 22.04 → 2.35) и становится
# требованием. dpkg-shlibdeps подставит точное значение сам, поэтому в списке
# пусто.
DEB_DEPENDS = []
RPM_REQUIRES = []


def _run(cmd, **kwargs):
    """Запускает команду, показывая её: сборочные логи иначе нечитаемы."""
    print('  $', ' '.join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, **kwargs)


def _copy_tree(source, target):
    os.makedirs(os.path.dirname(target.rstrip('/')), exist_ok=True)
    shutil.copytree(source, target, symlinks=True)


def _desktop_entry():
    """Содержимое .desktop-файла.

    StartupWMClass обязателен: без него GNOME и KDE считают окно приложения
    отдельным от значка в меню, и в панели задач появлялся второй безымянный
    элемент вместо подсветки уже запущенного.
    """
    return f"""[Desktop Entry]
Type=Application
Name={app_version.APP_NAME}
Comment={app_version.APP_DESCRIPTION}
Exec={PKG_NAME} %U
Icon={PKG_NAME}
Terminal=false
Categories=AudioVideo;Video;Player;
Keywords=video;youtube;library;player;
StartupNotify=true
StartupWMClass={app_version.APP_NAME}
"""


def _launcher_script():
    """Скрипт-обёртка в /usr/bin.

    Прямая символьная ссылка на исполняемый файл не годится: PyInstaller в
    режиме onedir определяет каталог с ресурсами по пути к своему файлу, и через
    ссылку из /usr/bin он искал бы их в /usr, где ничего нет.
    """
    return f"""#!/bin/sh
# Обёртка для запуска LocalTube из /usr/bin.
exec "{INSTALL_ROOT}/{app_version.APP_NAME}" "$@"
"""


def stage(source, staging):
    """Раскладывает файлы так, как они должны лежать в системе."""
    if os.path.isdir(staging):
        shutil.rmtree(staging)

    app_target = os.path.join(staging, INSTALL_ROOT.lstrip('/'))
    _copy_tree(source, app_target)

    # Бит выполнения: copytree его сохраняет, но архивы и CI иногда теряют, а
    # без него пакет устанавливается и не запускается.
    main_binary = os.path.join(app_target, app_version.APP_NAME)
    if os.path.isfile(main_binary):
        os.chmod(main_binary, 0o755)
    bundled_bin = os.path.join(app_target, '_internal', 'bin')
    if os.path.isdir(bundled_bin):
        for name in os.listdir(bundled_bin):
            os.chmod(os.path.join(bundled_bin, name), 0o755)

    bin_dir = os.path.join(staging, 'usr', 'bin')
    os.makedirs(bin_dir, exist_ok=True)
    launcher = os.path.join(bin_dir, PKG_NAME)
    with open(launcher, 'w', encoding='utf-8', newline='\n') as f:
        f.write(_launcher_script())
    os.chmod(launcher, 0o755)

    desktop_dir = os.path.join(staging, 'usr', 'share', 'applications')
    os.makedirs(desktop_dir, exist_ok=True)
    with open(os.path.join(desktop_dir, f'{app_version.APP_ID}.desktop'),
              'w', encoding='utf-8', newline='\n') as f:
        f.write(_desktop_entry())

    assets = os.path.join(_HERE, 'assets')
    for size in ICON_SIZES:
        icon = os.path.join(assets, f'localtube-{size}.png')
        if not os.path.isfile(icon):
            continue
        icon_dir = os.path.join(staging, 'usr', 'share', 'icons', 'hicolor',
                                f'{size}x{size}', 'apps')
        os.makedirs(icon_dir, exist_ok=True)
        shutil.copy2(icon, os.path.join(icon_dir, f'{PKG_NAME}.png'))

    # Лицензия и README: требование политики пакетов и в Debian, и в Fedora.
    doc_dir = os.path.join(staging, 'usr', 'share', 'doc', PKG_NAME)
    os.makedirs(doc_dir, exist_ok=True)
    for name in ('LICENSE', 'README.md'):
        candidate = os.path.join(_ROOT, name)
        if os.path.isfile(candidate):
            shutil.copy2(candidate, os.path.join(doc_dir, name))

    return staging


def _installed_size_kb(staging):
    total = 0
    for current, _dirs, files in os.walk(staging):
        for name in files:
            path = os.path.join(current, name)
            if not os.path.islink(path):
                total += os.path.getsize(path)
    return max(1, total // 1024)


def build_deb(staging, out_dir, arch='amd64'):
    """Собирает .deb через dpkg-deb."""
    control_dir = os.path.join(staging, 'DEBIAN')
    os.makedirs(control_dir, exist_ok=True)

    # Пустое поле Depends недопустимо в формате control, поэтому строка
    # появляется только когда зависимости действительно есть.
    depends = f"Depends: {', '.join(DEB_DEPENDS)}\n" if DEB_DEPENDS else ''
    control = f"""Package: {PKG_NAME}
Version: {app_version.__version__}
Section: video
Priority: optional
Architecture: {arch}
{depends}Maintainer: {app_version.APP_AUTHOR}
Installed-Size: {_installed_size_kb(staging)}
Homepage: {app_version.APP_URL}
Description: {app_version.APP_DESCRIPTION}
 LocalTube хранит скачанные видео на своём компьютере и показывает их
 в интерфейсе, похожем на YouTube: каналы, плейлисты, история, избранное.
 Библиотеку можно открыть с телефона в той же сети.
"""
    with open(os.path.join(control_dir, 'control'), 'w',
              encoding='utf-8', newline='\n') as f:
        f.write(control)

    # postinst/postrm обновляют кэш иконок и меню: без этого приложение не
    # появляется в списке программ до перезахода в систему.
    hooks = {
        'postinst': """#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
""",
        'postrm': """#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
""",
    }
    for name, body in hooks.items():
        path = os.path.join(control_dir, name)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
        os.chmod(path, 0o755)

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(
        out_dir, f'{PKG_NAME}_{app_version.__version__}_{arch}.deb')
    # --root-owner-group: без него файлы в пакете принадлежат пользователю
    # сборки, и lintian справедливо считает это ошибкой.
    _run(['dpkg-deb', '--build', '--root-owner-group', staging, out_path])
    return out_path


def build_rpm(staging, out_dir, arch='x86_64'):
    """Собирает .rpm через rpmbuild."""
    build_root = os.path.abspath(os.path.join(out_dir, 'rpmbuild'))
    for sub in ('BUILD', 'RPMS', 'SOURCES', 'SPECS', 'SRPMS', 'BUILDROOT'):
        os.makedirs(os.path.join(build_root, sub), exist_ok=True)

    spec_path = os.path.join(build_root, 'SPECS', f'{PKG_NAME}.spec')
    staged_abs = os.path.abspath(staging)
    spec = f"""Name:           {PKG_NAME}
Version:        {app_version.__version__}
Release:        1
Summary:        {app_version.APP_DESCRIPTION}
License:        MIT
URL:            {app_version.APP_URL}
{''.join(f'Requires:       {dep}{chr(10)}' for dep in RPM_REQUIRES)}\
# Приложение уже собрано PyInstaller: внутри свой Python и весь графический
# стек. Стандартные проверки RPM для такого набора неприменимы и только ломают
# сборку — debuginfo нечего извлекать. Автопоиск зависимостей выключен намеренно:
# иначе rpmbuild выписал бы требования на все вложенные библиотеки, которые
# пакет и так несёт с собой.
AutoReqProv:    no
%global debug_package %{{nil}}
%global __brp_check_rpaths %{{nil}}
%global __brp_mangle_shebangs %{{nil}}
%global __brp_strip %{{nil}}
%global __brp_strip_static_archive %{{nil}}
%global __brp_strip_comment_note %{{nil}}

%description
LocalTube хранит скачанные видео на своём компьютере и показывает их в
интерфейсе, похожем на YouTube: каналы, плейлисты, история, избранное.
Библиотеку можно открыть с телефона в той же сети.

%install
rm -rf %{{buildroot}}
mkdir -p %{{buildroot}}
cp -a {staged_abs}/. %{{buildroot}}/

%files
{INSTALL_ROOT}
/usr/bin/{PKG_NAME}
/usr/share/applications/{app_version.APP_ID}.desktop
/usr/share/icons/hicolor/*/apps/{PKG_NAME}.png
%doc /usr/share/doc/{PKG_NAME}

%post
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || :
fi

%postun
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || :
fi
"""
    with open(spec_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(spec)

    _run(['rpmbuild', '-bb',
          '--define', f'_topdir {build_root}',
          '--target', arch,
          spec_path])

    os.makedirs(out_dir, exist_ok=True)
    produced = []
    for current, _dirs, files in os.walk(os.path.join(build_root, 'RPMS')):
        for name in files:
            if name.endswith('.rpm'):
                target = os.path.join(out_dir, name)
                shutil.move(os.path.join(current, name), target)
                produced.append(target)
    if not produced:
        raise RuntimeError('rpmbuild не создал пакет')
    return produced[0]


def build_appimage(source, out_dir, arch='x86_64'):
    """Собирает AppImage через appimagetool.

    GTK и WebKitGTK внутрь не укладываются, хотя AppImage обычно самодостаточен.
    Причина в том, что окно рисует системный WebKitGTK через GObject
    Introspection: он собран компилятором пользователя и требует новой
    libstdc++. Наша сборка идёт на старом дистрибутиве (ради совместимости
    glibc), и её libstdc++ оказывается первой в пути загрузчика — системный
    WebKit падал на `GLIBCXX_3.4.26' not found. Поэтому C++/GLib/GTK/WebKit
    отдаются системе, как в DEB и RPM.
    """
    appdir = os.path.abspath(os.path.join(out_dir, 'LocalTube.AppDir'))
    if os.path.isdir(appdir):
        shutil.rmtree(appdir)

    app_target = os.path.join(appdir, 'usr', 'lib', PKG_NAME)
    _copy_tree(source, app_target)
    os.chmod(os.path.join(app_target, app_version.APP_NAME), 0o755)

    apprun = os.path.join(appdir, 'AppRun')
    with open(apprun, 'w', encoding='utf-8', newline='\n') as f:
        f.write(f"""#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/{PKG_NAME}/{app_version.APP_NAME}" "$@"
""")
    os.chmod(apprun, 0o755)

    with open(os.path.join(appdir, f'{app_version.APP_ID}.desktop'),
              'w', encoding='utf-8', newline='\n') as f:
        f.write(_desktop_entry())

    assets = os.path.join(_HERE, 'assets')
    icon_source = os.path.join(assets, 'localtube.png')
    if os.path.isfile(icon_source):
        shutil.copy2(icon_source, os.path.join(appdir, f'{PKG_NAME}.png'))
        icon_dir = os.path.join(appdir, 'usr', 'share', 'icons', 'hicolor',
                                '256x256', 'apps')
        os.makedirs(icon_dir, exist_ok=True)
        shutil.copy2(icon_source, os.path.join(icon_dir, f'{PKG_NAME}.png'))

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(
        out_dir, f'{app_version.APP_NAME}-{app_version.__version__}-{arch}.AppImage')

    # linuxdeploy сознательно не используется: он укладывает в AppDir GTK и
    # WebKit сборочной машины, и на новом дистрибутиве система линковалась с
    # ними вместо своих — окно не открывалось.
    tool = shutil.which('appimagetool') or shutil.which('appimagetool-x86_64.AppImage')
    if not tool:
        raise RuntimeError('appimagetool не найден в PATH')

    env = dict(os.environ)
    env['ARCH'] = arch
    _run([tool, appdir, out_path], env=env)
    os.chmod(out_path, 0o755)
    return out_path


def build_targz(source, out_dir, arch='x64'):
    """Собирает переносимый архив.

    Файл-маркер portable.txt внутри: распакованный архив держит данные рядом с
    собой, как и портативная версия для Windows.
    """
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(
        out_dir, f'{app_version.APP_NAME}-linux-{arch}.tar.gz')

    marker = os.path.join(source, 'portable.txt')
    created_marker = not os.path.exists(marker)
    if created_marker:
        with open(marker, 'w', encoding='utf-8', newline='\n') as f:
            f.write('Данные приложения хранятся в этой папке.\n')

    try:
        with tarfile.open(out_path, 'w:gz') as tf:
            tf.add(source, arcname=app_version.APP_NAME)
    finally:
        if created_marker:
            os.remove(marker)
    return out_path


FORMATS = {
    'deb': 'DEB (Debian, Ubuntu, Mint)',
    'rpm': 'RPM (Fedora, openSUSE, RHEL)',
    'appimage': 'AppImage (любой дистрибутив)',
    'targz': 'tar.gz (портативный архив)',
}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Сборка пакетов для Linux')
    parser.add_argument('--source', default=os.path.join(_ROOT, 'dist', 'LocalTube'),
                        help='Каталог сборки PyInstaller')
    parser.add_argument('--out', default=os.path.join(_ROOT, 'release'),
                        help='Куда положить пакеты')
    parser.add_argument('--formats', default='deb,rpm,appimage,targz',
                        help='Через запятую: ' + ', '.join(FORMATS))
    parser.add_argument('--arch', default='x64', choices=['x64', 'arm64'])
    args = parser.parse_args(argv)

    if not os.path.isdir(args.source):
        print(f'Каталог сборки не найден: {args.source}', file=sys.stderr)
        print('Сначала выполните: pyinstaller --noconfirm packaging/localtube.spec',
              file=sys.stderr)
        return 1

    deb_arch = 'amd64' if args.arch == 'x64' else 'arm64'
    rpm_arch = 'x86_64' if args.arch == 'x64' else 'aarch64'
    appimage_arch = 'x86_64' if args.arch == 'x64' else 'aarch64'

    requested = [f.strip() for f in args.formats.split(',') if f.strip()]
    unknown = [f for f in requested if f not in FORMATS]
    if unknown:
        print(f'Неизвестные форматы: {", ".join(unknown)}', file=sys.stderr)
        return 1

    staging = os.path.join(args.out, 'staging')
    built, failed = [], []

    for fmt in requested:
        print(f'\n=== {FORMATS[fmt]} ===')
        try:
            if fmt == 'deb':
                built.append(build_deb(stage(args.source, staging), args.out, deb_arch))
            elif fmt == 'rpm':
                built.append(build_rpm(stage(args.source, staging), args.out, rpm_arch))
            elif fmt == 'appimage':
                built.append(build_appimage(args.source, args.out, appimage_arch))
            elif fmt == 'targz':
                built.append(build_targz(args.source, args.out, args.arch))
        except (OSError, subprocess.CalledProcessError, RuntimeError) as e:
            # Один формат может не собраться (нет rpmbuild, нет сети для
            # appimagetool), и это не повод терять остальные пакеты.
            print(f'[!] {fmt} не собран: {e}', file=sys.stderr)
            failed.append(fmt)

    if os.path.isdir(staging):
        shutil.rmtree(staging)

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
