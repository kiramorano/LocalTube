#!/usr/bin/env python3
"""fetch_ffmpeg.py — кладёт ffmpeg внутрь сборки.

Без ffmpeg загрузка с YouTube обрывается на самом заметном месте: yt-dlp
скачивает видео и звук отдельными потоками и не может их объединить. Раньше
предполагалось, что пользователь установит ffmpeg сам, и на чистой системе
загрузка падала с «ffmpeg not found» уже после того, как файлы скачаны.

Скрипт запускается до PyInstaller и раскладывает бинарники в
``packaging/assets/ffmpeg``, откуда их забирает spec_common и кладёт в подкаталог
``bin`` собранного приложения — там их находит ``paths.find_binary``.

Скачиваются сборки gyan.dev (Windows) и johnvansickle.com (Linux): это те же
источники, которые рекомендует документация самого ffmpeg. Обе — GPL-сборки, что
важно указывать в документации к пакетам.

Запуск:
    python packaging/fetch_ffmpeg.py [--platform windows|linux] [--arch x64|x86]
"""
import argparse
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
TARGET_DIR = os.path.join(_HERE, 'assets', 'ffmpeg')

# Ссылки на «последнюю» сборку, а не на конкретную версию: у обоих проектов
# фиксированные версии со временем исчезают, и сборка ломалась бы на 404.
SOURCES = {
    ('windows', 'x64'): (
        'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip', 'zip'),
    # Отдельной 32-битной сборки gyan.dev не публикует: 32-битная версия для
    # Windows берётся у того же автора из архива builds/, но её там тоже нет,
    # поэтому x86-сборка идёт без вложенного ffmpeg и полагается на PATH.
    ('linux', 'x64'): (
        'https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz',
        'tar'),
    ('linux', 'arm64'): (
        'https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz',
        'tar'),
}

# Из архива нужны только два файла: сам ffmpeg и ffprobe (им приложение узнаёт
# длительность и кодек). Остальное (ffplay, документация, примеры) добавляет
# десятки мегабайт без всякой пользы.
WANTED = ('ffmpeg', 'ffprobe')


def _wanted(filename):
    base = os.path.basename(filename)
    stem = base[:-4] if base.lower().endswith('.exe') else base
    return stem in WANTED


def _extract_zip(archive_path, target):
    with zipfile.ZipFile(archive_path) as zf:
        for member in zf.namelist():
            if member.endswith('/') or not _wanted(member):
                continue
            out_path = os.path.join(target, os.path.basename(member))
            with zf.open(member) as src, open(out_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            yield out_path


def _extract_tar(archive_path, target):
    # Режим 'r:*' сам определяет сжатие: у johnvansickle это xz, но менять
    # формат они вправе, и жёсткое 'r:xz' сломало бы скрипт молча.
    with tarfile.open(archive_path, 'r:*') as tf:
        for member in tf.getmembers():
            if not member.isfile() or not _wanted(member.name):
                continue
            src = tf.extractfile(member)
            if src is None:
                continue
            out_path = os.path.join(target, os.path.basename(member.name))
            with src, open(out_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            # Бит выполнения в архиве есть, но при поштучном копировании он
            # теряется, и ffmpeg потом не запускался с Permission denied.
            os.chmod(out_path, 0o755)
            yield out_path


def fetch(platform_name, arch, target=TARGET_DIR):
    """Скачивает и распаковывает ffmpeg. Возвращает список файлов."""
    key = (platform_name, arch)
    if key not in SOURCES:
        print(f'[fetch_ffmpeg] для {platform_name}/{arch} вложенной сборки нет; '
              'приложение будет искать ffmpeg в PATH')
        return []

    url, kind = SOURCES[key]
    os.makedirs(target, exist_ok=True)
    print(f'[fetch_ffmpeg] скачиваю {url}')

    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, 'ffmpeg-archive')
        # Явный User-Agent: без него часть зеркал отвечает 403 на запросы от
        # urllib, и сборка падала с непонятной ошибкой доступа.
        request = urllib.request.Request(url, headers={'User-Agent': 'LocalTube-build'})
        with urllib.request.urlopen(request, timeout=300) as response:
            with open(archive, 'wb') as f:
                shutil.copyfileobj(response, f)

        extractor = _extract_zip if kind == 'zip' else _extract_tar
        found = list(extractor(archive, target))

    if not found:
        raise RuntimeError('в архиве не оказалось ffmpeg/ffprobe')
    for path in found:
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f'  {os.path.basename(path)} ({size_mb:.1f} МБ)')
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description='Загрузка ffmpeg для сборки')
    default_platform = 'windows' if sys.platform == 'win32' else (
        'linux' if sys.platform.startswith('linux') else 'macos')
    parser.add_argument('--platform', default=default_platform,
                        choices=['windows', 'linux', 'macos'])
    parser.add_argument('--arch', default='x64', choices=['x64', 'x86', 'arm64'])
    parser.add_argument('--out', default=TARGET_DIR)
    args = parser.parse_args(argv)

    try:
        fetch(args.platform, args.arch, args.out)
    except Exception as e:
        # Сборка без вложенного ffmpeg рабочая: приложение возьмёт его из PATH.
        # Поэтому недоступность зеркала не должна ронять весь релиз, но и
        # промолчать нельзя — иначе о причине узнает только пользователь.
        print(f'[fetch_ffmpeg] не удалось: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
