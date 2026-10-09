"""In-app guide, consent and consented telemetry.

The three factory packages (afguide, afconsent, aftelemetry) are vendored and not modified here.
This module is the product glue: live states, the two guide routes' data, the consent card,
and a local outbox that stays on this PC unless a receiver address and token are both set.
"""
import json
import copy
import gzip
import hashlib
import hmac
import os
import re
import secrets
import shutil
import threading
import time
from urllib.parse import urlsplit
import urllib.request
import urllib.error

import afconsent
import afguide
import aftelemetry
import auth as auth_mod
from version import DEVELOPER, PRODUCT_ID, ROOT, VERSION

_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:\-/]{0,79}$')
_LONG = re.compile(r'\d{8,}')
BUILTINS = ('owner', 'manager', 'cashier', 'storekeeper')
PAGES = {'home', 'pos', 'sales', 'customers', 'products', 'stock', 'receive', 'cash',
         'watch', 'reports', 'settings', 'help', 'signin', 'setup'}
# confirmed actions worth a count. Ids only: never an amount, a name or a record.
ACTIONS = {
    '/api/pos/sell': ('sale.pay', 'pos'),
    '/api/shift/open': ('shift.open', 'cash'),
    '/api/shift/close': ('shift.close', 'cash'),
    '/api/cash/expense': ('cash.expense', 'cash'),
    '/api/cash/safe': ('safe.move', 'cash'),
    '/api/return': ('sale.return', 'sales'),
    '/api/collect': ('instalment.collect', 'customers'),
    '/api/backup/now': ('backup.now', 'settings'),
    '/api/user/save': ('user.save', 'settings'),
    '/api/purchase': ('receive.save', 'receive'),
}


def guide_role(role, perms):
    """Map a profile to the closest built-in course. can() still hides guides the person cannot do."""
    if role in BUILTINS:
        return role
    have = set(perms or ())
    if 'settings.edit' in have or 'users.manage' in have:
        return 'owner'
    if 'reports.view' in have or 'cash.safe' in have or 'shifts.manage' in have:
        return 'manager'
    if 'pos.sell' in have:
        return 'cashier'
    if 'stock.view' in have or 'products.view' in have or 'stock.receive' in have:
        return 'storekeeper'
    return 'cashier'


def _machine_id(value):
    if isinstance(value, str) and _ID.fullmatch(value) and not _LONG.search(value) and '@' not in value:
        return value
    return None


def _report_fields(data):
    """Kind, text and contact must be text. A junk body (a number, a list) is a bad request, not a crash."""
    data = data if isinstance(data, dict) else {}
    kind = data.get('kind')
    text = data.get('text')
    contact = data.get('contact')
    return data, (
        kind if isinstance(kind, str) and kind else 'problem',
        text if isinstance(text, str) else '',
        contact if isinstance(contact, str) and contact else 'none',
    )


class Assist:
    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.closed = False
        self.catalogue, self.texts = afguide.load_dir(os.path.join(ROOT, 'guide'))
        self._ensure_cfg()
        self.consent = afconsent.Consent(app.db.conn, on_change=self._on_consent)
        # Product privacy is stricter than the factory's optional free-text feedback.
        tax = copy.deepcopy(aftelemetry.TAXONOMY)
        for name, spec in tax['types'].items():
            if name.startswith('fb.'):
                spec['data']['text'] = {'type': 'id'}
        self.tel = aftelemetry.Telemetry(
            os.path.join(app.home, 'telemetry.db'), self.app.cfg['telemetry_install_id'],
            node='shop', product=PRODUCT_ID, version=VERSION,
            env='practice' if app.practice else 'real', secret=self.app.cfg['telemetry_secret'],
            consent=self.consent, taxonomy=tax)
        with self.app.db.lock, self.lock:
            self._prune_pending()

    def close(self):
        with self.send_lock, self.lock:
            if not self.closed:
                self.closed = True
                self.tel.close()

    def rebind(self):
        """After a restore the shop connection is a new object. The outbox file is not part of that swap."""
        with self.app.db.lock, self.lock:
            self.consent.db = self.app.db.conn
            self._prune_pending()

    # ---------------------------------------------------------------- config (local only)
    def _cfg_path(self):
        return os.path.join(self.app.home, 'config.json')

    def _write_cfg(self):
        staged = self._cfg_path() + '.tmp'
        with open(staged, 'w', encoding='utf-8') as f:
            json.dump(self.app.cfg, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(staged, self._cfg_path())

    def _ensure_cfg(self):
        """A stable local id and HMAC secret. The receiver address and token stay empty, so nothing is sent."""
        cfg = self.app.cfg
        changed = False
        if not isinstance(cfg.get('telemetry_secret'), str) or len(cfg.get('telemetry_secret') or '') < 16:
            cfg['telemetry_secret'] = secrets.token_hex(32)
            changed = True
        ident = cfg.get('telemetry_install_id')
        if not isinstance(ident, str) or not ident.strip() or len(ident) > 80 or any(ch.isspace() for ch in ident):
            cfg['telemetry_install_id'] = aftelemetry.new_identity()[0]
            changed = True
        for key in ('telemetry_url', 'telemetry_token'):
            if key not in cfg:
                cfg[key] = ''
                changed = True
        if changed:
            self._write_cfg()

    def receiver_public(self):
        with self.lock:
            url = self.app.cfg.get('telemetry_url')
            token = self.app.cfg.get('telemetry_token')
            return {'url': url.strip() if isinstance(url, str) else '',
                    'has_token': bool(isinstance(token, str) and token.strip()),
                    'sending': bool(self._receiver())}

    @staticmethod
    def _valid_url(url):
        if not isinstance(url, str) or any(ch.isspace() or ord(ch) < 32 for ch in url):
            return False
        try:
            parsed = urlsplit(url)
            port = parsed.port
            return bool(parsed.hostname and parsed.username is None and parsed.password is None
                        and not parsed.fragment and (port is None or 1 <= port <= 65535)
                        and (parsed.scheme == 'https' or
                             (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost'))))
        except ValueError:
            return False

    def save_receiver(self, data, user=None):
        """Owner-only. The token is stored and never returned or written to the audit."""
        from core import Problem
        if not isinstance(data.get('url', ''), str) or not isinstance(data.get('token', ''), str) or \
                not isinstance(data.get('clear_token', False), bool):
            raise Problem('err.badRequest', 'Invalid receiver settings.')
        url = data.get('url', '')
        if any(ord(ch) < 32 for ch in url):
            raise Problem('err.badRequest', 'Invalid receiver address.')
        url = url.strip()
        if url and not self._valid_url(url):
            raise Problem('err.badRequest', 'The receiver address must be https, or this PC only.')
        token = data.get('token')
        if isinstance(token, str) and (len(token) > 4096 or any(ord(ch) < 32 or ord(ch) > 126 for ch in token)):
            raise Problem('err.badRequest', 'Invalid receiver token.')
        with self.app.db.lock, self.lock:
            old = dict(self.app.cfg)
            self.app.cfg['telemetry_url'] = url
            if isinstance(token, str) and token.strip():
                self.app.cfg['telemetry_token'] = token.strip()
            if data.get('clear_token'):
                self.app.cfg['telemetry_token'] = ''
            try:
                self._write_cfg()
            except OSError:
                self.app.cfg.clear()
                self.app.cfg.update(old)
                raise
            with self.app.db.tx():
                from core import Ctx
                if user:
                    Ctx(self.app.db, user, self._perms(user), '', self.app.org_id, self.app.branch_id).audit(
                        'telemetry.config', 'shop', '', {'configured': bool(self._receiver())})
        return self.receiver_public()

    def _receiver(self):
        url, token = (self.app.cfg.get(k) for k in ('telemetry_url', 'telemetry_token'))
        if not isinstance(url, str) or not isinstance(token, str):
            return None
        url, token = url.strip(), token.strip()
        if not url or not token or len(token) > 4096 or any(ord(ch) < 32 or ord(ch) > 126 for ch in token):
            return None
        if self._valid_url(url):
            return url, token
        return None

    # ---------------------------------------------------------------- guide
    def _perms(self, user):
        return set(auth_mod.effective_perms(user))

    def _live(self, user):
        db = self.app.db
        states = ['signed.in']
        if db.value('SELECT 1 FROM users'):
            states.append('setup.done')
        if db.value('SELECT 1 FROM shifts WHERE user_id = ? AND closed_at IS NULL', user['id']):
            states.append('shift.open')
        if db.value('SELECT 1 FROM sales WHERE by_user = ? LIMIT 1', user['id']):
            states.append('sale.first')
        if (db.value('SELECT COUNT(*) FROM users') or 0) > 1:
            states.append('person.second')
        try:
            names = os.listdir(self.app.backup_dir)
        except OSError:
            names = []
        if any(n.endswith('.db') for n in names):
            states.append('backup.made')
        return states

    def guide_state(self, user):
        perms = self._perms(user)
        role = guide_role(user.get('role'), perms)

        def can(perm):
            return perm in (None, '*') or perm in perms

        with self.app.db.lock:
            record = afguide.load(self.app.db.conn, user['id'])
            return afguide.state(self.catalogue, role, record, self._live(user), can)

    def save_progress(self, user, update):
        if isinstance(update, dict):
            for key in ('op', 'guide', 'lang'):
                if key in update and not isinstance(update[key], str):
                    raise ValueError('bad update')
        with self.app.db.tx():
            record = afguide.load(self.app.db.conn, user['id'])
            record = afguide.apply(record, update, self.catalogue)
            afguide.save(self.app.db.conn, user['id'], record)
        return self.guide_state(user)

    # ---------------------------------------------------------------- consent
    def _on_consent(self, scope, subject, decision):
        with self.lock:
            self.tel.on_consent_change(scope, subject, decision)
            if decision in ('decline', 'withdraw'):
                if scope == 'install':
                    self.tel.db.execute('DELETE FROM outbox')
                else:
                    self.tel.db.execute('DELETE FROM outbox WHERE subject = ?', (self.tel.subject(subject),))

    def prompt_for(self, user, lang):
        if lang not in ('ar', 'en'):
            lang = 'ar'
        body = afconsent.prompt(lang, afconsent.vendor_name({}, DEVELOPER))
        perms = self._perms(user)
        with self.app.db.lock:
            install = self.consent.current('install')
            if install is None and 'settings.edit' in perms:
                ask, scope = True, 'install'
            elif self.consent.needs_prompt(user['id']):
                ask, scope = True, 'person'
            else:
                ask, scope = False, 'person'
        body['ask'] = ask
        body['scope'] = scope
        return body

    def consent_status(self, user):
        with self.app.db.lock:
            status = self.consent.status(user['id'])
            status['feedback_always_allowed'] = False
            return status

    def decide(self, user, data):
        from auth import Forbidden
        decision = data.get('decision')
        text_id = data.get('text_id')
        lang = data.get('lang')
        scope = data.get('scope', 'person')
        if not isinstance(scope, str) or scope not in afconsent.SCOPES or \
                not isinstance(decision, str) or decision not in afconsent.DECISIONS:
            raise ValueError('bad scope or decision')
        if not isinstance(text_id, str) or text_id not in afconsent.TEXTS or \
                afconsent.TEXTS[text_id]['lang'] != lang:
            raise ValueError('unknown consent text')
        if scope == 'install' and 'settings.edit' not in self._perms(user):
            raise Forbidden('settings.edit')
        with self.app.db.tx():
            if scope == 'install':
                self.consent.record('install', '', decision, text_id, lang, user['id'])
                if decision in ('agree', 'decline') and self.consent.current('person', user['id']) is None:
                    self.consent.record('person', user['id'], decision, text_id, lang, user['id'])
            else:
                self.consent.record('person', user['id'], decision, text_id, lang, user['id'])
            from core import Ctx
            Ctx(self.app.db, user, self._perms(user), '', self.app.org_id, self.app.branch_id).audit(
                'consent', scope, user['id'] if scope == 'person' else '', {'decision': decision, 'text_id': text_id})
        return self.consent_status(user)

    # ---------------------------------------------------------------- telemetry
    def note_action(self, user, action, page):
        role = guide_role(user.get('role'), self._perms(user))
        with self.app.db.lock, self.lock:
            self.tel.emit('use.action', {'action': action, 'page': page}, user=user['id'], role=role, page=page)

    def browser_events(self, user, events):
        role = guide_role(user.get('role'), self._perms(user))
        safe = []
        rejected = 0
        codes = {code for problem in self.catalogue['problems'] for code in problem['errors']}
        known = {'page': PAGES, 'guide': {g['id'] for g in self.catalogue['guides']},
                 'problem': {p['id'] for p in self.catalogue['problems']}, 'lang': {'ar', 'en'},
                 'kind': {s['k'] for g in self.catalogue['guides'] for s in g['steps']},
                 'action': {a for a, _ in ACTIONS.values()}, 'perm': set(auth_mod.PERMISSIONS),
                 'shortcut': {'F1', 'F2', 'F4', 'F8', 'F9', 'f1', 'f2', 'f4', 'f8', 'f9', 'ctrl.k'},
                 'error': codes, 'code': codes | {'Error', 'TypeError', 'RangeError', 'ReferenceError',
                    'SyntaxError', 'URIError', 'EvalError', 'AggregateError', 'DOMException'}}
        files = {'promise', 'inline'}
        for directory, _, names in os.walk(os.path.join(ROOT, 'web', 'js')):
            files.update(name for name in names if name.endswith('.js'))
        for event in (events if isinstance(events, list) else [])[:200]:
            if not isinstance(event, dict) or not isinstance(event.get('type'), str) or \
                    not isinstance(event.get('data', {}), dict):
                rejected += 1
                continue
            page = event.get('page')
            data = event.get('data', {})
            valid = page is None or (isinstance(page, str) and page in PAGES)
            for key, value in data.items():
                if key in known:
                    valid = valid and isinstance(value, str) and value in known[key]
                elif key == 'where':
                    file, separator, line = value.rpartition(':') if isinstance(value, str) else ('', '', '')
                    valid = valid and bool(separator and file in files and re.fullmatch(r'\d{1,7}', line))
                elif key == 'fingerprint':
                    valid = valid and isinstance(value, str) and bool(re.fullmatch(r'[a-p]{8,32}', value))
            if not valid:
                rejected += 1
                continue
            safe.append(event)
        with self.app.db.lock, self.lock:
            result = self.tel.from_browser(safe, user['id'], role=role)
            result['rejected'] += rejected
            return result

    def capture(self, exc, where):
        # A request path starts with "/". The taxonomy rejects that, so the module path is "api/..." .
        # An unknown URL may contain a person's name or phone. Only real route ids survive.
        raw = (where or '').split('?', 1)[0]
        raw = raw.lstrip('/') if raw in ACTIONS or raw in (
            '/api/guide/state', '/api/guide/progress', '/api/consent/decide', '/api/telemetry/events') else 'server'
        with self.app.db.lock, self.lock:
            return self.tel.capture(exc, where=raw[:80], root=os.path.join(ROOT, 'server'))

    def diagnostics(self):
        """Allowlisted counts and versions only. Never a name, a path that identifies a person, or an amount."""
        try:
            free = int(shutil.disk_usage(self.app.home).free // (1024 * 1024))
        except OSError:
            free = 0
        try:
            db_mb = int(os.path.getsize(self.app.db.path) // (1024 * 1024))
        except OSError:
            db_mb = 0
        lic = _machine_id(self.app.licence().get('state')) or 'none'
        with self.lock:
            pending = int(self.tel.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0])
        return {
            'version': VERSION, 'os': _machine_id(os.name) or 'os', 'db_mb': db_mb, 'disk_free_mb': free,
            'pending_sync': pending, 'error_count': int(self.app.recent_errors()),
            'uptime_h': int((time.time() - self.app.started) // 3600), 'licence_state': lic, 'build': VERSION,
        }

    def _diagnostics(self, flag, snapshot=False):
        if flag is True:
            return self.diagnostics()
        # Never accept browser-supplied values in a diagnostic field.
        if snapshot and isinstance(flag, dict):
            return flag  # checked against the signed preview before anything is queued
        return None

    def _report_preview(self, data, snapshot=False):
        data, (kind, _, contact) = _report_fields(data)
        if kind not in ('problem', 'idea', 'question'):
            raise aftelemetry.PrivacyError('kind is problem, idea or question')
        known = {'page': PAGES, 'guide': {g['id'] for g in self.catalogue['guides']},
                 'problem': {p['id'] for p in self.catalogue['problems']}}
        args = {'contact': contact}
        allowed = self.tel.tax['types']['fb.' + kind]['data']
        for key in ('page', 'guide', 'problem'):
            value = data.get(key)
            if value is not None and (not isinstance(value, str) or value not in known[key]):
                raise aftelemetry.PrivacyError('unknown report context')
            if value is not None and key in allowed:
                args[key] = value
        if 'diagnostics' in allowed:
            diag = self._diagnostics(data.get('diagnostics'), snapshot)
            if diag is not None:
                args['diagnostics'] = diag
        return self.tel.preview(kind, 'user.report', **args), kind, args

    def _report_digest(self, event):
        return hmac.new(self.tel.secret.encode(), json.dumps(event, sort_keys=True).encode(), hashlib.sha256).hexdigest()

    def preview(self, data):
        # diagnostics() takes the shop lock before the outbox lock.
        if isinstance(data, dict) and data.get('diagnostics') is True:
            data = dict(data, diagnostics=self.diagnostics())
            snapshot = True
        else:
            snapshot = False
        with self.lock:
            result, _, _ = self._report_preview(data, snapshot)
            result['digest'] = self._report_digest(result['event'])
            return result

    def feedback(self, user, data):
        data = data if isinstance(data, dict) else {}
        if data.get('diagnostics') is True:
            raise aftelemetry.PrivacyError('send the diagnostic snapshot from the preview')
        if not isinstance(data.get('confirm'), str) or not data['confirm']:
            raise aftelemetry.PrivacyError('preview and confirm the report first')
        with self.app.db.lock, self.lock:
            if not self.consent.allowed(user['id']):
                raise aftelemetry.PrivacyError('remote help needs shop and person consent')
            result, kind, args = self._report_preview(data, snapshot=True)
            if not hmac.compare_digest(data['confirm'], self._report_digest(result['event'])):
                raise aftelemetry.PrivacyError('the report changed after the preview')
            eid = self.tel.feedback(
                kind, 'user.report', user=user['id'], confirm=result['digest'], **args)
        return {'ok': True, 'id': eid}

    def sent_public(self, user):
        with self.lock:
            rows = self.tel.recent_sent(30)
            subject = self.tel.subject(user['id'])
        return [{'type': ev.get('type'), 'ts': ev.get('ts'), 'page': ev.get('page')}
                for ev in rows if isinstance(ev, dict) and ev.get('subject') == subject]

    def heartbeat(self):
        try:
            free = int(shutil.disk_usage(self.app.home).free // (1024 * 1024))
        except OSError:
            free = 0
        people = int(self.app.db.value('SELECT COUNT(*) FROM users') or 0)
        with self.app.db.lock, self.lock:
            pending = int(self.tel.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0])
            self.tel.emit('hb', {
                'pending_sync': pending, 'error_count': int(self.app.recent_errors()), 'disk_free_mb': free,
                'uptime_h': int((time.time() - self.app.started) // 3600), 'people': people})

    def _prune_pending(self):
        """Restore can roll consent back while the independent outbox survives."""
        subjects = set()
        if self.consent.install_allowed():
            for row in self.app.db.all('SELECT id FROM users WHERE active = 1'):
                if self.consent.allowed(row['id']):
                    subjects.add(self.tel.subject(row['id']))
        for eid, subject, body in self.tel.db.execute('SELECT id, subject, body FROM outbox').fetchall():
            event = json.loads(body)
            # Remove old factory free-text reports too; they never meet this product's privacy rule.
            if (not self.consent.install_allowed() or (subject is not None and subject not in subjects)
                    or (event['type'].startswith('fb.') and
                        (subject not in subjects or event['data'].get('text') != 'user.report'))):
                self.tel.db.execute('DELETE FROM outbox WHERE id = ?', (eid,))

    def _post_remote(self, url, body, headers):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                return None
        request = urllib.request.Request(url, data=body, headers=headers, method='POST')
        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(request, timeout=20) as response:
                return response.status, aftelemetry._server_time(response.read(65536), response.headers.get('Date'))
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, aftelemetry._server_time(exc.read(65536), exc.headers.get('Date'))

    def flush_remote(self):
        """Send one batch only when a receiver and a token are both configured. Never call this on a request."""
        if not self.send_lock.acquire(blocking=False):
            return None
        try:
            with self.app.db.lock, self.lock:
                if self.closed or self.app.db.conn.in_transaction:
                    return None
                pair = self._receiver()
                if not pair:
                    return None
                self._prune_pending()
            with self.lock:
                if self.closed or self._receiver() != pair:
                    return None
                def post(url, body, headers):
                    # Freeze merge rows before releasing the queue lock: new counts get new ids.
                    batch = json.loads(gzip.decompress(body))
                    for event in batch:
                        self.tel.db.execute('UPDATE outbox SET merge_key = NULL WHERE id = ?', (event['id'],))
                    self.lock.release()
                    try:
                        return self._post_remote(url, body, headers)
                    finally:
                        self.lock.acquire()
                return self.tel.send_once(pair[0], pair[1], post=post)
        finally:
            self.send_lock.release()
