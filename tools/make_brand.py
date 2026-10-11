"""Writes the Al-Store logo files (docs/brand/*.svg) with the words drawn as outlines, so they look the same on any computer.
Build-time only: needs fonttools, brotli and uharfbuzz (pip install fonttools brotli uharfbuzz). The app itself draws the
mark from web/js/brand.js and the words with the bundled fonts; these files are for print, the installer and the website.

    python tools/make_brand.py
"""
import io
import os

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, 'web', 'fonts')
OUT = os.path.join(ROOT, 'docs', 'brand')
NAVY, IVORY, COPPER, INK_DARK = '#13213c', '#f3e9d8', '#c8743c', '#0e1726'
MARK = ('<rect width="48" height="48" rx="12" fill="{tile}"/><rect x="11" y="12" width="26" height="4.5" rx="2.25" fill="{beam}"/>'
        '<rect x="11" y="19.5" width="26" height="4.5" rx="2.25" fill="{pan}"/>'
        '<path d="M24 26 32 36H16Z" fill="{beam}" stroke="{beam}" stroke-width="1.5" stroke-linejoin="round"/>')


def words(file, text, weight, size, direction, track=0.0):
    """Shape text with HarfBuzz (Arabic joins correctly) and return (svg path, width) at the given size; track = extra px per letter."""
    font = TTFont(os.path.join(FONTS, file))
    font = instantiateVariableFont(font, {'wght': weight})
    buf = io.BytesIO()
    font.flavor = None
    font.save(buf)
    face = hb.Face(buf.getvalue())
    hfont = hb.Font(face)
    b = hb.Buffer()
    b.add_str(text)
    b.guess_segment_properties()
    b.direction = direction
    hb.shape(hfont, b)
    upem = font['head'].unitsPerEm
    scale = size / upem
    glyphs = font.getGlyphSet()
    order = font.getGlyphOrder()
    pen = SVGPathPen(glyphs)
    x = 0
    for info, pos in zip(b.glyph_infos, b.glyph_positions):
        t = TransformPen(pen, (scale, 0, 0, -scale, (x + pos.x_offset) * scale, -pos.y_offset * scale))
        glyphs[order[info.codepoint]].draw(t)
        x += pos.x_advance + track / scale
    return pen.getCommands(), x * scale - track


def lockup(tone):
    tile, beam, ink = (NAVY, IVORY, INK_DARK) if tone == 'light' else (IVORY, NAVY, '#ffffff')
    ar, ar_w = words('alexandria-arabic-wght-normal.woff2', 'الستور', 700, 40, 'rtl')
    la, la_w = words('readex-pro-latin-wght-normal.woff2', 'AL-STORE', 500, 11, 'ltr', track=3.2)
    gap = 14
    width = 56 + gap + max(ar_w, la_w) + 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} 62" role="img" aria-label="الستور Al-Store">'
            f'<g transform="translate(0 7)">{MARK.format(tile=tile, beam=beam, pan=COPPER)}</g>'
            f'<path transform="translate({56 + gap + max(0.0, la_w - ar_w):.1f} 33)" fill="{ink}" d="{ar}"/>'
            f'<path transform="translate({56 + gap + max(0.0, ar_w - la_w):.1f} 59)" fill="{COPPER}" d="{la}"/></svg>')  # under the word, aligned to where Arabic starts


def main():
    os.makedirs(OUT, exist_ok=True)
    files = {
        'store-mark.svg': f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">{MARK.format(tile=NAVY, beam=IVORY, pan=COPPER)}</svg>',
        'store-mark-on-dark.svg': f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">{MARK.format(tile=IVORY, beam=NAVY, pan=COPPER)}</svg>',
        'store-logo-on-light.svg': lockup('light'),
        'store-logo-on-dark.svg': lockup('dark'),
    }
    for name, svg in files.items():
        with open(os.path.join(OUT, name), 'w', encoding='utf-8') as f:
            f.write(svg + '\n')
        print('wrote', os.path.join('docs', 'brand', name))


if __name__ == '__main__':
    main()
