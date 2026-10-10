# -*- mode: python ; coding: utf-8 -*-
import os
ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
import sys
sys.path.insert(0, ROOT)

from PyInstaller.utils.hooks import collect_all
from packaging import spec_common as common

ytldlp_data, ytldlp_binaries, ytldlp_hiddenimports = collect_all('yt_dlp')

a = Analysis(
    [common.entry_script()],
    pathex=[ROOT],
    binaries=common.collect_binaries() + ytldlp_binaries,
    datas=common.collect_datas(),
    hiddenimports=common.collect_hidden_imports() + ytldlp_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=common.runtime_hooks(),
    excludes=common.EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LocalTube',
    icon=common.icon_path(),
    version=common.version_file(),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries + common.patch_webkit_exec_path(a.binaries),
    a.datas,
    *common.collect_gl_fallback(),
    *common.collect_gtk_stack(),
    *common.collect_gtk_support_files(),
    *common.collect_webkit_helpers(),
    strip=False,
    upx=False,
    name='LocalTube',
)
