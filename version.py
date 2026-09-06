"""version.py — единственное место с номером версии.

Номер нужен установщикам: MSI сравнивает версии при обновлении, DEB и RPM
кладут её в метаданные пакета, AppImage — в имя файла. Раньше версия жила
только в git-тегах, поэтому собрать пакет без git было нельзя.

Формат — три числа, как требует MSI (``ProductVersion``: major.minor.build,
каждое поле ограничено). Суффиксы вида ``-rc1`` здесь недопустимы намеренно:
Windows Installer их не понимает и молча обрезает.
"""

__version__ = "3.2.0"

# Название и издатель попадают в свойства exe, в «Установку и удаление
# программ», в .desktop и в метаданные пакетов.
APP_NAME = "LocalTube"
APP_DESCRIPTION = "Локальная библиотека видео с интерфейсом в стиле YouTube"
APP_AUTHOR = "kiramorano"
APP_ID = "io.github.kiramorano.LocalTube"
APP_URL = "https://github.com/kiramorano/LocalTube"


def version_tuple():
    """Версия числами — для сравнений и для WiX."""
    return tuple(int(part) for part in __version__.split("."))
