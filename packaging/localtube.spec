# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

ytldlp_data, ytldlp_binaries, ytldlp_hiddenimports = collect_all('yt_dlp')

a = Analysis(
    [os.path.join(ROOT, 'app.py')],
    pathex=[ROOT],
    binaries=ytldlp_binaries,
    datas=[
        (os.path.join(ROOT, 'templates'), 'templates'),
        (os.path.join(ROOT, 'static'), 'static'),
        (os.path.join(ROOT, 'config.json'), '.'),
    ] + ytldlp_data,
    hiddenimports=ytldlp_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='LocalTube', debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
