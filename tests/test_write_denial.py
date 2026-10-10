"""Deny by default for WRITES (IAM-03): a person with no ticks at all gets 403 from every write route that is not meant for everybody, before
any validation or lookup answers differently (found by posting an empty body to all 48 write routes: three answered 400/404 first, and a return
could be taken by a person with no counter permission when a manager typed a password). Complements the read matrix in test_permissions_matrix."""
import os
import re
import unittest

from harness import PW, Server

# routes that every signed-in person (or the sign-in itself) may call, each guarded by what it does
EVERYBODY = {'/api/login', '/api/logout', '/api/setup', '/api/recover', '/api/password', '/api/guide/progress', '/api/consent/decide',
             '/api/telemetry/events', '/api/telemetry/feedback', '/api/telemetry/feedback/preview', '/api/practice/open', '/api/watch/review'}
SKIP_FOR_THE_PROBE = {'/api/login', '/api/logout', '/api/setup', '/api/recover', '/api/password'}  # they would end the session this test needs


class WritesDenyByDefault(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Server()
        owner = cls.S.client()
        owner.login()
        for username, perms in (('nobody', []), ('seller', ['pos.sell'])):
            st, d, _ = owner.post('/api/user/save', {'username': username, 'full_name': username, 'role': 'custom', 'password': PW, 'perms': perms})
            assert st == 200, d
        st, d, _ = owner.post('/api/user/save', {'username': 'boss', 'full_name': 'Boss', 'role': 'manager', 'password': PW})
        assert st == 200, d
        with open(os.path.join(os.path.dirname(__file__), '..', 'server', 'app.py'), encoding='utf-8') as f:
            src = f.read()
        cls.routes = sorted(set(re.findall(r"path == '(/api/[a-z/_\-]+)'", src[src.index('def api_post'):])) - SKIP_FOR_THE_PROBE)

    @classmethod
    def tearDownClass(cls):
        cls.S.stop()

    def test_there_are_the_routes_we_think(self):
        self.assertGreater(len(self.routes), 40)
        self.assertIn('/api/return', self.routes)

    def test_a_person_with_no_ticks_is_refused_everywhere_with_a_403(self):
        odd = []
        for route in self.routes:
            if route in EVERYBODY:
                continue
            c = self.S.client()
            c.login('nobody', PW)
            st, d, _ = c.post(route, {})
            if st != 403:
                odd.append((route, st, d.get('key') if isinstance(d, dict) else None))
        self.assertEqual(odd, [])

    def test_a_person_with_only_the_counter_cannot_use_the_other_pages_write_routes(self):
        allowed = {'/api/pos/quote', '/api/pos/sell', '/api/shift/open', '/api/shift/close', '/api/return', '/api/pos/park', '/api/customer/save'}
        odd = []
        for route in self.routes:
            if route in EVERYBODY or route in allowed:
                continue
            c = self.S.client()
            c.login('seller', PW)
            st, d, _ = c.post(route, {})
            if st != 403:
                odd.append((route, st, d.get('key') if isinstance(d, dict) else None))
        self.assertEqual(odd, [])

    def test_a_manager_password_does_not_turn_a_person_with_no_counter_permission_into_a_cashier(self):
        owner = self.S.client()
        owner.login()
        shop = self.S.app.db.value("SELECT id FROM locations WHERE kind = 'shop'")
        st, d, _ = owner.post('/api/product/save', {'name': 'Kettle', 'category': 'Small', 'retail': 115000})
        pid = d['id']
        owner.post('/api/purchase', {'idem_key': 'buy', 'location_id': shop, 'lines': [{'product_id': pid, 'qty': 5, 'unit_cost': 90000}]})
        owner.post('/api/shift/open', {'opening_float': 500000})
        st, d, _ = owner.post('/api/pos/sell', {'idem_key': 's1', 'lines': [{'product_id': pid, 'qty': 1}], 'payments': [{'method': 'cash', 'amount': 115000}]})
        sale = owner.get('/api/sale?id=' + d['id'])[1]
        body = {'idem_key': 'r1', 'sale_id': sale['id'], 'reason': 'changed mind', 'refund_method': 'account',
                'lines': [{'sale_line_id': sale['lines'][0]['id'], 'qty': 1}], 'approval': {'username': 'boss', 'password': PW}}
        nobody = self.S.client()
        nobody.login('nobody', PW)
        st, d, _ = nobody.post('/api/return', body)
        self.assertEqual((st, d['key']), (403, 'err.forbidden'))
        self.assertEqual(self.S.app.db.value('SELECT COUNT(*) FROM returns'), 0)


if __name__ == '__main__':
    unittest.main()
