"""Is this copy allowed to sell today? The licence code pasted by the shop, checked on this PC.

- The vendor's Licence Studio (Apps-Factory apps/licence-studio) signs a code for this PC's device code.
  A trial's length is whatever the company signs into the code (14 days unless it set another for the product). A new code is needed after that.
- Only the vendor's public keys are inside the program (licence_keys.txt). They cannot make codes.
- Without a working code the shop can still open everything, read, print, export and back up (constitution 8):
  only actions that change data are refused, with a clear message and the device code to send to the vendor.
- A clock moved back by more than a day locks changes until the clock is right again (simple tamper evidence).
- When online, the licence relay's calendar day is remembered: a local date before that is treated as rollback; a hub
  date past the signed last day (plus grace) locks even if the PC clock lies. Offline or failed checks never lock.
"""
import email.utils
import os
import platform
import secrets
import subprocess
import threading
import urllib.request
from datetime import date, datetime, time as dt_time, timedelta, timezone

import afcodes
import ids
from version import PRODUCT_ID, ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(ROOT, 'licence_keys.txt')
CLOCK_TOLERANCE_HOURS = 24
META_TRUSTED = 'licence_trusted_date'
META_ONLINE = 'licence_online_at'
TRIAL_HUB_KIDS = frozenset({'trial-hub', 'trial_hub', 'hub-trial'})
_lock = threading.Lock()
_cache = {}


def _parse_key_entry(raw):
    raw = raw.strip()
    if not raw:
        return None
    if ':' in raw and len(raw.split(':', 1)[0]) <= 40:
        kid, key = raw.split(':', 1)
        return kid.strip(), key.strip()
    return '', raw


def trusted_key_entries():
    """(kid, public key) pairs — kid is '' when the line is key-only."""
    entries = []
    for raw in os.environ.get('STORE_LICENCE_KEYS', '').split(','):
        entry = _parse_key_entry(raw)
        if entry:
            entries.append(entry)
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                entry = _parse_key_entry(line)
                if entry:
                    entries.append(entry)
    return entries


def trusted_keys():
    return [key for _, key in trusted_key_entries()]


def trial_only_public_keys():
    """Public keys that may sign device-bound trials of at most 14 days only (licence hub)."""
    keys = set()
    for kid, key in trusted_key_entries():
        if kid and kid.lower() in TRIAL_HUB_KIDS:
            keys.add(key)
    for raw in os.environ.get('STORE_TRIAL_HUB_KEYS', '').split(','):
        entry = _parse_key_entry(raw)
        if entry:
            keys.add(entry[1])
    return frozenset(keys)


def parse_server_moment(value):
    """A calendar moment from the licence hub (ISO date or date-time). None when unknown."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        s = str(value)
        if 'T' in s:
            moment = datetime.fromisoformat(s[:19])
        else:
            moment = datetime.combine(date.fromisoformat(s[:10]), dt_time(12, 0))
        return moment
    except (ValueError, TypeError):
        return None


def probe_http_date(url, timeout=10, opener=None):
    """Lightweight online check: HTTPS Date header from the relay (fail-open: None on any error)."""
    url = (url or '').rstrip('/')
    if not url:
        return None
    try:
        req = urllib.request.Request(url + '/', method='HEAD')
        open_ = opener or urllib.request.urlopen
        with open_(req, timeout=timeout) as resp:
            raw = resp.headers.get('Date')
        if not raw:
            return None
        return email.utils.parsedate_to_datetime(raw).astimezone().replace(tzinfo=None)
    except Exception:
        return None


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


def trusted_day(db):
    raw = _meta(db, META_TRUSTED)
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def note_online(db, server_moment):
    """Trusted hub time (polling or HTTPS Date). Fail-open: None does nothing; never locks because the network failed."""
    when = parse_server_moment(server_moment)
    if when is None:
        return
    day = when.date()
    prev = trusted_day(db)
    if prev is None or day > prev:
        _meta(db, META_TRUSTED, day.isoformat())
    if 'T' in str(server_moment):
        mark = when.astimezone(timezone.utc) if when.tzinfo else when.replace(tzinfo=timezone.utc)
    else:
        mark = datetime.combine(day, dt_time(12, 0), tzinfo=timezone.utc)
    last = ids.parse(_meta(db, 'max_seen'))
    mark_utc = mark if mark.tzinfo else mark.replace(tzinfo=timezone.utc)
    if not last or mark_utc > last:
        _meta(db, 'max_seen', ids.iso(mark_utc))
    _meta(db, META_ONLINE, ids.iso(ids.utcnow()))
    with _lock:
        _cache.clear()


def _billing_day(today, trust):
    """Calendar day used for last_day/grace: local, raised by a trusted hub date when the PC is not behind the hub."""
    if trust and today < trust:
        return today
    return max(today, trust) if trust else today


def _local_before_trusted(today, trust):
    return bool(trust and today < trust)


def seen_now(db):
    """Remember the latest time this PC has shown, to notice a clock moved back."""
    now = ids.utcnow()
    last = ids.parse(_meta(db, 'max_seen'))
    trust = trusted_day(db)
    if trust:
        trust_mark = datetime.combine(trust, dt_time(12, 0), tzinfo=timezone.utc)
        if not last or trust_mark > last:
            last = trust_mark
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
    trust = trusted_day(db)
    key = (code, dev, today, trust, tuple(trusted_keys()))
    with _lock:
        cached = _cache.get('v')
        if cached and cached[0] == key:
            result = dict(cached[1])
        else:
            result = _check(code, dev, today, trust)
            _cache['v'] = (key, dict(result))
    if _local_before_trusted(today, trust) and not clock_back:
        clock_back = True
    if clock_back and result['full']:
        result.update(state='clock_back', full=False, reason='clock_back')
    return result


def _check(code, dev, today, trust=None):
    base = {'device': dev, 'full': False, 'edition': None, 'first_day': None, 'last_day': None, 'days_left': None,
            'serial': None, 'reason': '', 'grace_days': None}
    keys = trusted_keys()
    if not keys:
        return {**base, 'state': 'no_keys', 'reason': 'no_keys'}
    if not code:
        return {**base, 'state': 'none', 'reason': 'no_code'}
    billing = _billing_day(today, trust)
    if trust and today < trust:
        hub_billing = trust
        r_hub = afcodes.read_code(code, keys, PRODUCT_ID, dev, hub_billing, trial_only_keys=trial_only_public_keys())
        if r_hub.valid and r_hub.terms.get('edition') != 'perpetual':
            if r_hub.state == 'expired':
                out = _from_read(r_hub, base)
                return out
    r = afcodes.read_code(code, keys, PRODUCT_ID, dev, billing, trial_only_keys=trial_only_public_keys())
    return _from_read(r, base)


def _from_read(r, base):
    out = {**base, 'state': r.state, 'full': r.full_access, 'reason': r.reason}
    out.update({k: r.terms.get(k) for k in ('edition', 'first_day', 'last_day', 'days_left', 'serial', 'grace_days') if k in r.terms})
    if r.state == 'active' and r.terms.get('edition') == 'trial':
        out['state'] = 'trial'
    return out


def activate(db, code):
    """Check a pasted code before saving it. Returns the new status, or raises ValueError with the reason."""
    dev = device(db)
    code = code if isinstance(code, str) else ''
    today = date.fromisoformat(ids.local_day())
    trust = trusted_day(db)
    if _local_before_trusted(today, trust) or seen_now(db):
        raise ValueError('clock_back')
    result = _check(code, dev, today, trust)
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
