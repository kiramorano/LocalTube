# Сборка LocalTube

Все скрипты сборки лежат в `packaging/` и запускаются обычным Python. Отдельного Makefile нет намеренно: на Windows его нечем выполнять, а логика всё равно должна быть одинаковой у локальной сборки и у CI.

Порядок один и тот же: подготовить ассеты, собрать приложение через PyInstaller, упаковать результат.

## Что нужно

Общее:

- Python 3.9+ (собирается на 3.12; для Windows 7 нужен именно 3.8, см. ниже)
- зависимости приложения: `pip install -r requirements.txt`
- PyInstaller: `pip install pyinstaller`

Windows, дополнительно для MSI — достаточно любого из двух вариантов:

- **WiX 4.** Нужен .NET SDK: из него скрипт сам поставит инструмент, если найдёт `dotnet` вместе с SDK. Этот путь использует CI.
- **WiX 3.** Работает на .NET Framework, который есть в Windows из коробки, и не требует прав администратора. Скачайте [wix314-binaries.zip](https://github.com/wixtoolset/wix3/releases), распакуйте и укажите каталог в переменной окружения:

  ```powershell
  $env:WIX3_BIN = "C:\путь\к\wix3"
  ```

  Скрипт берёт WiX 3, только если WiX 4 недоступен. Помимо переменной он проверяет `PATH`, переменную `WIX` и стандартные каталоги установки WiX Toolset 3.14/3.11.

Одного рантайма `.NET` для WiX 4 не хватает: `dotnet tool install` требует именно SDK. Скрипт проверяет это заранее через `dotnet --list-sdks` и молча переходит на WiX 3, а не падает.

Linux, дополнительно:

```bash
sudo apt install -y libgirepository1.0-dev libcairo2-dev pkg-config python3-dev \
  gir1.2-gtk-3.0 gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 rpm dpkg-dev fuse libfuse2
pip install pycairo PyGObject
```

`rpm` нужен даже для сборки RPM на Ubuntu, `fuse` — для AppImage. Сам `appimagetool` скачивается с GitHub проекта AppImage.

## Windows

Одна команда собирает всё:

```powershell
python packaging\build_windows.py --targets zip,portable,msi
```

Результат — в `release/`. Отдельные цели: `--targets zip`, `--targets msi`. Для 32-битной сборки нужен 32-битный Python и ключ `--arch x86`.

Ключ `--no-ffmpeg` отключает вложение FFmpeg: сборка получится меньше, но потребует FFmpeg в `PATH` у пользователя.

## Linux

PyInstaller и упаковка вызываются отдельно, чтобы из одной сборки получить все четыре формата:

```bash
python packaging/make_icons.py
python packaging/fetch_ffmpeg.py --platform linux --arch x64
pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/localtube.spec
python packaging/build_linux.py --source dist/LocalTube --formats deb,rpm,appimage,targz
```

Если какой-то формат собрать нечем (нет `rpmbuild`, нет `appimagetool`), скрипт пропустит его с сообщением и соберёт остальные.

## Windows 7

Собирается только на Windows и требует именно Python 3.8: более новые версии на «семёрке» не запускаются, а PyInstaller 6.x объявляет поддержку Windows 8 и новее.

```powershell
py -3.8 -m pip install -r requirements-legacy.txt
py -3.8 packaging\build_windows.py --targets zip,portable --spec localtube-legacy.spec --out release-legacy
```

Спек `localtube-legacy.spec` укладывает внутрь Chromium (cefpython3) — на Windows 7 нет WebView2. Про ограничение загрузок с YouTube в этой сборке написано в [PLATFORMS.md](PLATFORMS.md#windows-7).

## Из чего состоят скрипты

| Файл | Задача |
|---|---|
| `packaging/spec_common.py` | общая часть трёх спеков: списки данных, скрытых импортов, исключений |
| `packaging/localtube.spec` | обычная сборка каталогом (для ZIP, MSI, DEB, RPM, AppImage) |
| `packaging/localtube-portable.spec` | портативная сборка одним файлом |
| `packaging/localtube-legacy.spec` | сборка для Windows 7 со вложенным Chromium |
| `packaging/make_icons.py` | генерирует `.ico` и набор PNG |
| `packaging/fetch_ffmpeg.py` | скачивает FFmpeg в `packaging/assets/ffmpeg` |
| `packaging/make_wxs.py` | описание MSI для WiX по содержимому сборки |
| `packaging/build_windows.py` | ZIP, portable.exe, MSI |
| `packaging/build_linux.py` | DEB, RPM, AppImage, tar.gz |

Иконки генерируются кодом, а не хранятся картинками: `.gitignore` исключает `*.png` и `*.ico` целиком, потому что под эти маски попадают превью и аватарки из библиотеки.

## Проверка сборки

Собранное приложение должно как минимум поднимать сервер:

```powershell
$env:LOCALTUBE_DATA_DIR = "$env:TEMP\lt-check"
.\release\dist\LocalTube\LocalTube.exe --no-window
# в другом окне:
curl http://127.0.0.1:5000/api/network/ping
```

Тот же шаг выполняется в CI после каждой сборки: без него в релиз уходила бы сборка, падающая при первом запуске из-за ненайденного модуля или отсутствующих шаблонов.

Тесты запускаются до сборки:

```bash
python -m pytest
```

## CI

`.github/workflows/build-release.yml` собирает всё перечисленное на тег `v*`: Windows x64/x86, Windows 7 x64/x86, Linux x64. Перед сборкой прогоняются тесты, после — проверка запуска и содержимого пакетов.
