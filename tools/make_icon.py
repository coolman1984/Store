"""Draws the Al-Store icon (the same shape as web/img/icon.svg) into a Windows .ico. Build-time only: needs Pillow.

    python tools/make_icon.py build/store.ico
"""
import sys

from PIL import Image, ImageDraw

INK, VOLT_A, VOLT_B = (18, 22, 27), (214, 255, 74), (159, 214, 15)
BOLT = [(35, 14), (20, 36), (32, 36), (29, 50), (44, 28), (32, 28)]


def draw(size):
    k = 8  # draw large, then shrink: smooth edges
    big = size * k
    unit = big / 64
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=18 * unit, fill=INK + (255,))
    face = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    px = face.load()
    for y in range(big):
        for x in range(big):
            t = (x + y) / (2 * big)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(VOLT_A, VOLT_B)) + (255,)
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([8 * unit, 8 * unit, 56 * unit, 56 * unit], radius=14 * unit, fill=255)
    img.paste(face, (0, 0), mask)
    ImageDraw.Draw(img).polygon([(x * unit, y * unit) for x, y in BOLT], fill=INK + (255,))
    return img.resize((size, size), Image.LANCZOS)


def main(out):
    sizes = [16, 24, 32, 48, 64, 128, 256]
    draw(256).save(out, format='ICO', sizes=[(s, s) for s in sizes])
    print('wrote', out)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'store.ico')
