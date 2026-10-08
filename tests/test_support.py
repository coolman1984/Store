"""The optional heartbeat to the vendor: off by default, exact fields only, secrets outside the database, never blocks the shop."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from harness import OWNER, Server
import support

SEEN = []


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        SEEN.append((self.path, self.headers.get('X-Install-Token'), body))
        ok = self.headers.get('X-Install-Token') == 'install-token-123456789'
        raw = json.dumps({'ok': True, 'repairs_waiting': 2} if ok else {'detail': 'no'}).encode()
        self.send_response(200 if ok else 401)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class SupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Server()
        cls.c = cls.S.client()
        cls.c.login()
        cls.stub = HTTPServer(('127.0.0.1', 0), Stub)
        threading.Thread(target=cls.stub.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.stub.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.stub.shutdown()
        cls.S.stop()

    def test_1_off_by_default_and_needs_address_and_code(self):
        st, d, _ = self.c.get('/api/support')
        self.assertEqual((st, d['enabled'], d['has_token']), (200, False, False))
        st, d, _ = self.c.post('/api/support/ping')
        self.assertEqual((st, d['key']), (409, 'err.supportOff'))
        st, d, _ = self.c.post('/api/support/save', {'enabled': True})
        self.assertEqual(d['key'], 'err.supportIncomplete')
        st, d, _ = self.c.post('/api/support/save', {'enabled': True, 'url': 'http://example.com', 'token': 'x' * 20})
        self.assertEqual(d['key'], 'err.supportUrl')  # plain http only for this PC itself
        st, d, _ = self.c.post('/api/support/save', {'enabled': True, 'url': 'https://u:p@example.com', 'token': 'x' * 20})
        self.assertEqual(d['key'], 'err.supportUrl')
        st, d, _ = self.c.post('/api/support/save', {'enabled': True, 'url': self.url, 'token': 'short'})
        self.assertEqual(d['key'], 'err.supportToken')

    def test_2_sends_exactly_the_allowed_fields_and_keeps_secrets_out_of_the_database(self):
        st, d, _ = self.c.post('/api/support/save', {'enabled': True, 'url': self.url, 'token': 'install-token-123456789'})
        self.assertEqual(st, 200, d)
        self.assertNotIn('install-token', json.dumps(d))  # the page never gets the code back
        st, d, _ = self.c.post('/api/support/ping')
        self.assertEqual((st, d['ok'], d['repairs_waiting']), (200, True, 2), d)
        path, token, body = SEEN[-1]
        self.assertEqual(path, '/api/agent/heartbeat')
        self.assertEqual(set(body), set(support.SENT_FIELDS))
        self.assertIn(body['licence_state'], ('active', 'grace', 'expired', 'not_yet_valid', 'invalid', 'none'))
        self.assertIsInstance(body['error_count'], int)
        db = self.S.app.db
        dump = json.dumps(db.all('SELECT * FROM settings')) + json.dumps(db.all('SELECT detail FROM audit'))
        self.assertNotIn('install-token', dump)
        self.assertNotIn(self.url, dump)
        self.assertTrue(os.path.exists(os.path.join(self.S.app.home, 'support.json')))

    def test_3_failures_are_remembered_not_raised(self):
        self.c.post('/api/support/save', {'enabled': True, 'url': self.url, 'token': 'a-wrong-token-1234567'})
        st, d, _ = self.c.post('/api/support/ping')
        self.assertEqual((st, d['ok'], d['error']), (200, False, 'http 401'))
        self.c.post('/api/support/save', {'enabled': True, 'url': 'http://127.0.0.1:1', 'token': 'a-wrong-token-1234567'})
        st, d, _ = self.c.post('/api/support/ping')
        self.assertEqual((st, d['ok']), (200, False))
        self.assertEqual(self.c.get('/api/support')[1]['last']['ok'], False)

    def test_4_cashier_cannot_touch_support(self):
        self.c.post('/api/user/save', {'username': 'cash9', 'full_name': 'Cash', 'role': 'cashier', 'password': 'Strong Pass 9'})
        k = self.S.client()
        k.login('cash9', 'Strong Pass 9')
        for call in (lambda: k.get('/api/support'), lambda: k.post('/api/support/save', {'enabled': False}), lambda: k.post('/api/support/ping')):
            self.assertEqual(call()[0], 403)


if __name__ == '__main__':
    unittest.main()
