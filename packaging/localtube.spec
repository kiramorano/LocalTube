# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

ytldlp_data, ytldlp_binaries, ytldlp_hiddenimports = collect_all('yt_dlp')

# config.json в .gitignore, поэтому в чистом клоне его нет. Приложение создаёт
# его при первом запуске со значениями по умолчанию, так что включаем только
# если файл существует.
extra_datas = [
    (os.path.join(ROOT, 'templates'), 'templates'),
    (os.path.join(ROOT, 'static'), 'static'),
]
config_path = os.path.join(ROOT, 'config.json')
if os.path.exists(config_path):
    extra_datas.append((config_path, '.'))

# Плагины PO Token: yt-dlp ищет пакет yt_dlp_plugins рядом с приложением.
plugins_path = os.path.join(ROOT, 'yt_dlp_plugins')
if os.path.isdir(plugins_path):
    extra_datas.append((plugins_path, 'yt_dlp_plugins'))

a = Analysis(
    [os.path.join(ROOT, 'app.py')],
    pathex=[ROOT],
    binaries=ytldlp_binaries,
    datas=extra_datas + ytldlp_data,
    # Модули проекта импортируются динамически либо как blueprints, поэтому
    # перечисляем их явно: анализатор находит не все.
    hiddenimports=ytldlp_hiddenimports + [
        'auth_options', 'audio_language', 'channel_assets', 'custom_quality',
        'download_lib', 'downloader', 'logger', 'po_manager', 'subtitles',
        'userdata', 'user_videos', 'utils', 'youtube_extractor',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

# onedir, а не onefile: workflow упаковывает каталог dist/LocalTube, а
# распакованная сборка запускается заметно быстрее одного большого exe.
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
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='LocalTube',
)
