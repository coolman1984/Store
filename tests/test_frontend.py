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
                continue  # the chart gradient stops are the brand volt colour by design
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
        """A shop PC is often old: keep the first load small (uncompressed bytes)."""
        total_js = sum(os.path.getsize(p) for p in JS)
        total_css = sum(os.path.getsize(p) for p in CSS)
        self.assertLess(total_js, 260_000, total_js)
        self.assertLess(total_css, 70_000, total_css)
        for name in os.listdir(os.path.join(WEB, 'fonts')):
            if name.endswith('.woff2'):
                self.assertLess(os.path.getsize(os.path.join(WEB, 'fonts', name)), 60_000, name)

    def test_fonts_are_local_and_licensed(self):
        css = read(os.path.join(WEB, 'css', 'tokens.css'))
        self.assertNotIn('http', css.split('*/', 1)[1])
        self.assertTrue(os.path.exists(os.path.join(WEB, 'fonts', 'OFL-ReadexPro.txt')))
        self.assertTrue(os.path.exists(os.path.join(WEB, 'fonts', 'OFL-Alexandria.txt')))


if __name__ == '__main__':
    unittest.main()
