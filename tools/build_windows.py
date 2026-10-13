"""Builds the Windows installer Al-Store-Setup-<version>.exe (run on Windows; the workflow .github/workflows/windows.yml does it).

Steps: draw the icon, compile the program into Al-Store.exe with Nuitka (Python translated to C: no readable source files next
to the program), put the web pages and the vendor's public keys beside it, then wrap it all in the Inno Setup installer.

    python tools/build_windows.py            needs: pip install nuitka ordered-set zstandard pillow, and Inno Setup 6
    python tools/build_windows.py --check    only checks that every shipped file is there and the version is described (any OS)
    python tools/build_windows.py --customer shop installer: needs a vendor public key and https relay (files or env); see --check --customer
"""
import glob
import ipaddress
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, 'build')
sys.path.insert(0, os.path.join(ROOT, 'server'))
from version import DEVELOPER, PRODUCT, VERSION  # noqa: E402

EXE = 'Al-Store.exe'
DIST = os.path.join(BUILD, 'app.dist')
SHIPPED = ('server/app.py', 'web/index.html', 'web/js/app.js', 'web/css/tokens.css', 'web/img/icons.svg', 'licence_keys.txt', 'licence_relay.txt',
           'installer/store.iss', 'tools/make_icon.py', 'docs/RELEASE_NOTES.md',
           'guide/catalogue.json', 'guide/ar.json', 'guide/en.json')
# Folders copied whole into the program folder (source folder -> folder inside app.dist).
DATA_DIRS = (('web', 'web'), ('guide', 'guide'))

PUBLIC_KEY_LINE = re.compile(r'^(?:[A-Za-z0-9_-]+:)?[A-Za-z0-9_-]{43}$')
# Host must end with one of these suffixes (add the owner's production domain here).
ALLOWED_RELAY_HOST_SUFFIXES = ('.workers.dev', '.example.com')
MAX_RELAY_SUBDOMAIN_WORD = 12
MAX_RELAY_SUBDOMAIN_DIGITS = 4
# Exact paths permitted after https://<host> (customer relay URLs only).
ALLOWED_RELAY_PATHS = frozenset(('', '/api', '/licence-hub'))
RELAY_SECRET_WORDS = re.compile(r'(?i)token|secret|key|pass')


class CustomerLicenceError(ValueError):
    """A customer installer was asked for without a safe public key and relay address."""


def active_lines(path):
    out = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            bit = line.split('#', 1)[0].strip()
            if bit:
                out.append(bit)
    return out


def validate_public_key_line(line):
    if '-----BEGIN' in line or 'PRIVATE KEY' in line:
        raise CustomerLicenceError('a private key must not be shipped in the installer')
    if not PUBLIC_KEY_LINE.fullmatch(line):
        raise CustomerLicenceError('licence key must be kid:key or a 43-character public key (url-safe base64)')
    key = line.split(':', 1)[-1]
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', key):
        raise CustomerLicenceError('only a 32-byte Ed25519 public key may be listed')


def _relay_host_is_ip_literal(host):
    probe = host
    if probe.startswith('[') and probe.endswith(']'):
        probe = probe[1:-1]
    try:
        ipaddress.ip_address(probe)
        return True
    except ValueError:
        return False


def _relay_subdomain_word_ok(word):
    if not word or len(word) > MAX_RELAY_SUBDOMAIN_WORD:
        return False
    if re.fullmatch(r'[a-z]+', word):
        return True
    m = re.fullmatch(r'([a-z]+)([0-9]{1,%d})' % MAX_RELAY_SUBDOMAIN_DIGITS, word)
    return bool(m) and len(m.group(1)) + len(m.group(2)) <= MAX_RELAY_SUBDOMAIN_WORD


def _relay_host_suffix(host):
    for suffix in sorted(ALLOWED_RELAY_HOST_SUFFIXES, key=len, reverse=True):
        if host.endswith(suffix) and len(host) > len(suffix):
            return suffix
    return None


def _validate_relay_label(label):
    if not label or label != label.lower():
        raise CustomerLicenceError('relay host labels must be lowercase')
    if label.startswith('xn--'):
        raise CustomerLicenceError('relay host must not use punycode labels')
    if label.startswith('-') or label.endswith('-') or '--' in label:
        raise CustomerLicenceError('relay host labels must not start or end with a hyphen or contain two hyphens in a row')
    if not re.fullmatch(r'[a-z0-9-]+', label):
        raise CustomerLicenceError('relay host labels may contain only lowercase letters, digits and hyphens')


def _validate_relay_host(host):
    if not host or host != host.lower():
        raise CustomerLicenceError('the relay host must use lowercase labels only')
    if _relay_host_is_ip_literal(host):
        raise CustomerLicenceError('the relay host must not be an IP address')
    if not _relay_host_suffix(host):
        raise CustomerLicenceError('the relay host must end with an allowed company domain suffix')
    labels = host.split('.')
    for label in labels:
        _validate_relay_label(label)
    leftmost = labels[0]
    for word in leftmost.split('-'):
        if not word:
            raise CustomerLicenceError('the relay subdomain must be lowercase words separated by single hyphens')
        if not _relay_subdomain_word_ok(word):
            raise CustomerLicenceError(
                'the relay subdomain must be short lowercase words (letters only, or letters with up to four digits at the end)'
            )


def validate_relay_line(line):
    line = line.strip()
    if not line.startswith('https://'):
        raise CustomerLicenceError('the relay address must start with https://')
    if '@' in line or '?' in line or '#' in line:
        raise CustomerLicenceError('the relay address must not carry userinfo, a query or a fragment')
    if RELAY_SECRET_WORDS.search(line):
        raise CustomerLicenceError('the relay address must not contain token, secret, key or pass')
    parsed = urlparse(line)
    if parsed.scheme != 'https':
        raise CustomerLicenceError('the relay address must use https')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CustomerLicenceError('the relay address must not carry a user, password or query string')
    if parsed.port not in (None, 443):
        raise CustomerLicenceError('the relay must use the default https port (no custom port)')
    host = parsed.hostname or ''
    path = parsed.path or ''
    if path == '/':
        path = ''
    if path not in ALLOWED_RELAY_PATHS:
        raise CustomerLicenceError('the relay path is not on the allowed list')
    _validate_relay_host(host)
    canonical = 'https://' + host + path
    if line != canonical:
        raise CustomerLicenceError('the relay address must be exactly https://<host> with an allowed path only')


def resolve_customer_licence(root=ROOT):
    """Return (licence_keys.txt body, licence_relay.txt body) for a customer build.

    Values come from STORE_RELEASE_PUBLIC_KEY and STORE_RELEASE_RELAY_URL when both are set; otherwise from
    licence_keys.txt and licence_relay.txt in ``root`` (exactly one active line in each).
    """
    env_key = os.environ.get('STORE_RELEASE_PUBLIC_KEY', '').strip()
    env_relay = os.environ.get('STORE_RELEASE_RELAY_URL', '').strip()
    if env_key or env_relay:
        if not env_key or not env_relay:
            raise CustomerLicenceError('set both STORE_RELEASE_PUBLIC_KEY and STORE_RELEASE_RELAY_URL, or neither')
        key_line, relay_line = env_key, env_relay
    else:
        keys = active_lines(os.path.join(root, 'licence_keys.txt'))
        relays = active_lines(os.path.join(root, 'licence_relay.txt'))
        if len(keys) != 1:
            raise CustomerLicenceError('licence_keys.txt must hold exactly one public key line for a customer build')
        if len(relays) != 1:
            raise CustomerLicenceError('licence_relay.txt must hold exactly one https relay address for a customer build')
        key_line, relay_line = keys[0], relays[0]
    validate_public_key_line(key_line)
    validate_relay_line(relay_line)
    return key_line + '\n', relay_line + '\n'


def relay_hostname(relay_url):
    return urlparse(relay_url.strip()).hostname or ''


def release_proof_licence_lines(customer, relay_url=''):
    if customer:
        host = relay_hostname(relay_url)
        return ('customer_licence: yes', f'relay_host: {host}' if host else 'relay_host: (unknown)')
    return ('customer_licence: no',)


def runtime_files():
    """Every non-Python file the program reads at run time, as (path in the repo, path inside app.dist).

    Compiled modules see the program folder as their own folder, so a data file next to server/x.py
    (for example server/aftelemetry_events.json) must sit at the top of app.dist, and web/ and guide/ keep
    their folder names (ROOT is the program folder when compiled; see server/version.py).
    """
    out = [('licence_keys.txt', 'licence_keys.txt'), ('licence_relay.txt', 'licence_relay.txt')]
    for name in sorted(os.listdir(os.path.join(ROOT, 'server'))):
        full = os.path.join(ROOT, 'server', name)
        if os.path.isfile(full) and not name.endswith(('.py', '.pyc')):
            out.append(('server/' + name, name))
    for src, dest in DATA_DIRS:
        for folder, dirs, names in os.walk(os.path.join(ROOT, src)):
            dirs[:] = sorted(d for d in dirs if d not in ('__pycache__', '_dev'))
            for name in sorted(names):
                rel = os.path.relpath(os.path.join(folder, name), ROOT).replace(os.sep, '/')
                out.append((rel, dest + rel[len(src):]))
    return out


def nuitka_data_args():
    """The Nuitka flags that put runtime_files() into app.dist."""
    args = [f'--include-data-dir={src}={dest}' for src, dest in DATA_DIRS]
    in_dirs = tuple(src + '/' for src, _ in DATA_DIRS)
    args += [f'--include-data-files={src}={dest}' for src, dest in runtime_files() if not src.startswith(in_dirs)]
    return args


def run(cmd):
    print('>', ' '.join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT)


def iscc():
    for p in [shutil.which('iscc'), r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe', r'C:\Program Files\Inno Setup 6\ISCC.exe']:
        if p and os.path.exists(p):
            return p
    sys.exit('Inno Setup 6 (ISCC.exe) was not found.')


def preflight():
    missing = [f for f in SHIPPED if not os.path.isfile(os.path.join(ROOT, f))]
    if missing:
        sys.exit('These files are needed for the installer and are missing: ' + ', '.join(missing))
    notes = open(os.path.join(ROOT, 'docs', 'RELEASE_NOTES.md'), encoding='utf-8').read()
    if VERSION not in notes:
        sys.exit(f'docs/RELEASE_NOTES.md does not describe version {VERSION} (server/version.py). Write what changed first.')
    if os.path.exists(os.path.join(ROOT, 'web', 'js', '_dev')):
        sys.exit('web/js/_dev must not ship.')


def write_customer_licence_to_dist(keys_body, relay_body):
    for name, body in (('licence_keys.txt', keys_body), ('licence_relay.txt', relay_body)):
        with open(os.path.join(DIST, name), 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)


def verify_customer_licence_in_dist(keys_body, relay_body):
    """The program folder must contain exactly the validated customer licence files."""
    for name, want in (('licence_keys.txt', keys_body), ('licence_relay.txt', relay_body)):
        path = os.path.join(DIST, name)
        if not os.path.isfile(path):
            raise CustomerLicenceError(f'{name} is missing from the program folder')
        got = open(path, encoding='utf-8').read()
        if got != want:
            raise CustomerLicenceError(f'{name} in the program folder does not match the customer release inputs')
    key_lines = active_lines(os.path.join(DIST, 'licence_keys.txt'))
    relay_lines = active_lines(os.path.join(DIST, 'licence_relay.txt'))
    if len(key_lines) != 1 or len(relay_lines) != 1:
        raise CustomerLicenceError('the program folder must ship exactly one key line and one relay address')
    validate_public_key_line(key_lines[0])
    validate_relay_line(relay_lines[0])


def compile_program(v4):
    run([sys.executable, '-m', 'nuitka', '--standalone', '--assume-yes-for-downloads', '--windows-console-mode=attach',
         f'--output-dir={BUILD}', f'--output-filename={EXE}', f'--windows-icon-from-ico={os.path.join(BUILD, "store.ico")}',
         f'--company-name={DEVELOPER}', f'--product-name={PRODUCT}', f'--file-description={PRODUCT}', f'--file-version={v4}',
         f'--product-version={v4}', *nuitka_data_args(),
         '--nofollow-import-to=tkinter,unittest,pydoc,test',
         os.path.join('server', 'app.py')])


def main():
    customer = '--customer' in sys.argv
    preflight()
    if '--release-proof-customer' in sys.argv:
        try:
            _, relay_body = resolve_customer_licence()
        except CustomerLicenceError as e:
            sys.exit(str(e))
        for line in release_proof_licence_lines(True, relay_body.strip()):
            print(line)
        return
    if customer:
        try:
            keys_body, relay_body = resolve_customer_licence()
        except CustomerLicenceError as e:
            sys.exit(str(e))
    if '--check' in sys.argv:
        if customer:
            print('Customer release inputs are valid for version', VERSION)
        else:
            print('Everything the installer needs is here, version', VERSION)
        return
    os.makedirs(BUILD, exist_ok=True)
    run([sys.executable, 'tools/make_icon.py', os.path.join(BUILD, 'store.ico')])
    v4 = '.'.join((VERSION.split('.') + ['0', '0', '0'])[:4])
    compile_program(v4)
    assert os.path.exists(os.path.join(DIST, EXE)), f'{EXE} was not built'
    leaks = glob.glob(os.path.join(DIST, '**', '*.py'), recursive=True)
    assert not leaks, f'source files in the program folder: {leaks}'
    if customer:
        write_customer_licence_to_dist(keys_body, relay_body)
        try:
            verify_customer_licence_in_dist(keys_body, relay_body)
        except CustomerLicenceError as e:
            sys.exit(str(e))
    missing = [dest for _, dest in runtime_files() if not os.path.isfile(os.path.join(DIST, dest))]
    assert not missing, f'runtime files did not reach the program folder: {missing}'
    run([iscc(), f'/DAppVersion={VERSION}', os.path.join('installer', 'store.iss')])
    out = os.path.join(ROOT, 'dist', f'Al-Store-Setup-{VERSION}.exe')
    assert os.path.exists(out), 'the installer was not produced'
    print('Built', out)


if __name__ == '__main__':
    main()
