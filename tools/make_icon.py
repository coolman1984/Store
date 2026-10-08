"""Draws the Mizan mark (the same shape as web/img/icon.svg) into a Windows .ico. Build-time only: needs Pillow.

    python tools/make_icon.py build/store.ico
"""
import sys

from PIL import Image, ImageDraw

NAVY, IVORY, COPPER = (19, 33, 60), (243, 233, 216), (200, 116, 60)


def draw(size):
    k = 8  # draw large, then shrink: smooth edges
    big = size * k
    u = big / 48  # the SVG is drawn on a 48-unit grid
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=12 * u, fill=NAVY + (255,))
    d.rounded_rectangle([11 * u, 12 * u, 37 * u, 16.5 * u], radius=2.25 * u, fill=IVORY + (255,))   # the beam
    d.rounded_rectangle([11 * u, 19.5 * u, 37 * u, 24 * u], radius=2.25 * u, fill=COPPER + (255,))  # the balancing bar
    d.polygon([(24 * u, 26 * u), (32 * u, 36 * u), (16 * u, 36 * u)], fill=IVORY + (255,))  # the fulcrum
    return img.resize((size, size), Image.LANCZOS)


def main(out):
    sizes = [16, 24, 32, 48, 64, 128, 256]
    draw(256).save(out, format='ICO', sizes=[(s, s) for s in sizes])
    print('wrote', out)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'store.ico')
