"""People, passwords, sessions and permissions.

- Passwords: salted PBKDF2-SHA256 (310,000 rounds, OWASP 2023+); never stored, never logged.
- Session: random 256-bit token in an HttpOnly SameSite=Strict cookie; only its SHA-256 is kept. Ends after idle time,
  a maximum age, logout, password change or when the person is disabled.
- Five wrong passwords lock the account for 15 minutes; the message never says which part was wrong.
- Every permission is checked here, on the server, for every request. Hiding a button is only a convenience.
- A manager can approve one action for a cashier (a big discount, selling under the minimum price, a return) by typing
  their own password on the cashier's screen. The approval is checked here and written to the audit.
"""
import hashlib
import hmac
import json
import os
import secrets
from datetime import timedelta

import ids

ITERATIONS = 310_000
IDLE_MINUTES = 30
MAX_HOURS = 14
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 8

# permission -> (group, English label). The Arabic labels live in the page dictionaries (perm.<id>).
PERMISSIONS = {
    'pos.sell': ('sell', 'Sell at the counter'),
    'pos.discount': ('sell', 'Give discounts up to the personal limit'),
    'pos.credit': ('sell', 'Sell on account or by shop instalments'),
    'sales.view_all': ('sell', 'See every sale, not only own'),
    'sales.return': ('sell', 'Take returns and exchanges'),
    'customers.edit': ('customers', 'Add and edit customers'),
    'customers.private': ('customers', 'See national ID numbers'),
    'installments.collect': ('customers', 'Collect instalments and account payments'),
    'products.edit': ('stock', 'Add and edit products'),
    'prices.change': ('stock', 'Change prices (single and bulk)'),
    'cost.view': ('stock', 'See purchase cost and profit'),
    'stock.receive': ('stock', 'Receive goods from suppliers'),
    'stock.transfer': ('stock', 'Move goods between store and shop'),
    'stock.count': ('stock', 'Count stock and settle differences'),
    'suppliers.pay': ('money', 'Pay suppliers'),
    'cash.expense': ('money', 'Record expenses from the drawer'),
    'cash.safe': ('money', 'Main safe: hand over and withdraw'),
    'shifts.manage': ('money', 'See and close every shift'),
    'reports.view': ('owner', 'Reports'),
    'watch.view': ('owner', "Owner's eye (alerts)"),
    'audit.view': ('owner', 'Activity log'),
    'users.manage': ('owner', 'Users and permissions'),
    'settings.edit': ('owner', 'Shop settings, backups and licence'),
}
ROLES = {
    'owner': {'perms': list(PERMISSIONS), 'max_discount_pct': 100},
    'manager': {'perms': [p for p in PERMISSIONS if p not in ('users.manage', 'settings.edit')], 'max_discount_pct': 15},
    'cashier': {'perms': ['pos.sell', 'pos.discount', 'pos.credit', 'customers.edit', 'installments.collect', 'cash.expense'],
                'max_discount_pct': 5},
    'storekeeper': {'perms': ['stock.receive', 'stock.transfer', 'stock.count', 'products.edit'], 'max_discount_pct': 0},
}


class AuthError(Exception):
    """Wrong login, locked account, weak password: shown to the person as is (keyed message)."""

    def __init__(self, key, text, **vars):
        super().__init__(text)
        self.key, self.vars = key, vars


class Forbidden(Exception):
    def __init__(self, perm, text=None):
        super().__init__(text or f'You do not have permission: {PERMISSIONS.get(perm, ("", perm))[1]}.')
        self.perm = perm


def hash_password(password):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, ITERATIONS)
    return f'pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}'


def check_password(password, stored):
    try:
        algo, n, salt, digest = stored.split('$')
        if algo != 'pbkdf2_sha256':
            return False
        test = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), int(n))
        return hmac.compare_digest(test.hex(), digest)
    except (ValueError, AttributeError):
        return False


_DUMMY = hash_password('timing-equaliser')  # unknown user names cost the same time as wrong passwords


def _perms(value):
    """A permission list from the page: only known names survive; anything else is ignored."""
    return sorted({x for x in value if isinstance(x, str)} & set(PERMISSIONS)) if isinstance(value, (list, tuple, set)) else []


def _pct(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise AuthError('auth.err.pct', 'The discount limit is a number from 0 to 100.')
    return max(0, min(100, int(value)))


def _text(value):
    return value if isinstance(value, str) else ''


def strong_enough(password, username=''):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AuthError('auth.err.short', f'Use at least {MIN_PASSWORD} characters.', n=MIN_PASSWORD)
    if username and password.lower() == username.lower():
        raise AuthError('auth.err.sameAsName', 'The password must not be the user name.')
    if len(set(password)) < 4:
        raise AuthError('auth.err.weak', 'This password is too easy to guess.')


def effective_perms(user):
    base = set(ROLES.get(user['role'], {'perms': []})['perms'])
    base |= set(json.loads(user.get('extra_perms') or '[]'))
    base -= set(json.loads(user.get('denied_perms') or '[]'))
    return sorted(p for p in base if p in PERMISSIONS)


def public(user):
    return {'id': user['id'], 'username': user['username'], 'full_name': user['full_name'], 'role': user['role'],
            'active': bool(user['active']), 'max_discount_pct': user['max_discount_pct'], 'perms': effective_perms(user),
            'extra_perms': json.loads(user['extra_perms']), 'denied_perms': json.loads(user['denied_perms'])}


class Auth:
    def __init__(self, db, org_id):
        self.db, self.org_id = db, org_id

    # ---------------------------------------------------------------- accounts
    def has_users(self):
        return bool(self.db.value('SELECT COUNT(*) FROM users'))

    def create(self, username, full_name, role, password, max_discount_pct=None, extra=(), denied=()):
        username = _text(username).strip()
        if not (2 <= len(username) <= 40) or any(ch.isspace() for ch in username):
            raise AuthError('auth.err.username', 'User name: 2 to 40 characters without spaces.')
        if not isinstance(role, str) or role not in ROLES:
            raise AuthError('auth.err.role', 'Unknown role.')
        if not _text(full_name).strip():
            raise AuthError('auth.err.fullName', 'Write the person\'s name.')
        strong_enough(password, username)
        if self.db.value('SELECT 1 FROM users WHERE username = ?', username):
            raise AuthError('auth.err.taken', 'This user name is already used.')
        now = ids.iso()
        pct = ROLES[role]['max_discount_pct'] if max_discount_pct is None else _pct(max_discount_pct)
        row = {'id': ids.uuid7(), 'org_id': self.org_id, 'username': username, 'full_name': full_name.strip()[:80], 'role': role,
               'extra_perms': json.dumps(_perms(extra)),
               'denied_perms': json.dumps(_perms(denied)), 'max_discount_pct': pct,
               'pass_hash': hash_password(password), 'active': 1, 'failed': 0, 'locked_until': None, 'created_at': now,
               'changed_at': now}
        self.db.insert('users', row)
        return row

    def get(self, user_id):
        return self.db.one('SELECT * FROM users WHERE id = ?', user_id)

    def update(self, user_id, changes):
        user = self.get(user_id)
        if not user:
            raise AuthError('auth.err.noUser', 'User not found.')
        fields = {}
        if 'full_name' in changes:
            fields['full_name'] = _text(changes['full_name']).strip()[:80] or user['full_name']
        if 'role' in changes:
            if not isinstance(changes['role'], str) or changes['role'] not in ROLES:
                raise AuthError('auth.err.role', 'Unknown role.')
            fields['role'] = changes['role']
        if 'max_discount_pct' in changes:
            fields['max_discount_pct'] = _pct(changes['max_discount_pct'])
        if 'extra_perms' in changes:
            fields['extra_perms'] = json.dumps(_perms(changes['extra_perms']))
        if 'denied_perms' in changes:
            fields['denied_perms'] = json.dumps(_perms(changes['denied_perms']))
        if 'active' in changes:
            fields['active'] = 1 if changes['active'] else 0
        if 'password' in changes and changes['password']:
            strong_enough(changes['password'], user['username'])
            fields['pass_hash'] = hash_password(changes['password'])
            fields['failed'], fields['locked_until'] = 0, None
        after = {**user, **fields}
        if user['role'] == 'owner' and (after['role'] != 'owner' or not after['active']):
            owners = self.db.value("SELECT COUNT(*) FROM users WHERE role='owner' AND active=1 AND id != ?", user_id)
            if not owners:
                raise AuthError('auth.err.lastOwner', 'The shop must keep at least one active owner.')
        if fields:
            fields['changed_at'] = ids.iso()
            sets = ', '.join(f'{k} = ?' for k in fields)
            self.db.run(f'UPDATE users SET {sets} WHERE id = ?', *fields.values(), user_id)
        if 'pass_hash' in fields or fields.get('active') == 0 or 'role' in fields:
            self.end_sessions(user_id)
        return self.get(user_id)

    # ---------------------------------------------------------------- login
    def verify(self, username, password):
        """Returns the user or raises AuthError. Locks after MAX_FAILED wrong passwords."""
        user = self.db.one('SELECT * FROM users WHERE username = ?', str(username or '').strip())
        if not user:
            check_password(str(password or ''), _DUMMY)
            raise AuthError('auth.err.wrong', 'Wrong user name or password.')
        now = ids.utcnow()
        if user['locked_until'] and ids.parse(user['locked_until']) > now:
            raise AuthError('auth.err.locked', 'Too many wrong tries. Try again after a few minutes.', minutes=LOCK_MINUTES)
        if not check_password(password or '', user['pass_hash']):
            failed = user['failed'] + 1
            locked = ids.iso(now + timedelta(minutes=LOCK_MINUTES)) if failed >= MAX_FAILED else None
            self.db.run('UPDATE users SET failed = ?, locked_until = ? WHERE id = ?', 0 if locked else failed, locked, user['id'])
            raise AuthError('auth.err.wrong', 'Wrong user name or password.')
        if not user['active']:
            raise AuthError('auth.err.disabled', 'This account is switched off. Ask the owner.')
        if user['failed'] or user['locked_until']:
            self.db.run('UPDATE users SET failed = 0, locked_until = NULL WHERE id = ?', user['id'])
        return user

    def start_session(self, user, ip):
        token = secrets.token_urlsafe(32)
        now = ids.iso()
        self.db.insert('sessions', {'token_hash': _h(token), 'user_id': user['id'], 'created_at': now, 'last_seen': now,
                                    'ip': ip, 'ended': 0})
        return token

    def session(self, token, touch=True):
        if not token:
            return None
        row = self.db.one('SELECT * FROM sessions WHERE token_hash = ? AND ended = 0', _h(token))
        if not row:
            return None
        now = ids.utcnow()
        if now - ids.parse(row['last_seen']) > timedelta(minutes=IDLE_MINUTES) or \
                now - ids.parse(row['created_at']) > timedelta(hours=MAX_HOURS):
            self.db.run('UPDATE sessions SET ended = 1 WHERE token_hash = ?', row['token_hash'])
            return None
        user = self.get(row['user_id'])
        if not user or not user['active']:
            return None
        if touch:
            self.db.run('UPDATE sessions SET last_seen = ? WHERE token_hash = ?', ids.iso(now), row['token_hash'])
        return user

    def end_session(self, token):
        self.db.run('UPDATE sessions SET ended = 1 WHERE token_hash = ?', _h(token or ''))

    def end_sessions(self, user_id):
        self.db.run('UPDATE sessions SET ended = 1 WHERE user_id = ?', user_id)

    def approve(self, approval, perm):
        """A manager's password typed on someone else's screen. Returns the approving user or raises."""
        if not isinstance(approval, dict):
            raise Forbidden(perm)
        user = self.verify(approval.get('username'), approval.get('password'))
        if perm not in effective_perms(user):
            raise Forbidden(perm, 'This person cannot approve this action.')
        return user


def _h(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()
