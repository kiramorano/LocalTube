# -*- mode: python ; coding: utf-8 -*-
"""localtube-legacy.spec — сборка для Windows 7 (x64 и x86).

Собирается на Python 3.8 — последней версии, работающей на Windows 7, — и
поэтому PyInstaller тоже нужен старый: начиная с шестой версии он объявляет
поддержку только Windows 8 и новее, и полученный exe на «семёрке» не
запускается вовсе.

Второе отличие — движок окна. WebView2 на Windows 7 нет и поставить его нельзя,
поэтому внутрь укладывается Chromium (cefpython3): он умеет H.264 и AAC, без
которых видео с YouTube не проигрывается. Qt WebEngine из PyPI на эту роль не
подходит, там проприетарные кодеки вырезаны — проверено запросом
canPlayType('video/mp4; codecs="avc1.42E01E, mp4a.40.2"'), который возвращает
пустую строку.
"""
import os
import sys

sys.path.insert(0, SPECPATH)
import spec_common as common

ROOT = common.ROOT

datas = common.collect_datas()
binaries = common.collect_binaries()
hidden = common.collect_hidden_imports()

# cefpython3 нужен целиком: он тащит libcef.dll, ресурсы Chromium и локали.
# collect_all, а не перечисление файлов, потому что набор ресурсов меняется
# между версиями, а без любого из них окно открывается пустым.
def _drop_foreign_cef_modules(items):
    """Убирает cefpython_pyXY.pyd для чужих версий Python.

    Колесо cefpython3 несёт по модулю на каждую версию от 2.7 до 3.9, а сборке
    нужен ровно один — под тот интерпретатор, которым она собрана. Остальные
    шесть добавляли к пакету около 9 МБ и никогда не загружались.

    До Analysis items — пары (src_path, dest_dir); после — TOC-кортежи
    (dest_name, src_path, type), где dest_name выглядит как
    'cefpython3.cefpython_py38'.
    """
    keep = 'cefpython_py%d%d.pyd' % sys.version_info[:2]
    keep_mod = 'cefpython_py%d%d' % sys.version_info[:2]
    result = []
    for item in items:
        # TOC-формат (после Analysis): (dest_name, src_path, type)
        if len(item) >= 3 and '.' in str(item[0]):
            dest_name = str(item[0])
            if dest_name.startswith('cefpython3.cefpython_py'):
                mod_name = dest_name.split('.', 1)[1]  # cefpython_py38
                if mod_name != keep_mod:
                    continue
        else:
            # Пары (src_path, dest_dir) — до Analysis
            name = os.path.basename(item[0])
            if name.startswith('cefpython_py') and name.endswith('.pyd'):
                if name != keep:
                    continue
        result.append(item)
    return result


try:
    from PyInstaller.utils.hooks import get_package_paths, collect_submodules
    cef_dir = get_package_paths('cefpython3')[1]
    cef_datas = []
    cef_binaries = []
    _pyd_keep = 'cefpython_py%d%d.pyd' % sys.version_info[:2]
    # Все данные cefpython3 идут в подкаталог cefpython3/, чтобы cefpython3
    # находил их через package_dir = os.path.dirname(__file__).
    _cef_dest = 'cefpython3'
    # __init__.py обязателен: без него пакет не импортируется в _MEIPASS.
    _init_py = os.path.join(cef_dir, '__init__.py')
    if os.path.isfile(_init_py):
        cef_datas.append((_init_py, _cef_dest))
    for _fn in sorted(os.listdir(cef_dir)):
        _path = os.path.join(cef_dir, _fn)
        if not os.path.isfile(_path):
            continue
        _ext = os.path.splitext(_fn)[1].lower()
        if _fn.startswith('cefpython_py') and _fn.endswith('.pyd'):
            if _fn != _pyd_keep:
                continue
            cef_datas.append((_path, _cef_dest))
        elif _ext in ('.exe', '.dll'):
            cef_binaries.append((_path, _cef_dest))
        elif _ext in ('.pak', '.dat', '.bin', '.txt', '.so'):
            cef_datas.append((_path, _cef_dest))
    # locales и swiftshader
    for _sub in ('locales', 'swiftshader'):
        _sub_dir = os.path.join(cef_dir, _sub)
        if os.path.isdir(_sub_dir):
            for _sfn in os.listdir(_sub_dir):
                _spath = os.path.join(_sub_dir, _sfn)
                if os.path.isfile(_spath):
                    cef_datas.append((_spath, os.path.join(_cef_dest, _sub)))
    cef_hidden = ['cefpython3'] + collect_submodules('cefpython3')
    cef_datas = _drop_foreign_cef_modules(cef_datas)
    datas += cef_datas
    binaries += _drop_foreign_cef_modules(cef_binaries)
    hidden += cef_hidden
except Exception as exc:  # noqa: BLE001 - сборка без CEF допустима
    # Отсутствие cefpython3 не должно ронять сборку: без него приложение
    # откроется в системном браузере, а не в своём окне. Печатаем предупреждение,
    # чтобы это не выяснилось только у пользователя.
    print(f'[legacy.spec] cefpython3 недоступен ({exc}); окно будет через браузер')

# CRT-библиотеки: на Windows 7 без KB2999221 или предварительно установленного
# vc_redist приложение может не запуститься с ошибкой
# «api-ms-win-crt-runtime-l1-1-0.dll не найден». Добавляем vcruntime140.dll и
# ucrtbase.dll рядом с python38.dll — они лежат в packaging/assets/crt_x64|x86
# и не требуют установки redistributable.
_crt_binaries = []
_is_x64 = sys.maxsize > 2**32
_crt_dir = os.path.join(common.ROOT, 'packaging',
                        'assets', 'crt_x64' if _is_x64 else 'crt_x86')
for _crt_fn in sorted(os.listdir(_crt_dir)):
    _crt_src = os.path.join(_crt_dir, _crt_fn)
    if os.path.isfile(_crt_src):
        _crt_binaries.append((_crt_src, '.'))

a = Analysis(
    [common.entry_script()],
    pathex=[ROOT],
    binaries=binaries + _crt_binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[SPECPATH],
    runtime_hooks=[os.path.join(SPECPATH, 'rthook_cef_win.py')],
    excludes=common.EXCLUDES,
    noarchive=False,
)
# Хук PyInstaller для cefpython3 добавляет пyd для всех версий Python
# (см. packaging/make_wxs.py). Хотя мы уже отфильтровали cef_datas и cef_binaries,
# hook работает позже и может добавить их заново — поэтому чистим a.datas и
# a.binaries окончательно здесь, после Analysis.
a.datas = _drop_foreign_cef_modules(a.datas)
a.binaries = _drop_foreign_cef_modules(a.binaries)
_cef_kept = [os.path.basename(i[0]) for i in a.binaries
             if 'cefpython' in os.path.basename(i[0]).lower()]
print(f'[legacy.spec] cefpython в a.binaries после фильтра: {_cef_kept}')
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LocalTube',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=common.icon_path(),
    version=common.version_file(),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='LocalTube',
)
