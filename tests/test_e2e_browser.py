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
        cls.S = Server(practice=cls.practice, licensed=getattr(cls, "licensed", True), setup=getattr(cls, 'setup', True))
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
        self.assertEqual(pg.query_selector_all('.pay-methods'), [])  # a new shop takes cash only: no other way is offered
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
        self.assertEqual(pg.query_selector_all('[data-seg="refund"]'), [])  # cash sale, cash shop: refunded in cash, no choice shown
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
class ReturnOnCredit(Browser):
    """An instalment sale returned from the screen: what the customer still owes is wiped first, and the drawer pays only money that came in
    (the independent review of 2026-10-09 found a cash refund of goods nobody had paid for)."""

    def test_returning_an_instalment_sale_wipes_the_debt_and_says_so(self):
        db = self.S.app.db
        plan = db.one('SELECT * FROM plans ORDER BY created_at LIMIT 1')
        owed_before = db.value('SELECT COALESCE(SUM(amount), 0) FROM ar_entries WHERE customer_id = ?', plan['customer_id'])
        pg = self.open('manager')
        status = pg.evaluate("fetch('/api/shift/open', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({opening_float: 5000000})}).then((r) => r.status)")
        self.assertIn(status, (200, 400))  # 400: this person already has a shift open today
        self.go(pg, 'sales?id=' + plan['sale_id'])
        pg.wait_for_selector('[data-return]')
        pg.click('[data-return]')
        pg.wait_for_selector('[data-rq]')
        self.assertIn('حسابه الأول', pg.inner_text('.dialog'))  # the hint about the account comes before the money
        pg.fill('[data-rq]', pg.get_attribute('[data-rq]', 'data-max'))
        pg.fill('#r-why', 'العميل رجّع الجهاز')
        pg.click('.dialog [data-ok]')
        pg.wait_for_selector('.toast')
        self.assertIn('اتخصم', pg.inner_text('.toasts'))  # "taken off the customer's account", not just "returned"
        wiped = db.value("SELECT COALESCE(SUM(amount), 0) FROM ar_entries WHERE kind = 'return' AND customer_id = ?", plan['customer_id'])
        self.assertLess(wiped, 0)
        owed_after = db.value('SELECT COALESCE(SUM(amount), 0) FROM ar_entries WHERE customer_id = ?', plan['customer_id'])
        self.assertEqual(owed_after, owed_before + wiped)
        self.assertEqual(self.errors, [])


@SKIP
class TwoShopsOneBrowser(Browser):
    """The real shop and the practice shop on one PC, in one browser. Cookies belong to a host, not to a port, so before 1.5.1 signing in
    to the practice shop signed the real shop out (found by the independent review of 2026-10-09)."""
    practice = False

    def test_signing_in_to_practice_does_not_sign_the_real_shop_out(self):
        import socket
        import subprocess
        import sys
        import tempfile
        import time
        from harness import ROOT, free_port
        port, home = free_port(), tempfile.mkdtemp(prefix='store-practice-')
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, 'server', 'app.py'), '--practice', '--home', home, '--port', str(port), '--host', '127.0.0.1',
                                 '--no-browser'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(80):
                try:
                    socket.create_connection(('127.0.0.1', port), timeout=0.5).close()
                    break
                except OSError:
                    time.sleep(0.25)
            ctx = self.browser.new_context(viewport={'width': 1366, 'height': 860})
            ctx.add_init_script("localStorage.setItem('store.prefs', %s)" % json.dumps(json.dumps({'lang': 'ar', 'sound': False, 'motion': 'off'})))

            def sign_in(base, user, password):
                pg = ctx.new_page()
                pg.goto(base)
                pg.wait_for_selector('#auth-form')
                pg.fill('#username', user)
                pg.fill('#password', password)
                pg.click('button[type=submit]')
                pg.wait_for_selector('.shell')
                return pg
            real = sign_in(self.S.base, OWNER[0], OWNER[1])
            practice = sign_in(f'http://127.0.0.1:{port}', 'owner', 'practice-1234')
            self.assertEqual(real.evaluate("fetch('/api/me').then((r) => r.status)"), 200, 'the real shop is still signed in')
            self.assertEqual(practice.evaluate("fetch('/api/me').then((r) => r.status)"), 200)
            real.reload()
            real.wait_for_selector('.shell')  # still in the real shop after a reload, no sign-in page
            self.assertEqual(sorted(c['name'] for c in ctx.cookies()), ['store_practice_session', 'store_session'])
            ctx.close()
        finally:
            proc.terminate()
            proc.wait(15)


@SKIP
class TrainingByClicking(Browser):
    """The three practice-shop exercises done with real clicks, by the account each one names. After the steps the exercise says "done" only
    because the shop's own books are right (a damaged return approved by a manager, a closed shift with no difference, a settled count)."""

    def lesson_data(self, pg, name):
        lessons = pg.evaluate("fetch('/api/training').then((r) => r.json())")['lessons']
        return next(x for x in lessons if x['id'] == name)

    def start(self, pg, name):
        self.go(pg, 'help')
        pg.wait_for_selector(f'[data-lesson="{name}"]')
        pg.click(f'[data-start="{name}"]')
        pg.wait_for_selector(f'[data-lesson="{name}"] [data-check]')
        self.assertEqual(pg.get_attribute(f'[data-lesson="{name}"] [data-state]', 'data-state'), 'open')

    def check(self, pg, name):
        self.go(pg, 'help')
        pg.wait_for_selector(f'[data-lesson="{name}"] [data-check]')
        pg.click(f'[data-lesson="{name}"] [data-check]')
        pg.wait_for_selector(f'[data-lesson="{name}"] [data-state="done"]')
        self.assertEqual(len(pg.query_selector_all(f'[data-lesson="{name}"] .train-checks li.ok')), len(pg.query_selector_all(f'[data-lesson="{name}"] .train-checks li')))

    def test_a_defective_fridge_comes_back(self):
        pg = self.open('cashier')
        self.start(pg, 'return')
        number = self.lesson_data(pg, 'return')['data']['number']
        self.assertIn(number, pg.inner_text('[data-lesson="return"]'))  # the story names the invoice
        self.go(pg, 'sales?q=' + number)
        pg.click('tr[data-id]')
        pg.wait_for_selector('[data-return]')
        pg.click('[data-return]')
        pg.fill('[data-rq]', '1')
        pg.select_option('[data-rc]', 'damaged')
        pg.fill('#r-why', 'الباب مش بيقفل')
        pg.click('.dialog [data-ok]')
        pg.wait_for_selector('#ap-u')
        pg.fill('#ap-u', 'manager')
        pg.fill('#ap-p', 'practice-1234')
        pg.locator('.dialog [data-ok]').last.click()
        pg.wait_for_selector('.toast')
        self.check(pg, 'return')
        self.assertEqual(self.errors, [])

    def test_the_drawer_is_short_by_a_forgotten_expense(self):
        pg = self.open('cashier')
        self.start(pg, 'drawer')
        physical = self.lesson_data(pg, 'drawer')['data']['physical'] / 100
        self.go(pg, 'cash')
        pg.click('[data-expense]')
        pg.fill('#ea', '15')
        pg.click('[data-seg="cat"] [data-v="hospitality"]')
        pg.fill('#en', 'شاي وقهوة')
        pg.click('.dialog [data-ok]')
        pg.wait_for_selector('.toast')
        pg.wait_for_selector('.dialog', state='detached')
        pg.click('#page [data-close]')
        pg.fill('#cc', f'{physical:g}')
        pg.locator('.dialog [data-ok]').last.click()
        pg.wait_for_selector('.done-mark')
        self.check(pg, 'drawer')
        self.assertEqual(self.errors, [])

    def test_the_shelf_holds_two_fans_fewer_than_the_books(self):
        pg = self.open('store')
        self.start(pg, 'count')
        d = self.lesson_data(pg, 'count')['data']
        self.go(pg, 'stock?tab=count')
        pg.select_option('#cl', label=d['place'])
        pg.click('[data-start]')
        pg.wait_for_selector(f'[data-cnt="{d["product_id"]}"]')
        pg.fill(f'[data-cnt="{d["product_id"]}"]', f'{d["physical"]:g}')
        pg.press(f'[data-cnt="{d["product_id"]}"]', 'Tab')
        pg.wait_for_selector(f'tr:has([data-cnt="{d["product_id"]}"]) .badge.bad')
        pg.click('[data-close-count]')
        pg.fill('#why', 'ناقص من الرف')
        pg.locator('.dialog [data-ok]').last.click()
        pg.wait_for_selector('.toast')
        self.check(pg, 'count')
        self.assertEqual(self.errors, [])

    def test_a_restart_sets_the_problem_up_again_and_the_owner_can_rebuild_everything(self):
        pg = self.open('owner')
        self.start(pg, 'drawer')
        first = self.lesson_data(pg, 'drawer')['data']['shift_id']
        pg.click('[data-restart="drawer"]')
        pg.click('.dialog [data-ok]')
        self.until(pg, "document.querySelector('[data-lesson=\"drawer\"] .small.muted')?.textContent.includes('2')")
        self.assertNotEqual(self.lesson_data(pg, 'drawer')['data']['shift_id'], first)
        pg.click('[data-reset]')
        pg.click('.dialog [data-ok]')
        pg.wait_for_selector('#auth-form')  # everyone signs in again
        pg.fill('#username', 'owner')
        pg.fill('#password', 'practice-1234')
        pg.click('button[type=submit]')
        pg.wait_for_selector('.shell')
        self.go(pg, 'help')
        pg.wait_for_selector('[data-start="drawer"]')  # nothing was started in the fresh shop
        self.assertEqual(self.errors, [])


@SKIP
class OpeningThePracticeShop(Browser):
    """From the real shop's Help page, one button starts the practice shop and offers its link."""
    practice = False

    def test_the_button_starts_it_and_offers_the_link(self):
        import shutil
        import practice as practice_mod
        from harness import free_port
        port = free_port()
        self.S.app.cfg['practice_port'] = port
        mine = self.S.app.home + '-practice'
        try:
            pg = self.open(OWNER[0], OWNER[1])
            self.go(pg, 'help')
            pg.wait_for_selector('[data-open-practice]')
            self.assertEqual(pg.query_selector_all('[data-lesson]'), [])  # the exercises live in the practice shop only
            pg.click('[data-open-practice]')
            pg.wait_for_selector(f'a[href="http://127.0.0.1:{port}/"]', timeout=60000)
            popup = [p for p in pg.context.pages if p is not pg]
            if popup:
                popup[0].wait_for_selector('#auth-form', timeout=30000)
                self.assertIn('تدريب', popup[0].inner_text('body'))
            self.assertEqual(self.S.app.db.value('SELECT COUNT(*) FROM sales'), 0)
            self.assertEqual(self.errors, [])
        finally:
            if practice_mod._child is not None:
                practice_mod._child.terminate()
                practice_mod._child.wait(15)
                practice_mod._child = None
            shutil.rmtree(mine, ignore_errors=True)


@SKIP
class LeavingWhileLoading(Browser):
    """Going to another page while the Today numbers are still on their way must not break anything (found by CI on 2026-10-09: the
    late answer looked for a box that was no longer on the screen and raised an error)."""

    def test_leaving_today_before_its_numbers_arrive_is_quiet(self):
        pg = self.open('owner')
        self.go(pg, 'customers')
        pg.route('**/api/home**', lambda r: (pg.wait_for_timeout(1200), r.continue_()))
        pg.evaluate("location.hash = '#/home'")
        pg.wait_for_timeout(200)
        pg.evaluate("location.hash = '#/sales'")
        pg.wait_for_timeout(2200)
        self.assertIn('المبيعات', pg.inner_text('#page h1'))
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
        # wait for the products route to render (a fixed 400 ms sometimes still counted the previous page's cards)
        self.until(cashier, "document.body.dataset.route === 'products' && document.querySelectorAll('#page .card').length === 1")
        cashier.wait_for_timeout(300)  # and it stays a single card
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


@SKIP
class AskingTheCompany(Browser):
    """The licence screen in a real browser: ask for the trial, see what is sent, see "no connection" with a retry button (never an error
    page), and watch the answer switch the program on by itself, with nothing copied. A stand-in relay plays the company."""
    practice = False
    licensed = False

    @classmethod
    def setUpClass(cls):
        from fake_relay import FakeRelay
        cls.relay = FakeRelay()
        os.environ['STORE_LICENCE_RELAY'] = cls.relay.base
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.relay.stop()
        os.environ.pop('STORE_LICENCE_RELAY', None)

    def test_ask_offline_retry_then_switch_on_by_itself(self):
        import trial
        from fake_relay import FakeRelay
        from harness import code_for
        pg = self.open(OWNER[0], OWNER[1], width=390, height=844)
        pg.wait_for_selector('.banner.licence')
        try:  # the first-sign-in agreement card covers the lower part of a phone: answer it, as a person would
            pg.wait_for_selector('[data-afc="decline"]', timeout=5000)
            pg.click('[data-afc="decline"]')
            pg.wait_for_selector('[data-afc="card"]', state='detached')
        except Exception:
            pass
        self.go(pg, 'settings?tab=licence')
        pg.wait_for_selector('[data-req="trial"]')
        device = pg.inner_text('#dev')
        self.assertIn('تليجرام', pg.inner_text('.lic'))  # the manual way names Telegram, not WhatsApp
        self.assertNotIn('واتساب', pg.inner_text('.lic') + pg.inner_text('.steps'))
        pg.click('[data-what]')
        pg.wait_for_selector('.dialog .stat-line')
        self.assertIn(device, pg.inner_text('.dialog'))  # exactly what would be sent is on the screen first
        self.assertEqual(self.relay.requests, {})
        pg.click('.dialog [data-close]')
        # no connection: a visible state with a retry button
        port = self.relay.port
        self.relay.stop()
        pg.click('[data-req="trial"]')
        pg.wait_for_selector('.lic-line.warn')
        self.assertIn('مفيش اتصال', pg.inner_text('#lic-auto'))
        pg.wait_for_selector('[data-retry]')
        self.assertIsNotNone(pg.query_selector('#lic-code'), 'the manual way is still there')
        # the company is reachable again: one press and the request goes through
        type(self).relay = FakeRelay(port)
        pg.click('[data-retry]')
        pg.wait_for_selector('.lic-line.busy')
        self.assertIn('بنستنى الرد', pg.inner_text('#lic-auto'))
        self.assertEqual(pg.evaluate(OVERFLOW), [], 'nothing spills out of the screen on a phone while waiting')
        # the owner's program answers; the program switches itself on, with nothing pasted
        self.relay.issue(self.relay.last(), code_for(device))
        trial.step(self.S.app, force=True)  # (in the running program the background loop does this every 20 seconds)
        self.until(pg, "document.querySelector('.lic.good') !== null", 20)
        self.assertEqual(self.S.app.licence()['state'], 'trial')
        self.assertEqual(pg.input_value('#lic-code'), '')
        self.assertIsNone(pg.query_selector('.banner.licence.bad'))
        self.assertEqual([e for e in self.errors if '400' not in e], [])


@SKIP
class OwnerRecovery(Browser):
    """Setup shows the paper code until the owner ticks that it is kept; «نسيت كلمة السر؟» uses it and shows a new one."""
    practice = False
    setup = False

    def test_setup_paper_code_then_forgotten_password(self):
        ctx = self.browser.new_context(viewport={'width': 390, 'height': 844})
        ctx.add_init_script("localStorage.setItem('store.prefs', %s)" % json.dumps(json.dumps({'lang': 'ar', 'sound': False, 'motion': 'off'})))
        pg = ctx.new_page()
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.goto(self.S.base)
        pg.wait_for_selector('#setup-form')
        pg.fill('#shop', 'محل التجربة')
        pg.fill('#fn', 'صاحب المحل')
        pg.fill('#un', 'boss')
        pg.fill('#pw', 'first-secret-1')
        pg.click('#setup-form [type=submit]')
        pg.wait_for_selector('[data-recovery-code]')
        code = pg.inner_text('[data-recovery-code]').strip()
        self.assertRegex(code, r'^[A-Z2-9]{4}(-[A-Z2-9]{4}){3}$')
        self.assertTrue(pg.is_disabled('.dialog [data-ok]'))  # cannot go on before ticking that the code is kept
        pg.keyboard.press('Escape')
        self.assertEqual(len(pg.query_selector_all('[data-recovery-code]')), 1)
        pg.check('#rc-kept')
        pg.click('.dialog [data-ok]')
        pg.wait_for_selector('.shell')
        ctx.clear_cookies()
        pg.goto(self.S.base)
        pg.wait_for_selector('[data-forgot]')
        self.assertNotIn('null', pg.text_content('.afg-fab'))  # af-guide 0.1.2: no course, no badge (it read «الدليلnull»)
        pg.click('[data-forgot]')
        pg.fill('#rc-code', 'AAAA-BBBB-CCCC-DDDD')
        pg.fill('#rc-new', 'second-secret-2')
        pg.click('#recover-form [type=submit]')
        pg.wait_for_selector('#rc-err:not(:empty)')
        self.assertIn('الكود الاحتياطي', pg.inner_text('#rc-err'))
        pg.fill('#rc-code', code.lower())
        pg.click('#recover-form [type=submit]')
        pg.wait_for_selector('[data-recovery-code]')
        self.assertNotEqual(pg.inner_text('[data-recovery-code]').strip(), code)
        pg.check('#rc-kept')
        pg.click('.dialog [data-ok]')
        pg.wait_for_selector('.shell')
        self.assertEqual(errors, [])
        ctx.close()


@SKIP
class GuideCoach(Browser):
    """The owner answers the first-sign-in consent card, opens help, and the open-shift coach
    shows step 1 of N, then moves on once that step is done."""

    def setUp(self):
        with self.S.app.db.tx():
            self.S.app.db.run('DELETE FROM consent_log')

    def test_owner_answers_consent_and_the_open_shift_coach_advances(self):
        import re
        pg = self.open('owner')
        pg.wait_for_selector('[data-afc="card"]')
        self.assertEqual(pg.locator('[data-afc="agree"], [data-afc="decline"]').count(), 2)
        pg.click('[data-afc="agree"]')
        pg.wait_for_selector('[data-afc="card"]', state='detached')
        pg.click('[data-afg="help"]')
        pg.wait_for_selector('[data-guide-id="open-shift"] [data-afg="start"]')
        pg.click('[data-guide-id="open-shift"] [data-afg="start"]')
        pg.wait_for_selector('[data-afg="coach"] [data-afg="step"]')
        step = pg.inner_text('[data-afg="step"]')
        found = re.search(r'1\D+(\d+)', step)
        self.assertIsNotNone(found, step)
        self.assertGreater(int(found.group(1)), 1, step)
        pg.click('[data-afg="there"]')
        advanced = self.until(pg, """(() => {
          const s = document.querySelector('[data-afg="step"]');
          const t = s ? s.textContent : '';
          return /2\\D+[0-9]+/.test(t) ? t : '';
        })()""")
        again = re.search(r'2\D+(\d+)', advanced)
        self.assertIsNotNone(again, advanced)
        self.assertEqual(again.group(1), found.group(1), advanced)
        self.assertEqual(self.errors, [])

    def test_consent_card_is_nonmodal_and_a_shop_dialog_stays_clickable(self):
        pg = self.open('owner', width=360, height=844)
        pg.wait_for_selector('[data-afc="card"]')
        self.assertEqual(pg.get_attribute('[data-afc="card"] section', 'aria-modal'), 'false')
        pg.click('[data-cmdk]')
        pg.wait_for_selector('#cmdk-q')
        pg.fill('#cmdk-q', 'غلاية')
        pg.keyboard.press('Escape')
        self.assertLessEqual(pg.evaluate('document.documentElement.scrollWidth'), 360)
        self.assertEqual(self.errors, [])

    def test_relogin_has_one_guide_and_f1_uses_the_current_person(self):
        pg = self.open('owner')
        pg.wait_for_selector('[data-afc="card"]')
        pg.click('[data-afc="decline"]')
        pg.wait_for_selector('[data-afc="card"]', state='detached')
        pg.click('[data-logout]')
        pg.wait_for_selector('#auth-form')
        self.assertEqual(pg.locator('[data-afc="card"]').count(), 0)
        pg.fill('#username', 'store')
        pg.fill('#password', 'practice-1234')
        pg.click('button[type=submit]')
        pg.wait_for_selector('.shell')
        self.until(pg, "!!window.__afguide && window.__afguideLive")
        pg.keyboard.press('F1')
        pg.wait_for_selector('[data-afg="panel"]', state='visible')
        self.assertEqual(pg.locator('[data-afg="fab"]').count(), 1)
        self.assertEqual(pg.locator('[data-afg="panel"]').count(), 1)
        self.assertEqual(pg.locator('[data-guide-id="make-sale"]').count(), 0)
        self.assertGreater(pg.locator('[data-guide-id="read-stock"]').count(), 0)
        self.assertEqual(self.errors, [])

    def test_language_switch_keeps_guide_controls_inside_the_panel(self):
        pg = self.open('owner')
        pg.wait_for_selector('[data-afc="card"]')
        pg.click('[data-afc="decline"]')
        pg.wait_for_selector('[data-afc="card"]', state='detached')
        pg.click('[data-afg="help"]')
        pg.wait_for_selector('[data-afg="panel"]', state='visible')
        pg.keyboard.press('Escape')
        pg.click('[data-lang]')
        self.until(pg, "document.documentElement.lang === 'en'")
        pg.click('[data-afg="help"]')
        pg.wait_for_selector('[data-afg="panel"]', state='visible')
        self.assertEqual(pg.locator('body > [data-afg="start"], body > [data-afg="help"]').count(), 0)
        self.assertGreater(pg.locator('[data-afg="panel"] [data-afg="start"]').count(), 0)
        self.assertEqual(pg.locator('[data-afg="help"]').count(), 1)
        self.assertEqual(self.errors, [])

    def test_report_previews_redacted_words_and_queues_only_after_send(self):
        text = 'Sale screen freezes password=fixture-only phone 01000000000'
        for language, theme, width in (('ar', 'day', 1366), ('en', 'night', 390)):
            with self.subTest(language=language, theme=theme):
                self.setUp()
                pg = self.open('owner', width=width, prefs={'lang': language, 'theme': theme})
                pg.wait_for_selector('[data-afc="agree"]')
                pg.click('[data-afc="agree"]')
                pg.wait_for_selector('[data-afc="card"]', state='detached')
                pg.click('[data-afg="help"]')
                pg.click('[data-guide-id="open-shift"] [data-afg="start"]')
                pg.wait_for_selector('[data-afg="coach"]', state='visible')
                pg.click('[data-afg="help"]')
                pg.click('[data-afg="report"]')
                pg.wait_for_selector('[data-report-text]')
                reports = lambda: [e for e in self.S.app.assist.tel.pending() if e['type'] == 'fb.problem']
                before = {e['id'] for e in reports()}
                self.assertTrue(pg.locator('[data-report-send]').is_disabled())
                pg.fill('[data-report-text]', text)
                pg.check('[data-report-diag]')
                pg.click('[data-report-check]')
                pg.wait_for_selector('[data-report-review]', state='visible')
                preview = json.loads(pg.text_content('[data-report-raw]'))
                self.assertEqual(preview['data']['text'], 'Sale screen freezes password=[SECRET] phone [PHONE]')
                self.assertIn('diagnostics', preview['data'])
                self.assertEqual(pg.get_attribute('[data-report-raw]', 'dir'), 'ltr')
                self.assertTrue(pg.evaluate("""(() => {
                  const r = document.querySelector('[data-report-send]').getBoundingClientRect();
                  return r.top >= 0 && r.bottom <= innerHeight;
                })()"""))
                self.assertNotIn('fixture-only', json.dumps(preview))
                self.assertNotIn('01000000000', json.dumps(preview))
                self.assertEqual({e['id'] for e in reports()}, before)
                pg.fill('[data-report-text]', text + ' after opening the shift')
                self.assertTrue(pg.locator('[data-report-send]').is_disabled())
                self.assertTrue(pg.locator('[data-report-review]').is_hidden())
                pg.click('[data-report-check]')
                pg.wait_for_selector('[data-report-review]', state='visible')
                preview = json.loads(pg.text_content('[data-report-raw]'))
                self.assertLessEqual(pg.evaluate('document.documentElement.scrollWidth'), width)
                pg.click('[data-report-send]')
                pg.wait_for_selector('[data-report-text]', state='detached')
                saved = [e for e in reports() if e['id'] not in before]
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0]['data'], preview['data'])
                self.assertEqual(saved[0]['type'], preview['type'])
                self.assertEqual(self.errors, [])
                pg.context.close()

    def test_edit_during_report_preview_does_not_enable_stale_send(self):
        pg = self.open('owner')
        pg.wait_for_selector('[data-afc="agree"]')
        pg.click('[data-afc="agree"]')
        pg.wait_for_selector('[data-afc="card"]', state='detached')
        pg.click('[data-afg="help"]')
        pg.click('[data-afg="report"]')
        pg.wait_for_selector('[data-report-text]')
        pg.fill('[data-report-text]', 'Original report')
        waiting = []
        pg.route('**/api/telemetry/feedback/preview', lambda route: waiting.append(route))
        with pg.expect_request('**/api/telemetry/feedback/preview'):
            pg.click('[data-report-check]')
        self.assertEqual(len(waiting), 1)
        preview = pg.request.post(self.S.base + '/api/telemetry/feedback/preview',
                                  data=waiting[0].request.post_data_json)
        self.assertEqual(preview.status, 200)
        pg.fill('[data-report-text]', 'Edited while waiting')
        waiting[0].fulfill(status=200, json=preview.json())
        pg.wait_for_selector('[data-report-check][aria-busy="true"]', state='detached')
        self.assertTrue(pg.locator('[data-report-send]').is_disabled())
        self.assertTrue(pg.locator('[data-report-review]').is_hidden())
        pg.unroute('**/api/telemetry/feedback/preview')
        pg.click('[data-report-check]')
        pg.wait_for_selector('[data-report-review]', state='visible')
        self.assertEqual(json.loads(pg.text_content('[data-report-raw]'))['data']['text'], 'Edited while waiting')
        self.assertTrue(pg.locator('[data-report-send]').is_enabled())
        self.assertEqual(self.errors, [])

    def test_report_review_is_plain_language_with_technical_details_on_request(self):
        typed = 'Sale screen freezes password=fixture-only phone 01000000000'
        for language, labels in (('ar', ('ما سيُرسل', 'ما لن يُرسل', 'إصدار البرنامج', 'البيع', 'عرض التفاصيل الفنية')),
                                 ('en', ('What will be sent', 'What will NOT be sent', 'Program version', 'Sell',
                                         'Show technical details'))):
            with self.subTest(language=language):
                self.setUp()
                pg = self.open('owner', width=390, prefs={'lang': language})
                pg.wait_for_selector('[data-afc="agree"]')
                pg.click('[data-afc="agree"]')
                pg.wait_for_selector('[data-afc="card"]', state='detached')
                pg.goto(self.S.base + '/#/pos')
                self.until(pg, "document.body.dataset.route === 'pos'")
                pg.click('[data-afg="help"]')
                pg.click('[data-afg="report"]')
                pg.wait_for_selector('[data-report-text]')
                reports = lambda: [e for e in self.S.app.assist.tel.pending() if e['type'] == 'fb.problem']
                before = {e['id'] for e in reports()}
                pg.fill('[data-report-text]', typed)
                pg.click('[data-report-check]')
                pg.wait_for_selector('[data-report-review]', state='visible')
                review = pg.inner_text('[data-report-review]')
                for label in labels[:3]:
                    self.assertIn(label, review)
                page_label = pg.evaluate("(() => { const d = [...document.querySelectorAll('[data-report-facts] dd')]; return d[4].textContent; })()")
                self.assertEqual(page_label, labels[3])
                sent = pg.text_content('[data-report-sent-text]')
                self.assertEqual(sent, 'Sale screen freezes password=[SECRET] phone [PHONE]')
                from version import VERSION
                self.assertIn(VERSION, review)
                self.assertTrue(pg.locator('[data-report-redacted]').is_visible())
                self.assertEqual(pg.locator('.report-not-sent li').count(), 4)
                self.assertNotIn('fixture-only', review)
                self.assertNotIn('01000000000', review)
                # the raw payload is there but folded away until asked for
                self.assertFalse(pg.locator('[data-report-raw]').is_visible())
                self.assertNotIn('"type"', review)
                pg.click('[data-report-tech] summary')
                self.assertTrue(pg.locator('[data-report-raw]').is_visible())
                self.assertEqual(json.loads(pg.text_content('[data-report-raw]'))['data']['text'], sent)
                self.assertIn(labels[4], pg.inner_text('[data-report-tech] summary'))
                self.assertLessEqual(pg.evaluate('document.documentElement.scrollWidth'), 390)
                # Cancel closes and queues nothing
                pg.click('[data-report-cancel]')
                pg.wait_for_selector('[data-report-text]', state='detached')
                self.assertEqual({e['id'] for e in reports()}, before)
                self.assertEqual(self.errors, [])
                pg.context.close()


_ = PW
