"""Al-Store (الستور) – the shop's local web server. Python standard library only.

Run:  python server/app.py            (Windows: start.bat). Opens the browser on this PC; phones on the shop Wi-Fi use the
                                       address shown in Settings.
      python server/app.py --practice  a separate practice shop with sample data (its own folder, port and banner).

Security (local web apps are attacked through the browser, factory SEC-07): strict Content-Security-Policy, Host check
(DNS rebinding), Origin check on every write, HttpOnly SameSite=Strict session cookie, permission check on the server for
every action, audit of every write, small request bodies before login.
"""
import argparse
import gzip
import hashlib
import json
import logging
import logging.handlers
import mimetypes
import os
import shutil
import socket
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import afaccess  # noqa: E402
import aftelemetry  # noqa: E402
import assist  # noqa: E402
import auth as auth_mod  # noqa: E402
import backup  # noqa: E402
import catalog  # noqa: E402
import core  # noqa: E402
import ids  # noqa: E402
import licence  # noqa: E402
import money as cash  # noqa: E402
import reports  # noqa: E402
import sales  # noqa: E402
import stock  # noqa: E402
import support  # noqa: E402
from auth import AuthError, Forbidden  # noqa: E402
from core import Ctx, Problem  # noqa: E402
from db import Database, NewerData  # noqa: E402
from version import FROZEN, PRODUCT, PRODUCT_AR, ROOT, VERSION  # noqa: E402

WEB = os.path.join(ROOT, 'web')
COOKIE = 'store_session'
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
TYPES = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8',
         '.json': 'application/json', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.png': 'image/png',
         '.webmanifest': 'application/manifest+json', '.ico': 'image/x-icon'}
# writes allowed while the licence does not give full access: reading, keeping data safe, and getting a new code
OPEN_WRITES = {'/api/setup', '/api/login', '/api/logout', '/api/password', '/api/licence/activate', '/api/backup/now',
               '/api/shift/close', '/api/watch/review', '/api/support/save', '/api/support/ping',
               '/api/guide/progress', '/api/consent/decide', '/api/telemetry/events',
               '/api/telemetry/feedback', '/api/telemetry/feedback/preview'}
log = logging.getLogger('store')


class NotLoggedIn(Exception):
    pass


class LicenceLocked(Exception):
    pass


class App:
    """Everything the request handler needs: the database, the configuration, the folders."""

    def __init__(self, home, practice=False, port=None, host=None):
        self.home = home
        self.practice = practice
        os.makedirs(home, exist_ok=True)
        cfg_path = os.path.join(home, 'config.json')
        self.cfg = {'port': 8096 if not practice else 8097, 'host': '0.0.0.0', 'backup_hours': 4, 'keep_backups': 60,
                    'extra_backup_dirs': [], 'open_browser': True}
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding='utf-8') as f:
                self.cfg.update(json.load(f))
        else:
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(self.cfg, f, indent=2)
        if port:
            self.cfg['port'] = port
        if host:
            self.cfg['host'] = host
        self.data_dir = os.path.join(home, 'data')
        self.backup_dir = os.path.join(home, 'backups')
        self.db = Database(os.path.join(self.data_dir, 'store.db'), self.backup_dir)
        self.org_id = self._meta_id('org_id')
        self.branch_id = self._meta_id('branch_id')
        self.auth = auth_mod.Auth(self.db, self.org_id)
        self.assist = assist.Assist(self)
        self._static = {}
        self.started = time.time()
        self.failed_ips = {}
        self._errors = []

    def _meta_id(self, key):
        value = self.db.value('SELECT value FROM meta WHERE key = ?', key)
        if not value:
            value = ids.uuid7()
            self.db.run('INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)', key, value)
        return self.db.value('SELECT value FROM meta WHERE key = ?', key)

    def note_error(self):
        self._errors = [t for t in self._errors if time.time() - t < 86400][-200:] + [time.time()]

    def recent_errors(self):
        return len([t for t in self._errors if time.time() - t < 86400])

    def licence(self):
        if self.practice:
            return {'state': 'practice', 'full': True, 'device': licence.device(self.db), 'reason': ''}
        return licence.status(self.db)

    def setup_needed(self):
        return not self.auth.has_users()

    def setup(self, data, ip):
        """First run: the shop's name and its owner account. Also creates the shop and store places."""
        if not self.setup_needed():
            raise Problem('err.setupDone', 'The shop is already set up.', 409)
        with self.db.tx():
            user = self.auth.create(data.get('username'), data.get('full_name'), 'owner', data.get('password'))
            ctx = Ctx(self.db, user, auth_mod.effective_perms(user), ip, self.org_id, self.branch_id)
            core.set_setting(self.db, 'shop_name', core.text(data.get('shop_name'), 'shop_name', 80, True))
            for key in ('shop_phone', 'shop_address'):
                if data.get(key):
                    core.set_setting(self.db, key, core.text(data.get(key), key, 200))
            if not self.db.value('SELECT 1 FROM locations'):
                stock.save_location(ctx, {'name': 'المعرض', 'kind': 'shop'})
                stock.save_location(ctx, {'name': 'المخزن', 'kind': 'warehouse'})
                stock.save_location(ctx, {'name': 'تالف وصيانة', 'kind': 'damaged'})
            ctx.audit('setup', 'shop', self.org_id, {'shop': data.get('shop_name')})
        return user

    def backup_now(self, tag=''):
        item = backup.make(self.db, self.backup_dir, tag, self.cfg.get('extra_backup_dirs') or [])
        backup.prune(self.backup_dir, int(self.cfg.get('keep_backups', 60)))
        return item

    def restore(self, name):
        if not isinstance(name, str) or not backup.NAME.fullmatch(name):
            raise Problem('err.backupName', 'Choose a backup from the list.')
        path = os.path.join(self.backup_dir, name)
        if not os.path.exists(path) or not backup.check(path):
            raise Problem('err.backupBad', 'This backup cannot be read. Choose another one.')
        if backup.org_of(path) != self.org_id:
            raise Problem('err.backupOtherShop', 'This backup belongs to another shop.')
        self.backup_now('before-restore')
        target = self.db.path
        with self.db.lock:
            staged = target + '.restoring'  # copy beside the database, then swap in one step: a power cut never leaves half a file
            with open(path, 'rb') as src, open(staged, 'wb') as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            self.db.conn.close()
            try:
                for suffix in ('-wal', '-shm'):
                    try:
                        os.remove(target + suffix)
                    except FileNotFoundError:
                        pass
                os.replace(staged, target)
            finally:
                # A failed swap must not leave the live server with a closed connection.
                fresh = Database(target, self.backup_dir)
                self.db.conn = fresh.conn
                self.auth = auth_mod.Auth(self.db, self.org_id)
                if getattr(self, 'assist', None):
                    self.assist.rebind()

    def static(self, rel, gz):
        """Static file bytes (+ gzip copy) cached in memory, with an ETag from the content."""
        path = os.path.normpath(os.path.join(WEB, rel))
        if not path.startswith(WEB + os.sep) or not os.path.isfile(path):
            return None
        mtime = os.path.getmtime(path)
        hit = self._static.get(path)
        if not hit or hit['mtime'] != mtime:
            with open(path, 'rb') as f:
                body = f.read()
            ext = os.path.splitext(path)[1]
            hit = {'mtime': mtime, 'body': body, 'etag': '"' + hashlib.sha1(body).hexdigest()[:16] + '"',
                   'type': TYPES.get(ext) or mimetypes.guess_type(path)[0] or 'application/octet-stream',
                   'gz': gzip.compress(body, 6) if ext in ('.js', '.css', '.html', '.svg', '.json') and len(body) > 1024 else None}
            self._static[path] = hit
        return hit


APP = None


def _lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith('127.'))


class Handler(BaseHTTPRequestHandler):
    server_version = 'AlStore/' + VERSION
    protocol_version = 'HTTP/1.1'
    timeout = 60

    def log_message(self, fmt, *args):
        pass

    # ------------------------------------------------------------ plumbing
    @property
    def ip(self):
        return self.client_address[0]

    def host_ok(self):
        """DNS-rebinding guard: only names that really mean this PC."""
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0].strip('[]').lower()
        allowed = {'localhost', '127.0.0.1', '::1', socket.gethostname().lower()} | set(_lan_ips())
        return host in allowed or host.endswith('.local') or _is_private_ip(host)

    def origin_ok(self):
        origin = self.headers.get('Origin')
        if not origin:
            return self.headers.get('Sec-Fetch-Site') in (None, 'same-origin', 'none')
        return urlparse(origin).netloc.lower() == (self.headers.get('Host') or '').lower()

    def token(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == COOKIE:
                return v
        return ''

    def send(self, code, body=b'', ctype='application/json', headers=None):
        if body is None:
            body = b'null'
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        if ctype == 'application/json' and len(body) > 2048 and 'gzip' in (self.headers.get('Accept-Encoding') or ''):
            body = gzip.compress(body, 5)
            headers = dict(headers or {}, **{'Content-Encoding': 'gzip'})
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Permissions-Policy', 'camera=(self), microphone=(), geolocation=()')
        if ctype.startswith('text/html'):
            self.send_header('Content-Security-Policy', CSP)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if self.path.startswith('/api/'):
            self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def body(self, limit):
        raw = self.headers.get('Content-Length') or '0'
        if not raw.isdigit() or int(raw) > limit:
            self.close_connection = True
            raise Problem('err.tooLarge', 'The request is too large.', 413)
        n = int(raw)
        data = self.rfile.read(n) if n else b''
        parsed = json.loads(data.decode('utf-8')) if data else {}
        if not isinstance(parsed, dict):
            raise Problem('err.badRequest', 'The request is not understood.', 400)
        return parsed

    def user(self, touch=True):
        u = APP.auth.session(self.token(), touch)
        if not u:
            raise NotLoggedIn()
        return u

    def ctx(self, u):
        return Ctx(APP.db, u, auth_mod.effective_perms(u), self.ip, APP.org_id, APP.branch_id)

    def safely(self, fn):
        u = None
        try:
            fn()
        except NotLoggedIn:
            self.send(401, {'error': 'Please sign in.', 'key': 'err.signIn', 'login': True},
                      headers={'Set-Cookie': f'{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'})
        except LicenceLocked:
            self.send(402, {'error': 'The licence does not allow changes now.', 'key': 'err.licence', 'licence': APP.licence()})
        except Forbidden as e:
            try:
                u = APP.auth.session(self.token(), False)
                if u:
                    APP.db.insert('audit', {'id': ids.uuid7(), 'at': ids.iso(), 'user_id': u['id'], 'user_name': u['full_name'],
                                            'ip': self.ip, 'action': 'denied', 'entity': self.path.split('?')[0], 'entity_id': '',
                                            'detail': json.dumps({'perm': e.perm})})
            except Exception:
                pass
            self.send(403, {'error': str(e), 'key': 'err.forbidden', 'vars': {'perm': e.perm}})
        except AuthError as e:
            self.send(400, {'error': str(e), 'key': e.key, 'vars': e.vars})
        except Problem as e:
            self.send(e.status, {'error': str(e), 'key': e.key, 'vars': e.vars})
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send(400, {'error': 'Bad request.', 'key': 'err.badRequest'})
        except (ValueError, OverflowError):  # a number or date in the request that cannot be read: calm 400, kept in the log
            log.warning('BAD INPUT %s\n%s', self.path, traceback.format_exc())
            self.send(400, {'error': 'A number or date in the request is not valid.', 'key': 'err.badRequest'})
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as e:  # a bug: log the details on this PC, show a calm message
            log.error('ERROR %s\n%s', self.path, traceback.format_exc())
            APP.note_error()
            try:  # type and fingerprint only; never the message. Consent still applies inside capture.
                APP.assist.capture(e, self.path.split('?', 1)[0])
            except Exception:
                log.warning('telemetry capture failed', exc_info=True)
            self.send(500, {'error': f'Unexpected problem: {e.__class__.__name__}', 'key': 'err.server'})

    # ------------------------------------------------------------ routing
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.host_ok():
            return self.send(421, {'error': 'Unknown host'})
        url = urlparse(self.path)
        if url.path.startswith('/guide/'):
            return self.safely(lambda: self.guide_file(url.path))
        if url.path.startswith('/api/'):
            qs = {k: v[-1] for k, v in parse_qs(url.query).items()}
            return self.safely(lambda: self.api_get(url.path, qs))
        return self.serve(url.path)

    def do_POST(self):
        if not self.host_ok() or not self.origin_ok():
            self.close_connection = True  # the body is not read: never reuse this connection
            return self.send(403, {'error': 'Cross-site request refused', 'key': 'err.origin'}, headers={'Connection': 'close'})
        url = urlparse(self.path)
        self.safely(lambda: self.api_post(url.path))

    def serve(self, path):
        if path in ('/', '/index.html') or not os.path.splitext(path)[1]:
            rel = 'index.html'
        else:
            rel = path.lstrip('/')
        hit = APP.static(rel, True)
        if not hit:
            return self.send(404, b'Not found', 'text/plain')
        if self.headers.get('If-None-Match') == hit['etag']:
            self.send_response(304)
            self.send_header('ETag', hit['etag'])
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        headers = {'ETag': hit['etag'],
                   'Cache-Control': 'public, max-age=31536000, immutable' if rel.startswith('fonts/') else 'no-cache'}
        body = hit['body']
        if hit['gz'] and 'gzip' in (self.headers.get('Accept-Encoding') or ''):
            body, headers['Content-Encoding'] = hit['gz'], 'gzip'
            headers['Vary'] = 'Accept-Encoding'
        self.send(200, body, hit['type'], headers)

    # ------------------------------------------------------------ GET
    def api_get(self, path, qs):
        db = APP.db
        if path == '/api/boot':
            u = APP.auth.session(self.token(), False)
            cfg = core.settings(db)
            return self.send(200, {'product': PRODUCT, 'product_ar': PRODUCT_AR, 'version': VERSION, 'practice': APP.practice,
                                   'setup': APP.setup_needed(), 'shop_name': cfg['shop_name'], 'licence': APP.licence(),
                                   'user': self.me(u) if u else None, 'today': ids.local_day()})
        u = self.user()
        ctx = self.ctx(u)
        can_cost = ctx.can('cost.view')
        d = None
        if path == '/api/me':
            d = self.me(u)
        elif path == '/api/home':
            d = reports.home(db, ctx, APP.licence(), backup.age_hours(APP.backup_dir))
        elif path == '/api/lookups':
            cfg = core.settings(db)
            d = {**catalog.lookups(db), 'settings': {k: cfg[k] for k in (
                'shop_name', 'shop_phone', 'shop_address', 'receipt_footer', 'receipt_width', 'return_days', 'defect_days',
                'tax_rate_pct', 'wallet_number', 'min_down_payment_pct', 'instalment_markup_pct', 'max_instalment_months',
                'finance_providers', 'expense_categories', 'tax_number')}, 'pay_methods': core.pay_methods(db),
                 'users': db.all('SELECT id, full_name, role FROM users WHERE active = 1 ORDER BY full_name')}
        elif path == '/api/products':
            ctx.need_any('products.view', 'stock.view')
            d = catalog.search(db, qs.get('q', ''), qint(qs, 'limit', 200, 1, 1000), True, qs.get('location_id'),
                               qs.get('hidden') == '1', {'category_id': qs.get('category_id'), 'brand_id': qs.get('brand_id')})
            if can_cost:
                for r in d['items']:
                    r['avg_cost'] = catalog.current_cost(db, r['id'])['avg_cost']
        elif path == '/api/product':
            ctx.need_any('products.view', 'stock.view')
            d = stock.detail(db, qs.get('id'), can_cost)
        elif path == '/api/pos/search':
            ctx.need('pos.sell')
            d = catalog.search(db, qs.get('q', ''), 12, True, qs.get('location_id'))
        elif path == '/api/serials':
            ctx.need_any('pos.sell', 'products.view', 'stock.view')
            d = stock.serials_in_stock(db, qs.get('product_id'), qs.get('location_id'))
        elif path == '/api/sales':
            d = sales.sales_list(db, ctx, qs.get('from'), qs.get('to'), qs.get('q', ''), qs.get('user_id'))
        elif path == '/api/sale':
            s = sales.sale_view(db, qs.get('id'), can_cost)
            if s['by_user'] != u['id'] and not ctx.can('sales.view_all') and not ctx.can('sales.return'):
                raise Forbidden('sales.view_all')
            d = s
        elif path == '/api/return':
            d = sales.return_view(db, qs.get('id'))
        elif path == '/api/warranty':
            d = sales.warranty(db, qs.get('serial'))
        elif path == '/api/customers':
            ctx.need_any('customers.view', 'pos.sell')  # the counter picks the customer of a credit sale
            d = cash.customers_list(db, qs.get('q', ''), qs.get('only', 'all'))
        elif path == '/api/customer':
            ctx.need('customers.view')
            d = cash.customer_view(db, qs.get('id'), ctx.can('customers.private'))
        elif path == '/api/instalments':
            ctx.need('customers.view')
            d = {'due': cash.instalments_due(db), 'upcoming': cash.instalments_upcoming(db, 7)}
        elif path == '/api/suppliers':
            ctx.need_any('stock.receive', 'suppliers.pay')
            d = cash.suppliers_list(db)
        elif path == '/api/supplier':
            ctx.need_any('stock.receive', 'suppliers.pay')
            d = cash.supplier_view(db, qs.get('id'))
        elif path == '/api/purchases':
            ctx.need('stock.receive')
            d = db.all('SELECT p.id, p.number, p.at, p.total, p.supplier_ref, s.name AS supplier, l.name AS place, u.full_name AS by_name, '
                       '(SELECT COUNT(*) FROM purchase_lines x WHERE x.purchase_id = p.id) AS lines FROM purchases p '
                       'LEFT JOIN suppliers s ON s.id = p.supplier_id JOIN locations l ON l.id = p.location_id '
                       'JOIN users u ON u.id = p.by_user ORDER BY p.at DESC LIMIT 200')
            if not can_cost:
                for r in d:
                    r.pop('total')
        elif path == '/api/purchase':
            ctx.need('stock.receive')
            d = db.one('SELECT p.*, s.name AS supplier, l.name AS place FROM purchases p LEFT JOIN suppliers s ON s.id = p.supplier_id '
                       'JOIN locations l ON l.id = p.location_id WHERE p.id = ?', qs.get('id'))
            if not d:
                raise core.NotFound('purchase')
            d['lines'] = db.all('SELECT pl.*, pr.name, pr.sku FROM purchase_lines pl JOIN products pr ON pr.id = pl.product_id '
                                'WHERE purchase_id = ?', d['id'])
        elif path == '/api/stock':
            ctx.need('stock.view')
            d = stock.overview(db, can_cost, qs.get('q', ''), qs.get('only', 'all'), qs.get('location_id'))
        elif path == '/api/stock/value':
            ctx.need('cost.view')
            d = {'value': stock.stock_value(db), 'slow': stock.slow_movers(db, qint(qs, 'days', 60, 1, 3650), 30)}
        elif path == '/api/counts':
            ctx.need('stock.view')
            d = db.all('SELECT c.*, l.name AS place, u.full_name AS by_name FROM counts c JOIN locations l ON l.id = c.location_id '
                       'JOIN users u ON u.id = c.started_by ORDER BY c.started_at DESC LIMIT 50')
        elif path == '/api/count':
            ctx.need('stock.view')
            d = stock.count_view(db, qs.get('id'), can_cost)
        elif path == '/api/transfers':
            ctx.need('stock.view')
            d = db.all('SELECT t.*, a.name AS from_name, b.name AS to_name, u.full_name AS by_name FROM transfers t '
                       'JOIN locations a ON a.id = t.from_id JOIN locations b ON b.id = t.to_id JOIN users u ON u.id = t.by_user '
                       'ORDER BY t.at DESC LIMIT 100')
        elif path == '/api/shift':
            s = cash.open_shift_of(db, u['id'])
            d = cash.shift_summary(db, s['id']) if s else None
        elif path == '/api/shifts':
            where = '' if ctx.can('shifts.manage') else 'WHERE s.user_id = ?'
            args = () if ctx.can('shifts.manage') else (u['id'],)
            d = db.all('SELECT s.*, u.full_name AS user_name, (SELECT COALESCE(SUM(amount), 0) FROM cash_moves c WHERE '
                       "c.account = 'drawer' AND c.shift_id = s.id) AS drawer_now FROM shifts s JOIN users u ON u.id = s.user_id "
                       f'{where} ORDER BY s.opened_at DESC LIMIT 100', *args)
        elif path == '/api/shift/view':
            s = cash.shift_summary(db, qs.get('id'))
            if s['user_id'] != u['id']:
                ctx.need('shifts.manage')
            d = s
        elif path == '/api/safe':
            ctx.need('cash.safe')
            d = {'balance': cash.safe_balance(db), 'finance_due': cash.finance_due(db),
                 'moves': db.all("SELECT c.*, u.full_name AS by_name, (SELECT 1 FROM cash_moves r WHERE r.reverses = c.id) AS reversed "
                                 "FROM cash_moves c JOIN users u ON u.id = c.by_user WHERE c.account = 'safe' ORDER BY c.at DESC LIMIT 200")}
        elif path == '/api/expenses':
            ctx.need('cash.expense')
            d = db.all("SELECT c.*, u.full_name AS by_name, (SELECT 1 FROM cash_moves r WHERE r.reverses = c.id) AS reversed FROM cash_moves c "
                       "JOIN users u ON u.id = c.by_user WHERE c.kind = 'expense' ORDER BY c.at DESC LIMIT 200")
        elif path == '/api/reports':
            ctx.need('reports.view')
            f, t = qs.get('from') or ids.local_day(), qs.get('to') or ids.local_day()
            d = {'summary': reports.summary(db, f, t, can_cost), 'series': reports.daily_series(db, qint(qs, 'days', 30, 1, 366), can_cost),
                 'by_category': reports.by_group(db, f, t, 'category', can_cost), 'by_brand': reports.by_group(db, f, t, 'brand', can_cost),
                 'by_product': reports.by_group(db, f, t, 'product', can_cost, 30), 'by_user': reports.by_group(db, f, t, 'user', can_cost),
                 'year': reports.year_turnover(db), 'balances': reports.balances(db)}
            if can_cost:
                d['stock_value'] = stock.stock_value(db)
                d['slow'] = stock.slow_movers(db, 60, 15)
        elif path == '/api/watch':
            ctx.need('watch.view')
            d = reports.watch(db, qint(qs, 'days', 7, 1, 400), qs.get('all') == '1')
        elif path == '/api/audit':
            ctx.need('audit.view')
            d = db.all('SELECT * FROM audit ORDER BY at DESC LIMIT ?', qint(qs, 'limit', 300, 1, 2000))
        elif path == '/api/users':
            ctx.need('users.manage')
            d = {'users': [auth_mod.public(x) for x in db.all('SELECT * FROM users ORDER BY active DESC, full_name')],
                 'profiles': APP.auth.profiles(), 'permissions': auth_mod.perm_list(), 'groups': auth_mod.GROUPS,
                 'locked': auth_mod.LOCKED}
        elif path == '/api/settings':
            ctx.need('settings.edit')
            d = {'settings': core.settings(db), 'licence': APP.licence(), 'backups': backup.listing(APP.backup_dir)[:30],
                 'backup_age_hours': backup.age_hours(APP.backup_dir), 'extra_backup_dirs': APP.cfg.get('extra_backup_dirs') or [],
                 'addresses': [f'http://{ip}:{APP.cfg["port"]}' for ip in _lan_ips()], 'version': VERSION,
                 'locations': db.all('SELECT * FROM locations ORDER BY active DESC, kind DESC, name')}
        elif path == '/api/licence':
            d = APP.licence()
        elif path == '/api/support':
            ctx.need('settings.edit')
            d = support.public(APP.home)
        elif path == '/api/guide/state':
            d = APP.assist.guide_state(u)
        elif path == '/api/consent/status':
            d = APP.assist.consent_status(u)
        elif path == '/api/consent/prompt':
            d = APP.assist.prompt_for(u, qs.get('lang') or 'ar')
        elif path == '/api/telemetry/sent':
            d = APP.assist.sent_public(u)
        elif path == '/api/telemetry/config':
            ctx.need('settings.edit')
            d = APP.assist.receiver_public()
        elif path == '/api/export':
            ctx.need('settings.edit')
            body = backup.export_zip(db)
            ctx.audit('export', 'shop', '', {'bytes': len(body)})
            name = f'al-store-export-{ids.local_day()}.zip'
            return self.send(200, body, 'application/zip', {'Content-Disposition': f'attachment; filename="{name}"'})
        else:
            raise Problem('err.notFound', 'Unknown address.', 404)
        self.send(200, d)

    def me(self, u):
        if not u:
            return None
        shift = cash.open_shift_of(APP.db, u['id'])
        return {**auth_mod.public(u), 'shift_id': shift['id'] if shift else None}

    # ------------------------------------------------------------ POST
    def api_post(self, path):
        db = APP.db
        if path == '/api/setup':
            data = self.body(65536)
            user = APP.setup(data, self.ip)
            token = APP.auth.start_session(user, self.ip)
            return self.send(200, {'ok': True}, headers=self.cookie(token))
        if path == '/api/login':
            data = self.body(65536)
            if self.too_many(self.ip):
                raise Problem('auth.err.locked', 'Too many wrong tries. Try again after a few minutes.', 429)
            try:
                user = APP.auth.verify(data.get('username'), data.get('password'))
            except AuthError:
                self.too_many(self.ip, add=True)
                raise
            token = APP.auth.start_session(user, self.ip)
            with db.tx():
                Ctx(db, user, [], self.ip, APP.org_id, APP.branch_id).audit('login')
            return self.send(200, {'ok': True, 'user': self.me(user)}, headers=self.cookie(token))
        if path == '/api/logout':
            self.body(65536)
            APP.auth.end_session(self.token())
            return self.send(200, {'ok': True}, headers={'Set-Cookie': f'{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'})
        u = self.user()
        ctx = self.ctx(u)
        data = self.body(2 * 1048576)
        if path == '/api/backup/now':  # outside a transaction: SQLite cannot copy a database while it is being written
            ctx.need('settings.edit')
            item = APP.backup_now('manual')
            with APP.db.tx():
                ctx.audit('backup', 'backup', item['name'])
            self._track('/api/backup/now', u)
            return self.send(200, item)
        if path == '/api/support/ping':  # network call: never while the database is locked for a write
            ctx.need('settings.edit')
            return self.send(200, support.send(APP))
        if path == '/api/backup/restore':  # outside a transaction: the restore swaps the database file
            ctx.need('settings.edit')
            APP.auth.verify(u['username'], data.get('password'))  # step-up: the owner types the password again
            APP.restore(data.get('name'))
            with APP.db.tx():
                self.ctx(u).audit('backup.restore', 'backup', data.get('name'))
            return self.send(200, {'ok': True})
        if path in ('/api/guide/progress', '/api/consent/decide', '/api/telemetry/events',
                    '/api/telemetry/feedback', '/api/telemetry/feedback/preview'):
            return self.assist_post(path, u, data)
        if path == '/api/telemetry/config':
            ctx.need('settings.edit')
            # Withdrawing remote help remains available even when the licence is locked.
            disabling = not data.get('url') or data.get('clear_token') is True
            if not disabling and not APP.licence()['full']:
                raise LicenceLocked()
            return self.send(200, APP.assist.save_receiver(data, u))
        if path not in OPEN_WRITES and not APP.licence()['full']:
            raise LicenceLocked()
        if isinstance(data.get('approval'), dict):  # checked outside the transaction so a wrong password is counted
            ctx.approver = APP.auth.verify(data['approval'].get('username'), data['approval'].get('password'))
        with db.tx():
            out = self.write(path, ctx, u, data)
        self._track(path, u)
        self.send(200, out if out is not None else {'ok': True})

    def write(self, path, ctx, u, data):
        db = APP.db
        if path == '/api/password':
            APP.auth.verify(u['username'], data.get('old'))
            APP.auth.update(u['id'], {'password': data.get('new')})
            ctx.audit('password.change', 'user', u['id'])
            return {'ok': True, 'login': True}
        if path == '/api/licence/activate':
            ctx.need('settings.edit')
            try:
                st = licence.activate(db, data.get('code', ''))
            except ValueError as e:
                raise Problem('lic.err.' + str(e), 'This code does not work on this PC.', 400, reason=str(e))
            ctx.audit('licence.activate', 'licence', st.get('serial') or '', {'state': st['state'], 'last_day': st.get('last_day')})
            return st
        if path == '/api/product/save':
            pid = catalog.save_product(ctx, data)
            return stock.detail(db, pid, ctx.can('cost.view'))
        if path == '/api/product/active':
            catalog.set_active(ctx, data.get('id'), data.get('active'))
            return {'ok': True}
        if path == '/api/product/place':
            ctx.need('stock.transfer')
            catalog.set_place(ctx, data.get('product_id'), data.get('location_id'), data.get('shelf', ''))
            ctx.audit('product.place', 'product', data.get('product_id'), {'shelf': data.get('shelf')})
            return {'ok': True}
        if path == '/api/prices/bulk':
            return catalog.bulk_price(ctx, data, bool(data.get('apply')))
        if path == '/api/location/save':
            return {'id': stock.save_location(ctx, data)}
        if path == '/api/pos/quote':
            ctx.need('pos.sell')
            return sales.quote(ctx, data)
        if path == '/api/pos/sell':
            return sales.sell(ctx, data)
        if path == '/api/return':
            return sales.take_return(ctx, data)
        if path == '/api/purchase':
            return stock.receive(ctx, data)
        if path == '/api/transfer':
            return stock.transfer(ctx, data)
        if path == '/api/count/start':
            return {'id': stock.start_count(ctx, data.get('location_id'), data.get('note', ''))}
        if path == '/api/count/line':
            stock.count_line(ctx, data.get('count_id'), data.get('product_id'), data.get('counted'))
            return {'ok': True}
        if path == '/api/count/close':
            return stock.close_count(ctx, data.get('count_id'), data.get('reason'))
        if path == '/api/shift/open':
            return {'id': cash.open_shift(ctx, data.get('opening_float', 0))}
        if path == '/api/shift/close':
            return cash.close_shift(ctx, data.get('shift_id'), data.get('counted'), data.get('note', ''))
        if path == '/api/cash/expense':
            return cash.expense(ctx, data)
        if path == '/api/cash/safe':
            return cash.safe_move(ctx, data)
        if path == '/api/cash/reverse':
            return cash.reverse_cash(ctx, data.get('id'), data.get('reason'))
        if path == '/api/customer/save':
            return {'id': cash.save_customer(ctx, data)}
        if path == '/api/collect':
            return cash.collect(ctx, data)
        if path == '/api/collect/reverse':
            return cash.reverse_collection(ctx, data.get('id'), data.get('reason'))
        if path == '/api/supplier/save':
            return {'id': cash.save_supplier(ctx, data)}
        if path == '/api/supplier/pay':
            return cash.pay_supplier(ctx, data)
        if path == '/api/finance/settle':
            return cash.finance_settle(ctx, data)
        if path == '/api/support/save':
            ctx.need('settings.edit')
            support.save(APP.home, data.get('enabled'), data.get('url'), data.get('token'))
            ctx.audit('support.save', 'support', '', {'enabled': bool(data.get('enabled'))})  # the address and code are never logged
            return support.public(APP.home)
        if path == '/api/watch/review':
            reports.review(ctx, data.get('key'), data.get('note'))
            return {'ok': True}
        if path == '/api/user/save':
            ctx.need('users.manage')
            if data.get('id'):
                old = APP.auth.get(data['id']) if isinstance(data['id'], str) else None
                user = APP.auth.update(data['id'], data, ctx.uid)
                before, after = auth_mod.public(old), auth_mod.public(user)
                ctx.audit('user.edit', 'user', data['id'], {  # who changed what: the ticks added and removed, never a password
                    'before': {k: before[k] for k in ('role', 'active', 'max_discount_pct')},
                    'after': {k: after[k] for k in ('role', 'active', 'max_discount_pct')},
                    **afaccess.perm_diff(before['perms'], after['perms']), 'password': bool(data.get('password'))})
            else:
                user = APP.auth.create(data.get('username'), data.get('full_name'), data.get('role'), data.get('password'),
                                       data.get('max_discount_pct'), data.get('extra_perms') or (), data.get('denied_perms') or (),
                                       data['perms'] if isinstance(data.get('perms'), list) else None)
                ctx.audit('user.add', 'user', user['id'], {'username': user['username'], 'role': user['role'],
                                                           'perms': auth_mod.effective_perms(user)})
            return auth_mod.public(user)
        if path == '/api/profile/save':
            ctx.need('users.manage')
            prof, before, n = APP.auth.save_profile(data, ctx.uid)
            ctx.audit('profile.save', 'profile', prof['id'], {'name': prof['name'] or prof['id'], 'people_updated': n,
                                                              **afaccess.perm_diff(before['perms'] if before else [], prof['perms'])})
            return {'profile': prof, 'updated': n}
        if path == '/api/profile/delete':
            ctx.need('users.manage')
            prof, n = APP.auth.delete_profile(data.get('id'))
            ctx.audit('profile.delete', 'profile', prof['id'], {'name': prof['name'] or prof['id'], 'people_kept_their_ticks': n})
            return {'ok': True, 'people': n}
        if path == '/api/settings/save':
            ctx.need('settings.edit')
            changed = {}
            for key, value in (data.get('settings') if isinstance(data.get('settings'), dict) else {}).items():
                core.set_setting(db, key, value)
                changed[key] = value
            ctx.audit('settings', 'shop', '', changed)
            return core.settings(db)
        raise Problem('err.notFound', 'Unknown address.', 404)

    def guide_file(self, path):
        """Guide JSON is outside web/ so the sign-in screen can load it. Only the three known names."""
        name = path[len('/guide/'):]
        if name not in ('catalogue.json', 'ar.json', 'en.json') or '/' in name or '\\' in name:
            raise Problem('err.notFound', 'Unknown address.', 404)
        full = os.path.join(ROOT, 'guide', name)
        if not os.path.isfile(full):
            raise Problem('err.notFound', 'Unknown address.', 404)
        with open(full, 'rb') as f:
            body = f.read()
        self.send(200, body, 'application/json; charset=utf-8')

    def assist_post(self, path, u, data):
        try:
            if path == '/api/guide/progress':
                out = APP.assist.save_progress(u, data.get('update') if isinstance(data, dict) else None)
            elif path == '/api/consent/decide':
                out = APP.assist.decide(u, data if isinstance(data, dict) else {})
            elif path == '/api/telemetry/events':
                out = APP.assist.browser_events(u, data.get('events') if isinstance(data, dict) else None)
            elif path == '/api/telemetry/feedback/preview':
                out = APP.assist.preview(data if isinstance(data, dict) else {})
            else:
                out = APP.assist.feedback(u, data if isinstance(data, dict) else {})
        except aftelemetry.PrivacyError as e:
            return self.send(400, {'error': str(e), 'key': 'err.badRequest'})
        except ValueError as e:
            return self.send(400, {'error': str(e), 'key': 'err.badRequest'})
        self.send(200, out if out is not None else {'ok': True})

    def _track(self, path, u):
        spec = assist.ACTIONS.get(path)
        if not spec or not u:
            return
        try:
            APP.assist.note_action(u, spec[0], spec[1])
        except Exception:
            log.warning('telemetry note failed', exc_info=True)

    def cookie(self, token):
        return {'Set-Cookie': f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict'}

    def too_many(self, ip, add=False):
        now = time.time()
        hits = [t for t in APP.failed_ips.get(ip, []) if now - t < 900]
        if add:
            hits.append(now)
        APP.failed_ips[ip] = hits
        return len(hits) >= 20


def qint(qs, name, default, low, high):
    """A whole number from the address bar, kept inside sane bounds (a huge `days` must not hang the shop PC)."""
    try:
        value = int(qs.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _is_private_ip(host):
    import ipaddress
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def default_home(practice):
    if os.environ.get('STORE_HOME'):
        return os.environ['STORE_HOME']
    if os.name == 'nt' and os.environ.get('PROGRAMDATA') and FROZEN:
        base = os.path.join(os.environ['PROGRAMDATA'], 'Al-Store')
    else:
        base = os.path.join(ROOT, 'shop-data')
    return base + ('-practice' if practice else '')


def build(home, practice=False, port=None, host=None):
    global APP
    APP = App(home, practice, port, host)
    if practice and not APP.auth.has_users():
        import sample
        sample.load(APP)
    return APP


def serve(app, open_browser=None):
    httpd = ThreadingHTTPServer((app.cfg['host'], int(app.cfg['port'])), Handler)
    httpd.daemon_threads = True

    def keep_backing_up():
        while True:
            try:
                if app.auth.has_users():
                    age = backup.age_hours(app.backup_dir)
                    if age is None or age >= float(app.cfg.get('backup_hours', 4)):
                        app.backup_now()
            except Exception:
                log.error('backup failed\n%s', traceback.format_exc())
            time.sleep(600)

    threading.Thread(target=keep_backing_up, daemon=True).start()

    def keep_reporting():
        """Heartbeat and the optional send. Never on a request, and never while a shop write is open."""
        while True:
            try:
                app.assist.heartbeat()
                app.assist.flush_remote()
            except Exception:
                log.error('telemetry\n%s', traceback.format_exc())
            time.sleep(300)

    threading.Thread(target=keep_reporting, daemon=True).start()
    if not app.practice:
        threading.Thread(target=support.loop, args=(app,), daemon=True).start()
    url = f'http://127.0.0.1:{app.cfg["port"]}/'
    say(f'{PRODUCT_AR} {VERSION}{" (تدريب)" if app.practice else ""} يعمل الآن: {url}')
    for ip in _lan_ips():
        say(f'  من الموبايل على نفس الشبكة: http://{ip}:{app.cfg["port"]}/')
    if open_browser if open_browser is not None else app.cfg.get('open_browser'):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def say(text):
    """Print for the person at the console. A Windows console or redirected output may not speak Arabic, and a program started
    by a double click may have no console at all: neither may ever stop the shop's server."""
    try:
        print(text, flush=True)
    except (UnicodeEncodeError, AttributeError, OSError, ValueError):
        try:
            print(text.encode('ascii', 'replace').decode('ascii'), flush=True)
        except Exception:
            pass


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass
    parser = argparse.ArgumentParser(prog='al-store')
    parser.add_argument('--practice', action='store_true', help='practice shop with sample data')
    parser.add_argument('--home', help='folder for data, backups and config')
    parser.add_argument('--port', type=int)
    parser.add_argument('--host')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--version', action='store_true')
    args = parser.parse_args(argv)
    if args.version:
        say(f'{PRODUCT} {VERSION}')
        return 0
    home = args.home or default_home(args.practice)
    os.makedirs(home, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(os.path.join(home, 'store.log'), maxBytes=2_000_000, backupCount=5, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    try:
        app = build(home, args.practice, args.port, args.host)
    except NewerData:
        say('هذه البيانات من نسخة أحدث من البرنامج. ثبّت النسخة الأحدث.')
        return 2
    serve(app, False if args.no_browser else None)
    return 0


if __name__ == '__main__':
    sys.exit(main())
