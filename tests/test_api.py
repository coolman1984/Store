"""The real HTTP server: sign-in, licence gate, roles, browser-attack guards, backups, practice mode."""
import io
import http.client
import json
import unittest
import zipfile

from harness import HAVE_CRYPTO, OWNER, PW, Server, code_for
import ids


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Server()
        cls.owner = cls.S.client()
        cls.owner.login()
        for username, role in (('cash', 'cashier'), ('keeper', 'storekeeper'), ('boss', 'manager')):
            st, d, _ = cls.owner.post('/api/user/save', {'username': username, 'full_name': username, 'role': role, 'password': PW})
            assert st == 200, d
        st, d, _ = cls.owner.post('/api/product/save', {'name': 'Kettle', 'retail': 115000, 'min': 100000, 'barcodes': ['111222333']})
        cls.pid = d['id']
        shop = cls.S.app.db.value("SELECT id FROM locations WHERE kind = 'shop'")
        st, d, _ = cls.owner.post('/api/purchase', {'idem_key': 'buy1', 'location_id': shop,
                                                    'lines': [{'product_id': cls.pid, 'qty': 20, 'unit_cost': 90000}]})
        assert st == 200, d

    @classmethod
    def tearDownClass(cls):
        cls.S.stop()

    def client(self, username):
        c = self.S.client()
        c.login(username, PW)
        return c

    def test_activation_and_restore_with_junk_never_crash(self):
        for junk in (None, 1, 1.5, True, [], ['a'], {}, 'x' * 3000, '\u0000', '0' * 144):
            for path, body in (('/api/licence/activate', {'code': junk}),
                               ('/api/backup/restore', {'name': junk, 'password': OWNER[1]})):  # (a wrong password would lock the owner: that is tested apart)
                st, d, _ = self.owner.post(path, body)
                self.assertLess(st, 500, (path, str(junk)[:20], d))
        self.assertEqual(self.owner.get('/api/licence')[1]['state'], 'trial')  # nothing above may wipe the working code

    def test_boot_and_security_headers(self):
        st, d, h = self.S.client().get('/api/boot')
        self.assertEqual(st, 200)
        self.assertFalse(d['setup'])
        self.assertIsNone(d['user'])
        st, body, h = self.S.client().get('/')
        self.assertEqual(st, 200)
        self.assertIn("script-src 'self'", h['Content-Security-Policy'])
        self.assertNotIn('unsafe-inline', h['Content-Security-Policy'])
        self.assertEqual(h['X-Frame-Options'], 'DENY')

    def test_reads_need_sign_in(self):
        st, d, _ = self.S.client().get('/api/home')
        self.assertEqual(st, 401)
        self.assertTrue(d['login'])

    def test_logout_consumes_body_and_relogin_works_on_the_same_connection(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.S.port, timeout=5)
        headers = {'Content-Type': 'application/json', 'Origin': self.S.base}
        try:
            connection.request('POST', '/api/login', json.dumps({'username': OWNER[0], 'password': OWNER[1]}), headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())['ok'])
            headers['Cookie'] = response.getheader('Set-Cookie').split(';', 1)[0]
            live_socket = connection.sock
            connection.request('POST', '/api/logout', '{}', headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())['ok'])
            self.assertIn('Max-Age=0', response.getheader('Set-Cookie'))
            headers.pop('Cookie')
            connection.request('GET', '/api/boot')
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIsNone(json.loads(response.read())['user'])
            connection.request('POST', '/api/login', json.dumps({'username': 'keeper', 'password': PW}), headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())['user']['role'], 'storekeeper')
            self.assertIs(connection.sock, live_socket)
        finally:
            connection.close()

    def test_only_the_owner_turns_on_other_ways_of_paying(self):
        st, d, _ = self.owner.get('/api/lookups')
        self.assertEqual(d['pay_methods'], ['cash'])
        st, d, _ = self.client('cash').post('/api/settings/save', {'settings': {'pay_methods': ['cash', 'card']}})
        self.assertEqual(st, 403)
        st, d, _ = self.owner.post('/api/settings/save', {'settings': {'pay_methods': ['card']}})
        self.assertEqual((st, d['pay_methods']), (200, ['cash', 'card']))
        self.assertEqual(self.owner.get('/api/lookups')[1]['pay_methods'], ['cash', 'card'])
        audit = self.S.app.db.one("SELECT detail FROM audit WHERE action = 'settings' ORDER BY rowid DESC LIMIT 1")
        self.assertIn('card', audit['detail'])
        st, d, _ = self.owner.post('/api/settings/save', {'settings': {'pay_methods': ['cash']}})
        self.assertEqual(d['pay_methods'], ['cash'])

    def test_dns_rebinding_and_cross_site_writes_refused(self):
        st, _, _ = self.owner.get('/api/home', headers={'Host': 'evil.example.com'})
        self.assertEqual(st, 421)
        st, d, _ = self.owner.post('/api/product/save', {'name': 'X'}, headers={'Origin': 'http://evil.example.com'})
        self.assertEqual(st, 403)
        self.assertEqual(d['key'], 'err.origin')

    def test_wrong_password_is_vague_and_locks(self):
        c = self.S.client()
        st, d, _ = c.post('/api/login', {'username': 'nobody', 'password': 'x'})
        st2, d2, _ = c.post('/api/login', {'username': OWNER[0], 'password': 'x'})
        self.assertEqual((st, d['key']), (st2, d2['key']))
        for _ in range(5):
            c.post('/api/login', {'username': 'keeper', 'password': 'bad'})
        st, d, _ = c.post('/api/login', {'username': 'keeper', 'password': PW})
        self.assertEqual(d['key'], 'auth.err.locked')
        self.S.app.db.run("UPDATE users SET locked_until = NULL, failed = 0 WHERE username = 'keeper'")

    def test_cashier_sees_no_cost_and_cannot_manage(self):
        c = self.client('cash')
        st, d, _ = c.get('/api/products?q=Kettle')
        self.assertEqual(st, 200)
        self.assertNotIn('avg_cost', d['items'][0])
        st, d, _ = c.get('/api/product?id=' + self.pid)
        self.assertNotIn('cost', d)
        for path in ('/api/users', '/api/settings', '/api/watch', '/api/reports', '/api/audit', '/api/safe'):
            self.assertEqual(c.get(path)[0], 403, path)
        st, d, _ = c.post('/api/product/save', {'id': self.pid, 'retail': 1})
        self.assertEqual(st, 403)
        self.assertEqual(self.owner.get('/api/product?id=' + self.pid)[1]['prices']['retail'], 115000)
        denied = self.S.app.db.value("SELECT COUNT(*) FROM audit WHERE action = 'denied'")
        self.assertGreater(denied, 0)

    def test_full_sale_and_receipt_over_http(self):
        c = self.client('cash')
        self.assertEqual(c.post('/api/shift/open', {'opening_float': 20000})[0], 200)
        st, q, _ = c.post('/api/pos/quote', {'lines': [{'product_id': self.pid, 'qty': 2}]})
        self.assertEqual(q['total'], 230000)
        body = {'idem_key': ids.uuid7(), 'lines': [{'product_id': self.pid, 'qty': 2}], 'payments': [{'method': 'cash', 'amount': 230000}],
                'cash_received': 250000}
        st, d, _ = c.post('/api/pos/sell', body)
        self.assertEqual(st, 200, d)
        self.assertEqual(d['change'], 20000)
        st, again, _ = c.post('/api/pos/sell', body)
        self.assertEqual(again['id'], d['id'])
        st, view, _ = c.get('/api/sale?id=' + d['number'])
        self.assertEqual(view['total'], 230000)
        self.assertNotIn('cost_total', view)
        st, mine, _ = c.get('/api/sales')
        self.assertTrue(any(s['id'] == d['id'] for s in mine))
        # a big discount needs the manager's password typed on the cashier's screen
        lines = [{'product_id': self.pid, 'qty': 1, 'unit_price': 101000}]
        st, d, _ = c.post('/api/pos/sell', {'idem_key': ids.uuid7(), 'lines': lines, 'payments': [{'method': 'cash', 'amount': 101000}]})
        self.assertEqual((st, d['key']), (403, 'err.needsApproval'))
        st, d, _ = c.post('/api/pos/sell', {'idem_key': ids.uuid7(), 'lines': lines, 'payments': [{'method': 'cash', 'amount': 101000}],
                                            'approval': {'username': 'boss', 'password': PW}})
        self.assertEqual(st, 200, d)

    def test_storekeeper_cannot_sell(self):
        c = self.client('keeper')
        st, _, _ = c.post('/api/shift/open', {'opening_float': 0})
        self.assertEqual(st, 403)

    def test_export_and_backup(self):
        st, body, h = self.owner.get('/api/export')
        self.assertEqual(st, 200)
        names = zipfile.ZipFile(io.BytesIO(body)).namelist()
        self.assertIn('sales.csv', names)
        st, d, _ = self.owner.post('/api/backup/now')
        self.assertEqual(st, 200, d)
        st, s, _ = self.owner.get('/api/settings')
        self.assertTrue(any(b['name'] == d['name'] for b in s['backups']))

    def test_static_files_are_cached_and_compressed(self):
        st, body, h = self.S.client().get('/', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(st, 200)
        etag = h.get('ETag')
        self.assertTrue(etag)
        st, _, _ = self.S.client().get('/', headers={'If-None-Match': etag})
        self.assertEqual(st, 304)
        st, _, _ = self.S.client().get('/../server/app.py')
        self.assertIn(st, (200, 404))  # unknown paths fall back to the page, never to a file outside web/
        self.assertNotIn(b'import', _ if isinstance(_, bytes) else b'')


class RestoreTests(unittest.TestCase):
    """A backup that cannot be restored is not a backup: the whole round trip over HTTP, with the safety copy."""

    def test_restore_brings_back_the_data_and_keeps_a_listed_safety_copy(self):
        S = Server()
        try:
            c = S.client()
            c.login()
            st, a, _ = c.post('/api/product/save', {'name': 'Before backup', 'retail': 10000})
            self.assertEqual(st, 200, a)
            st, b, _ = c.post('/api/backup/now')
            self.assertEqual(st, 200, b)
            c.post('/api/product/save', {'name': 'After backup', 'retail': 20000})
            self.assertGreaterEqual(c.post('/api/backup/restore', {'name': b['name'], 'password': 'wrong'})[0], 400)  # step-up: the owner types the password
            st, d, _ = c.post('/api/backup/restore', {'name': b['name'], 'password': OWNER[1]})
            self.assertEqual(st, 200, d)
            names = [p['name'] for p in c.get('/api/products?q=backup')[1]['items']]
            self.assertEqual(names, ['Before backup'])
            st, settings, _ = c.get('/api/settings')
            safety = [x['name'] for x in settings['backups'] if 'before-restore' in x['name']]
            self.assertTrue(safety, 'the copy made before the restore must be listed')
            self.assertEqual(c.post('/api/backup/restore', {'name': safety[0], 'password': OWNER[1]})[0], 200)  # and it can be restored
            names = sorted(p['name'] for p in c.get('/api/products?q=backup')[1]['items'])
            self.assertEqual(names, ['After backup', 'Before backup'])
        finally:
            S.stop()


@unittest.skipUnless(HAVE_CRYPTO, 'cryptography is needed to sign test licence codes')
class RecoveryTests(unittest.TestCase):
    """A forgotten owner password: the paper code from setup, once, counted like wrong passwords; no master password."""

    def setUp(self):
        self.S = Server(setup=False)
        self.owner = self.S.client()
        st, d, _ = self.owner.post('/api/setup', {'username': OWNER[0], 'full_name': 'Owner', 'password': OWNER[1], 'shop_name': 'Shop'})
        self.assertEqual(st, 200, d)
        self.code = d['recovery_code']
        if HAVE_CRYPTO:
            import licence
            licence.activate(self.S.app.db, code_for(licence.device(self.S.app.db)))

    def tearDown(self):
        self.S.stop()

    def test_setup_gives_a_paper_code_and_only_its_hash_is_kept(self):
        self.assertRegex(self.code, r'^[A-HJKMNP-Z2-9]{4}(-[A-HJKMNP-Z2-9]{4}){3}$')
        kept = self.S.app.db.value("SELECT value FROM meta WHERE key = 'recovery'")
        self.assertNotIn(self.code.replace('-', ''), kept)
        self.assertTrue(self.owner.get('/api/me')[1]['recovery'])
        st, d, _ = self.owner.post('/api/setup', {'username': 'x2', 'full_name': 'X', 'password': 'another-pass-1', 'shop_name': 'S'})
        self.assertEqual(st, 409)

    def test_right_code_sets_a_new_password_once_and_ends_old_sessions(self):
        st, d, _ = self.S.client().post('/api/recover', {'code': 'AAAA-BBBB-CCCC-DDDD', 'password': 'new-secret-77'})
        self.assertEqual((st, d['key']), (400, 'auth.err.recovery'))
        st, d, _ = self.S.client().post('/api/recover', {'code': self.code, 'password': 'abc'})
        self.assertEqual(d['key'], 'auth.err.short')  # a weak password changes nothing and keeps the code
        c = self.S.client()
        typed = self.code.lower().replace('-', ' ')  # read off paper: small letters and spaces are fine
        st, d, _ = c.post('/api/recover', {'code': typed, 'password': 'new-secret-77'})
        self.assertEqual(st, 200, d)
        self.assertEqual(d['user']['username'], OWNER[0])
        self.assertNotEqual(d['recovery_code'], self.code)
        self.assertEqual(c.get('/api/me')[0], 200)
        self.assertEqual(self.owner.get('/api/me')[0], 401)  # the old session ended
        st, d, _ = self.S.client().post('/api/recover', {'code': self.code, 'password': 'other-secret-88'})
        self.assertEqual(d['key'], 'auth.err.recovery')  # the old paper works once
        self.S.client().login(OWNER[0], 'new-secret-77')
        audit = self.S.app.db.one("SELECT * FROM audit WHERE action = 'password.recover'")
        self.assertNotIn(self.code.replace('-', ''), audit['detail'])

    def test_a_locked_owner_gets_back_in_and_wrong_codes_are_throttled(self):
        for _ in range(6):
            self.S.client().post('/api/login', {'username': OWNER[0], 'password': 'wrong-wrong'})
        st, d, _ = self.S.client().post('/api/login', {'username': OWNER[0], 'password': OWNER[1]})
        self.assertEqual(d['key'], 'auth.err.locked')
        st, d, _ = self.S.client().post('/api/recover', {'code': self.code, 'password': 'new-secret-77'})
        self.assertEqual(st, 200, d)
        self.S.app.failed_ips.clear()
        for _ in range(20):
            self.S.client().post('/api/recover', {'code': 'AAAA-BBBB-CCCC-DDDD', 'password': 'new-secret-77'})
        st, d, _ = self.S.client().post('/api/recover', {'code': d['recovery_code'], 'password': 'new-secret-78'})
        self.assertEqual((st, d['key']), (429, 'auth.err.locked'))

    def test_recovery_works_while_the_licence_is_locked(self):
        S = Server(setup=False)
        try:
            c = S.client()
            st, d, _ = c.post('/api/setup', {'username': OWNER[0], 'full_name': 'Owner', 'password': OWNER[1], 'shop_name': 'Shop'})
            self.assertFalse(S.app.licence()['full'])
            st, d, _ = c.post('/api/recovery/new', {'password': OWNER[1]})
            self.assertEqual(st, 200, d)
            st, d, _ = S.client().post('/api/recover', {'code': d['recovery_code'], 'password': 'new-secret-77'})
            self.assertEqual(st, 200, d)
        finally:
            S.stop()

    @unittest.skipUnless(HAVE_CRYPTO, 'cryptography needed')
    def test_only_the_holder_makes_a_new_code_after_typing_the_password(self):
        st, d, _ = self.owner.post('/api/user/save', {'username': 'boss', 'full_name': 'Boss', 'role': 'manager', 'password': PW})
        self.assertEqual(st, 200, d)
        boss = self.S.client()
        boss.login('boss', PW)
        self.assertFalse(boss.get('/api/me')[1]['recovery'])
        self.assertEqual(boss.post('/api/recovery/new', {'password': PW})[0], 403)
        st, d, _ = self.owner.post('/api/recovery/new', {'password': 'wrong-wrong'})
        self.assertEqual(d['key'], 'auth.err.wrong')
        st, d, _ = self.owner.post('/api/recovery/new', {'password': OWNER[1]})
        self.assertEqual(st, 200, d)
        st, d2, _ = self.S.client().post('/api/recover', {'code': self.code, 'password': 'new-secret-77'})
        self.assertEqual(d2['key'], 'auth.err.recovery')  # the lost paper stopped working
        st, d2, _ = self.S.client().post('/api/recover', {'code': d['recovery_code'], 'password': 'new-secret-77'})
        self.assertEqual(st, 200, d2)


class LicenceGateTests(unittest.TestCase):
    def setUp(self):
        self.S = Server(licensed=False)
        self.c = self.S.client()
        self.c.login()

    def tearDown(self):
        self.S.stop()

    def test_without_code_reads_work_and_writes_are_refused(self):
        st, lic, _ = self.c.get('/api/licence')
        self.assertEqual(lic['state'], 'none')
        self.assertRegex(lic['device'], r'^[0-9A-Z]{5}-[0-9A-Z]{5}$')
        self.assertEqual(self.c.get('/api/home')[0], 200)
        st, d, _ = self.c.post('/api/product/save', {'name': 'X', 'retail': 100})
        self.assertEqual(st, 402)
        self.assertEqual(d['key'], 'err.licence')
        self.assertEqual(self.c.post('/api/backup/now')[0], 200)  # keeping data safe is always allowed
        self.assertEqual(self.c.get('/api/export')[0], 200)

    def test_code_for_another_pc_is_refused_then_right_code_unlocks(self):
        st, d, _ = self.c.post('/api/licence/activate', {'code': code_for('AAAAA-BBBBB')})
        self.assertEqual(st, 400)
        self.assertEqual(d['key'], 'lic.err.other_device')
        device = self.c.get('/api/licence')[1]['device']
        st, d, _ = self.c.post('/api/licence/activate', {'code': code_for(device).lower()})
        self.assertEqual(st, 200, d)
        self.assertEqual(d['state'], 'trial')
        self.assertEqual(d['days_left'], 14)
        self.assertEqual(self.c.post('/api/product/save', {'name': 'X', 'retail': 100})[0], 200)

    def test_monthly_subscription_grace_then_read_only(self):
        from datetime import date, timedelta
        import licence
        device = self.c.get('/api/licence')[1]['device']
        st, d, _ = self.c.post('/api/licence/activate', {'code': code_for(device, 30, edition='standard', grace=3)})
        self.assertEqual((st, d['state'], d['edition'], d['days_left'], d['full']), (200, 'active', 'standard', 30, True))
        today = date.fromisoformat(ids.local_day())
        late = code_for(device, 30, today - timedelta(days=31), edition='standard', grace=3)  # ended 2 days ago
        st, d, _ = self.c.post('/api/licence/activate', {'code': late})
        self.assertEqual((d['state'], d['full']), ('grace', True))
        self.assertEqual(self.c.post('/api/product/save', {'name': 'In grace', 'retail': 100})[0], 200)
        ended = code_for(device, 30, today - timedelta(days=40), edition='standard', grace=3)
        self.S.app.db.run("UPDATE meta SET value = ? WHERE key = 'licence_code'", ended)  # the month ran out on this PC
        licence._cache.clear()
        self.assertEqual(self.c.get('/api/licence')[1]['state'], 'expired')
        self.assertEqual(self.c.post('/api/product/save', {'name': 'After', 'retail': 100})[0], 402)
        self.assertEqual(self.c.get('/api/products')[0], 200)  # reading, export and backup stay open
        self.assertEqual(self.c.get('/api/export')[0], 200)
        self.assertEqual(self.c.post('/api/backup/now')[0], 200)

    def test_perpetual_code_unlocks_for_good_on_this_pc_only(self):
        device = self.c.get('/api/licence')[1]['device']
        st, d, _ = self.c.post('/api/licence/activate', {'code': code_for('AAAAA-BBBBB', edition='perpetual')})
        self.assertEqual(d['key'], 'lic.err.other_device')
        st, d, _ = self.c.post('/api/licence/activate', {'code': code_for(device, edition='perpetual')})
        self.assertEqual((st, d['state'], d['edition'], d['last_day'], d['days_left'], d['full']),
                         (200, 'active', 'perpetual', None, None, True))
        self.assertEqual(self.c.post('/api/product/save', {'name': 'Forever', 'retail': 100})[0], 200)
        home = self.c.get('/api/home')[1]
        self.assertNotIn('licence_soon', json.dumps(home))

    def test_expired_code_cannot_be_activated(self):
        from datetime import date, timedelta
        device = self.c.get('/api/licence')[1]['device']
        old = code_for(device, 14, date.fromisoformat(ids.local_day()) - timedelta(days=20))
        st, d, _ = self.c.post('/api/licence/activate', {'code': old})
        self.assertEqual(d['key'], 'lic.err.expired')

    def test_clock_moved_back_locks_changes(self):
        device = self.c.get('/api/licence')[1]['device']
        self.c.post('/api/licence/activate', {'code': code_for(device)})
        future = ids.iso(ids.utcnow().replace(year=ids.utcnow().year + 1))
        self.S.app.db.run("UPDATE meta SET value = ? WHERE key = 'max_seen'", future)
        st, lic, _ = self.c.get('/api/licence')
        self.assertEqual(lic['state'], 'clock_back')
        self.assertEqual(self.c.post('/api/product/save', {'name': 'Y', 'retail': 100})[0], 402)


class PracticeTests(unittest.TestCase):
    def test_practice_shop_has_history_and_demo_accounts(self):
        S = Server(practice=True)
        try:
            c = S.client()
            st, boot, _ = c.get('/api/boot')
            self.assertTrue(boot['practice'])
            self.assertEqual(boot['licence']['state'], 'practice')
            c.login('owner', 'practice-1234')
            st, home, _ = c.get('/api/home')
            self.assertEqual(st, 200)
            self.assertGreater(sum(x['sales'] for x in home['series']), 0)
            st, w, _ = c.get('/api/watch?days=30')
            self.assertTrue(w)
        finally:
            S.stop()


class SetupTests(unittest.TestCase):
    def test_first_run_creates_owner_once(self):
        S = Server(setup=False)
        try:
            c = S.client()
            self.assertTrue(c.get('/api/boot')[1]['setup'])
            st, d, _ = c.post('/api/setup', {'username': 'me', 'full_name': 'Me', 'password': '123', 'shop_name': 'S'})
            self.assertEqual(d['key'], 'auth.err.short')
            st, d, _ = c.post('/api/setup', {'username': 'me', 'full_name': 'Me', 'password': PW, 'shop_name': 'Shop'})
            self.assertEqual(st, 200, d)
            self.assertEqual(c.get('/api/me')[1]['role'], 'owner')
            st, d, _ = S.client().post('/api/setup', {'username': 'x', 'full_name': 'X', 'password': PW, 'shop_name': 'Y'})
            self.assertEqual(st, 409)
            kinds = {r['kind'] for r in S.app.db.all('SELECT kind FROM locations')}
            self.assertEqual(kinds, {'shop', 'warehouse', 'damaged'})
        finally:
            S.stop()


if __name__ == '__main__':
    unittest.main()
