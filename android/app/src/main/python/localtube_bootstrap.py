# -*- coding: utf-8 -*-
"""
localtube_bootstrap.py — точка входа Python-сервера LocalTube на Android.

Вызывается из ServerService (Chaquopy) в фоновом потоке:
1. Отключает signal-хендлеры (доступны только в главном потоке).
2. Делает ffmpeg/ffprobe доступными через PATH (симлинки на nativeLibraryDir).
3. Запускает app.py из распакованной папки приложения — точно так же,
   как это происходит на ПК.
"""
import os
import sys
import runpy


def _setup_ffmpeg(app_root: str, native_lib_dir: str) -> None:
    """Android разрешает исполнять бинарники только из nativeLibraryDir.
    ffmpeg/ffprobe упакованы как libffmpeg.so / libffprobe.so; создаём
    симлинки с нормальными именами и добавляем их папку в PATH."""
    bin_dir = os.path.join(app_root, "bin")
    os.makedirs(bin_dir, exist_ok=True)

    for name, lib in (("ffmpeg", "libffmpeg.so"), ("ffprobe", "libffprobe.so")):
        target = os.path.join(native_lib_dir, lib)
        link = os.path.join(bin_dir, name)
        if not os.path.exists(target):
            continue
        try:
            if os.path.islink(link) or os.path.exists(link):
                os.remove(link)
            os.symlink(target, link)
        except OSError:
            pass

    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


def _patch_signal() -> None:
    """app.py регистрирует SIGINT/SIGTERM хендлеры на уровне модуля.
    На Android сервер работает не в главном потоке, где signal.signal
    бросает ValueError — заменяем на заглушку."""
    import signal

    signal.signal = lambda *args, **kwargs: None  # type: ignore[assignment]


def start_server(app_root: str, native_lib_dir: str) -> None:
    _patch_signal()
    _setup_ffmpeg(app_root, native_lib_dir)

    os.environ.setdefault("HOME", app_root)
    os.environ.setdefault("PORT", "8000")

    os.chdir(app_root)
    if app_root not in sys.path:
        sys.path.insert(0, app_root)

    # Запускаем как __main__, чтобы сработала точка входа app.run(...)
    runpy.run_path(os.path.join(app_root, "app.py"), run_name="__main__")
