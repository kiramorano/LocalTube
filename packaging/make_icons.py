#!/usr/bin/env python3
"""make_icons.py — генерирует иконки приложения для всех сборок.

Иконки собираются кодом, а не лежат готовыми картинками, по двум причинам.
Во-первых, ``.gitignore`` в этом проекте исключает ``*.png`` и ``*.ico``
целиком (там прячутся превью и аватарки из библиотеки), поэтому набор бинарных
файлов пришлось бы протаскивать исключениями и следить, чтобы вместе с ними в
историю не попали чужие картинки. Во-вторых, форматов нужно много: Windows
хочет многоразмерный ``.ico``, DEB и RPM — набор PNG под каталоги hicolor,
AppImage — один PNG рядом с ``.desktop``.

Запуск:
    python packaging/make_icons.py [--out КАТАЛОГ]
"""
import argparse
import os
import sys

# Каталог проекта нужен в пути раньше импорта version: скрипт запускают из
# packaging/, и без этого «import version» падал бы на ModuleNotFoundError.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Размеры для .ico: Windows берёт из файла подходящий сам — 16 для списка
# файлов, 32 для панели задач, 256 для крупных значков рабочего стола.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# Размеры PNG для каталогов hicolor в DEB и RPM.
PNG_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)

# Цвета: тёмный фон интерфейса и красная кнопка воспроизведения.
BG_DARK = (15, 15, 15, 255)
ACCENT = (255, 0, 51, 255)
GLYPH = (255, 255, 255, 255)


def _rounded_mask(size, radius_ratio=0.22):
    """Маска скруглённого квадрата.

    Прямой квадрат выглядит чужеродно и в панели задач Windows, и в докax
    Linux, где все остальные значки скруглены.
    """
    from PIL import Image, ImageDraw

    mask = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(size * radius_ratio)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def render(size):
    """Рисует иконку заданного размера: тёмная плитка и белый треугольник.

    Рисуем на увеличенном холсте и уменьшаем результат: прямая отрисовка
    треугольника в 16 пикселей даёт рваные края, потому что PIL не сглаживает
    полигоны.
    """
    from PIL import Image, ImageDraw

    scale = 8 if size <= 64 else 4
    big = size * scale
    canvas = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    draw.rectangle((0, 0, big - 1, big - 1), fill=BG_DARK)

    # Красный «экран» с белым треугольником — узнаваемая метафора плеера.
    pad = big * 0.18
    draw.rounded_rectangle((pad, pad * 1.35, big - pad, big - pad * 1.35),
                           radius=int(big * 0.12), fill=ACCENT)

    cx, cy = big / 2, big / 2
    half = big * 0.13
    draw.polygon([(cx - half * 0.8, cy - half),
                  (cx - half * 0.8, cy + half),
                  (cx + half * 1.1, cy)], fill=GLYPH)

    canvas.putalpha(_rounded_mask(big))
    return canvas.resize((size, size), Image.LANCZOS)


def write_icons(out_dir):
    """Создаёт .ico, .png набор и мастер-файл. Возвращает список путей."""
    from PIL import Image

    os.makedirs(out_dir, exist_ok=True)
    written = []

    images = {size: render(size) for size in sorted(set(ICO_SIZES + PNG_SIZES))}

    # Windows: один .ico со всеми размерами внутри.
    ico_path = os.path.join(out_dir, 'localtube.ico')
    base = images[max(ICO_SIZES)]
    base.save(ico_path, format='ICO',
              sizes=[(s, s) for s in ICO_SIZES])
    written.append(ico_path)

    # Linux: отдельные файлы под каталоги hicolor.
    for size in PNG_SIZES:
        png_path = os.path.join(out_dir, f'localtube-{size}.png')
        images[size].save(png_path, format='PNG')
        written.append(png_path)

    # Основной PNG: окно pywebview на Linux и .desktop-файл ссылаются на него.
    main_png = os.path.join(out_dir, 'localtube.png')
    images[256].save(main_png, format='PNG')
    written.append(main_png)

    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description='Генерация иконок LocalTube')
    parser.add_argument('--out', default=os.path.join(_HERE, 'assets'),
                        help='Каталог для иконок (по умолчанию packaging/assets)')
    args = parser.parse_args(argv)

    try:
        import PIL  # noqa: F401
    except ImportError:
        print('Нужен Pillow: pip install pillow', file=sys.stderr)
        return 1

    for path in write_icons(args.out):
        print(f'  создан {os.path.relpath(path, _ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
