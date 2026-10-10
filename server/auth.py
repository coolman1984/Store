"""People, passwords, sessions and permissions.

- Passwords: salted PBKDF2-SHA256 (310,000 rounds, OWASP 2023+); never stored, never logged.
- Session: random 256-bit token in an HttpOnly SameSite=Strict cookie; only its SHA-256 is kept. Ends after idle time,
  a maximum age, logout, password change or when the person is disabled.
- Five wrong passwords lock the account for 15 minutes; the message never says which part was wrong.
- Every permission is checked here, on the server, for every request. Hiding a button is only a convenience.
- The owner gets a one-time recovery code at setup (printed on paper). It sets a new password when the owner forgets it;
  only its PBKDF2 hash is kept, it works once and a new code replaces it. There is no vendor master password.
- A manager can approve one action for a cashier (a big discount, selling under the minimum price, a return) by typing
  their own password on the cashier's screen. The approval is checked here and written to the audit.
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import timedelta

import afaccess
import ids

ITERATIONS = 310_000
IDLE_MINUTES = 30
MAX_HOURS = 14
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 8
# Never accepted in a real shop (factory IAM-06): the practice shop's published password and the passwords people try first.
REFUSED_PASSWORDS = frozenset({'practice-1234', '12345678', '123456789', '1234567890', '87654321', '11111111', '00000000',
                               'password', 'password1', 'admin123', 'admin1234', 'qwerty123', 'abcd1234', 'a1234567'})
RECOVERY_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'  # no 0/O, 1/I/L: read off paper without mistakes

# permission -> (group, English label). The Arabic labels live in the page dictionaries (perm.<id>, permg.<group>).
# The order is the order on the people screen. The rules (one administrator group, a locked profile with every right,
# pages guarded, profiles usable) are checked by the factory gate afaccess in tests/test_access.py.
GROUPS = ['pages', 'sell', 'customers', 'stock', 'money', 'owner', 'admin']
ADMIN_GROUP = 'admin'
PERMISSIONS = {
    'products.view': ('pages', 'Products page: names, prices and places'),
    'stock.view': ('pages', 'Stock page: quantities, counts and transfers'),
    'customers.view': ('pages', 'Customers page: balances and instalments'),
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
    'users.manage': ('admin', 'People, profiles and permissions'),
    'settings.edit': ('admin', 'Shop settings, backups and licence'),
}
ADMIN_PERMS = {p for p, (g, _) in PERMISSIONS.items() if g == ADMIN_GROUP}
KINDS = {'products.view': 'page', 'stock.view': 'page', 'customers.view': 'page', 'pos.sell': 'page', 'reports.view': 'page',
         'watch.view': 'page', 'cost.view': 'field', 'customers.private': 'field',
         'users.manage': 'admin', 'settings.edit': 'admin'}
# an action is useless without the page it is done on: the people screen ticks the page with it
REQUIRES = {'pos.discount': ['pos.sell'], 'pos.credit': ['pos.sell'], 'customers.edit': ['customers.view'],
            'installments.collect': ['customers.view'], 'products.edit': ['products.view'], 'prices.change': ['products.view'],
            'stock.transfer': ['stock.view'], 'stock.count': ['stock.view']}
# which pages need which permission (any one of them): the menu and the server follow the same table
PAGES = {'home': '*', 'help': '*', 'settings': '*', 'pos': ['pos.sell'], 'sales': ['pos.sell', 'sales.view_all', 'sales.return'],
         'customers': ['customers.view'], 'products': ['products.view'], 'stock': ['stock.view'], 'receive': ['stock.receive'],
         'cash': ['pos.sell', 'cash.safe', 'shifts.manage', 'cash.expense'], 'watch': ['watch.view'], 'reports': ['reports.view']}
WORK = [p for p in PERMISSIONS if p not in ADMIN_PERMS]
# ready-made profiles; the owner can rename, change or delete them (except the owner profile) and make new ones
ROLES = {
    'owner': {'perms': list(PERMISSIONS), 'max_discount_pct': 100},
    'manager': {'perms': WORK, 'max_discount_pct': 15},
    'cashier': {'perms': ['products.view', 'stock.view', 'customers.view', 'pos.sell', 'pos.discount', 'pos.credit', 'customers.edit',
                          'installments.collect', 'cash.expense'], 'max_discount_pct': 5},
    'storekeeper': {'perms': ['products.view', 'stock.view', 'stock.receive', 'stock.transfer', 'stock.count', 'products.edit'],
                    'max_discount_pct': 0},
}
# the names the ready-made profiles show while not renamed (the page dictionaries' role.<id>; a test keeps them equal), so a new
# profile cannot take the same name and two choices look alike in the picker
BUILTIN_NAMES = {'owner': ('Owner', 'صاحب المحل'), 'manager': ('Manager', 'مدير'), 'cashier': ('Cashier', 'كاشير'),
                 'storekeeper': ('Storekeeper', 'أمين مخزن')}
LOCKED = 'owner'  # always every permission, cannot be changed or deleted: there is always a way to manage the shop
CUSTOM = 'custom'  # a person whose ticks match no profile
_OLD_ROLE_PERMS = {  # the fixed roles of 1.0 (pages were open to everybody then): used once to carry old people over
    'owner': list(PERMISSIONS),
    'manager': [p for p in PERMISSIONS if p not in ADMIN_PERMS],
    'cashier': ['pos.sell', 'pos.discount', 'pos.credit', 'customers.edit', 'installments.collect', 'cash.expense'],
    'storekeeper': ['stock.receive', 'stock.transfer', 'stock.count', 'products.edit'],
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


def strong_enough(password, username='', practice=False):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AuthError('auth.err.short', f'Use at least {MIN_PASSWORD} characters.', n=MIN_PASSWORD)
    if username and password.lower() == username.lower():
        raise AuthError('auth.err.sameAsName', 'The password must not be the user name.')
    if len(set(password)) < 4 or (not practice and password.lower() in REFUSED_PASSWORDS):
        raise AuthError('auth.err.weak', 'This password is too easy to guess.')


def _legacy_perms(user):
    """1.0 people: role + own extra ticks - own removed ticks; pages that were open to everybody stay open."""
    try:
        extra, denied = json.loads(user.get('extra_perms') or '[]'), json.loads(user.get('denied_perms') or '[]')
    except ValueError:
        extra, denied = [], []
    have = set(afaccess.effective(_OLD_ROLE_PERMS.get(user.get('role'), []), extra, denied))
    have |= {'products.view', 'stock.view'}
    if have & {'customers.edit', 'installments.collect'}:
        have.add('customers.view')
    return sorted(p for p in have if p in PERMISSIONS)


def effective_perms(user):
    """What the person may do now. The owner profile always has everything; everybody else has their own ticks."""
    if user.get('role') == LOCKED:
        return sorted(PERMISSIONS)
    if user.get('perms') is not None:
        try:
            return sorted(p for p in json.loads(user['perms']) if p in PERMISSIONS)
        except ValueError:
            return []
    return _legacy_perms(user)


def public(user):
    return {'id': user['id'], 'username': user['username'], 'full_name': user['full_name'], 'role': user['role'],
            'active': bool(user['active']), 'max_discount_pct': user['max_discount_pct'], 'perms': effective_perms(user)}


def perm_list():
    return [{'id': k, 'group': g, 'label': label, 'kind': KINDS.get(k, 'action'), 'admin': g == ADMIN_GROUP,
             'requires': REQUIRES.get(k, [])} for k, (g, label) in PERMISSIONS.items()]


def catalogue(profiles=None, labels=None):
    """The permission catalogue in the factory format (packages/af-access), for the gate and the owner's matrix.
    `labels`: {lang: {dictionary key: words}} to add the words of the page dictionaries."""
    labels = labels or {}
    langs = ['en', *labels]

    def words(key, en):
        return {'en': en, **{lang: d.get(key, '') for lang, d in labels.items()}}
    groups = [{'id': g, 'admin': g == ADMIN_GROUP, 'labels': words('permg.' + g, g.title()),
               'permissions': [{'id': p['id'], 'kind': p['kind'], 'requires': p['requires'], 'labels': words('perm.' + p['id'], p['label'])}
                               for p in perm_list() if p['group'] == g]} for g in GROUPS]
    profs = profiles if profiles is not None else [{'id': k, 'name': '', 'perms': v['perms'], 'locked': k == LOCKED} for k, v in ROLES.items()]
    return {'product': 'al-store', 'languages': langs, 'manage': 'users.manage', 'groups': groups, 'pages': PAGES,
            'profiles': [{'id': p['id'], 'locked': p.get('locked', False), 'perms': p['perms'],
                          'labels': {'en': p['name'] or p['id'].title(),
                                     **{lang: p['name'] or d.get('role.' + p['id'], '') for lang, d in labels.items()}}} for p in profs]}


class Auth:
    def __init__(self, db, org_id, practice=False):
        self.db, self.org_id, self.practice = db, org_id, practice
        self._carry_over()

    def _carry_over(self):
        """People saved by 1.0 get their own ticks once (same rights as before). If nobody active could manage people
        any more (possible in 1.0 by removing that tick from the only owner), the 1.0 owners get the owner profile back."""
        with self.db.tx():
            owners = []
            for u in self.db.all('SELECT * FROM users WHERE perms IS NULL'):
                perms = _legacy_perms(u)
                if u['role'] == LOCKED:
                    owners.append(u['id'])
                role = u['role'] if set(perms) == set(ROLES.get(u['role'], {}).get('perms', [None])) else CUSTOM
                self.db.run('UPDATE users SET perms = ?, role = ? WHERE id = ?', json.dumps(perms), role, u['id'])
            if owners and not any(u['active'] and 'users.manage' in effective_perms(u) for u in self.db.all('SELECT * FROM users')):
                for uid in owners:
                    self.db.run('UPDATE users SET role = ?, perms = ? WHERE id = ? AND active = 1', LOCKED,
                                json.dumps(sorted(PERMISSIONS)), uid)

    # ---------------------------------------------------------------- profiles (named sets of ticks)
    def profiles(self):
        """Ready-made profiles (as changed by the owner) and the owner's own, with how many people have each."""
        rows = {r['id']: r for r in self.db.all('SELECT * FROM profiles')}
        used = {}
        for r in self.db.all('SELECT role FROM users'):
            used[r['role']] = used.get(r['role'], 0) + 1
        out = []

        def add(pid, row, perms, pct, builtin):
            perms = sorted(PERMISSIONS) if pid == LOCKED else sorted(p for p in perms if p in PERMISSIONS)
            out.append({'id': pid, 'name': row['name'] if row else '', 'perms': perms, 'max_discount_pct': pct, 'builtin': builtin,
                        'locked': pid == LOCKED, 'users': used.get(pid, 0)})
        for pid, spec in ROLES.items():
            r = rows.pop(pid, None)
            if r is None:
                add(pid, None, spec['perms'], spec['max_discount_pct'], True)
            elif not r['deleted'] or pid == LOCKED:
                add(pid, r, json.loads(r['perms']), r['max_discount_pct'], True)
        for r in sorted(rows.values(), key=lambda r: r['name'].lower()):
            if not r['deleted']:
                add(r['id'], r, json.loads(r['perms']), r['max_discount_pct'], False)
        return out

    def profile(self, pid):
        return next((p for p in self.profiles() if p['id'] == pid), None) if isinstance(pid, str) else None

    def _role_for(self, role, perms):
        """The profile name a person shows: the chosen profile while the ticks are exactly its ticks, else a profile with
        exactly these ticks, else Custom. The owner profile means every permission, so fewer ticks are Custom."""
        profs = self.profiles()
        chosen = next((p for p in profs if p['id'] == role), None)
        if chosen and set(chosen['perms']) == set(perms):
            return role
        return next((p['id'] for p in profs if not p['locked'] and set(p['perms']) == set(perms)), CUSTOM)

    def _safe(self, actor_id, changed):
        """Refuses a change that would lock the shop out of its own people screen (factory rule IAM-10)."""
        people = self.db.all('SELECT * FROM users')
        before = [{'id': u['id'], 'active': bool(u['active']), 'perms': effective_perms(u)} for u in people]
        after = [{**b, **changed[b['id']]} if b['id'] in changed else b for b in before]
        problems = afaccess.admin_safety(before, after, actor_id, ADMIN_PERMS) if actor_id else \
            [x for x in afaccess.admin_safety(before, after, None, ADMIN_PERMS) if x != 'self-lockout']
        if 'self-lockout' in problems:
            raise AuthError('auth.err.selfLockout', 'You cannot switch yourself off or remove your own right to manage people.')
        if 'last-manager' in problems:
            raise AuthError('auth.err.lastManager', 'At least one active person must keep the right to manage people and permissions.')

    def save_profile(self, data, actor_id=None):
        """Creates or changes a profile; with apply, everybody who has it gets the new ticks. Returns (profile, before, n)."""
        pid = data.get('id') if isinstance(data.get('id'), str) and data.get('id') else None
        name = ' '.join(_text(data.get('name')).split())[:40]
        perms = _perms(data.get('perms'))
        pct = _pct(data.get('max_discount_pct', 0))
        cur = self.profile(pid) if pid else None
        if pid and not cur:
            raise AuthError('auth.err.noProfile', 'This profile no longer exists.')
        if cur and cur['locked']:
            raise AuthError('auth.err.lockedProfile', 'The owner profile always has every right. It cannot be changed.')
        if not name and not (cur and cur['builtin']):
            raise AuthError('auth.err.profileName', 'Give the profile a name, for example "Senior cashier".')
        if name.lower() in afaccess.RESERVED_PROFILE_NAMES:
            raise AuthError('auth.err.profileReserved', '"Custom" is for people with their own ticks. Choose another name.')
        shown = lambda p: {p['name'].lower()} if p['name'] else {n.lower() for n in BUILTIN_NAMES.get(p['id'], ())}  # noqa: E731
        if name and any(p['id'] != pid and name.lower() in shown(p) for p in self.profiles()):
            raise AuthError('auth.err.profileTaken', 'There is already a profile with this name.')
        new_id = pid or ids.uuid7()
        holders = [u for u in self.db.all('SELECT * FROM users WHERE role = ?', new_id)] if cur and data.get('apply', True) is not False else []
        self._safe(actor_id, {u['id']: {'perms': perms} for u in holders})
        now = ids.iso()
        if self.db.value('SELECT 1 FROM profiles WHERE id = ?', new_id):
            self.db.run('UPDATE profiles SET name = ?, perms = ?, max_discount_pct = ?, deleted = 0, changed_at = ? WHERE id = ?',
                        name, json.dumps(perms), pct, now, new_id)
        else:
            self.db.insert('profiles', {'id': new_id, 'org_id': self.org_id, 'name': name, 'perms': json.dumps(perms),
                                        'max_discount_pct': pct, 'deleted': 0, 'changed_at': now})
        for u in holders:
            self.db.run('UPDATE users SET perms = ?, changed_at = ? WHERE id = ?', json.dumps(perms), now, u['id'])
        if cur and not holders:  # the people keep their ticks; they no longer match the changed profile
            for u in self.db.all('SELECT * FROM users WHERE role = ?', new_id):
                self.db.run('UPDATE users SET role = ? WHERE id = ?', self._role_for(new_id, effective_perms(u)), u['id'])
        return self.profile(new_id), cur, len(holders)

    def delete_profile(self, pid):
        """The profile disappears; the people who had it keep their ticks and show as Custom."""
        cur = self.profile(pid)
        if not cur:
            raise AuthError('auth.err.noProfile', 'This profile no longer exists.')
        if cur['locked']:
            raise AuthError('auth.err.lockedProfile', 'The owner profile always has every right. It cannot be changed.')
        now = ids.iso()
        if self.db.value('SELECT 1 FROM profiles WHERE id = ?', pid):
            self.db.run('UPDATE profiles SET deleted = 1, changed_at = ? WHERE id = ?', now, pid)
        else:
            self.db.insert('profiles', {'id': pid, 'org_id': self.org_id, 'name': '', 'perms': json.dumps(cur['perms']),
                                        'max_discount_pct': cur['max_discount_pct'], 'deleted': 1, 'changed_at': now})
        n = self.db.value('SELECT COUNT(*) FROM users WHERE role = ?', pid)
        self.db.run('UPDATE users SET role = ? WHERE role = ?', CUSTOM, pid)
        return cur, n

    # ---------------------------------------------------------------- accounts
    def has_users(self):
        return bool(self.db.value('SELECT COUNT(*) FROM users'))

    def _ticks(self, role, current, changes):
        """The person's new ticks from a save: explicit ticks, or the profile with own extra/removed ticks (1.0 form)."""
        prof = self.profile(role)
        if role != CUSTOM and not prof:
            raise AuthError('auth.err.role', 'Unknown profile.')
        base = prof['perms'] if prof else current
        if 'perms' in changes:
            return _perms(changes['perms'])
        if 'extra_perms' in changes or 'denied_perms' in changes:
            return afaccess.effective(base, _perms(changes.get('extra_perms')), _perms(changes.get('denied_perms')))
        return list(base)

    def create(self, username, full_name, role, password, max_discount_pct=None, extra=(), denied=(), perms=None):
        username = _text(username).strip()
        if not (2 <= len(username) <= 40) or any(ch.isspace() for ch in username):
            raise AuthError('auth.err.username', 'User name: 2 to 40 characters without spaces.')
        if not isinstance(role, str) or (role != CUSTOM and not self.profile(role)) or (role == CUSTOM and perms is None):
            raise AuthError('auth.err.role', 'Unknown profile.')
        if not _text(full_name).strip():
            raise AuthError('auth.err.fullName', 'Write the person\'s name.')
        strong_enough(password, username, self.practice)
        if self.db.value('SELECT 1 FROM users WHERE username = ?', username):
            raise AuthError('auth.err.taken', 'This user name is already used.')
        now = ids.iso()
        ticks = self._ticks(role, [], {'perms': perms} if perms is not None else {'extra_perms': extra, 'denied_perms': denied})
        prof = self.profile(role)
        pct = (prof['max_discount_pct'] if prof else 0) if max_discount_pct is None else _pct(max_discount_pct)
        row = {'id': ids.uuid7(), 'org_id': self.org_id, 'username': username, 'full_name': full_name.strip()[:80],
               'role': self._role_for(role, ticks), 'perms': json.dumps(ticks),
               'max_discount_pct': pct, 'pass_hash': hash_password(password), 'active': 1, 'failed': 0, 'locked_until': None,
               'created_at': now, 'changed_at': now}
        self.db.insert('users', row)
        return self.get(row['id'])

    def get(self, user_id):
        return self.db.one('SELECT * FROM users WHERE id = ?', user_id)

    def update(self, user_id, changes, actor_id=None):
        user = self.get(user_id)
        if not user:
            raise AuthError('auth.err.noUser', 'User not found.')
        fields = {}
        if 'full_name' in changes:
            fields['full_name'] = _text(changes['full_name']).strip()[:80] or user['full_name']
        if {'role', 'perms', 'extra_perms', 'denied_perms'} & set(changes):
            role = changes.get('role', user['role'])
            if not isinstance(role, str) or (role != CUSTOM and not self.profile(role)):
                raise AuthError('auth.err.role', 'Unknown profile.')
            ticks = self._ticks(role, effective_perms(user), changes)
            fields['role'] = self._role_for(role, ticks)
            fields['perms'] = json.dumps(ticks)
        if 'max_discount_pct' in changes:
            fields['max_discount_pct'] = _pct(changes['max_discount_pct'])
        if 'active' in changes:
            fields['active'] = 1 if changes['active'] else 0
        if 'password' in changes and changes['password']:
            strong_enough(changes['password'], user['username'], self.practice)
            fields['pass_hash'] = hash_password(changes['password'])
            fields['failed'], fields['locked_until'] = 0, None
        after = {**user, **fields}
        self._safe(actor_id, {user_id: {'active': bool(after['active']), 'perms': effective_perms(after)}})
        if fields:
            fields['changed_at'] = ids.iso()
            sets = ', '.join(f'{k} = ?' for k in fields)
            self.db.run(f'UPDATE users SET {sets} WHERE id = ?', *fields.values(), user_id)
        if 'pass_hash' in fields or fields.get('active') == 0:  # ticks need no new sign-in: they are read on every request
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
        if touch and not self.db.busy():  # "last seen" is a convenience: while another program holds the file it must not make reading wait or fail
            try:
                self.db.run('UPDATE sessions SET last_seen = ? WHERE token_hash = ?', ids.iso(now), row['token_hash'])
            except sqlite3.OperationalError:
                self.db.mark_busy()
        return user

    def end_session(self, token):
        self.db.run('UPDATE sessions SET ended = 1 WHERE token_hash = ?', _h(token or ''))

    def end_sessions(self, user_id):
        self.db.run('UPDATE sessions SET ended = 1 WHERE user_id = ?', user_id)

    # ---------------------------------------------------------------- recovery code (forgotten owner password)
    def recovery_holder(self):
        """The id of the person the recovery code belongs to, or None when no code was made."""
        row = self.db.value("SELECT value FROM meta WHERE key = 'recovery'")
        return json.loads(row)['user_id'] if row else None

    def new_recovery(self, user_id):
        """Makes a new code for this person and forgets the old one. Returns the code to show once."""
        raw = ''.join(secrets.choice(RECOVERY_ALPHABET) for _ in range(16))  # 16 of 31 letters: about 79 bits
        value = json.dumps({'user_id': user_id, 'hash': hash_password(raw), 'made_at': ids.iso()})
        self.db.run("INSERT INTO meta(key, value) VALUES ('recovery', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    value)
        return '-'.join(raw[i:i + 4] for i in range(0, 16, 4))

    def recover(self, code, new_password):
        """Right code: sets the password, unlocks and switches the person on, ends their sessions and makes a new code.
        Returns (user, new code). Wrong code: AuthError, counted by the caller like a wrong password."""
        row = self.db.value("SELECT value FROM meta WHERE key = 'recovery'")
        typed = ''.join(c for c in str(code or '').upper() if c.isalnum())
        held = json.loads(row) if row else None
        if not held:
            check_password(typed, _DUMMY)  # same time as a wrong code
        if not held or len(typed) != 16 or not check_password(typed, held['hash']):
            raise AuthError('auth.err.recovery', 'This recovery code is not right.')
        user = self.get(held['user_id'])
        if not user:
            raise AuthError('auth.err.recovery', 'This recovery code is not right.')
        self.update(user['id'], {'password': new_password, 'active': True})
        return self.get(user['id']), self.new_recovery(user['id'])

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
