"""Static checks of the page code: words in both languages, no inline styles (the CSP forbids them), logical CSS only,
icons that exist, size budgets. Fast, no browser."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'web')
JS = [os.path.join(dp, f) for dp, _, fs in os.walk(os.path.join(WEB, 'js')) for f in fs if f.endswith('.js')]
CSS = [os.path.join(WEB, 'css', f) for f in os.listdir(os.path.join(WEB, 'css'))]
KEY = re.compile(r"""(?:^|[,{])\s*(?:'([^']+)'|([A-Za-z_]\w*))\s*:\s*['"]""", re.M)
DYNAMIC = {  # prefixes built in code: every listed suffix must exist
    'nav.': ['pos', 'home', 'sales', 'customers', 'products', 'stock', 'receive', 'cash', 'watch', 'reports', 'settings', 'help'],
    'pay.': ['cash', 'card', 'wallet', 'instapay', 'finance', 'account', 'installment', 'split'],
    'role.': ['owner', 'manager', 'cashier', 'storekeeper'],
    'cashk.': ['float', 'float_out', 'sale', 'collection', 'deposit', 'drop_in', 'drop_out', 'over_short', 'expense', 'refund', 'supplier', 'purchase',
               'withdraw', 'reversal'],
    'move.': ['purchase', 'opening', 'sale', 'return', 'transfer_in', 'transfer_out', 'adjust'],
    'lic.state.': ['none', 'trial', 'active', 'grace', 'expired', 'not_yet_valid', 'invalid', 'clock_back', 'no_keys', 'practice'],
    'lic.err.': ['no_code', 'other_device', 'expired', 'bad_signature', 'wrong_length', 'bad_character', 'unknown_key', 'wrong_product', 'no_keys',
                 'unknown_version', 'invalid'],
    'support.field.': ['version', 'licence_state', 'last_backup_at', 'error_count', 'disk_free_mb'],
    'watch.k.': ['discount', 'under_cost', 'after_hours', 'return', 'drawer_short', 'drawer_over', 'big_expense', 'reversal', 'withdraw',
                 'price_change', 'stock_loss', 'negative_stock', 'payment_reversed', 'denied'],
}


def keys(path):
    text = read(path)
    body = text[text.index('export default {'):]
    return {a or b for a, b in KEY.findall(body)}


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


class Words(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ar = keys(os.path.join(WEB, 'i18n', 'ar.js'))
        cls.en = keys(os.path.join(WEB, 'i18n', 'en.js'))

    def test_both_languages_have_the_same_keys(self):
        self.assertGreater(len(self.ar), 800)
        self.assertEqual(sorted(self.ar - self.en), [])
        self.assertEqual(sorted(self.en - self.ar), [])

    def test_every_key_used_in_code_exists(self):
        missing = set()
        for path in JS:
            for k in re.findall(r"\bt\('([\w.]+)'(?!\s*\+)", read(path)):
                if k not in self.ar:
                    missing.add(f'{k} ({os.path.basename(path)})')
        self.assertEqual(sorted(missing), [])

    def test_dynamic_keys_exist(self):
        missing = [p + s for p, ss in DYNAMIC.items() for s in ss if p + s not in self.ar]
        self.assertEqual(missing, [])

    def test_every_server_problem_key_has_words(self):
        missing = set()
        for name in os.listdir(os.path.join(ROOT, 'server')):
            if name.endswith('.py'):
                for k in re.findall(r"(?:Problem|AuthError)\('((?:err|auth\.err)\.[\w]+)'", read(os.path.join(ROOT, 'server', name))):
                    if k not in self.ar:
                        missing.add(k)
        self.assertEqual(sorted(missing), [])

    def test_arabic_dictionary_is_arabic(self):
        text = read(os.path.join(WEB, 'i18n', 'ar.js'))
        values = re.findall(r":\s*'([^']*)'", text)
        arabic = [v for v in values if re.search('[؀-ۿ]', v)]
        self.assertGreater(len(arabic) / len(values), 0.9)


class PageCode(unittest.TestCase):
    def test_no_inline_styles_or_scripts(self):
        """The Content-Security-Policy forbids inline styles and scripts: they would silently not work."""
        for path in JS + [os.path.join(WEB, 'index.html')]:
            text = read(path)
            self.assertNotRegex(text, r'\sstyle="', path)
            self.assertNotIn('onclick=', text, path)
            self.assertNotIn('<script>', text, path)

    def test_quoted_attribute_strings_are_raw(self):
        """`${x ? 'attr="v"' : ''}` inside html`` would be escaped into a broken attribute; use raw()/CUR."""
        for path in JS:
            self.assertNotRegex(read(path), r"\?\s*'[a-z-]+=\"[^']*\"'", path)

    def test_css_uses_logical_properties(self):
        bad = re.compile(r'(?<![-\w])(margin|padding)-(left|right)\s*:|(?<![-\w])(left|right)\s*:\s*[-\d]|text-align:\s*(left|right)')
        for path in CSS:
            for n, line in enumerate(read(path).splitlines(), 1):
                self.assertIsNone(bad.search(line), f'{os.path.basename(path)}:{n}: {line.strip()}')

    def test_views_use_tokens_not_colours(self):
        for path in JS:
            if os.path.basename(path) == 'home.js':
                continue  # the chart gradient stops are the brand accent colour by design
            self.assertNotRegex(read(path), r'#[0-9a-fA-F]{6}\b', path)

    def test_icons_exist(self):
        sprite = read(os.path.join(WEB, 'img', 'icons.svg'))
        have = set(re.findall(r'<symbol id="([\w-]+)"', sprite))
        used = set()
        for path in JS:
            text = read(path)
            used |= set(re.findall(r"icon\('([\w-]+)'", text))
            used |= set(re.findall(r"icon: '([\w-]+)'", text))
            used |= set(re.findall(r"\['[\w]+', '([\w-]+)'(?:, [^\]]+)?\]", text)) & (have | {'x-missing'})
        for path in (os.path.join(WEB, 'i18n', 'help-ar.js'), os.path.join(WEB, 'i18n', 'help-en.js')):
            used |= set(re.findall(r"icon: '([\w-]+)'", read(path)))
        self.assertEqual(sorted(used - have), [])

    def test_size_budgets(self):
        """A shop PC is often old: keep the first load small (uncompressed bytes).
        The ceiling includes the vendored factory guide, consent and telemetry files. Those are required and not edited here."""
        total_js = sum(os.path.getsize(p) for p in JS)
        total_css = sum(os.path.getsize(p) for p in CSS)
        self.assertLess(total_js, 320_000, total_js)
        self.assertLess(total_css, 80_000, total_css)
        for name in os.listdir(os.path.join(WEB, 'fonts')):
            if name.endswith('.woff2'):
                self.assertLess(os.path.getsize(os.path.join(WEB, 'fonts', name)), 60_000, name)

    def test_fonts_are_local_and_licensed(self):
        css = read(os.path.join(WEB, 'css', 'tokens.css'))
        self.assertNotIn('http', css.split('*/', 1)[1])
        self.assertTrue(os.path.exists(os.path.join(WEB, 'fonts', 'OFL-ReadexPro.txt')))
        self.assertTrue(os.path.exists(os.path.join(WEB, 'fonts', 'OFL-Alexandria.txt')))


def _lum(hex_):
    c = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]


def contrast(a, b):
    a, b = _lum(a), _lum(b)
    return (max(a, b) + .05) / (min(a, b) + .05)


class DesignSystem(unittest.TestCase):
    """Al-Store design system v2 (the scale mark, navy/ivory/copper): the tokens keep WCAG AA contrast in both themes, the mark is one drawing everywhere."""

    @classmethod
    def setUpClass(cls):
        css = read(os.path.join(WEB, 'css', 'tokens.css'))
        def block(sel):
            body = css[css.index(sel + ' {'):]
            return dict(re.findall(r'--([\w-]+):\s*(#[0-9a-fA-F]{6})', body[:body.index('\n}')]))
        cls.day = block(':root')
        cls.night = {**cls.day, **block('[data-theme="night"]')}

    def test_text_contrast_is_aa_in_both_themes(self):
        pairs = [('ink', 'surface'), ('ink-2', 'surface'), ('ink-3', 'surface'), ('ink-3', 'canvas'), ('ink-3', 'surface-3'),
                 ('accent-ink', 'accent'), ('brand-ink', 'brand'), ('ok', 'ok-soft'), ('warn', 'warn-soft'), ('bad', 'bad-soft'),
                 ('info', 'info-soft'), ('accent', 'accent-soft')]
        for name, theme in (('day', self.day), ('night', self.night)):
            for fg, bg in pairs:
                self.assertGreaterEqual(contrast(theme[fg], theme[bg]), 4.5, f'{name}: --{fg} on --{bg}')
        self.assertGreaterEqual(contrast(self.day['rail-ink-2'], self.day['rail']), 4.5)

    def test_one_mark_drawing_everywhere(self):
        """The app (brand.js), the splash (index.html), the favicon and the Windows icon draw the same mark."""
        for rel in ('js/brand.js', 'index.html', 'img/icon.svg'):
            text = read(os.path.join(WEB, rel))
            for part in ('y="12" width="26" height="4.5"', 'y="19.5" width="26" height="4.5"', 'M24 26 32 36H16Z'):
                self.assertIn(part, text, rel)
        icon = read(os.path.join(ROOT, 'tools', 'make_icon.py'))
        self.assertIn('(24 * u, 26 * u), (32 * u, 36 * u), (16 * u, 36 * u)', icon)

    def test_the_product_is_called_al_store_and_never_mizan(self):
        """«Mizan» is the owner's accounting product (factory decision of 2026-10-10): nothing a shop sees may carry it."""
        for rel in ('index.html', 'manifest.webmanifest', 'i18n/ar.js', 'i18n/en.js', 'js/brand.js', 'js/app.js'):
            text = read(os.path.join(WEB, rel))
            self.assertNotRegex(text, r'ميزان|Mizan|MIZAN', rel)
        ar, en = read(os.path.join(WEB, 'i18n', 'ar.js')), read(os.path.join(WEB, 'i18n', 'en.js'))
        self.assertIn("'app.name': 'الستور'", ar)
        self.assertIn("'app.name': 'Al-Store'", en)
        brand = os.path.join(ROOT, 'docs', 'brand')
        self.assertFalse([f for f in os.listdir(brand) if 'mizan' in f.lower()], 'logo files carry the new name')
        for f in os.listdir(brand):
            self.assertNotRegex(read(os.path.join(brand, f)), r'Mizan|ميزان', f)

    def test_no_leftover_of_the_old_identity(self):
        for path in JS + CSS:
            self.assertNotIn('volt', read(path), path)

    def test_no_backdrop_blur(self):
        """A backdrop blur costs ~20 ms a frame on an old shop PC (UI Lab, 1.0.1); a sticky bar repaints it on every scroll."""
        for path in CSS:
            self.assertNotIn('backdrop-filter', read(path), path)

    def test_endless_animations_stop_when_motion_is_reduced(self):
        """Durations from tokens drop to 1 ms on their own; a literal endless one needs its own off switch in both places."""
        css = ''.join(read(p) for p in CSS)
        loops = set(re.findall(r'animation:\s*([\w-]+)\s+[\d.]+m?s[^;]*infinite', css)) - {'spin', 'shimmer'}  # busy indicators stay
        self.assertTrue(loops)
        for name in loops:
            owner = re.search(r'([.\w-]+(?:::?[\w-]+)?)\s*\{[^}]*animation:\s*' + name, css).group(1)
            self.assertIn('prefers-reduced-motion: reduce) { ' + owner + ' { animation: none', css, name)
            self.assertIn('[data-motion="off"] ' + owner + ' { animation: none', css, name)

    def test_icons_and_controls_follow_the_geometry(self):
        tokens = read(os.path.join(WEB, 'css', 'tokens.css'))
        for rule in ('--fs: 16px', '--icon: 20px', '--tap: 44px'):
            self.assertIn(rule, tokens)


if __name__ == '__main__':
    unittest.main()
