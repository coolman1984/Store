"""Starts a built Al-Store.exe in a temporary practice shop and checks that it really serves the pages (used by the Windows workflow).

    python tools/smoke_exe.py "C:\\Program Files\\Al-Store\\Al-Store.exe"      (or: python tools/smoke_exe.py python server/app.py)
Stdlib only. Exit code 0 = healthy.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def get(port, path):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}')
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, dict(r.headers), r.read()


def main(*cmd):
    out = subprocess.run([*cmd, '--version'], capture_output=True, text=True, timeout=60)
    print('version:', out.stdout.strip())
    assert out.returncode == 0 and 'Al-Store' in out.stdout, out
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    home = tempfile.mkdtemp(prefix='store-smoke-')
    log_path = os.path.join(home, 'smoke-output.txt')
    log_file = open(log_path, 'w', encoding='utf-8', errors='replace')
    proc = subprocess.Popen([*cmd, '--practice', '--no-browser', '--port', str(port), '--host', '127.0.0.1', '--home', home],
                            stdout=log_file, stderr=subprocess.STDOUT)

    def fail(message):
        log_file.flush()
        print(open(log_path, encoding='utf-8', errors='replace').read()[-4000:])
        for name in ('store.log',):
            path = os.path.join(home, name)
            if os.path.exists(path):
                print(f'--- {name} ---')
                print(open(path, encoding='utf-8', errors='replace').read()[-3000:])
        sys.exit(message)

    try:
        for _ in range(120):
            try:
                st, _, body = get(port, '/api/boot')
                break
            except OSError:
                if proc.poll() is not None:
                    fail(f'the program stopped early with code {proc.returncode}')
                time.sleep(0.5)
        else:
            fail('the program did not answer in 60 seconds')
        boot = json.loads(body)
        assert boot.get('practice') is True, boot
        st, headers, page = get(port, '/')
        assert st == 200 and b'<html' in page.lower(), 'the home page is not served'
        assert "script-src 'self'" in headers.get('Content-Security-Policy', ''), 'the security policy header is missing'
        for asset in ('/js/app.js', '/css/tokens.css', '/img/icons.svg', '/fonts/readex-pro-arabic-wght-normal.woff2', '/i18n/ar.js'):
            st, _, data = get(port, asset)
            assert st == 200 and data, f'{asset} is not served from the program folder'
        for name in ('catalogue', 'ar', 'en'):  # the in-app guide is read from the program folder
            st, _, data = get(port, f'/guide/{name}.json')
            assert st == 200 and json.loads(data), f'/guide/{name}.json is not served from the program folder'
        print('OK: the program starts, serves its pages, assets and guide, practice mode is on')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == '__main__':
    main(*sys.argv[1:])
