"""The practice shop and the real shop never share anything: not a folder, not a database, not a browser cookie, not a network call.

The practice shop is a made-up appliance shop (sample.py) that the owner or a new cashier can break and rebuild without fear. It runs as its
own program instance on its own port (127.0.0.1 only) and in its own folder. This file holds the three things that keep it apart:

- a folder of one kind is never opened as the other kind (`guard`): the made-up shop on real data, or the real shop on made-up data, stops
  with a plain message instead of mixing them;
- the real shop can start the practice shop for the person who asks (`launch`), and tell whether it is running (`status`);
- the made-up shop can be thrown away and rebuilt (`App.reset_practice` uses `mark`, `MARKER`).
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from core import Problem
from version import FROZEN, PRODUCT, ROOT

PORT = 8097
KIND_KEY = 'shop_kind'
MARKER = 'PRACTICE.txt'  # written into a practice folder; the reset refuses a folder that does not carry it
_lock = threading.Lock()
_child = None


class WrongShop(Exception):
    """A folder of the other kind was opened. `key` says which."""

    def __init__(self, key):
        super().__init__(key)
        self.key = key

    def words(self):
        return {'practice_on_real': 'هذا مجلد محل حقيقي، ومحل التدريب لا يفتحه أبدًا. شغّل التدريب من زر «المساعدة» داخل البرنامج.',
                'real_on_practice': 'هذا مجلد محل التدريب (بيانات وهمية)، والمحل الحقيقي لا يفتحه. افتح مجلد محلك الحقيقي.'}[self.key]


def home_for(real_home):
    """The practice shop's folder, beside the real shop's: the same name with `-practice` after it."""
    return real_home.rstrip('/\\') + '-practice'


def kind_of(db):
    return db.value('SELECT value FROM meta WHERE key = ?', KIND_KEY)


def mark(db):
    db.run("INSERT INTO meta(key, value) VALUES (?, 'practice') ON CONFLICT(key) DO UPDATE SET value = excluded.value", KIND_KEY)


def _was_practice_before_marks(db):
    """A practice folder made by an older version has no mark. It is recognised only by all four made-up accounts and the made-up shop name."""
    import core as core_mod
    import sample
    names = {r['username'] for r in db.all('SELECT username FROM users')}
    return all(u[0] in names for u in sample.DEMO_USERS) and core_mod.settings(db)['shop_name'] == sample.SHOP_NAME


def write_marker(home):
    try:
        with open(os.path.join(home, MARKER), 'w', encoding='utf-8') as f:
            f.write('Made-up shop for training. Nothing here is real. It is safe to delete this folder.\n')
    except OSError:
        pass


def guard(db, practice, home):
    """Called when a program instance opens its folder. Raises WrongShop before anything is read or written for a person."""
    kind = kind_of(db)
    people = db.value('SELECT COUNT(*) FROM users') or 0
    if practice:
        if people and kind != 'practice':
            if not _was_practice_before_marks(db):
                raise WrongShop('practice_on_real')
            mark(db)
        if people or kind == 'practice':
            write_marker(home)
    elif kind == 'practice':
        raise WrongShop('real_on_practice')


def port_of(app):
    try:
        return int(app.cfg.get('practice_port') or PORT)
    except (TypeError, ValueError):
        return PORT


def _probe(port):
    """What answers on the practice port: 'running' (our practice shop), 'other' (something else), or 'stopped'.
    Two steps, because Windows takes about two seconds to refuse a connection to a closed port: a connect that does not succeed in time
    means nobody is listening ('stopped'); only a listener that accepted the connection and then did not speak for us is 'other'."""
    try:
        socket.create_connection(('127.0.0.1', port), timeout=0.6).close()
    except OSError:  # refused, or too slow to refuse (Windows)
        return 'stopped'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f'http://127.0.0.1:{port}/api/boot', timeout=0.8) as r:
            d = json.loads(r.read(65536).decode('utf-8'))
        return 'running' if d.get('practice') is True and d.get('product') == PRODUCT else 'other'
    except (urllib.error.URLError, OSError, ValueError):  # it accepted the connection but is not our practice shop (or never answered)
        return 'other'


def status(app):
    """For the real shop's Help page. 'starting' = we started it and it has not answered yet."""
    port = port_of(app)
    state = _probe(port)
    if state == 'stopped' and _child is not None and _child.poll() is None:
        state = 'starting'
    return {'state': state, 'url': f'http://127.0.0.1:{port}/' if state in ('running', 'starting') else ''}


def alive(pid):
    """Is that program still running? (Never os.kill(pid, 0) on Windows: there any signal ends the program.)"""
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102  # still waiting = still running
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def follow(pid, stop, every=3):
    """In the practice shop that the real shop started: leave when the real shop leaves, so no hidden program is left holding files
    (an update of the installed program would fail on a running one)."""
    def watch():
        while True:
            time.sleep(every)
            if not alive(pid):
                stop()
                return
    threading.Thread(target=watch, daemon=True).start()


def _command(home, port):
    args = ['--practice', '--no-browser', '--home', home, '--port', str(port), '--host', '127.0.0.1', '--parent', str(os.getpid())]
    return [sys.executable, *args] if FROZEN else [sys.executable, os.path.join(ROOT, 'server', 'app.py'), *args]


def launch(app):
    """Start the practice shop for a person who asked, unless it already runs. Its folder is beside this shop's, never this shop's."""
    global _child
    st = status(app)
    if st['state'] in ('running', 'starting'):
        return st
    if st['state'] == 'other':
        raise Problem('err.practicePort', 'Another program is using the practice shop\'s port.', 409)
    home = home_for(app.home)
    port = port_of(app)
    env = {k: v for k, v in os.environ.items() if k not in ('STORE_HOME', 'STORE_PRACTICE_HOME')}
    flags = {}
    if os.name == 'nt':
        flags['creationflags'] = 0x08000000 | 0x00000200  # no console window, own process group
    else:
        flags['start_new_session'] = True
    with _lock:
        if _child is None or _child.poll() is not None:
            _child = subprocess.Popen(_command(home, port), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, cwd=ROOT, **flags)
    return {'state': 'starting', 'url': f'http://127.0.0.1:{port}/'}
