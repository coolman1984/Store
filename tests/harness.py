"""Shared test helpers: a fresh shop in a temp folder, a signing key for licence codes, a live server on a free port."""
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))
os.environ.setdefault('STORE_DEVICE_ID', 'test-machine-guid')

import afcodes  # noqa: E402
import app as app_mod  # noqa: E402
import auth  # noqa: E402
import core  # noqa: E402
import ids  # noqa: E402

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64

    _PRIVATE = Ed25519PrivateKey.generate()
    PRIVATE_PEM = _PRIVATE.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    PUBLIC = base64.urlsafe_b64encode(_PRIVATE.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                                      ).decode().rstrip('=')
    os.environ['STORE_LICENCE_KEYS'] = PUBLIC
    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover
    PRIVATE_PEM = PUBLIC = None
    HAVE_CRYPTO = False

OWNER = ('owner1', 'Owner Pass 1')
PW = 'Strong Pass 9'


def code_for(device, days=14, first=None, edition='trial', product='al-store'):
    """A licence code signed with the test key (the vendored module has the same issue_code as Apps-Factory)."""
    first = first or date.fromisoformat(ids.local_day())
    return afcodes.issue_code(PRIVATE_PEM, product, edition, first, days, device)['code']


class Shop:
    """A shop in a temp folder, set up with an owner, licensed for 14 days, without HTTP."""

    def __init__(self, licensed=True):
        self.dir = tempfile.mkdtemp(prefix='store-test-')
        self.app = app_mod.build(self.dir, practice=False)
        self.app.setup({'username': OWNER[0], 'full_name': 'Owner', 'password': OWNER[1], 'shop_name': 'Test shop'}, '127.0.0.1')
        self.db = self.app.db
        if licensed and HAVE_CRYPTO:
            import licence
            licence.activate(self.db, code_for(licence.device(self.db)))
        self.users = {'owner': self.db.one('SELECT * FROM users WHERE username = ?', OWNER[0])}
        self.shop = self.db.value("SELECT id FROM locations WHERE kind = 'shop'")
        self.store = self.db.value("SELECT id FROM locations WHERE kind = 'warehouse'")
        self.damaged = self.db.value("SELECT id FROM locations WHERE kind = 'damaged'")

    def user(self, role, username=None, **kw):
        username = username or role + str(len(self.users))
        with self.db.tx():
            u = self.app.auth.create(username, role.title(), role, PW, **kw)
        self.users[username] = u
        return u

    def ctx(self, user=None):
        user = user or self.users['owner']
        user = self.db.one('SELECT * FROM users WHERE id = ?', user['id'])
        return core.Ctx(self.db, user, auth.effective_perms(user), '127.0.0.1', self.app.org_id, self.app.branch_id)

    def do(self, fn, *args, user=None, **kw):
        ctx = self.ctx(user)
        for a in args:  # the server checks a manager's password before the transaction; do the same here
            if isinstance(a, dict) and isinstance(a.get('approval'), dict):
                ctx.approver = self.app.auth.verify(a['approval'].get('username'), a['approval'].get('password'))
        with self.db.tx():
            return fn(ctx, *args, **kw)

    def product(self, name='Fan', retail=100000, cost=80000, qty=10, serial=False, place=None, minimum=0, **extra):
        import catalog
        import stock
        data = {'name': name, 'retail': retail, 'min': minimum, 'track_serial': serial, 'warranty_months': 12, **extra}
        pid = self.do(catalog.save_product, data)
        if qty:
            serials = [f'{name[:3].upper()}{i:04d}' for i in range(qty)] if serial else []
            self.do(stock.receive, {'idem_key': ids.uuid7(), 'location_id': place or self.shop,
                                    'lines': [{'product_id': pid, 'qty': qty, 'unit_cost': cost, 'serials': serials}]})
        return pid

    def cleanup(self):
        try:
            self.app.assist.close()
            self.db.close()
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server:
    """The real HTTP server on a free port, in a thread."""

    def __init__(self, practice=False, licensed=True, setup=True):
        self.dir = tempfile.mkdtemp(prefix='store-http-')
        self.port = free_port()
        self.app = app_mod.build(self.dir, practice=practice, port=self.port, host='127.0.0.1')
        if setup and not practice:
            self.app.setup({'username': OWNER[0], 'full_name': 'Owner', 'password': OWNER[1], 'shop_name': 'Test shop'}, '127.0.0.1')
            if licensed and HAVE_CRYPTO:
                import licence
                licence.activate(self.app.db, code_for(licence.device(self.app.db)))
        from http.server import ThreadingHTTPServer
        self.httpd = ThreadingHTTPServer(('127.0.0.1', self.port), app_mod.Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.port}'

    def client(self):
        return Client(self.port)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.app.assist.close()
        self.app.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)


class Client:
    def __init__(self, port):
        self.port, self.cookie = port, ''

    def call(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        h = {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        if method == 'POST':
            h['Origin'] = f'http://127.0.0.1:{self.port}'
        if self.cookie:
            h['Cookie'] = self.cookie
        h.update(headers or {})
        c.request(method, path, json.dumps(body).encode() if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        for k, v in r.getheaders():
            if k.lower() == 'set-cookie':
                self.cookie = v.split(';', 1)[0]
        try:
            data = json.loads(raw.decode('utf-8')) if raw and 'json' in (r.getheader('Content-Type') or '') else raw
        except ValueError:
            data = raw
        c.close()
        return r.status, data, dict(r.getheaders())

    def get(self, path, **kw):
        return self.call('GET', path, **kw)

    def post(self, path, body=None, **kw):
        return self.call('POST', path, body or {}, **kw)

    def login(self, username=OWNER[0], password=OWNER[1]):
        status, data, _ = self.post('/api/login', {'username': username, 'password': password})
        assert status == 200, data
        return data


def day(offset=0):
    return (date.fromisoformat(ids.local_day()) + timedelta(days=offset)).isoformat()

