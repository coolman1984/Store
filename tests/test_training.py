"""The practice shop: kept apart from the real shop, and three hands-on exercises that are set up and checked from the books.

Isolation (nothing of the practice shop can touch real data):
- a folder of one kind is never opened as the other kind; the practice folder is always beside the real one, never on it;
- the practice shop never sends telemetry or support data, whatever its settings say;
- only the practice shop answers the training calls and can be rebuilt, and only in a folder marked as practice.

Exercises: each one is "done" only when the shop's own books say so (a damaged return with a manager's approval and cash back; a closed
shift with a zero difference after the missing expense; a closed count that settled the missing pieces)."""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from contextlib import redirect_stdout

from harness import HAVE_CRYPTO, OWNER, ROOT, Server, Shop, free_port  # noqa: F401  (harness first: it prepares the import path)

import app as app_mod
import auth as auth_mod
import money as cash
import practice
import sales
import sample
import stock
import support
import training
from core import Problem


def new_practice():
    home = tempfile.mkdtemp(prefix='store-training-')
    app = app_mod.App(home, practice=True)
    sample.load(app)
    return app, home


def tx(app, fn, username='owner', approver=None):
    """Run a domain call as one of the practice people, in a transaction, the way the server does."""
    user = app.db.one('SELECT * FROM users WHERE username = ?', username)
    ctx = sample.ctx_for(app, user)
    if approver:
        ctx.approver = app.db.one('SELECT * FROM users WHERE username = ?', approver)
    with app.db.tx():
        return fn(ctx)


def lesson(app, name):
    return next(x for x in training.view(app)['lessons'] if x['id'] == name)


class Isolation(unittest.TestCase):
    def test_the_practice_folder_is_beside_the_real_one_never_on_it(self):
        saved = {k: os.environ.pop(k, None) for k in ('STORE_HOME', 'STORE_PRACTICE_HOME')}
        try:
            os.environ['STORE_HOME'] = os.path.join(tempfile.gettempdir(), 'real-shop')
            self.assertEqual(app_mod.default_home(False), os.environ['STORE_HOME'])
            self.assertNotEqual(app_mod.default_home(True), app_mod.default_home(False), 'before: both pointed at the same folder')
            self.assertEqual(app_mod.default_home(True), os.environ['STORE_HOME'] + '-practice')
            os.environ['STORE_PRACTICE_HOME'] = os.path.join(tempfile.gettempdir(), 'elsewhere')
            self.assertEqual(app_mod.default_home(True), os.environ['STORE_PRACTICE_HOME'])
        finally:
            for k in ('STORE_HOME', 'STORE_PRACTICE_HOME'):
                os.environ.pop(k, None)
                if saved[k] is not None:
                    os.environ[k] = saved[k]

    def test_the_practice_shop_refuses_a_real_shops_folder(self):
        shop = Shop()
        try:
            with self.assertRaises(practice.WrongShop) as e:
                app_mod.App(shop.dir, practice=True)
            self.assertEqual(e.exception.key, 'practice_on_real')
            self.assertEqual(shop.db.value('SELECT COUNT(*) FROM users WHERE username = ?', 'owner'), 0, 'nothing was added to the real shop')
            self.assertIsNone(practice.kind_of(shop.db))
        finally:
            shop.cleanup()

    def test_a_real_shop_refuses_the_practice_folder(self):
        app, home = new_practice()
        try:
            self.assertEqual(practice.kind_of(app.db), 'practice')
            self.assertTrue(os.path.exists(os.path.join(home, practice.MARKER)))
            app.assist.close()
            app.db.close()
            with self.assertRaises(practice.WrongShop) as e:
                app_mod.App(home, practice=False)
            self.assertEqual(e.exception.key, 'real_on_practice')
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_the_program_says_so_in_plain_words_and_does_not_start(self):
        app, home = new_practice()
        app.assist.close()
        app.db.close()
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                code = app_mod.main(['--home', home, '--no-browser'])  # the real shop pointed at the practice folder
            self.assertEqual(code, 3)
            self.assertIn('محل التدريب', out.getvalue())
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_a_practice_folder_made_by_an_older_version_is_recognised_and_marked(self):
        app, home = new_practice()
        app.db.run("DELETE FROM meta WHERE key = ?", practice.KIND_KEY)
        os.remove(os.path.join(home, practice.MARKER))
        app.assist.close()
        app.db.close()
        again = app_mod.App(home, practice=True)
        try:
            self.assertEqual(practice.kind_of(again.db), 'practice')
            self.assertTrue(os.path.exists(os.path.join(home, practice.MARKER)))
        finally:
            again.assist.close()
            again.db.close()
            shutil.rmtree(home, ignore_errors=True)

    def test_an_older_practice_folder_is_refused_by_the_real_shop_too(self):
        """Review of PR #19: without its mark, an older practice folder opened as a real shop served its made-up sales as real."""
        app, home = new_practice()
        app.db.run("DELETE FROM meta WHERE key = ?", practice.KIND_KEY)
        os.remove(os.path.join(home, practice.MARKER))
        app.assist.close()
        app.db.close()
        try:
            with self.assertRaises(practice.WrongShop) as e:
                app_mod.App(home, practice=False)
            self.assertEqual(e.exception.key, 'real_on_practice')
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_a_refused_folder_is_not_touched_at_all(self):
        """Review of PR #19: the refusal came after the database was opened (migrations, upgrade copy, ids). Now it comes first."""
        import hashlib
        shop = Shop()
        path = os.path.join(shop.dir, 'data', 'store.db')
        shop.app.assist.close()
        shop.db.close()
        for extra in ('-wal', '-shm'):
            if os.path.exists(path + extra):
                os.remove(path + extra)
        before = hashlib.sha256(open(path, 'rb').read()).hexdigest()
        backups = sorted(os.listdir(os.path.join(shop.dir, 'backups'))) if os.path.isdir(os.path.join(shop.dir, 'backups')) else []
        try:
            with self.assertRaises(practice.WrongShop):
                app_mod.App(shop.dir, practice=True)
            self.assertEqual(hashlib.sha256(open(path, 'rb').read()).hexdigest(), before, 'the real database file is byte for byte the same')
            self.assertEqual(sorted(os.listdir(os.path.join(shop.dir, 'backups'))) if os.path.isdir(os.path.join(shop.dir, 'backups')) else [], backups)
        finally:
            shutil.rmtree(shop.dir, ignore_errors=True)

    def test_four_users_with_the_demo_names_in_a_real_shop_are_not_taken_for_a_practice_shop(self):
        shop = Shop()
        try:
            for username, _name, role in sample.DEMO_USERS:
                shop.user(role, username)
            with self.assertRaises(practice.WrongShop):  # the shop name is not the made-up one
                practice.guard(shop.db, True, shop.dir)
        finally:
            shop.cleanup()

    def test_nothing_leaves_the_practice_shop(self):
        app, home = new_practice()
        try:
            app.cfg.update(telemetry_url='https://example.invalid/ingest', telemetry_token='tok-12345')
            app.assist._post_remote = lambda *a, **k: self.fail('the practice shop must never send telemetry')
            self.assertIsNone(app.assist.flush_remote())
            support.save(app.home, True, 'https://example.invalid', 'tok-1234567890abcdef')
            with self.assertRaises(Problem) as e:
                support.send(app)
            self.assertEqual(e.exception.key, 'err.supportOff')
        finally:
            app.assist.close()
            app.db.close()
            shutil.rmtree(home, ignore_errors=True)

    def test_the_rebuild_is_refused_in_a_real_shop_and_in_an_unmarked_folder(self):
        shop = Shop()
        try:
            with self.assertRaises(Problem) as e:
                shop.app.reset_practice()
            self.assertEqual(e.exception.status, 403)
            self.assertEqual(shop.db.value('SELECT COUNT(*) FROM users'), 1, 'the real shop was not touched')
        finally:
            shop.cleanup()
        app, home = new_practice()
        try:
            os.remove(os.path.join(home, practice.MARKER))
            with self.assertRaises(Problem):
                app.reset_practice()
            self.assertGreater(app.db.value('SELECT COUNT(*) FROM sales'), 0, 'the folder was not touched either')
        finally:
            app.assist.close()
            app.db.close()
            shutil.rmtree(home, ignore_errors=True)

    def test_the_real_shop_has_no_training(self):
        shop = Shop()
        try:
            with self.assertRaises(Problem) as e:
                with shop.db.tx():
                    training.start(shop.app, shop.ctx(), 'return')
            self.assertEqual(e.exception.status, 403)
        finally:
            shop.cleanup()


class Exercises(unittest.TestCase):
    def setUp(self):
        self.app, self.home = new_practice()

    def tearDown(self):
        self.app.assist.close()
        self.app.db.close()
        shutil.rmtree(self.home, ignore_errors=True)

    def start(self, name, restart=False):
        return tx(self.app, lambda ctx: training.start(self.app, ctx, name, restart))

    def test_all_four_start_fresh_and_nothing_is_done_yet(self):
        for name in training.LESSONS:
            self.start(name)
        for x in training.view(self.app)['lessons']:
            self.assertEqual(x['state'], 'open', x)
            self.assertFalse(any(c['ok'] for c in x['checks']), x)

    def test_starting_twice_adds_nothing_and_a_restart_adds_a_new_problem(self):
        self.start('return')
        sales_now = self.app.db.value('SELECT COUNT(*) FROM sales')
        first = lesson(self.app, 'return')['data']['sale_id']
        self.start('return')
        self.assertEqual(self.app.db.value('SELECT COUNT(*) FROM sales'), sales_now, 'a second start must not set anything up again')
        self.start('return', restart=True)
        self.assertEqual(self.app.db.value('SELECT COUNT(*) FROM sales'), sales_now + 1)
        again = lesson(self.app, 'return')
        self.assertNotEqual(again['data']['sale_id'], first)
        self.assertEqual(again['attempt'], 2)

    def test_return_is_done_only_when_damaged_approved_and_paid_back_in_cash(self):
        self.start('return')
        d = lesson(self.app, 'return')['data']
        sale = sales.sale_view(self.app.db, d['sale_id'], True)
        line = {'sale_line_id': sale['lines'][0]['id'], 'qty': 1}

        def take(condition, approver='manager', who='cashier'):
            return tx(self.app, lambda ctx: sales.take_return(ctx, {'idem_key': 'k' + condition + str(time.time()), 'sale_id': d['sale_id'], 'reason': 'الباب مش بيقفل',
                                                                    'refund_method': 'cash', 'lines': [{**line, 'condition': condition}]}), who, approver)
        # the cashier needs a manager: without one nothing happens
        with self.assertRaises(Problem) as e:
            take('damaged', approver=None)
        self.assertEqual(e.exception.key, 'err.needsApproval')
        self.assertFalse(any(c['ok'] for c in lesson(self.app, 'return')['checks']))
        take('damaged')
        x = lesson(self.app, 'return')
        self.assertEqual({c['key']: c['ok'] for c in x['checks']}, {'returned': True, 'damaged': True, 'approved': True, 'cash': True})
        self.assertEqual(x['state'], 'done')
        self.assertEqual(stock.serial_state(self.app.db, d['serial'])['location_id'], self.app.db.value("SELECT id FROM locations WHERE kind = 'damaged'"))

    def test_return_taken_as_good_is_not_done(self):
        self.start('return')
        d = lesson(self.app, 'return')['data']
        sale = sales.sale_view(self.app.db, d['sale_id'], True)
        tx(self.app, lambda ctx: sales.take_return(ctx, {'idem_key': 'good-1', 'sale_id': d['sale_id'], 'reason': 'غيّر رأيه', 'refund_method': 'cash',
                                                         'lines': [{'sale_line_id': sale['lines'][0]['id'], 'qty': 1, 'condition': 'good'}]}), 'cashier', 'manager')
        x = lesson(self.app, 'return')
        self.assertEqual({c['key']: c['ok'] for c in x['checks']}, {'returned': True, 'damaged': False, 'approved': True, 'cash': True})
        self.assertEqual(x['state'], 'open')

    def test_return_by_a_manager_alone_skips_the_approval_lesson(self):
        self.start('return')
        d = lesson(self.app, 'return')['data']
        # The refund comes out of the manager's own drawer, and what that drawer holds depends on the hour the practice shop was built (before
        # 10:05 the manager's shift is only the float of a small made-up return). This test is about approvals, not about cash: fund it first.
        mgr = self.app.db.one("SELECT id FROM users WHERE username = 'manager'")
        old = cash.open_shift_of(self.app.db, mgr['id'])
        if old:
            tx(self.app, lambda ctx: cash.close_shift(ctx, old['id'], cash.drawer_expected(self.app.db, old['id']), ''), 'manager')
        tx(self.app, lambda ctx: cash.open_shift(ctx, d['total'] + 100000), 'manager')
        sale = sales.sale_view(self.app.db, d['sale_id'], True)
        tx(self.app, lambda ctx: sales.take_return(ctx, {'idem_key': 'mgr-1', 'sale_id': d['sale_id'], 'reason': 'عيب في الباب', 'refund_method': 'cash',
                                                         'lines': [{'sale_line_id': sale['lines'][0]['id'], 'qty': 1, 'condition': 'damaged'}]}), 'manager')
        x = lesson(self.app, 'return')
        self.assertFalse({c['key']: c['ok'] for c in x['checks']}['approved'])
        self.assertEqual(x['state'], 'open')

    def test_drawer_is_done_only_after_the_expense_and_a_zero_difference(self):
        self.start('drawer')
        d = lesson(self.app, 'drawer')['data']
        self.assertEqual(d['physical'], d['expected'] - training.MISSING_CASH)
        shift = d['shift_id']
        self.assertEqual(cash.drawer_expected(self.app.db, shift), d['expected'])
        # the wrong way: close with the shortage written off as "forgot". It is allowed (the books record it) but the exercise is not done.
        # ... so first the right way on a second attempt; here we show what the checks say after the right steps.
        tx(self.app, lambda ctx: cash.expense(ctx, {'idem_key': 'tea-1', 'category': 'hospitality', 'amount': training.MISSING_CASH, 'note': 'شاي وقهوة'}), 'cashier')
        x = lesson(self.app, 'drawer')
        self.assertEqual({c['key']: c['ok'] for c in x['checks']}, {'expense': True, 'closed': False, 'exact': False})
        tx(self.app, lambda ctx: cash.close_shift(ctx, shift, d['physical'], ''), 'cashier')
        x = lesson(self.app, 'drawer')
        self.assertEqual({c['key']: c['ok'] for c in x['checks']}, {'expense': True, 'closed': True, 'exact': True})
        self.assertEqual(x['state'], 'done')

    def test_drawer_closed_with_the_shortage_is_not_done_and_can_be_started_again(self):
        self.start('drawer')
        d = lesson(self.app, 'drawer')['data']
        tx(self.app, lambda ctx: cash.close_shift(ctx, d['shift_id'], d['physical'], 'ناقص'), 'cashier')
        x = lesson(self.app, 'drawer')
        self.assertEqual({c['key']: c['ok'] for c in x['checks']}, {'expense': False, 'closed': True, 'exact': False})
        self.assertEqual(x['state'], 'open')
        self.start('drawer', restart=True)
        again = lesson(self.app, 'drawer')
        self.assertNotEqual(again['data']['shift_id'], d['shift_id'])
        self.assertEqual(again['state'], 'open')
        self.assertFalse(any(c['ok'] for c in again['checks']))

    def test_a_reversed_expense_does_not_count(self):
        self.start('drawer')
        row = tx(self.app, lambda ctx: cash.expense(ctx, {'idem_key': 'tea-2', 'category': 'hospitality', 'amount': training.MISSING_CASH, 'note': 'شاي وقهوة'}), 'cashier')
        self.assertTrue(lesson(self.app, 'drawer')['checks'][0]['ok'])
        tx(self.app, lambda ctx: cash.reverse_cash(ctx, row['id'], 'اتسجل بالغلط'), 'owner')
        self.assertFalse(lesson(self.app, 'drawer')['checks'][0]['ok'], 'a cancelled expense must not count')

    def test_count_is_done_only_when_counted_closed_and_settled(self):
        self.start('count')
        d = lesson(self.app, 'count')['data']
        self.assertEqual(d['physical'], d['expected'] - training.MISSING_PIECES)
        cid = tx(self.app, lambda ctx: stock.start_count(ctx, d['location_id'], ''), 'store')
        tx(self.app, lambda ctx: stock.count_line(ctx, cid, d['product_id'], d['physical']), 'store')
        x = lesson(self.app, 'count')
        self.assertEqual({c['key']: c['ok'] for c in x['checks']}, {'counted': True, 'closed': False, 'settled': False})
        tx(self.app, lambda ctx: stock.close_count(ctx, cid, 'ناقص من الرف'), 'store')
        x = lesson(self.app, 'count')
        self.assertEqual({c['key']: c['ok'] for c in x['checks']}, {'counted': True, 'closed': True, 'settled': True})
        self.assertEqual(x['state'], 'done')
        self.assertEqual(stock.on_hand(self.app.db, d['product_id'], d['location_id']), d['physical'])

    def test_count_with_the_wrong_number_is_not_done(self):
        self.start('count')
        d = lesson(self.app, 'count')['data']
        cid = tx(self.app, lambda ctx: stock.start_count(ctx, d['location_id'], ''), 'store')
        tx(self.app, lambda ctx: stock.count_line(ctx, cid, d['product_id'], d['expected']), 'store')  # counted what the books already said
        tx(self.app, lambda ctx: stock.close_count(ctx, cid, 'كله تمام'), 'store')
        x = lesson(self.app, 'count')
        self.assertEqual({c['key']: c['ok'] for c in x['checks']}, {'counted': False, 'closed': True, 'settled': False})
        self.assertEqual(x['state'], 'open')

    def test_an_unfinished_count_does_not_block_a_restart(self):
        self.start('count')
        d = lesson(self.app, 'count')['data']
        tx(self.app, lambda ctx: stock.start_count(ctx, d['location_id'], ''), 'store')   # left open
        self.start('count', restart=True)
        self.assertEqual(lesson(self.app, 'count')['attempt'], 2)
        tx(self.app, lambda ctx: stock.start_count(ctx, d['location_id'], ''), 'store')   # a new sheet can be started

    def test_the_owners_exercise_is_a_discount_the_cashier_gave_and_a_manager_approved(self):
        import reports
        self.start('discount')
        x = lesson(self.app, 'discount')
        d = x['data']
        self.assertEqual((x['account'], x['state']), ('owner', 'open'))
        sale = self.app.db.one('SELECT s.*, u.username AS by, a.username AS approver FROM sales s JOIN users u ON u.id = s.by_user '
                               'LEFT JOIN users a ON a.id = s.approved_by WHERE s.id = ?', d['sale_id'])
        self.assertEqual((sale['by'], sale['approver']), ('cashier', 'manager'), 'a cashier sold it and a manager approved it')
        self.assertEqual(sale['discount'], d['given'])
        self.assertGreaterEqual(d['pct'], 10)
        self.assertLessEqual(d['pct'], 15)
        listed = [i for i in reports.watch(self.app.db, 1) if i['key'] == 'disc:' + d['sale_id']]
        self.assertEqual(len(listed), 1, "the Owner's eye shows it, which is where the exercise sends the owner")

    def test_the_discount_is_done_only_when_seen_with_a_note_of_the_owners_own(self):
        import reports
        self.start('discount')
        d = lesson(self.app, 'discount')['data']
        key = 'disc:' + d['sale_id']
        self.assertEqual({c['key']: c['ok'] for c in lesson(self.app, 'discount')['checks']}, {'seen': False, 'noted': False})
        tx(self.app, lambda ctx: reports.review(ctx, key, ''))          # a bare tick
        x = lesson(self.app, 'discount')
        self.assertEqual(({c['key']: c['ok'] for c in x['checks']}, x['state']), ({'seen': True, 'noted': False}, 'open'))
        tx(self.app, lambda ctx: reports.review(ctx, key, 'كلّمت الكاشير والموضوع تمام'))
        x = lesson(self.app, 'discount')
        self.assertEqual(({c['key']: c['ok'] for c in x['checks']}, x['state']), ({'seen': True, 'noted': True}, 'done'))

    def test_seeing_a_different_item_does_not_finish_the_discount(self):
        import reports
        self.start('discount')
        other = self.app.db.value("SELECT id FROM sales WHERE id != ? ORDER BY at DESC LIMIT 1", lesson(self.app, 'discount')['data']['sale_id'])
        tx(self.app, lambda ctx: reports.review(ctx, 'disc:' + other, 'تمام'))
        self.assertEqual(lesson(self.app, 'discount')['state'], 'open')

    def test_the_discount_restarts_with_a_new_sale_and_leaves_the_old_review_alone(self):
        import reports
        self.start('discount')
        first = lesson(self.app, 'discount')['data']['sale_id']
        tx(self.app, lambda ctx: reports.review(ctx, 'disc:' + first, 'تمام'))
        self.start('discount', restart=True)
        x = lesson(self.app, 'discount')
        self.assertNotEqual(x['data']['sale_id'], first)
        self.assertEqual((x['state'], x['attempt']), ('open', 2), 'the earlier review does not count for the new problem')
        self.assertEqual(self.app.db.value('SELECT COUNT(*) FROM watch_reviews WHERE item = ?', 'disc:' + first), 1)

    def test_the_exercises_only_ever_add_rows(self):
        before = {t: self.app.db.value(f'SELECT COUNT(*) FROM {t}') for t in ('sales', 'stock_moves', 'cash_moves', 'returns', 'audit')}
        for name in training.LESSONS:
            self.start(name)
            self.start(name, restart=True)
        for t, n in before.items():
            self.assertGreaterEqual(self.app.db.value(f'SELECT COUNT(*) FROM {t}'), n, t)


class OverHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Server(practice=True)

    @classmethod
    def tearDownClass(cls):
        cls.S.stop()

    def login(self, user):
        c = self.S.client()
        self.assertEqual(c.post('/api/login', {'username': user, 'password': sample.DEMO_PASSWORD})[0], 200)
        return c

    def test_training_needs_a_signed_in_person(self):
        self.assertEqual(self.S.client().get('/api/training')[0], 401)
        self.assertEqual(self.S.client().post('/api/training/start', {'lesson': 'return'})[0], 401)

    def test_a_cashier_runs_an_exercise_through_the_server(self):
        c = self.login('cashier')
        st, d, _ = c.get('/api/training')
        self.assertEqual(st, 200)
        self.assertEqual([x['id'] for x in d['lessons']], list(training.LESSONS))
        self.assertEqual(c.post('/api/training/start', {'lesson': 'nonsense'})[0], 400)
        st, d, _ = c.post('/api/training/start', {'lesson': 'drawer'})
        self.assertEqual(st, 200, d)
        x = next(y for y in d['lessons'] if y['id'] == 'drawer')
        self.assertEqual(x['state'], 'open')
        self.assertEqual(x['account'], 'cashier')

    def test_a_phone_on_the_shop_network_is_told_to_use_the_counter_pc(self):
        """Review of PR #19: a phone got a 127.0.0.1 link, which is the phone itself: a dead page."""
        import app as app_mod2
        real = app_mod2.Handler.local
        app_mod2.Handler.local = lambda self: False
        try:
            c = self.login('owner')
            self.assertEqual(c.get('/api/practice')[1]['state'], 'here')  # this test server is itself a practice shop
        finally:
            app_mod2.Handler.local = real

    def test_only_a_person_who_may_edit_settings_can_rebuild_the_shop(self):
        c = self.login('cashier')
        self.assertEqual(c.post('/api/practice/reset')[0], 403)
        self.assertEqual(self.S.app.db.value("SELECT COUNT(*) FROM users"), 4)


class RebuildAndLaunch(unittest.TestCase):
    """Real processes: the practice shop started from a real shop, and rebuilt on request."""

    def start_practice(self, home):
        port = free_port()
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, 'server', 'app.py'), '--practice', '--home', home, '--port', str(port), '--host', '127.0.0.1',
                                 '--no-browser'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.2)
        return proc, port

    def call(self, port, method, path, body=None, cookie=''):
        import http.client
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        h = {'Host': f'127.0.0.1:{port}', 'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{port}', **({'Cookie': cookie} if cookie else {})}
        c.request(method, path, json.dumps(body).encode() if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        set_cookie = (r.getheader('Set-Cookie') or '').split(';', 1)[0]
        c.close()
        return r.status, (json.loads(raw) if raw[:1] in (b'{', b'[') else raw), set_cookie

    def test_the_owner_rebuilds_the_practice_shop_and_everyone_signs_in_again(self):
        home = tempfile.mkdtemp(prefix='store-practice-')
        proc, port = self.start_practice(home)
        try:
            st, d, cookie = self.call(port, 'POST', '/api/login', {'username': 'owner', 'password': sample.DEMO_PASSWORD})
            self.assertEqual(st, 200)
            self.assertEqual(self.call(port, 'POST', '/api/training/start', {'lesson': 'return'}, cookie)[0], 200)
            self.assertEqual(self.call(port, 'GET', '/api/training', cookie=cookie)[1]['lessons'][0]['state'], 'open')
            st, d, _ = self.call(port, 'POST', '/api/practice/reset', {}, cookie)
            self.assertEqual((st, d.get('ok')), (200, True), d)
            self.assertEqual(self.call(port, 'GET', '/api/me', cookie=cookie)[0], 401, 'the old session is gone')
            st, d, cookie = self.call(port, 'POST', '/api/login', {'username': 'owner', 'password': sample.DEMO_PASSWORD})
            self.assertEqual(st, 200, 'the same accounts exist in the fresh shop')
            self.assertEqual([x['state'] for x in self.call(port, 'GET', '/api/training', cookie=cookie)[1]['lessons']], ['new'] * len(training.LESSONS))
            self.assertGreater(len(self.call(port, 'GET', '/api/products', cookie=cookie)[1]['items']), 10, 'a fresh made-up shop with its goods')
            self.assertTrue(os.path.exists(os.path.join(home, practice.MARKER)))
            rows = self.call(port, 'GET', '/api/audit?limit=20', cookie=cookie)[1]
            self.assertIn('practice.reset', [r['action'] for r in rows], 'the rebuild is the first line of the new audit')
        finally:
            proc.terminate()
            proc.wait(15)
            shutil.rmtree(home, ignore_errors=True)

    def test_the_real_shop_starts_the_practice_shop_beside_itself(self):
        shop = Server(practice=False)
        port = free_port()
        shop.app.cfg['practice_port'] = port
        mine = shop.app.home + '-practice'
        try:
            c = shop.client()
            self.assertEqual(c.post('/api/login', {'username': OWNER[0], 'password': OWNER[1]})[0], 200)
            self.assertEqual(c.get('/api/practice')[1]['state'], 'stopped')
            real_local = app_mod.Handler.local
            app_mod.Handler.local = lambda self: False  # the same press from a phone on the shop network
            try:
                self.assertEqual(c.post('/api/practice/open')[1], {'state': 'remote', 'url': ''})
                self.assertEqual(c.get('/api/practice')[1]['state'], 'remote')
            finally:
                app_mod.Handler.local = real_local
            self.assertIsNone(practice._child, 'nothing was started for the phone')
            self.assertEqual(c.get('/api/training')[0], 403, 'the real shop has no training')
            st, d, _ = c.post('/api/practice/open')
            self.assertEqual(st, 200, d)
            self.assertIn(d['state'], ('starting', 'running'))
            for _ in range(150):
                if c.get('/api/practice')[1]['state'] == 'running':
                    break
                time.sleep(0.3)
            self.assertEqual(c.get('/api/practice')[1]['state'], 'running')
            # a second press changes nothing
            self.assertEqual(c.post('/api/practice/open')[1]['state'], 'running')
            # it is a different shop: its own folder, its own database, its own sign-in
            self.assertTrue(os.path.isdir(mine))
            self.assertTrue(os.path.exists(os.path.join(mine, practice.MARKER)))
            self.assertNotEqual(os.path.realpath(mine), os.path.realpath(shop.app.home))
            st, d, cookie = self.call(port, 'POST', '/api/login', {'username': 'owner', 'password': sample.DEMO_PASSWORD})
            self.assertEqual(st, 200)
            self.assertEqual(self.call(port, 'GET', '/api/boot')[1]['practice'], True)
            self.assertEqual(shop.app.db.value('SELECT COUNT(*) FROM sales'), 0, 'nothing from the practice shop reached the real one')
            self.assertIn(self.call(port, 'POST', '/api/login', {'username': OWNER[0], 'password': OWNER[1]})[0], (400, 401), 'real accounts do not exist there')
            self.assertEqual(shop.app.db.value("SELECT COUNT(*) FROM audit WHERE action = 'practice.open'"), 2)
        finally:
            if practice._child is not None:
                practice._child.terminate()
                practice._child.wait(15)
                practice._child = None
            shop.stop()
            shutil.rmtree(mine, ignore_errors=True)

    def test_the_practice_shop_leaves_when_the_real_shop_that_started_it_leaves(self):
        """No hidden program may stay behind holding files: an update of the installed program would fail on a running one."""
        self.assertTrue(practice.alive(os.getpid()))
        gone = subprocess.Popen([sys.executable, '-c', 'pass'])
        gone.wait()
        self.assertFalse(practice.alive(gone.pid))
        parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
        home = tempfile.mkdtemp(prefix='store-practice-')
        port = free_port()
        child = subprocess.Popen([sys.executable, os.path.join(ROOT, 'server', 'app.py'), '--practice', '--home', home, '--port', str(port), '--host', '127.0.0.1',
                                  '--no-browser', '--parent', str(parent.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
        try:
            for _ in range(100):
                try:
                    socket.create_connection(('127.0.0.1', port), timeout=0.5).close()
                    break
                except OSError:
                    time.sleep(0.2)
            time.sleep(4)
            self.assertIsNone(child.poll(), 'it keeps running while the real shop does')
            parent.terminate()
            parent.wait(15)
            child.wait(timeout=30)  # the watcher looks every 3 seconds
            self.assertIsNotNone(child.returncode)
        finally:
            for p in (parent, child):
                if p.poll() is None:
                    p.kill()
            shutil.rmtree(home, ignore_errors=True)

    def test_in_the_compiled_build_the_program_is_found_without_sys_executable(self):
        """Found by the Windows build: sys.executable was not a file inside the compiled program, so Popen raised FileNotFoundError (a 500)."""
        saved = (practice.FROZEN, sys.executable, sys.argv, getattr(sys, 'orig_argv', None))
        try:
            practice.FROZEN = True
            sys.executable = os.path.join(tempfile.gettempdir(), 'no-such-python.exe')
            sys.orig_argv = None
            sys.argv = [os.path.abspath(__file__)]  # any file that exists stands in for Al-Store.exe
            self.assertEqual(practice.program(), os.path.abspath(__file__))
            self.assertEqual(practice._command('h', 1)[0], os.path.abspath(__file__))
            sys.argv = [os.path.join(tempfile.gettempdir(), 'nothing-here.exe')]
            with self.assertRaises(OSError):
                practice.program()
        finally:
            practice.FROZEN, sys.executable, sys.argv, sys.orig_argv = saved

    def test_a_program_that_cannot_start_is_a_plain_message_not_a_500(self):
        shop = Server(practice=False)
        real = subprocess.Popen

        def broken(*a, **k):
            raise FileNotFoundError('nope')
        subprocess.Popen = broken
        try:
            c = shop.client()
            self.assertEqual(c.post('/api/login', {'username': OWNER[0], 'password': OWNER[1]})[0], 200)
            st, d, _ = c.post('/api/practice/open')
            self.assertEqual((st, d.get('key')), (500, 'err.practiceStart'))
        finally:
            subprocess.Popen = real
            shop.stop()

    def test_a_slow_refusal_is_a_stopped_practice_shop_not_another_program(self):
        """Found by the Windows build: a closed port takes about two seconds to refuse there, longer than we wait. That is 'stopped'."""
        real = socket.create_connection

        def slow(*a, **k):
            raise TimeoutError('timed out')
        socket.create_connection = slow
        try:
            self.assertEqual(practice._probe(free_port()), 'stopped')
        finally:
            socket.create_connection = real
        self.assertEqual(practice._probe(free_port()), 'stopped')

    def test_a_port_held_by_another_program_is_said_plainly(self):
        shop = Server(practice=False)
        busy = socket.socket()
        busy.bind(('127.0.0.1', 0))
        busy.listen(1)
        shop.app.cfg['practice_port'] = busy.getsockname()[1]
        try:
            c = shop.client()
            self.assertEqual(c.post('/api/login', {'username': OWNER[0], 'password': OWNER[1]})[0], 200)
            st, d, _ = c.post('/api/practice/open')
            self.assertEqual((st, d.get('key')), (409, 'err.practicePort'))
        finally:
            busy.close()
            shop.stop()


@unittest.skipUnless(shutil.which('node'), 'needs Node to read the two dictionaries')
class TheTwoLanguages(unittest.TestCase):
    def test_both_exercise_dictionaries_have_the_same_shape_and_places(self):
        script = (
            "const [a, b] = await Promise.all([import(process.argv[1]), import(process.argv[2])]);"
            "const shape = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v && typeof v === 'object' && !Array.isArray(v) ? shape(v) : Array.isArray(v) ? v.length : typeof v]));"
            "const holes = (o) => JSON.stringify(o, (k, v) => v).match(/\\{\\w+\\}/g)?.sort().join() ?? '';"
            "console.log(JSON.stringify({ a: shape(a.default), b: shape(b.default), ha: holes(a.default), hb: holes(b.default) }));")
        d = tempfile.mkdtemp()
        try:
            files = []
            for n in ('ar', 'en'):  # copy as .mjs so Node reads them as modules without a package.json
                dst = os.path.join(d, f'{n}.mjs')
                shutil.copy(os.path.join(ROOT, 'web', 'i18n', f'training-{n}.js'), dst)
                files.append('file://' + dst)
            out = subprocess.run([shutil.which('node'), '--input-type=module', '-e', script, *files], capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            got = json.loads(out.stdout)
            self.assertEqual(got['a'], got['b'])
            self.assertEqual(sorted(got['ha'].split(',')) , sorted(got['hb'].split(',')), 'the same {places} in both languages')
            self.assertEqual(set(got['a']), set(training.LESSONS))
            for name in training.LESSONS:
                checks = got['a'][name]['checks']
                self.assertEqual(len(checks), len(training.CHECK[name](self._db(), self._data(name))))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def _db(self):
        app, home = new_practice()
        self.addCleanup(lambda: (app.assist.close(), app.db.close(), shutil.rmtree(home, ignore_errors=True)))
        self.app = app
        return app.db

    def _data(self, name):
        with self.app.db.tx():
            training.start(self.app, sample.ctx_for(self.app, self.app.db.one("SELECT * FROM users WHERE username = 'owner'")), name)
        return {**training._state(self.app.db)[name]['data'], 'at': training._state(self.app.db)[name]['at']}


if __name__ == '__main__':
    unittest.main()
