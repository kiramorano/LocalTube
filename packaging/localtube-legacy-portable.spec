# -*- mode: python ; coding: utf-8 -*-
"""localtube-legacy-portable.spec — портативная сборка Windows 7 одним файлом.

Сочетает портативный формат localtube-portable.spec (onefile) и сборку
cefpython3 из localtube-legacy.spec: на Windows 7 WebView2 нет, поэтому
окно открывается через встроенный Chromium.
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
# collect_all из PyInstaller 4+ здесь недоступен, поэтому файлы перечисляются
# вручную через get_package_paths: набор ресурсов меняется между версиями, а
# без любого из них окно открывается пустым.
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
        if len(item) >= 3 and '.' in str(item[0]):
            dest_name = str(item[0])
            if dest_name.startswith('cefpython3.cefpython_py'):
                mod_name = dest_name.split('.', 1)[1]
                if mod_name != keep_mod:
                    continue
        else:
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
    _cef_dest = 'cefpython3'
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
    print(f'[legacy-portable.spec] cefpython3 недоступен ({exc}); окно будет через браузер')

# CRT: vcruntime140.dll (+ vcruntime140_1.dll для x64) из embeddable Python,
# чтобы сборка запускалась на чистой Windows 7 без установки vc_redist.
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
# Хук PyInstaller для cefpython3 добавляет пyd для всех версий Python.
# collect_all в collect_datas мы уже отфильтровали, но hook работает позже —
# чистим a.datas и a.binaries окончательно здесь, после Analysis.
a.datas = _drop_foreign_cef_modules(a.datas)
a.binaries = _drop_foreign_cef_modules(a.binaries)
_cef_kept = [os.path.basename(i[0]) for i in a.binaries
             if 'cefpython' in os.path.basename(i[0]).lower()]
print(f'[legacy-portable.spec] cefpython в a.binaries после фильтра: {_cef_kept}')
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
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon=common.icon_path(),
    version=common.version_file(),
)
