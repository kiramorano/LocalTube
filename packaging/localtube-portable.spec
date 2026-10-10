# -*- mode: python ; coding: utf-8 -*-
"""localtube-portable.spec — портативная сборка одним файлом.

Один exe, который можно носить на флешке. Данные при этом лежат не внутри него,
а рядом: сборщик кладёт возле exe файл-маркер ``portable.txt``, и
``paths.is_portable`` по нему выбирает каталог данных. Без маркера портативная
версия писала бы библиотеку в профиль пользователя, то есть на чужой машине
оставляла бы следы и теряла данные при переносе.
"""
import os
import sys

sys.path.insert(0, SPECPATH)
import spec_common as common

ROOT = common.ROOT

a = Analysis(
    [common.entry_script()],
    pathex=[ROOT],
    binaries=common.collect_binaries(),
    datas=common.collect_datas(),
    hiddenimports=common.collect_hidden_imports(),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=common.runtime_hooks(),
    excludes=common.EXCLUDES,
    noarchive=False,
)

# См. комментарий в localtube.spec: графический стек идёт внутри сборки, чтобы
# приложение работало и там, где GTK с WebKit не установлены.
a.binaries += common.collect_gtk_stack()
a.binaries += common.collect_webkit_helpers()
a.binaries += common.collect_gl_fallback()
a.datas += common.collect_gtk_support_files()

# См. localtube.spec: путь к helper-процессам WebKit вшит в библиотеку, и в
# нашей копии он заменяется на относительный.
a.binaries = common.patch_webkit_exec_path(a.binaries)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LocalTube-portable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # upx=False намеренно: сжатый бинарник чаще попадает в эвристики
    # антивирусов, а выигрыш в размере для портативной версии не критичен.
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon=common.icon_path(),
    version=common.version_file(),
)
