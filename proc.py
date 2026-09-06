"""proc.py — запуск внешних программ без мигающих окон консоли.

В оконной сборке у процесса нет своей консоли, поэтому Windows открывает новое
окно на каждый запуск ffmpeg или ffprobe. При конвертации и снятии превью это
десятки чёрных окон, которые появляются поверх интерфейса и забирают фокус.

``CREATE_NO_WINDOW`` подавляет их. Флага нет в других системах и в старых
сборках Python, поэтому набор параметров собирается один раз здесь, а не
дублируется в каждом вызове subprocess.
"""
import subprocess
import sys

# Параметры, которые нужно передать в subprocess.*, чтобы окно не появлялось.
# На не-Windows остаётся пустым словарём: там проблемы нет.
NO_WINDOW = {}

if sys.platform == "win32":
    # getattr, а не прямой доступ: константа появилась в Python 3.7, и на
    # неожиданно старом интерпретаторе AttributeError уронил бы импорт.
    _flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    NO_WINDOW = {"creationflags": _flag}


def run(cmd, **kwargs):
    """subprocess.run без окна консоли."""
    merged = dict(NO_WINDOW)
    merged.update(kwargs)
    return subprocess.run(cmd, **merged)


def popen(cmd, **kwargs):
    """subprocess.Popen без окна консоли."""
    merged = dict(NO_WINDOW)
    merged.update(kwargs)
    return subprocess.Popen(cmd, **merged)
