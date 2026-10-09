"""In-app guide: the catalogue matches the real shop, and progress is saved per person."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))

import afguide  # noqa: E402
import assist  # noqa: E402
import auth  # noqa: E402
import ids  # noqa: E402
import money as cash  # noqa: E402
import sales  # noqa: E402
from harness import PW, Server, Shop  # noqa: E402

GUIDE = os.path.join(ROOT, 'guide')
# Reasons licence.activate can raise (it wraps them as lic.err.<reason>). Not status-only reasons.
LICENCE_REASONS = (
    'no_code', 'other_device', 'expired', 'bad_signature', 'wrong_length', 'bad_character',
    'unknown_key', 'wrong_product', 'unknown_edition', 'unbound_perpetual', 'no_keys', 'unknown_version', 'invalid',
)
KEY = re.compile(r"""(?:^|[,{])\s*(?:'([^']+)'|([A-Za-z_]\w*))\s*:\s*['"]""", re.M)


def server_error_codes():
    """Every key the server can put on an error response. Factory modules are not product errors."""
    found = set()
    server = os.path.join(ROOT, 'server')
    for name in os.listdir(server):
        if not name.endswith('.py') or name.startswith('af'):
            continue
        with open(os.path.join(server, name), encoding='utf-8') as f:
            text = f.read()
        found.update(re.findall(r"(?:Problem|AuthError)\(\s*'((?:err|auth\.err)\.[A-Za-z0-9_.]+)'", text))
        found.update(re.findall(r"'key'\s*:\s*'((?:err|auth\.err)\.[A-Za-z0-9_.]+)'", text))
    found.update('lic.err.' + r for r in LICENCE_REASONS)
    return found


def ui_map(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    body = text[text.index('export default {'):]
    return {a or b: a or b for a, b in KEY.findall(body)}


def load_guide():
    cat, texts = afguide.load_dir(GUIDE)
    return cat, texts


class Catalogue(unittest.TestCase):
    def test_sale_title_uses_simple_formal_arabic(self):
        _, texts = load_guide()
        self.assertEqual(texts['ar']['guide.make-sale.title'], 'إنشاء فاتورة بيع')
        self.assertNotIn('عمل فاتورة', json.dumps(texts['ar'], ensure_ascii=False))

    def test_release_check_uses_the_real_shop(self):
        cat, texts = load_guide()
        codes = server_error_codes()
        access = auth.catalogue()
        ui = {
            'ar': ui_map(os.path.join(ROOT, 'web', 'i18n', 'ar.js')),
            'en': ui_map(os.path.join(ROOT, 'web', 'i18n', 'en.js')),
        }
        found = afguide.errors(cat, texts, ui=ui, access=access, error_codes=codes, release=True)
        self.assertEqual(found, [], [f'{f.code} {f.where}: {f.message}' for f in found])
        explained = {c for p in cat['problems'] for c in p['errors']}
        self.assertEqual(explained, codes)
        self.assertEqual({r['id'] for r in cat['roles']}, set(auth.ROLES))

    def test_cli_check_release(self):
        codes = sorted(server_error_codes())
        with tempfile.TemporaryDirectory() as tmp:
            ui_ar = os.path.join(tmp, 'ui-ar.json')
            ui_en = os.path.join(tmp, 'ui-en.json')
            acc = os.path.join(tmp, 'access.json')
            errs = os.path.join(tmp, 'errors.json')
            for path, obj in ((ui_ar, ui_map(os.path.join(ROOT, 'web', 'i18n', 'ar.js'))),
                              (ui_en, ui_map(os.path.join(ROOT, 'web', 'i18n', 'en.js'))),
                              (acc, auth.catalogue()), (errs, codes)):
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(obj, f)
            r = subprocess.run(
                [sys.executable, os.path.join(ROOT, 'server', 'afguide.py'), 'check', 'guide',
                 '--ui', ui_ar, '--ui', ui_en, '--access', acc, '--errors', errs, '--release'],
                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('OK:', r.stdout)
        self.assertIn('0 errors', r.stdout)

    def test_every_target_is_a_real_control(self):
        cat, _ = load_guide()
        blob = []
        for dp, _, fs in os.walk(os.path.join(ROOT, 'web', 'js')):
            if os.path.basename(dp) == 'vendor':
                continue
            for name in fs:
                if name.endswith('.js'):
                    with open(os.path.join(dp, name), encoding='utf-8') as f:
                        blob.append(f.read())
        text = '\n'.join(blob)
        missing = []
        for tid, spec in cat['targets'].items():
            m = re.search(r'data-guide="([^"]+)"', spec.get('sel', ''))
            if not m or m.group(1) not in text:
                missing.append(tid)
        self.assertEqual(missing, [])

    def test_custom_profiles_follow_a_built_in_course(self):
        self.assertEqual(assist.guide_role('cashier', ['pos.sell']), 'cashier')
        self.assertEqual(assist.guide_role('made-up', ['settings.edit']), 'owner')
        self.assertEqual(assist.guide_role('made-up', ['users.manage']), 'owner')
        self.assertEqual(assist.guide_role('made-up', ['reports.view']), 'manager')
        self.assertEqual(assist.guide_role('made-up', ['cash.safe']), 'manager')
        self.assertEqual(assist.guide_role('made-up', ['pos.sell']), 'cashier')
        self.assertEqual(assist.guide_role('made-up', ['stock.receive']), 'storekeeper')
        self.assertEqual(assist.guide_role('made-up', []), 'cashier')


class LiveStates(unittest.TestCase):
    def setUp(self):
        self.s = Shop()

    def tearDown(self):
        self.s.app.assist.close()
        self.s.cleanup()

    def test_states_follow_the_shop(self):
        u = self.s.users['owner']
        self.assertEqual(self.s.db.value("SELECT name FROM sqlite_master WHERE type='table' AND name='guide_progress'"), 'guide_progress')
        self.assertEqual(self.s.db.value("SELECT name FROM sqlite_master WHERE type='table' AND name='consent_log'"), 'consent_log')
        live = set(self.s.app.assist._live(u))
        self.assertIn('signed.in', live)
        self.assertIn('setup.done', live)
        self.assertNotIn('shift.open', live)
        self.assertNotIn('sale.first', live)
        self.assertNotIn('person.second', live)
        self.assertNotIn('backup.made', live)
        self.s.do(cash.open_shift, 1000)
        self.assertIn('shift.open', self.s.app.assist._live(u))
        pid = self.s.product(qty=2)
        q = self.s.do(sales.quote, {'lines': [{'product_id': pid, 'qty': 1}]})
        self.s.do(sales.sell, {'idem_key': ids.uuid7(), 'lines': [{'product_id': pid, 'qty': 1}],
                               'payments': [{'method': 'cash', 'amount': q['total']}]})
        self.assertIn('sale.first', self.s.app.assist._live(u))
        self.s.user('cashier', 'c2')
        self.assertIn('person.second', self.s.app.assist._live(u))
        import backup
        backup.make(self.s.db, self.s.app.backup_dir, 'manual')
        self.assertIn('backup.made', self.s.app.assist._live(u))


class GuideHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Server()
        cls.owner = cls.S.client()
        me = cls.owner.login()
        cls.owner_id = me['user']['id']
        for username, role in (('cash', 'cashier'), ('keep', 'storekeeper')):
            st, d, _ = cls.owner.post('/api/user/save', {'username': username, 'full_name': username, 'role': role, 'password': PW})
            assert st == 200, d
        cls.cash = cls.S.client()
        cls.cash.login('cash', PW)
        cls.keep = cls.S.client()
        cls.keep.login('keep', PW)

    @classmethod
    def tearDownClass(cls):
        cls.S.app.assist.close()
        cls.S.stop()

    def test_state_depends_on_the_person(self):
        st, owner, _ = self.owner.get('/api/guide/state')
        st2, cash, _ = self.cash.get('/api/guide/state')
        st3, keep, _ = self.keep.get('/api/guide/state')
        self.assertEqual((st, st2, st3), (200, 200, 200))
        self.assertEqual(owner['course']['role'], 'owner')
        self.assertEqual(cash['course']['role'], 'cashier')
        self.assertEqual(keep['course']['role'], 'storekeeper')
        self.assertIn('signed.in', owner['states'])
        self.assertIn('setup.done', owner['states'])
        self.assertIn('person.second', owner['states'])
        owner_ids = [i['id'] for i in owner['course']['items']]
        cash_ids = [i['id'] for i in cash['course']['items']]
        keep_ids = [i['id'] for i in keep['course']['items']]
        self.assertIn('shop-settings', owner_ids)
        self.assertIn('add-user', owner_ids)
        self.assertNotIn('shop-settings', cash_ids)
        self.assertIn('make-sale', cash_ids)
        self.assertNotIn('make-sale', keep_ids)
        self.assertIn('receive-goods', keep_ids)
        self.assertIn('read-stock', keep_ids)

    def test_progress_is_per_person_and_a_bad_update_is_400(self):
        st, d, _ = self.owner.post('/api/guide/progress', {'update': {'op': 'done', 'guide': 'home-today'}})
        self.assertEqual(st, 200, d)
        self.assertIn('home-today', d['progress']['done'])
        _, cash, _ = self.cash.get('/api/guide/state')
        self.assertNotIn('home-today', cash['progress']['done'])
        _, again, _ = self.owner.get('/api/guide/state')
        self.assertIn('home-today', again['progress']['done'])
        st, bad, _ = self.owner.post('/api/guide/progress', {'update': {'op': 'nope'}})
        self.assertEqual(st, 400)
        self.assertEqual(bad['key'], 'err.badRequest')
        self.assertIn('bad', bad['error'])
        self.assertNotIn('number or date', bad['error'])

    def test_guide_files_are_public_and_locked_to_three_names(self):
        guest = self.S.client()
        st, d, _ = guest.get('/guide/catalogue.json')
        self.assertEqual(st, 200)
        self.assertIn('guides', d)
        st, _, _ = guest.get('/guide/ar.json')
        self.assertEqual(st, 200)
        st, _, _ = guest.get('/guide/en.json')
        self.assertEqual(st, 200)
        st, _, _ = guest.get('/guide/../server/auth.py')
        self.assertEqual(st, 404)

    def test_opening_a_shift_is_a_live_state_for_that_person(self):
        st, d, _ = self.cash.post('/api/shift/open', {'opening_float': 5000})
        self.assertEqual(st, 200, d)
        _, cash, _ = self.cash.get('/api/guide/state')
        _, owner, _ = self.owner.get('/api/guide/state')
        self.assertIn('shift.open', cash['states'])
        self.assertNotIn('shift.open', owner['states'])


if __name__ == '__main__':
    unittest.main()
