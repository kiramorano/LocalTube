#!/usr/bin/env python3
"""
server.py – Умный менеджер HTTP-сервера PO-токенов.
Запускает сервер через BAT-файл в новом окне.
"""

import os
import sys
import time
import subprocess
import threading
import requests
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('[PO-SERVER] %(levelname)s: %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CLI_PATH = os.path.join(PROJECT_ROOT, 'bgutil-pot-windows-x86_64.exe')
PO_SERVER_PORT = 4416
PO_SERVER_URLS = [
    f'http://127.0.0.1:{PO_SERVER_PORT}',
    f'http://localhost:{PO_SERVER_PORT}',
    f'http://[::1]:{PO_SERVER_PORT}',
]
MAX_RESTART_ATTEMPTS = 5
MONITOR_INTERVAL = 3


class PoServerManager:
    def __init__(self):
        self.process = None
        self._monitor_thread = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._restart_count = 0
        self._running = False
        self._server_url = None

    def _is_server_responding(self) -> bool:
        for url in PO_SERVER_URLS:
            try:
                resp = requests.get(f'{url}/ping', timeout=2)
                if resp.status_code == 200:
                    self._server_url = url
                    return True
            except:
                continue
        return False

    def is_running(self) -> bool:
        return self._is_server_responding()

    def get_url(self) -> Optional[str]:
        if self._server_url:
            return self._server_url
        for url in PO_SERVER_URLS:
            try:
                resp = requests.get(f'{url}/ping', timeout=2)
                if resp.status_code == 200:
                    self._server_url = url
                    return url
            except:
                continue
        return None

    def _kill_process_on_port(self, port: int = PO_SERVER_PORT) -> bool:
        try:
            result = subprocess.run(
                f'netstat -ano | findstr :{port}',
                shell=True, capture_output=True, text=True
            )
            lines = result.stdout.strip().split('\n')
            pids = set()
            for line in lines:
                if 'LISTENING' in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        if pid.isdigit():
                            pids.add(int(pid))
            for pid in pids:
                try:
                    subprocess.run(f'taskkill /PID {pid} /F', shell=True, capture_output=True)
                    logger.info(f"Убит процесс {pid}, занимавший порт {port}")
                except:
                    pass
            return True
        except Exception as e:
            logger.warning(f"Не удалось убить процесс на порту {port}: {e}")
            return False

    def _create_bat_file(self) -> str:
        bat_path = os.path.join(PROJECT_ROOT, 'start_server.bat')
        with open(bat_path, 'w', encoding='utf-8') as f:
            f.write('@echo off\n')
            f.write(f'cd /d "{PROJECT_ROOT}"\n')
            f.write(f'"{CLI_PATH}" server\n')
            f.write('echo.\n')
            f.write('echo Сервер завершил работу. Нажмите любую клавишу для закрытия окна...\n')
            f.write('pause >nul\n')
        logger.info(f"Создан BAT-файл: {bat_path}")
        return bat_path

    def _launch_server(self) -> bool:
        if not os.path.exists(CLI_PATH):
            logger.error(f"Файл {CLI_PATH} не найден")
            return False

        self._kill_process_on_port(PO_SERVER_PORT)

        try:
            bat_path = self._create_bat_file()
            cmd = f'start "PO-Server" "{bat_path}"'
            logger.info(f"Выполняем: {cmd}")
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info("Команда запуска сервера отправлена")
            return True
        except Exception as e:
            logger.error(f"Ошибка запуска сервера: {e}")
            return False

    def start(self, wait: bool = True, timeout: int = 30) -> bool:
        with self._lock:
            if self.is_running():
                logger.info("Сервер уже запущен")
                return True

            if not self._launch_server():
                return False

            if not wait:
                self._running = True
                return True

            logger.info(f"Ожидание запуска сервера (до {timeout}с)...")
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.is_running():
                    logger.info(f"✅ Сервер успешно запущен ({self.get_url()})")
                    self._running = True
                    self._restart_count = 0
                    self._start_monitor()
                    return True
                time.sleep(0.5)

            logger.warning(f"Сервер не запустился за {timeout} секунд")
            self.stop()
            return False

    def stop(self) -> bool:
        with self._lock:
            self._stop_event.set()
            self._running = False
            if self.process:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=3)
                    logger.info("Сервер остановлен")
                except Exception:
                    self.process.kill()
                    logger.warning("Сервер принудительно завершён")
                self.process = None
            return self._kill_process_on_port(PO_SERVER_PORT)

    def restart(self) -> bool:
        logger.info("Перезапуск сервера...")
        self.stop()
        time.sleep(1)
        return self.start(wait=True, timeout=30)

    def _monitor_loop(self):
        while not self._stop_event.is_set():
            time.sleep(MONITOR_INTERVAL)
            if self._running and not self.is_running():
                logger.warning("Сервер не отвечает, пытаемся перезапустить...")
                with self._lock:
                    if self._restart_count >= MAX_RESTART_ATTEMPTS:
                        logger.error(f"Достигнут лимит перезапусков ({MAX_RESTART_ATTEMPTS})")
                        self._stop_event.set()
                        break
                    self._restart_count += 1
                    logger.info(f"Перезапуск #{self._restart_count}")
                    self._kill_process_on_port(PO_SERVER_PORT)
                    time.sleep(2)
                    if self._launch_server():
                        start_time = time.time()
                        while time.time() - start_time < 30:
                            if self.is_running():
                                logger.info(f"Сервер перезапущен ({self.get_url()})")
                                break
                            time.sleep(0.5)
                        else:
                            logger.warning("Не удалось перезапустить сервер")
                    else:
                        logger.warning("Ошибка при запуске сервера")

    def _start_monitor(self):
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._stop_event.clear()
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()

    def status(self) -> Dict[str, Any]:
        return {
            'running': self.is_running(),
            'url': self.get_url(),
            'port': PO_SERVER_PORT,
            'pid': self.process.pid if self.process else None,
            'restart_count': self._restart_count,
            'max_restarts': MAX_RESTART_ATTEMPTS,
        }

    def shutdown(self):
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2)
        self.stop()


_manager = PoServerManager()


def ensure_server() -> bool:
    return _manager.start(wait=True, timeout=30)


def is_server_running() -> bool:
    return _manager.is_running()


def get_server_url() -> Optional[str]:
    return _manager.get_url()


def restart_server() -> bool:
    return _manager.restart()


def stop_server() -> bool:
    return _manager.stop()


def get_server_status() -> Dict[str, Any]:
    return _manager.status()


def shutdown_server():
    _manager.shutdown()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--restart', action='store_true')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()

    if args.start:
        if ensure_server():
            print("✅ Сервер запущен")
        else:
            print("❌ Не удалось запустить сервер")
    elif args.stop:
        if stop_server():
            print("✅ Сервер остановлен")
        else:
            print("❌ Ошибка при остановке")
    elif args.restart:
        if restart_server():
            print("✅ Сервер перезапущен")
        else:
            print("❌ Не удалось перезапустить сервер")
    elif args.status:
        status = get_server_status()
        print(f"Статус: {'✅ Запущен' if status['running'] else '❌ Остановлен'}")
        print(f"URL: {status['url'] or 'не доступен'}")
        print(f"Порт: {status['port']}")
        print(f"PID: {status['pid'] or 'нет'}")
        print(f"Перезапусков: {status['restart_count']} / {status['max_restarts']}")
    else:
        parser.print_help()