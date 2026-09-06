"""
logger.py – простая настройка логирования.
Записывает логи в файл logs.txt и дублирует в консоль.
"""

import logging
import os
import sys

import paths

# Лог пишется в каталог данных, а не рядом с кодом: в установленной версии
# каталог программы доступен только для чтения, и FileHandler падал бы с
# PermissionError ещё на импорте, до единой строчки полезной работы.
LOG_FILE = paths.data_path('logs.txt')

def setup_logger(name=__name__, log_file=LOG_FILE, level=logging.DEBUG):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.hasHandlers():
        logger.handlers.clear()

    # Каталог данных при первом запуске ещё не существует, а FileHandler сам его
    # не создаёт: без makedirs логирование падало бы с FileNotFoundError.
    os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # В оконной сборке консоли нет вовсе: PyInstaller оставляет sys.stderr
    # равным None, и StreamHandler падал на первом же сообщении с
    # AttributeError: 'NoneType' object has no attribute 'write'.
    if sys.stderr is not None:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    return logger

logger = setup_logger('LocalTube')