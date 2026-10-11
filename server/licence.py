"""Is this copy allowed to sell today? The licence code pasted by the shop, checked on this PC.

- The vendor's Licence Studio (Apps-Factory apps/licence-studio) signs a code for this PC's device code.
  A trial's length is whatever the company signs into the code (14 days unless it set another for the product). A new code is needed after that.
- Only the vendor's public keys are inside the program (licence_keys.txt). They cannot make codes.
- Without a working code the shop can still open everything, read, print, export and back up (constitution 8):
  only actions that change data are refused, with a clear message and the device code to send to the vendor.
- A clock moved back by more than a day locks changes until the clock is right again (simple tamper evidence).
"""
import os
import platform
import secrets
import subprocess
import threading
from datetime import date, timedelta

import afcodes
import ids
from version import PRODUCT_ID, ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(ROOT, 'licence_keys.txt')
CLOCK_TOLERANCE_HOURS = 24
_lock = threading.Lock()
_cache = {}


def trusted_keys():
    keys = [k.strip() for k in os.environ.get('STORE_LICENCE_KEYS', '').split(',') if k.strip()]
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                if line:
                    keys.append(line.split(':', 1)[-1])  # accepts "kid:key" or "key"
    return keys


def _machine_id():
    """A value that stays the same on this PC and differs between PCs. Never personal data."""
    if platform.system() == 'Windows':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                return winreg.QueryValueEx(k, 'MachineGuid')[0]
        except OSError:
            pass
    for path in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
        try:
            with open(path, encoding='ascii') as f:
                value = f.read().strip()
                if value:
                    return value
        except OSError:
            pass
    if platform.system() == 'Darwin':
        try:
            out = subprocess.run(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                if 'IOPlatformUUID' in line:
                    return line.split('"')[-2]
        except (OSError, subprocess.SubprocessError):
            pass
    return platform.node() or 'unknown'


def install_id(db):
    value = db.value("SELECT value FROM meta WHERE key = 'install_id'")
    if not value:
        value = secrets.token_hex(16)
        db.run("INSERT OR IGNORE INTO meta(key, value) VALUES ('install_id', ?)", value)
        value = db.value("SELECT value FROM meta WHERE key = 'install_id'")
    return value


def device(db):
    override = os.environ.get('STORE_DEVICE_ID')  # tests only: a fixed identity for a fake PC
    return afcodes.device_code(override or _machine_id(), install_id(db), PRODUCT_ID)


def _meta(db, key, value=None):
    if value is None:
        return db.value('SELECT value FROM meta WHERE key = ?', key)
    db.run('INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', key, value)


def seen_now(db):
    """Remember the latest time this PC has shown, to notice a clock moved back."""
    now = ids.utcnow()
    last = ids.parse(_meta(db, 'max_seen'))
    if not last or now > last:
        if not last or now - last > timedelta(minutes=5):  # a write at most every few minutes
            _meta(db, 'max_seen', ids.iso(now))
        return False
    return now < last - timedelta(hours=CLOCK_TOLERANCE_HOURS)


def status(db):
    """{'state', 'full', 'device', 'edition', 'first_day', 'last_day', 'days_left', 'reason'} – cached per code and day."""
    code = _meta(db, 'licence_code') or ''
    dev = device(db)
    clock_back = seen_now(db)
    today = date.fromisoformat(ids.local_day())
    key = (code, dev, today, tuple(trusted_keys()))
    with _lock:
        cached = _cache.get('v')
        if cached and cached[0] == key:
            result = dict(cached[1])
        else:
            result = _check(code, dev, today)
            _cache['v'] = (key, dict(result))
    if clock_back and result['full']:
        result.update(state='clock_back', full=False, reason='clock_back')
    return result


def _check(code, dev, today):
    base = {'device': dev, 'full': False, 'edition': None, 'first_day': None, 'last_day': None, 'days_left': None,
            'serial': None, 'reason': ''}
    keys = trusted_keys()
    if not keys:
        return {**base, 'state': 'no_keys', 'reason': 'no_keys'}
    if not code:
        return {**base, 'state': 'none', 'reason': 'no_code'}
    r = afcodes.read_code(code, keys, PRODUCT_ID, dev, today)
    out = {**base, 'state': r.state, 'full': r.full_access, 'reason': r.reason}
    out.update({k: r.terms.get(k) for k in ('edition', 'first_day', 'last_day', 'days_left', 'serial') if k in r.terms})
    if r.state == 'active' and r.terms.get('edition') == 'trial':
        out['state'] = 'trial'
    return out


def activate(db, code):
    """Check a pasted code before saving it. Returns the new status, or raises ValueError with the reason."""
    dev = device(db)
    code = code if isinstance(code, str) else ''
    result = _check(code, dev, date.fromisoformat(ids.local_day()))
    if result['state'] == 'none':  # an empty box must never wipe the working code
        raise ValueError('no_code')
    if result['state'] in ('invalid', 'no_keys'):
        raise ValueError(result['reason'] or 'invalid')
    if result['state'] == 'expired':
        raise ValueError('expired')
    _meta(db, 'licence_code', afcodes.group(afcodes.normalize(code)))
    with _lock:
        _cache.clear()
    return status(db)
