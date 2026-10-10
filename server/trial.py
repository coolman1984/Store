"""Ask the company for a trial (or a paid code) from the licence screen, and switch the program on with the answer: no copying.

The shop sends the company a small request through the vendor's relay (templates/telemetry-relay in the Apps Factory): its device code,
a tag of this PC, the shop name and the version. Nothing else: no sales, no customers, no names of people, no amounts. The owner's phone is
told on Telegram; the owner's trusted licensing program signs a code for THIS device code and puts it back on the relay. This program asks
for the answer, checks the code with the vendor's PUBLIC key (licence.activate: signature, product, device, dates), saves it, and tells
the relay it has it. The relay is not trusted: a wrong, other-PC or forged code is refused here exactly as a pasted one is.

- The request keeps its own id (`nonce`): sending it again after a lost answer creates nothing new.
- One trial per PC: the machine tag does not change when the program is reinstalled, so the company refuses a second trial.
- Offline or the relay down: the state says so, retries back off (1, 5, 15, 60 minutes), a button retries at once, and the manual way
  (device code out, code in) is always on the same screen. The program keeps working in read / print / export / backup mode meanwhile.
- The relay address is public configuration: `STORE_LICENCE_RELAY`, or `licence_relay.txt` next to `licence_keys.txt`, or `licence_relay` in config.json.
  Without one the button says so and only the manual way is offered.
"""
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import timedelta
from urllib.parse import urlparse

import core
import ids
import licence
from core import Problem
from version import PRODUCT_ID, ROOT, VERSION

KINDS = ('trial', 'monthly', 'permanent')
BACKOFF = (60, 300, 900, 3600)  # seconds between tries while the relay cannot be reached
POLL = ((600, 20), (3600, 120), (10 ** 9, 600))  # (age of the request in seconds, seconds between looks): quick at first, calmer later
SENT_FIELDS = ('product', 'kind', 'device', 'machine', 'nonce', 'shop', 'ref', 'version')  # exactly this goes out: shown on the screen first
ACTIVE = ('sending', 'waiting', 'failed')
MANUAL_KEY = 'licence_manual_at'  # when a person last pasted a working code by hand: a late answer to an older request never replaces it
# Lock order, everywhere: this module's lock first, then the database. `step` holds the lock across the network call, so nothing may take
# the lock while it holds the database (a request typed during a slow relay answer once froze the whole shop that way: review of PR #17).
_lock = threading.Lock()


def relay_url(app=None):
    """The relay's address (public), or ''. Always https, except a program on this PC (tests). The practice shop never asks."""
    if app is not None and app.practice:
        return ''
    url = os.environ.get('STORE_LICENCE_RELAY', '').strip()
    if not url and app is not None:
        url = str(app.cfg.get('licence_relay') or '').strip()
    if not url:
        try:
            with open(os.path.join(ROOT, 'licence_relay.txt'), encoding='utf-8') as f:
                for line in f:
                    line = line.split('#', 1)[0].strip()
                    if line:
                        url = line
                        break
        except OSError:
            pass
    url = url.rstrip('/')
    parts = urlparse(url)
    local = parts.hostname in ('127.0.0.1', 'localhost', '::1')
    if not url or parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or (parts.scheme == 'http' and not local):
        return ''
    return url


def machine_tag():
    """A fingerprint of this PC for the one-trial-per-PC rule. It does not change when the program is reinstalled, and it is a hash:
    the PC's own identity never leaves it."""
    ident = os.environ.get('STORE_DEVICE_ID') or licence._machine_id()
    return hashlib.sha256(f'AF-MACHINE/1|{ident}|{PRODUCT_ID}'.encode('utf-8')).hexdigest()


def _meta(db, value=None, clear=False):
    if clear:
        db.run("DELETE FROM meta WHERE key = 'licence_request'")
        return None
    if value is None:
        raw = db.value("SELECT value FROM meta WHERE key = 'licence_request'")
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None
    db.run("INSERT INTO meta(key, value) VALUES ('licence_request', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", json.dumps(value))
    return value


def public(app):
    """What the screen may see (never the poll token)."""
    st = _meta(app.db)
    base = {'available': bool(relay_url(app)), 'fields': list(SENT_FIELDS)}
    if not st:
        return {**base, 'status': 'none'}
    keep = ('status', 'kind', 'reason', 'created_at', 'tries', 'next_try', 'error', 'serial', 'stage')
    out = {**base, **{k: st.get(k) for k in keep}}
    if out['status'] != 'waiting' or out.get('error'):
        out['stage'] = ''  # "the company approved" is only a word for a request that is still waiting and reachable
    if out['status'] in ACTIVE + ('issued',) and _superseded(app.db, st):
        out.update(status='closed', reason='manual', error='')  # what the next look will record; the screen need not wait for it
    return out


def preview(app, kind, ref=''):
    """Exactly what a request would send, for the person to read before pressing the button."""
    return _body(app, kind, ref, 'preview')


def _body(app, kind, ref, nonce):
    return {'product': PRODUCT_ID, 'kind': kind, 'device': licence.device(app.db), 'machine': machine_tag(),
            'nonce': nonce, 'shop': core.settings(app.db)['shop_name'][:60], 'ref': ref[:60], 'version': VERSION}


def _call(method, url, body=None, token=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json', 'User-Agent': f'AlStore/{VERSION}',
                                          **({'Authorization': 'Bearer ' + token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode('utf-8') or '{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8') or '{}')
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        raise ConnectionError(e.__class__.__name__) from None


def _soon(state, seconds):
    state['next_try'] = ids.iso(ids.utcnow() + timedelta(seconds=seconds))


def _failed(state, error):
    state['tries'] = state.get('tries', 0) + 1
    state.update(status='failed' if state.get('id') is None else 'waiting', error=error)
    _soon(state, BACKOFF[min(state['tries'] - 1, len(BACKOFF) - 1)])


def note_manual(db):
    """Called inside the transaction that saved a code pasted by hand. Takes no lock of this module (see the lock order above)."""
    db.run('INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', MANUAL_KEY, ids.iso())


def _superseded(db, st):
    """A code was pasted by hand after this request was made: that code is the one the person chose."""
    manual = db.value('SELECT value FROM meta WHERE key = ?', MANUAL_KEY)
    return bool(manual and st.get('created_at') and manual >= st['created_at'])


def begin(app, ctx, kind, ref=''):
    """The button, first half: record the request in its own short transaction (no network). Idempotent: a request that is still
    running is returned, not repeated. The caller then calls `step`: the shop's database is never locked by the internet."""
    if kind not in KINDS:
        raise Problem('err.badRequest', 'The request is not understood.', 400)
    if not relay_url(app):
        raise Problem('err.trialOff', 'This copy cannot ask the company by itself. Send the device code to the company and paste the code.', 409)
    with _lock, app.db.tx():
        st = _meta(app.db)
        if st and st.get('status') in ACTIVE + ('issued',):
            return public(app)
        if kind == 'trial' and licence.status(app.db)['full']:
            raise Problem('err.trialHave', 'This PC already has a working licence.', 409)
        st = {'status': 'sending', 'kind': kind, 'nonce': str(uuid.uuid4()), 'ref': str(ref or '').strip()[:60], 'id': None, 'poll_token': None,
              'created_at': ids.iso(), 'by': ctx.uid, 'tries': 0, 'error': '', 'reason': ''}
        _meta(app.db, st)
        ctx.audit('licence.request', 'licence', st['nonce'], {'kind': kind, 'device': licence.device(app.db)})
    return public(app)


def clear(app, ctx):
    """Forget a refused, failed or finished request so a new one can be made."""
    with _lock, app.db.tx():
        st = _meta(app.db)
        if st and st.get('status') in ('refused', 'failed', 'activated', 'closed'):
            _meta(app.db, clear=True)
            ctx.audit('licence.request.clear', 'licence', st.get('nonce') or '', {'status': st.get('status')})
    return public(app)


def step(app, now=None, force=False):
    """One look: send the request, or ask for the answer. Never raises; the state says what happened."""
    with _lock:
        st = _meta(app.db)
        if not st or st.get('status') not in ACTIVE + ('issued',):
            return public(app)
        if _superseded(app.db, st):
            st.update(status='closed', reason='manual', error='', poll_token=None)
            _meta(app.db, st)
            return public(app)
        now = now or ids.utcnow()
        due = ids.parse(st.get('next_try'))
        if not force and due and now < due:
            return public(app)
        url = relay_url(app)
        if not url:
            st.update(status='failed', error='relay_off')
            _meta(app.db, st)
            return public(app)
        try:
            if not st.get('id'):
                code, d = _call('POST', url + '/licence/request', _body(app, st['kind'], st.get('ref', ''), st['nonce']))
                if code == 429 or code == 503:
                    _failed(st, 'busy')
                elif code == 400:
                    st.update(status='failed', error='refused_input:' + str(d.get('field', '')))
                elif d.get('replay') and not d.get('poll_token'):
                    # the answer to our first try was lost and the request is already there: we cannot read it without the token
                    # (a replay never learns it). A new nonce makes a new request; the relay hands over a waiting code or refuses a used trial.
                    st.update(nonce=str(uuid.uuid4()), stage='')
                    _soon(st, 5)
                else:
                    st.update(id=d.get('id'), poll_token=d.get('poll_token'), status='waiting', error='', tries=0, reason=d.get('reason', ''), stage='')
                    if d.get('status') == 'refused':
                        st.update(status='refused', reason=d.get('reason', 'refused'))
                    _soon(st, 5)
            else:
                code, d = _call('GET', url + '/licence/status?id=' + st['id'], token=st['poll_token'])
                if code == 401:
                    st.update(status='failed', error='token', id=None, poll_token=None, nonce=str(uuid.uuid4()), stage='')
                elif code != 200:
                    _failed(st, f'http_{code}')
                elif d.get('status') == 'issued':
                    _activate(app, st, url, d.get('code'))
                elif d.get('status') == 'refused':
                    st.update(status='refused', reason=d.get('reason') or 'refused', error='', stage='')
                elif d.get('status') in ('expired',):
                    st.update(status='closed', reason='expired', error='', stage='')
                elif d.get('status') == 'delivered':
                    st.update(status='activated' if licence.status(app.db)['full'] else 'closed', reason='delivered', error='')
                else:
                    age = (now - (ids.parse(st['created_at']) or now)).total_seconds()
                    # `stage: approved` = the company's owner agreed and the code is on its way: said on the screen, but never a licence
                    st.update(status='waiting', error='', stage='approved' if d.get('stage') == 'approved' else '')
                    _soon(st, next(wait for limit, wait in POLL if age < limit))
        except ConnectionError as e:
            _failed(st, 'offline:' + str(e))
        _meta(app.db, st)
        return public(app)


class _Manual(Exception):
    pass


def _activate(app, st, url, code):
    """The answer arrived: check it exactly like a pasted code. Only a code that works is saved, and only then does the relay forget it."""
    try:
        with app.db.tx():
            if _superseded(app.db, st):  # checked inside the transaction: a code pasted a moment ago always wins
                raise _Manual()
            lic = licence.activate(app.db, code)
            app.db.insert('audit', {'id': ids.uuid7(), 'at': ids.iso(), 'user_id': st.get('by') or '', 'user_name': 'licence', 'ip': '',
                                    'action': 'licence.auto', 'entity': 'licence', 'entity_id': lic.get('serial') or '',
                                    'detail': json.dumps({'state': lic['state'], 'last_day': lic.get('last_day'), 'kind': st['kind']})})
    except _Manual:
        st.update(status='closed', reason='manual', error='', poll_token=None)
        return
    except ValueError as e:
        st.update(status='failed', error='code:' + str(e), reason=str(e))  # shown with the manual way; the relay keeps the code
        _soon(st, 900)
        return
    try:
        _call('POST', url + '/licence/ack', {'id': st['id']}, token=st['poll_token'])
    except ConnectionError:
        pass  # the code is saved and working; the relay drops it by itself after two weeks
    st.update(status='activated', serial=lic.get('serial'), error='', poll_token=None)


def loop(app, every=20):
    """Background: look for the answer while a request is open, even when nobody has the page open."""
    while True:
        try:
            st = _meta(app.db)
            if st and st.get('status') in ACTIVE + ('issued',):
                step(app)
        except Exception:  # never let this reach the shop
            pass
        time.sleep(every)
