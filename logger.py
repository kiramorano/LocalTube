"""
logger.py – простая настройка логирования.
Записывает логи в файл logs.txt и дублирует в консоль.
"""

import logging
import os

LOG_FILE = os.path.join(os.path.dirname(__file__), 'logs.txt')

def setup_logger(name=__name__, log_file=LOG_FILE, level=logging.DEBUG):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.hasHandlers():
        logger.handlers.clear()

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger

logger = setup_logger('LocalTube')