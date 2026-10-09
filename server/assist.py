"""In-app guide, consent and consented telemetry.

The three factory packages (afguide, afconsent, aftelemetry) are vendored and not modified here.
This module is the product glue: live states, the two guide routes' data, the consent card,
and a local outbox that stays on this PC unless a receiver address and token are both set.
"""
import json
import os
import re
import secrets
import shutil
import threading
import time

import afconsent
import afguide
import aftelemetry
import auth as auth_mod
from version import DEVELOPER, PRODUCT_ID, ROOT, VERSION

_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:\-/]{0,79}$')
_LONG = re.compile(r'\d{8,}')
BUILTINS = ('owner', 'manager', 'cashier', 'storekeeper')
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
    if isinstance(value, str) and _ID.match(value) and not _LONG.search(value) and '@' not in value:
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
        self.catalogue, self.texts = afguide.load_dir(os.path.join(ROOT, 'guide'))
        self._ensure_cfg()
        self.consent = afconsent.Consent(app.db.conn, on_change=self._on_consent)
        self.tel = aftelemetry.Telemetry(
            os.path.join(app.home, 'telemetry.db'), self.app.cfg['telemetry_install_id'],
            node='shop', product=PRODUCT_ID, version=VERSION,
            env='practice' if app.practice else 'real', secret=self.app.cfg['telemetry_secret'],
            consent=self.consent)

    def close(self):
        try:
            self.tel.close()
        except Exception:
            pass

    def rebind(self):
        """After a restore the shop connection is a new object. The outbox file is not part of that swap."""
        self.consent.db = self.app.db.conn

    # ---------------------------------------------------------------- config (local only)
    def _cfg_path(self):
        return os.path.join(self.app.home, 'config.json')

    def _write_cfg(self):
        with open(self._cfg_path(), 'w', encoding='utf-8') as f:
            json.dump(self.app.cfg, f, indent=2)
            f.write('\n')

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
        url = (self.app.cfg.get('telemetry_url') or '').strip()
        return {'url': url, 'has_token': bool((self.app.cfg.get('telemetry_token') or '').strip()),
                'sending': bool(url and (self.app.cfg.get('telemetry_token') or '').strip())}

    def save_receiver(self, data):
        """Owner-only. The token is stored and never returned or written to the audit."""
        from core import Problem
        url = data.get('url') if isinstance(data.get('url'), str) else ''
        url = url.strip()
        if url and not (url.startswith('https://') or url.startswith('http://127.0.0.1') or url.startswith('http://localhost')):
            raise Problem('err.badRequest', 'The receiver address must be https, or this PC only.')
        self.app.cfg['telemetry_url'] = url
        token = data.get('token')
        if isinstance(token, str) and token.strip():
            self.app.cfg['telemetry_token'] = token.strip()
        if data.get('clear_token'):
            self.app.cfg['telemetry_token'] = ''
        self._write_cfg()
        return self.receiver_public()

    def _receiver(self):
        url = (self.app.cfg.get('telemetry_url') or '').strip()
        token = (self.app.cfg.get('telemetry_token') or '').strip()
        if not url or not token:
            return None
        if url.startswith('https://') or url.startswith('http://127.0.0.1') or url.startswith('http://localhost'):
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
        with self.app.db.tx():
            record = afguide.load(self.app.db.conn, user['id'])
            record = afguide.apply(record, update, self.catalogue)
            afguide.save(self.app.db.conn, user['id'], record)
        return self.guide_state(user)

    # ---------------------------------------------------------------- consent
    def _on_consent(self, scope, subject, decision):
        with self.lock:
            self.tel.on_consent_change(scope, subject, decision)

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
            return self.consent.status(user['id'])

    def decide(self, user, data):
        from auth import Forbidden
        decision = data.get('decision')
        text_id = data.get('text_id')
        lang = data.get('lang')
        scope = data.get('scope') or 'person'
        if scope == 'install' and 'settings.edit' not in self._perms(user):
            raise Forbidden('settings.edit')
        if scope not in ('install', 'person'):
            raise ValueError('bad scope or decision')
        with self.app.db.tx():
            if scope == 'install':
                inst = 'decline' if decision == 'decline' else decision
                self.consent.record('install', '', inst, text_id, lang, user['id'])
                if decision in ('agree', 'decline'):
                    self.consent.record('person', user['id'], decision, text_id, lang, user['id'])
            else:
                self.consent.record('person', user['id'], decision, text_id, lang, user['id'])
        return self.consent_status(user)

    # ---------------------------------------------------------------- telemetry
    def note_action(self, user, action, page):
        role = guide_role(user.get('role'), self._perms(user))
        with self.lock:
            self.tel.emit('use.action', {'action': action, 'page': page}, user=user['id'], role=role, page=page)

    def browser_events(self, user, events):
        role = guide_role(user.get('role'), self._perms(user))
        with self.lock:
            return self.tel.from_browser(events if isinstance(events, list) else [], user['id'], role=role)

    def capture(self, exc, where):
        # A request path starts with "/". The taxonomy rejects that, so the module path is "api/..." .
        raw = (where or 'server').split('?', 1)[0].lstrip('/') or 'server'
        with self.lock:
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

    def _diagnostics(self, flag):
        if flag is True:
            return self.diagnostics()
        if isinstance(flag, dict):
            allow = set(self.tel.tax.get('diagnostics', []))
            out = {k: v for k, v in flag.items() if k in allow}
            return out or None
        return None

    def preview(self, data):
        data, (kind, text, contact) = _report_fields(data)
        diag = self._diagnostics(data.get('diagnostics'))
        with self.lock:
            return self.tel.preview(
                kind, text, page=_machine_id(data.get('page')),
                guide=_machine_id(data.get('guide')), problem=_machine_id(data.get('problem')),
                contact=contact, diagnostics=diag)

    def feedback(self, user, data):
        data, (kind, text, contact) = _report_fields(data)
        diag = self._diagnostics(data.get('diagnostics'))
        with self.lock:
            eid = self.tel.feedback(
                kind, text, user=user['id'], confirm=data.get('confirm'),
                page=_machine_id(data.get('page')), guide=_machine_id(data.get('guide')),
                problem=_machine_id(data.get('problem')), contact=contact, diagnostics=diag)
        return {'ok': True, 'id': eid}

    def sent_public(self):
        with self.lock:
            rows = self.tel.recent_sent(30)
        return [{'type': ev.get('type'), 'ts': ev.get('ts'), 'page': ev.get('page')}
                for ev in rows if isinstance(ev, dict)]

    def heartbeat(self):
        try:
            free = int(shutil.disk_usage(self.app.home).free // (1024 * 1024))
        except OSError:
            free = 0
        people = int(self.app.db.value('SELECT COUNT(*) FROM users') or 0)
        with self.lock:
            pending = int(self.tel.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0])
            self.tel.emit('hb', {
                'pending_sync': pending, 'error_count': int(self.app.recent_errors()), 'disk_free_mb': free,
                'uptime_h': int((time.time() - self.app.started) // 3600), 'people': people})

    def flush_remote(self):
        """Send one batch only when a receiver and a token are both configured. Never call this on a request."""
        pair = self._receiver()
        if not pair:
            return None
        with self.lock:
            return self.tel.send_once(pair[0], pair[1])
