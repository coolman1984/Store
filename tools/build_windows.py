"""Builds the Windows installer Al-Store-Setup-<version>.exe (run on Windows; the workflow .github/workflows/windows.yml does it).

Steps: draw the icon, compile the program into Al-Store.exe with Nuitka (Python translated to C: no readable source files next
to the program), put the web pages and the vendor's public keys beside it, then wrap it all in the Inno Setup installer.

    python tools/build_windows.py            needs: pip install nuitka ordered-set zstandard pillow, and Inno Setup 6
    python tools/build_windows.py --check    only checks that every shipped file is there and the version is described (any OS)
"""
import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, 'build')
sys.path.insert(0, os.path.join(ROOT, 'server'))
from version import DEVELOPER, PRODUCT, VERSION  # noqa: E402

EXE = 'Al-Store.exe'
DIST = os.path.join(BUILD, 'app.dist')
SHIPPED = ('server/app.py', 'web/index.html', 'web/js/app.js', 'web/css/tokens.css', 'web/img/icons.svg', 'licence_keys.txt',
           'installer/store.iss', 'tools/make_icon.py', 'docs/RELEASE_NOTES.md')


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


def compile_program(v4):
    run([sys.executable, '-m', 'nuitka', '--standalone', '--assume-yes-for-downloads', '--windows-console-mode=attach',
         f'--output-dir={BUILD}', f'--output-filename={EXE}', f'--windows-icon-from-ico={os.path.join(BUILD, "store.ico")}',
         f'--company-name={DEVELOPER}', f'--product-name={PRODUCT}', f'--file-description={PRODUCT}', f'--file-version={v4}',
         f'--product-version={v4}', '--include-data-dir=web=web', '--include-data-files=licence_keys.txt=licence_keys.txt',
         '--nofollow-import-to=tkinter,unittest,pydoc,test',
         os.path.join('server', 'app.py')])


def main():
    preflight()
    if '--check' in sys.argv:
        print('Everything the installer needs is here, version', VERSION)
        return
    os.makedirs(BUILD, exist_ok=True)
    run([sys.executable, 'tools/make_icon.py', os.path.join(BUILD, 'store.ico')])
    v4 = '.'.join((VERSION.split('.') + ['0', '0', '0'])[:4])
    compile_program(v4)
    assert os.path.exists(os.path.join(DIST, EXE)), f'{EXE} was not built'
    leaks = glob.glob(os.path.join(DIST, '**', '*.py'), recursive=True)
    assert not leaks, f'source files in the program folder: {leaks}'
    for must in ('web/index.html', 'licence_keys.txt'):
        assert os.path.exists(os.path.join(DIST, must)), f'{must} did not reach the program folder'
    run([iscc(), f'/DAppVersion={VERSION}', os.path.join('installer', 'store.iss')])
    out = os.path.join(ROOT, 'dist', f'Al-Store-Setup-{VERSION}.exe')
    assert os.path.exists(out), 'the installer was not produced'
    print('Built', out)


if __name__ == '__main__':
    main()
