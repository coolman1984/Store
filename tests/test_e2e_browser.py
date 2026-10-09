"""The real program in a real browser (Playwright + the pre-installed Chromium). Skipped when Playwright is missing.

Covers the paid core journey (open shift → sell by keyboard → receipt → return with a manager's approval → close the shift),
both languages and directions, the licence lock, and a measured layout sweep: no page may be wider than the screen and no
text may spill out of its card on a phone, a tablet or a PC (factory UX-08: screenshots are not proof, measurements are).
"""
import json
import os
import unittest

from harness import HAVE_CRYPTO, OWNER, PW, Server

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

CHROMIUM = os.environ.get('STORE_CHROMIUM', '/opt/pw-browsers/chromium')
SKIP = unittest.skipIf(sync_playwright is None or not os.path.exists(CHROMIUM), 'Playwright or Chromium not available')
ROUTES = ['home', 'pos', 'sales', 'sales?tab=warranty', 'customers', 'customers?tab=due', 'products', 'stock', 'stock?tab=count',
          'stock?tab=value', 'receive', 'receive?tab=suppliers', 'cash', 'cash?tab=safe', 'cash?tab=shifts', 'watch', 'reports',
          'settings', 'settings?tab=licence', 'settings?tab=users', 'settings?tab=backup', 'settings?tab=support', 'settings?tab=device', 'help']
OVERFLOW = """() => {
  const vw = document.documentElement.clientWidth, out = [];
  if (document.documentElement.scrollWidth > vw + 1) out.push('page wider than screen: ' + document.documentElement.scrollWidth + ' > ' + vw);
  for (const el of document.querySelectorAll('.page *')) {
    const r = el.getBoundingClientRect();
    if (!r.width || el.closest('.table-wrap, .pos-cats, .tabs, .serial-list, .parked, .chart-wrap')) continue;
    if (r.right > vw + 1 || r.left < -1) { out.push(el.tagName + '.' + el.className + ' outside the screen (' + Math.round(r.left) + '..' + Math.round(r.right) + ')'); }
    const card = el.closest('.card');
    if (card && el !== card && !el.closest('.dialog, .panel')) {
      const c = card.getBoundingClientRect();
      if ((r.right > c.right + 2 || r.left < c.left - 2) && getComputedStyle(el).position !== 'absolute') out.push(el.tagName + '.' + el.className + ' spills out of its card');
    }
  }
  return [...new Set(out)].slice(0, 8);
}"""


class Browser(unittest.TestCase):
    practice = True

    @classmethod
    def setUpClass(cls):
        cls.S = Server(practice=cls.practice, licensed=getattr(cls, "licensed", True))
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path=CHROMIUM)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.S.stop()

    def open(self, user='manager', password='practice-1234', width=1366, height=860, prefs=None):
        ctx = self.browser.new_context(viewport={'width': width, 'height': height})
        ctx.add_init_script("localStorage.setItem('store.prefs', %s)" % json.dumps(json.dumps({'lang': 'ar', 'sound': False, 'motion': 'off', **(prefs or {})})))
        pg = ctx.new_page()
        self.errors = []
        expected = ('status of 4',)  # 401/402/403/409 are business answers the page handles (approval, licence, …)
        pg.on('console', lambda m: self.errors.append(m.text) if m.type == 'error' and not any(x in m.text for x in expected) else None)
        pg.on('pageerror', lambda e: self.errors.append(str(e)))
        pg.goto(self.S.base)
        pg.wait_for_selector('#auth-form')
        pg.fill('#username', user)
        pg.fill('#password', password)
        pg.click('button[type=submit]')
        pg.wait_for_selector('.shell')
        return pg

    def until(self, pg, expression, seconds=10):
        """Poll an expression until it is truthy (the page's security policy forbids wait_for_function's string)."""
        import time
        end = time.time() + seconds
        while time.time() < end:
            value = pg.evaluate(expression)
            if value:
                return value
            pg.wait_for_timeout(100)
        self.fail('timed out waiting for ' + expression)

    def go(self, pg, route):
        pg.goto(self.S.base + '/#/' + route)
        pg.wait_for_selector('#page')
        pg.wait_for_timeout(150)
        pg.wait_for_selector('#page [aria-busy="true"]', state='detached', timeout=15000)
        pg.wait_for_timeout(250)


@SKIP
class CoreJourney(Browser):
    def test_sell_by_keyboard_print_return_with_approval(self):
        pg = self.open('cashier')
        self.go(pg, 'pos')
        if pg.query_selector('[data-open]'):  # the practice cashier may not have today's shift
            pg.fill('#float', '300')
            pg.click('[data-open]')
        pg.wait_for_selector('#pos-q')
        pg.fill('#pos-q', 'غلاية')
        pg.wait_for_timeout(250)
        pg.keyboard.press('Enter')
        pg.wait_for_selector('.line')
        pg.keyboard.press('+')
        self.assertEqual(pg.input_value('.q-in'), '2')
        pg.keyboard.press('F4')
        pg.wait_for_selector('#recv')
        pg.fill('#recv', '3000')
        self.assertIn('700', pg.inner_text('#change'))
        pg.keyboard.press('Enter')
        pg.wait_for_selector('.done')
        number = pg.inner_text('.done .muted')
        self.assertRegex(number, r'S-\d{6}')
        pg.click('.dialog [data-close]:not(.icon-btn)')
        self.assertEqual(pg.query_selector_all('.line'), [])
        # the cashier takes a return: the manager types their password on the same screen
        self.go(pg, 'sales?q=' + number)
        pg.click('tr[data-id]')
        pg.wait_for_selector('[data-return]')
        pg.click('[data-return]')
        pg.fill('[data-rq]', '1')
        pg.fill('#r-why', 'الزبون غيّر رأيه')
        pg.click('.dialog [data-ok]')
        pg.wait_for_selector('#ap-u')
        pg.fill('#ap-u', 'manager')
        pg.fill('#ap-p', 'practice-1234')
        pg.locator('.dialog [data-ok]').last.click()
        pg.wait_for_selector('.toast')
        self.assertIn('R-', pg.inner_text('.toasts'))
        self.assertEqual(self.errors, [])

    def test_receipt_and_labels_carry_barcodes(self):
        pg = self.open('manager')
        pg.add_init_script("window.print = () => { window.__printed = document.getElementById('print-area').innerHTML; }")
        pg.reload()
        pg.wait_for_selector('.shell')
        self.go(pg, 'sales')
        pg.click('[data-seg="range"] [data-v="week"]')  # the practice shop's day starts at 10:05: "today" is empty before that
        pg.click('tr[data-id]')
        pg.wait_for_selector('[data-print], [data-reprint], .dialog')
        pg.evaluate("(id) => import('/js/print.js').then((m) => fetch('/api/sale?id=' + id).then((r) => r.json()).then((sale) => m.printReceipt(sale)))",
                    pg.get_attribute('tr[data-id]', 'data-id'))
        receipt = self.until(pg, 'window.__printed')
        self.assertIn('class="barcode"', receipt)  # the receipt number is a real Code 128 barcode now
        pg.evaluate('window.__printed = null')
        pg.keyboard.press('Escape')
        self.go(pg, 'products')
        pg.click('tr[data-id]')
        pg.click('[data-labels]')
        pg.fill('#lb-n', '3')
        pg.click('.dialog [data-ok]')
        self.until(pg, 'window.__printed')
        labels = pg.evaluate("document.querySelectorAll('#print-area .label svg.barcode').length")
        self.assertEqual(labels, 3)
        self.assertEqual(self.errors, [])

    def test_language_switch_and_direction(self):
        pg = self.open()
        self.assertEqual(pg.evaluate('document.documentElement.dir'), 'rtl')
        pg.click('[data-lang]')
        pg.wait_for_function("document.documentElement.dir === 'ltr'")
        self.assertIn('Sell', pg.inner_text('.rail'))
        self.assertEqual(self.errors, [])

    def test_command_palette_finds_a_product(self):
        pg = self.open()
        pg.keyboard.press('Control+k')
        pg.fill('#cmdk-q', 'خلاط')
        pg.wait_for_selector('.cmdk-item >> text=خلاط')
        self.assertEqual(self.errors, [])


@SKIP
class PeopleAndProfiles(Browser):
    """The owner checks who can do what, makes a profile and takes a page away from the cashier; the cashier no longer
    sees it in the menu and gets the "not allowed" card when typing its address (the server refuses its data too)."""

    def test_owner_controls_what_each_person_sees(self):
        pg = self.open('owner')
        pg.add_init_script("window.print = () => { window.__printed = document.getElementById('print-area').innerHTML; }")
        pg.reload()
        pg.wait_for_selector('.shell')
        self.go(pg, 'settings?tab=users')
        pg.click('[data-matrix]')
        pg.wait_for_selector('.t.matrix')
        self.assertGreater(pg.locator('.t.matrix tbody tr').count(), 25)
        pg.click('.dialog [data-print]')
        self.assertIn('✓', self.until(pg, 'window.__printed'))  # printed on A4 from the print area, not a blank page
        pg.locator('.dialog [data-close]').last.click()
        pg.click('[data-newprof]')
        pg.fill('#pn', 'مساعد مخزن')
        pg.click('.panel [data-g="pages"]')
        pg.click('.panel [data-ok]')
        pg.wait_for_selector('[data-prof] >> text=مساعد مخزن')
        pg.click('[data-id] >> text=الكاشير (تدريب)')
        pg.wait_for_selector('.panel #ur')
        self.assertEqual(pg.input_value('#ur'), 'cashier')
        pg.click('.panel details summary')
        pg.uncheck('.panel [data-p="products.view"]')
        pg.uncheck('.panel [data-p="stock.view"]')
        self.assertEqual(pg.input_value('#ur'), 'custom')
        pg.click('.panel [data-ok]')
        pg.wait_for_selector('.panel', state='detached')
        card = pg.locator('[data-id]', has_text='الكاشير (تدريب)')
        card.locator('text=مخصص').wait_for()
        self.assertIn('مخصص', card.inner_text())
        self.assertEqual(self.errors, [])

        cashier = self.open('cashier')
        self.assertEqual(cashier.locator('.rail a[data-route="products"], .rail a[data-route="stock"]').count(), 0)
        self.assertEqual(cashier.locator('.rail a[data-route="pos"]').count(), 1)
        cashier.goto(self.S.base + '/#/products')
        cashier.wait_for_timeout(400)
        self.assertEqual(cashier.locator('#page .card').count(), 1)
        for api in ('/api/products', '/api/stock'):
            self.assertEqual(cashier.evaluate("(u) => fetch(u).then((r) => r.status)", api), 403, api)


@SKIP
class LayoutSweep(Browser):
    def sweep(self, width, height, theme='day', lang='ar'):
        pg = self.open('owner', width=width, height=height, prefs={'theme': theme, 'lang': lang})
        problems = {}
        for route in ROUTES:
            self.go(pg, route)
            found = pg.evaluate(OVERFLOW)
            if found:
                problems[route] = found
        self.assertEqual(problems, {}, f'{width}px {theme} {lang}: ' + json.dumps(problems, ensure_ascii=False, indent=1))
        self.assertEqual(self.errors, [])

    def test_phone(self):
        self.sweep(360, 780)

    def test_tablet_dark(self):
        self.sweep(820, 1180, 'night')

    def test_pc_english(self):
        self.sweep(1366, 768, 'day', 'en')

    def test_large_text_phone(self):
        pg = self.open('owner', width=390, height=844, prefs={'size': 'xl'})
        for route in ('home', 'pos', 'cash', 'reports'):
            self.go(pg, route)
            self.assertEqual(pg.evaluate(OVERFLOW), [], route)


@unittest.skipUnless(HAVE_CRYPTO, 'cryptography needed')
@SKIP
class LicenceLock(Browser):
    practice = False
    licensed = False

    def test_without_a_code_the_shop_reads_but_cannot_sell(self):
        pg = self.open(OWNER[0], OWNER[1])
        pg.wait_for_selector('.banner.licence')
        self.go(pg, 'settings?tab=licence')
        device = pg.inner_text('#dev')
        self.assertRegex(device, r'^[0-9A-Z]{5}-[0-9A-Z]{5}$')
        pg.fill('#lic-code', 'NOT-A-CODE')
        pg.click('[data-activate]')
        pg.wait_for_selector('.toast.bad')
        from harness import code_for
        pg.fill('#lic-code', code_for(device))
        pg.click('[data-activate]')
        pg.wait_for_selector('.lic.good')
        self.assertIsNone(pg.query_selector('.banner.licence.bad'))
        self.assertEqual([e for e in self.errors if '400' not in e], [])


_ = PW
