"""The paid journey on a built (or source) program, in a real shop folder, before and after an update (factory REL-03, OPS-07).

    python tools/journey_exe.py first <home> "C:\\Program Files\\Al-Store\\Al-Store.exe"
    (run the newer installer over the installed program)
    python tools/journey_exe.py after <home> "C:\\Program Files\\Al-Store\\Al-Store.exe"

`first`: sets up a real (not practice) shop, activates it with a test licence code, adds a product, receives stock, opens a
shift, sells for cash, takes a backup and stops the program. `after`: starts the program on the same folder, signs in and
checks that the sale, the stock and the backup are still there and that it can still sell. Exit code 0 = good.
The signing key is made here for this run only (needs the `cryptography` package); only its public half reaches the program.
Also works on the source: python tools/journey_exe.py first <home> python server/app.py
"""
import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))
OWNER, PASSWORD = 'journey-owner', 'Journey Pass 7'


class Shop:
    def __init__(self, port):
        self.port, self.cookie = port, ''

    def call(self, method, path, body=None):
        headers = {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        if method == 'POST':
            headers['Origin'] = f'http://127.0.0.1:{self.port}'
        if self.cookie:
            headers['Cookie'] = self.cookie
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', json.dumps(body or {}).encode() if method == 'POST' else None,
                                     headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status, raw, set_cookie = r.status, r.read(), r.headers.get('Set-Cookie')
        except urllib.error.HTTPError as e:
            status, raw, set_cookie = e.code, e.read(), None
        if set_cookie:
            self.cookie = set_cookie.split(';', 1)[0]
        data = json.loads(raw) if raw else {}
        if status != 200:
            raise SystemExit(f'{method} {path} -> {status}: {data}')
        return data


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start(cmd, home, env):
    port = free_port()
    log = open(os.path.join(home, 'journey-output.txt'), 'a', encoding='utf-8', errors='replace')
    proc = subprocess.Popen([*cmd, '--no-browser', '--port', str(port), '--host', '127.0.0.1', '--home', home],
                            stdout=log, stderr=subprocess.STDOUT, env=env)
    for _ in range(120):
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/api/boot', timeout=5).read()
            return proc, Shop(port)
        except OSError:
            if proc.poll() is not None:
                raise SystemExit(f'the program stopped early with code {proc.returncode}')
            time.sleep(0.5)
    proc.kill()
    raise SystemExit('the program did not answer in 60 seconds')


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def first(home, cmd):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import afcodes
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode().rstrip('=')
    os.makedirs(home, exist_ok=True)
    practice_port = free_port()  # the practice shop of this run listens here, not on the usual port (the runner may use it)
    with open(os.path.join(home, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump({'practice_port': practice_port}, f)
    env = {**os.environ, 'STORE_LICENCE_KEYS': public}
    proc, shop = start(cmd, home, env)
    try:
        assert shop.call('GET', '/api/boot')['setup'] is True, 'a new folder must ask for setup'
        made = shop.call('POST', '/api/setup', {'username': OWNER, 'full_name': 'Journey', 'password': PASSWORD, 'shop_name': 'محل التجربة'})
        assert len(made['recovery_code']) == 19, 'setup must give the owner a recovery code'
        device = shop.call('GET', '/api/licence')['device']
        code = afcodes.issue_code(pem, 'al-store', 'standard', date.today(), 30, device, 3)['code']
        lic = shop.call('POST', '/api/licence/activate', {'code': code})
        assert lic['full'] and lic['edition'] == 'standard', lic
        assert shop.call('GET', '/api/lookups')['pay_methods'] == ['cash'], 'a new shop takes cash only'
        place = next(l['id'] for l in shop.call('GET', '/api/lookups')['locations'] if l['kind'] == 'shop')
        product = shop.call('POST', '/api/product/save', {'name': 'غلاية', 'retail': 50000, 'barcodes': ['622000000001']})['id']
        shop.call('POST', '/api/purchase', {'idem_key': 'journey-buy', 'location_id': place,
                                            'lines': [{'product_id': product, 'qty': 5, 'unit_cost': 40000}]})
        shop.call('POST', '/api/shift/open', {'opening_float': 20000})
        sale = shop.call('POST', '/api/pos/sell', {'idem_key': 'journey-sale-1', 'lines': [{'product_id': product, 'qty': 1}],
                                                   'payments': [{'method': 'cash', 'amount': 50000}], 'cash_received': 100000})
        assert sale['change'] == 50000, sale
        again = shop.call('POST', '/api/pos/sell', {'idem_key': 'journey-sale-1', 'lines': [{'product_id': product, 'qty': 1}],
                                                    'payments': [{'method': 'cash', 'amount': 50000}], 'cash_received': 100000})
        assert again['id'] == sale['id'], 'a retried sale must not record twice'
        kept = shop.call('POST', '/api/backup/now')
        json.dump({'public': public, 'product': product, 'sale': sale['number'], 'backup': kept['name']},
                  open(os.path.join(home, 'journey.json'), 'w'))
        print(f"OK first: shop set up, licensed (subscription), sold {sale['number']} for cash, backup {kept['name']}")
        # the practice shop from Help: it starts from this very program, in its own folder, with nothing of the real shop in it
        assert shop.call('GET', '/api/practice')['state'] == 'stopped'
        shop.call('POST', '/api/login', {'username': OWNER, 'password': PASSWORD})
        try:
            shop.call('POST', '/api/practice/open')
        except SystemExit:
            log_path = os.path.join(home, 'store.log')
            if os.path.exists(log_path):
                print('--- the shop log, last lines ---')
                print(''.join(open(log_path, encoding='utf-8', errors='replace').readlines()[-25:]))
            raise
        for _ in range(180):
            if shop.call('GET', '/api/practice')['state'] == 'running':
                break
            time.sleep(0.5)
        else:
            raise SystemExit('the practice shop did not start from the program in 90 seconds')
        boot = Shop(practice_port).call('GET', '/api/boot')
        assert boot['practice'] is True and boot['setup'] is False and boot['shop_name'] != 'محل التجربة', boot
        print(f'OK practice: started from the program on port {practice_port}, made-up shop {ascii(boot["shop_name"])}')  # ascii(): a Windows console may not print Arabic
    finally:
        stop(proc)
    # it must leave with the real shop, or it would hold the installed program's files and the next update would fail
    for _ in range(60):
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{practice_port}/api/boot', timeout=2).read()
            time.sleep(0.5)
        except OSError:
            print('OK practice: gone with the real shop')
            break
    else:
        raise SystemExit('the practice shop stayed behind after the real shop stopped')


def after(home, cmd):
    state = json.load(open(os.path.join(home, 'journey.json')))
    proc, shop = start(cmd, home, {**os.environ, 'STORE_LICENCE_KEYS': state['public']})
    try:
        assert shop.call('GET', '/api/boot')['setup'] is False, 'the update must keep the shop'
        shop.call('POST', '/api/login', {'username': OWNER, 'password': PASSWORD})
        sales = shop.call('GET', '/api/sales')
        items = sales['items'] if isinstance(sales, dict) else sales
        assert any(s['number'] == state['sale'] for s in items), 'the sale made before the update is missing'
        on_hand = shop.call('GET', '/api/product?id=' + state['product'])['on_hand']
        assert on_hand == 4, f'5 received - 1 sold must leave 4, found {on_hand}'
        names = [b['name'] for b in shop.call('GET', '/api/settings')['backups']]
        assert state['backup'] in names, 'the backup made before the update is missing'
        sale = shop.call('POST', '/api/pos/sell', {'idem_key': 'journey-sale-2', 'lines': [{'product_id': state['product'], 'qty': 1}],
                                                   'payments': [{'method': 'cash', 'amount': 50000}]})
        print(f"OK after: {state['sale']} and backup {state['backup']} kept; sold {sale['number']} after the update")
    finally:
        stop(proc)


if __name__ == '__main__':
    if len(sys.argv) < 4 or sys.argv[1] not in ('first', 'after'):
        sys.exit(__doc__)
    {'first': first, 'after': after}[sys.argv[1]](sys.argv[2], sys.argv[3:])
