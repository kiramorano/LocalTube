# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

block_cipher = None

ytdlp_datas, ytdlp_binaries, ytdlp_hiddenimports = collect_all("yt_dlp")

analysis = Analysis(
    ["app.py"],
    pathex=[],
    binaries=ytdlp_binaries,
    datas=[
        ("templates", "templates"),
        ("static", "static"),
        ("config.json", "."),
    ] + ytdlp_datas,
    hiddenimports=ytdlp_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="LocalTube",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=True,
    name="LocalTube",
)
