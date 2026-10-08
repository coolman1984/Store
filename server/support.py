"""Optional heartbeat to the vendor's Control Center (Apps-Factory apps/control-center), so a problem is seen before the shop calls.

Rules (factory SUP-01..04, constitution privacy):
- Off until the owner switches it on. The address and the install token live in `support.json` next to the data, never in the
  shop database, never in a log.
- Exactly these fields are sent, nothing else (the Control Center refuses any extra field): version, licence state, last backup
  time, error count of the last 24 hours, free disk space. No sales, no customers, no names, no prices.
- A failed send is remembered and shown, never raised: the counter never waits for the internet.
"""
import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import backup
import ids
from core import Problem
from version import VERSION

SENT_FIELDS = ('version', 'licence_state', 'last_backup_at', 'error_count', 'disk_free_mb')
STATE_FOR_CONTROL_CENTER = {'trial': 'active', 'active': 'active', 'grace': 'grace', 'expired': 'expired', 'not_yet_valid': 'not_yet_valid',
                            'invalid': 'invalid', 'clock_back': 'invalid', 'none': 'none', 'no_keys': 'none', 'practice': 'none'}
_lock = threading.Lock()
_last = {}


def _file(home):
    return os.path.join(home, 'support.json')


def load(home):
    try:
        with open(_file(home), encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    return {'enabled': bool(cfg.get('enabled')), 'url': str(cfg.get('url') or ''), 'token': str(cfg.get('token') or '')}


def save(home, enabled, url, token=None):
    cfg = load(home)
    url = (url or '').strip().rstrip('/')
    if url:
        parts = urlparse(url)
        local = parts.hostname in ('127.0.0.1', 'localhost', '::1')
        if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or (parts.scheme == 'http' and not local):
            raise Problem('err.supportUrl', 'The support address must start with https://', 400)
        cfg['url'] = url
    elif url == '':
        cfg['url'] = ''
    if token:
        if not isinstance(token, str) or len(token) < 16 or len(token) > 200 or any(ch.isspace() for ch in token):
            raise Problem('err.supportToken', 'The support code is not valid.', 400)
        cfg['token'] = token
    cfg['enabled'] = bool(enabled)
    if cfg['enabled'] and not (cfg['url'] and cfg['token']):
        raise Problem('err.supportIncomplete', 'Write the support address and code first.', 400)
    tmp = _file(home) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, _file(home))


def public(home):
    cfg = load(home)
    return {'enabled': cfg['enabled'], 'url': cfg['url'], 'has_token': bool(cfg['token']), 'last': dict(_last), 'fields': list(SENT_FIELDS)}


def payload(app):
    newest = backup.listing(app.backup_dir)
    return {'version': VERSION,
            'licence_state': STATE_FOR_CONTROL_CENTER.get(app.licence().get('state'), 'none'),
            'last_backup_at': newest[0]['mtime'] if newest else None,
            'error_count': app.recent_errors(),
            'disk_free_mb': int(shutil.disk_usage(app.data_dir).free // 1048576)}


def send(app):
    cfg = load(app.home)
    if not (cfg['enabled'] and cfg['url'] and cfg['token']):
        raise Problem('err.supportOff', 'Support sharing is switched off.', 409)
    body = payload(app)
    assert set(body) == set(SENT_FIELDS)
    req = urllib.request.Request(cfg['url'] + '/api/agent/heartbeat', data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'X-Install-Token': cfg['token']})
    result = {'at': ids.iso(), 'ok': False, 'error': '', 'repairs_waiting': 0}
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            answer = json.loads(r.read().decode('utf-8') or '{}')
        result.update(ok=True, repairs_waiting=int(answer.get('repairs_waiting') or 0))
    except urllib.error.HTTPError as e:
        result['error'] = f'http {e.code}'
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        result['error'] = e.__class__.__name__
    with _lock:
        _last.clear()
        _last.update(result)
    return result


def loop(app, every_seconds=6 * 3600):
    """Background sender: first beat a minute after start, then every few hours; silent when switched off or offline."""
    time.sleep(60)
    while True:
        try:
            if load(app.home)['enabled']:
                send(app)
        except Exception:  # never let a support problem reach the shop
            pass
        time.sleep(every_seconds)
