#!/usr/bin/env python3
"""make_wxs.py — генерирует описание MSI для WiX по содержимому сборки.

Файл ``.wxs`` нельзя написать один раз и забыть: WiX требует перечислить в нём
каждый файл пакета со своим уникальным идентификатором, а состав сборки
PyInstaller меняется от версии к версии (каждое обновление yt-dlp приносит новые
модули). Список, написанный руками, устаревал бы после первого же обновления
зависимостей, и в установщик просто не попадала бы часть файлов.

Идентификаторы компонентов строятся из хеша относительного пути. Это не
украшательство: WiX требует, чтобы ID начинался с буквы и содержал только буквы,
цифры, точку и подчёркивание, а имена файлов внутри yt-dlp содержат дефисы и
неанглийские символы. Кроме того, ID обязан быть стабильным между версиями —
иначе установщик при обновлении удалит и заново поставит все файлы.

Запуск:
    python packaging/make_wxs.py --source dist/LocalTube --out build/LocalTube.wxs
"""
import argparse
import hashlib
import os
import sys
import uuid
import xml.etree.ElementTree as ET

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import version as app_version  # noqa: E402

WIX_NS = 'http://wixtoolset.org/schemas/v4/wxs'
# WiX 3 использует другое пространство имён и другую структуру документа. Обе
# схемы нужны: v4 ставится как dotnet-инструмент и требует .NET SDK, а v3
# работает на .NET Framework, который есть в Windows из коробки, и запускается
# из распакованного архива без прав администратора.
WIX3_NS = 'http://schemas.microsoft.com/wix/2006/wi'

# Язык пакета: 1049 — русский. Значение не косметическое: при 1033 (английский)
# MSI берёт кодовую страницу 1252, где кириллицы нет, и light падает с LGHT0311
# на русских строках — названии автора, описании и тексте об отказе от
# понижения версии.
WIX3_LANGUAGE = '1049'
# Кодовая страница базы MSI. UTF-8 принимает любые строки, поэтому текст
# описания не приходится ограничивать латиницей.
WIX3_CODEPAGE = '65001'
# Сводка (Summary Information Stream) UTF-8 не принимает: candle отвечает
# CNDL0349 и требует ANSI-страницу. 1251 — кириллическая ANSI, её хватает для
# названия и имени автора.
WIX3_SUMMARY_CODEPAGE = '1251'
# InstallerVersion 500 — Windows Installer 5.0, он есть во всех поддерживаемых
# версиях Windows и нужен для 64-битных пакетов.
WIX3_INSTALLER_VERSION = '500'

# Пространство имён для UUID: GUID пакета и компонентов должны быть одинаковыми
# при каждой сборке одной и той же версии, иначе Windows считает переустановку
# другим продуктом и в «Установке и удалении программ» появляются дубликаты.
UUID_NAMESPACE = uuid.UUID('6f2b4a1e-9c3d-4f7a-8b52-1d0e7c4a9f31')


def stable_guid(*parts):
    """Постоянный GUID из строки. Одинаковый ввод даёт одинаковый GUID."""
    name = '/'.join(str(p) for p in parts)
    return str(uuid.uuid5(UUID_NAMESPACE, name)).upper()


def safe_id(prefix, relative_path):
    """Идентификатор WiX: буквы, цифры и подчёркивания, начинается с буквы.

    К очищенному имени добавляется хеш полного пути: без него файлы
    ``a/utils.py`` и ``b/utils.py`` получали бы один и тот же ID, и WiX
    отказывался собирать пакет с ошибкой о дубликате.
    """
    digest = hashlib.sha1(relative_path.encode('utf-8')).hexdigest()[:10]
    cleaned = ''.join(ch if ch.isalnum() else '_'
                      for ch in os.path.basename(relative_path))
    # Ограничение длины: WiX не принимает идентификаторы длиннее 72 символов.
    cleaned = cleaned[:40]
    return f'{prefix}_{cleaned}_{digest}'


def _walk(source):
    """Каталоги и файлы сборки, отсортированные для воспроизводимости."""
    for current, dirs, files in os.walk(source):
        dirs.sort()
        files.sort()
        yield current, dirs, files


def build_tree(source):
    """Строит XML установщика по каталогу сборки."""
    ET.register_namespace('', WIX_NS)
    root = ET.Element(f'{{{WIX_NS}}}Wix')

    package = ET.SubElement(root, 'Package', {
        'Name': app_version.APP_NAME,
        'Manufacturer': app_version.APP_AUTHOR,
        'Version': app_version.__version__,
        # UpgradeCode обязан не меняться никогда: по нему установщик находит
        # предыдущую версию и обновляет её вместо установки второй копии.
        'UpgradeCode': stable_guid('upgrade-code'),
        'Scope': 'perMachine',
        'Compressed': 'yes',
    })

    ET.SubElement(package, 'MajorUpgrade', {
        # Понижение версии запрещаем с внятным текстом: по умолчанию установщик
        # молча падал бы с кодом 1603, который ничего не объясняет.
        'DowngradeErrorMessage':
            'Уже установлена более новая версия LocalTube.',
        # Обновление после установки новых файлов: иначе установщик сначала
        # удаляет старую версию, и при сбое пользователь остаётся без программы.
        'Schedule': 'afterInstallExecute',
    })

    # Встроенный CAB: MSI одним файлом, без внешних архивов рядом.
    ET.SubElement(package, 'MediaTemplate', {'EmbedCab': 'yes'})

    # Иконка для «Установки и удаления программ».
    icon_path = os.path.join(_HERE, 'assets', 'localtube.ico')
    if os.path.isfile(icon_path):
        ET.SubElement(package, 'Icon', {
            'Id': 'LocalTubeIcon', 'SourceFile': icon_path})
        ET.SubElement(package, 'Property', {
            'Id': 'ARPPRODUCTICON', 'Value': 'LocalTubeIcon'})
    ET.SubElement(package, 'Property', {
        'Id': 'ARPURLINFOABOUT', 'Value': app_version.APP_URL})

    # Каталог установки: Program Files, подпапка с названием программы.
    std_dir = ET.SubElement(package, 'StandardDirectory', {
        'Id': 'ProgramFiles64Folder'})
    install_dir = ET.SubElement(std_dir, 'Directory', {
        'Id': 'INSTALLFOLDER', 'Name': app_version.APP_NAME})

    # Ярлыки: меню «Пуск» и рабочий стол.
    menu_dir = ET.SubElement(package, 'StandardDirectory', {
        'Id': 'ProgramMenuFolder'})
    ET.SubElement(package, 'StandardDirectory', {'Id': 'DesktopFolder'})

    feature = ET.SubElement(package, 'Feature', {
        'Id': 'Main',
        'Title': app_version.APP_NAME,
        'Level': '1',
    })

    components = []
    dir_elements = {os.path.abspath(source): install_dir}

    for current, subdirs, files in _walk(source):
        parent = dir_elements[os.path.abspath(current)]
        for name in subdirs:
            full = os.path.join(current, name)
            rel = os.path.relpath(full, source)
            child = ET.SubElement(parent, 'Directory', {
                'Id': safe_id('dir', rel),
                'Name': name,
            })
            dir_elements[os.path.abspath(full)] = child

        for name in files:
            full = os.path.join(current, name)
            rel = os.path.relpath(full, source).replace('\\', '/')
            component_id = safe_id('cmp', rel)
            component = ET.SubElement(parent, 'Component', {
                'Id': component_id,
                'Guid': stable_guid('component', rel),
            })
            ET.SubElement(component, 'File', {
                'Id': safe_id('fil', rel),
                'Source': full,
                'KeyPath': 'yes',
            })
            components.append(component_id)

    # Ярлыки отдельным компонентом: их KeyPath — запись в реестре, потому что
    # ярлык в меню «Пуск» сам по себе ключевым файлом быть не может.
    shortcut_component = ET.SubElement(menu_dir, 'Component', {
        'Id': 'cmp_shortcuts',
        'Guid': stable_guid('component', 'shortcuts'),
    })
    ET.SubElement(shortcut_component, 'Shortcut', {
        'Id': 'StartMenuShortcut',
        'Name': app_version.APP_NAME,
        'Description': app_version.APP_DESCRIPTION,
        'Target': f'[INSTALLFOLDER]{app_version.APP_NAME}.exe',
        'WorkingDirectory': 'INSTALLFOLDER',
    })
    ET.SubElement(shortcut_component, 'Shortcut', {
        'Id': 'DesktopShortcut',
        'Directory': 'DesktopFolder',
        'Name': app_version.APP_NAME,
        'Description': app_version.APP_DESCRIPTION,
        'Target': f'[INSTALLFOLDER]{app_version.APP_NAME}.exe',
        'WorkingDirectory': 'INSTALLFOLDER',
    })
    # Ярлыки удаляются вместе с программой: без RemoveFolder в меню «Пуск»
    # оставалась пустая папка.
    ET.SubElement(shortcut_component, 'RemoveFolder', {
        'Id': 'RemoveStartMenuFolder',
        'On': 'uninstall',
    })
    ET.SubElement(shortcut_component, 'RegistryValue', {
        'Root': 'HKCU',
        'Key': f'Software\\{app_version.APP_AUTHOR}\\{app_version.APP_NAME}',
        'Name': 'installed',
        'Type': 'integer',
        'Value': '1',
        'KeyPath': 'yes',
    })
    components.append('cmp_shortcuts')

    for component_id in components:
        ET.SubElement(feature, 'ComponentRef', {'Id': component_id})

    return root


def build_tree_v3(source, arch='x64'):
    """То же описание пакета для схемы WiX 3.

    Отличия от v4 не косметические, поэтому вторая функция, а не флаги в первой:
    корневой элемент называется Product, каталоги строятся от TARGETDIR вручную
    (StandardDirectory в v3 нет), а 64-битным компонентам нужен атрибут Win64 —
    без него файлы уходили бы в Program Files (x86).
    """
    ET.register_namespace('', WIX3_NS)
    root = ET.Element(f'{{{WIX3_NS}}}Wix')

    win64 = 'yes' if arch == 'x64' else 'no'

    product = ET.SubElement(root, 'Product', {
        'Id': '*',  # новый GUID на каждую сборку: так требует MajorUpgrade
        'Name': app_version.APP_NAME,
        'Language': WIX3_LANGUAGE,
        'Codepage': WIX3_CODEPAGE,
        'Version': app_version.__version__,
        'Manufacturer': app_version.APP_AUTHOR,
        'UpgradeCode': stable_guid('upgrade-code'),
    })

    ET.SubElement(product, 'Package', {
        'InstallerVersion': WIX3_INSTALLER_VERSION,
        'Compressed': 'yes',
        # perMachine: программа ставится в Program Files для всех пользователей.
        'InstallScope': 'perMachine',
        'Platform': arch,
        'Languages': WIX3_LANGUAGE,
        'SummaryCodepage': WIX3_SUMMARY_CODEPAGE,
    })

    ET.SubElement(product, 'MajorUpgrade', {
        'DowngradeErrorMessage':
            'Уже установлена более новая версия LocalTube.',
        'Schedule': 'afterInstallExecute',
    })
    ET.SubElement(product, 'MediaTemplate', {'EmbedCab': 'yes'})

    icon_path = os.path.join(_HERE, 'assets', 'localtube.ico')
    if os.path.isfile(icon_path):
        ET.SubElement(product, 'Icon', {
            'Id': 'LocalTubeIcon', 'SourceFile': icon_path})
        ET.SubElement(product, 'Property', {
            'Id': 'ARPPRODUCTICON', 'Value': 'LocalTubeIcon'})
    ET.SubElement(product, 'Property', {
        'Id': 'ARPURLINFOABOUT', 'Value': app_version.APP_URL})

    # В v3 всё дерево каталогов растёт от TARGETDIR.
    target = ET.SubElement(product, 'Directory', {
        'Id': 'TARGETDIR', 'Name': 'SourceDir'})
    program_files_id = ('ProgramFiles64Folder' if arch == 'x64'
                        else 'ProgramFilesFolder')
    program_files = ET.SubElement(target, 'Directory', {
        'Id': program_files_id})
    install_dir = ET.SubElement(program_files, 'Directory', {
        'Id': 'INSTALLFOLDER', 'Name': app_version.APP_NAME})
    menu_dir = ET.SubElement(target, 'Directory', {'Id': 'ProgramMenuFolder'})
    ET.SubElement(target, 'Directory', {'Id': 'DesktopFolder'})

    feature = ET.SubElement(product, 'Feature', {
        'Id': 'Main',
        'Title': app_version.APP_NAME,
        'Level': '1',
    })

    components = []
    dir_elements = {os.path.abspath(source): install_dir}

    for current, subdirs, files in _walk(source):
        parent = dir_elements[os.path.abspath(current)]
        for name in subdirs:
            full = os.path.join(current, name)
            rel = os.path.relpath(full, source)
            child = ET.SubElement(parent, 'Directory', {
                'Id': safe_id('dir', rel),
                'Name': name,
            })
            dir_elements[os.path.abspath(full)] = child

        for name in files:
            full = os.path.join(current, name)
            rel = os.path.relpath(full, source).replace('\\', '/')
            component_id = safe_id('cmp', rel)
            component = ET.SubElement(parent, 'Component', {
                'Id': component_id,
                'Guid': stable_guid('component', rel),
                'Win64': win64,
            })
            ET.SubElement(component, 'File', {
                'Id': safe_id('fil', rel),
                'Source': full,
                'KeyPath': 'yes',
            })
            components.append(component_id)

    shortcut_component = ET.SubElement(menu_dir, 'Component', {
        'Id': 'cmp_shortcuts',
        'Guid': stable_guid('component', 'shortcuts'),
        'Win64': win64,
    })
    ET.SubElement(shortcut_component, 'Shortcut', {
        'Id': 'StartMenuShortcut',
        'Name': app_version.APP_NAME,
        'Description': app_version.APP_DESCRIPTION,
        'Target': f'[INSTALLFOLDER]{app_version.APP_NAME}.exe',
        'WorkingDirectory': 'INSTALLFOLDER',
    })
    ET.SubElement(shortcut_component, 'Shortcut', {
        'Id': 'DesktopShortcut',
        'Directory': 'DesktopFolder',
        'Name': app_version.APP_NAME,
        'Description': app_version.APP_DESCRIPTION,
        'Target': f'[INSTALLFOLDER]{app_version.APP_NAME}.exe',
        'WorkingDirectory': 'INSTALLFOLDER',
    })
    ET.SubElement(shortcut_component, 'RemoveFolder', {
        'Id': 'RemoveStartMenuFolder',
        'On': 'uninstall',
    })
    ET.SubElement(shortcut_component, 'RegistryValue', {
        'Root': 'HKCU',
        'Key': f'Software\\{app_version.APP_AUTHOR}\\{app_version.APP_NAME}',
        'Name': 'installed',
        'Type': 'integer',
        'Value': '1',
        'KeyPath': 'yes',
    })
    components.append('cmp_shortcuts')

    for component_id in components:
        ET.SubElement(feature, 'ComponentRef', {'Id': component_id})

    return root


def main(argv=None):
    parser = argparse.ArgumentParser(description='Генерация .wxs для MSI')
    parser.add_argument('--source', required=True,
                        help='Каталог сборки (dist/LocalTube)')
    parser.add_argument('--out', required=True, help='Куда записать .wxs')
    parser.add_argument('--wix-version', default='4', choices=['3', '4'],
                        help='Схема .wxs: 4 (по умолчанию) или 3')
    parser.add_argument('--arch', default='x64', choices=['x64', 'x86'],
                        help='Разрядность пакета (нужна схеме 3)')
    args = parser.parse_args(argv)

    if not os.path.isdir(args.source):
        print(f'Каталог сборки не найден: {args.source}', file=sys.stderr)
        return 1

    if args.wix_version == '3':
        tree = ET.ElementTree(build_tree_v3(args.source, args.arch))
    else:
        tree = ET.ElementTree(build_tree(args.source))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    # indent для читаемости: сгенерированный файл приходится смотреть глазами,
    # когда WiX жалуется на конкретную строку.
    if hasattr(ET, 'indent'):
        ET.indent(tree, space='  ')
    tree.write(args.out, encoding='utf-8', xml_declaration=True)

    file_count = sum(len(files) for _, _, files in _walk(args.source))
    print(f'{args.out}: описано файлов — {file_count}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
