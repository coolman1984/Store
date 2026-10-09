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
           'installer/store.iss', 'tools/make_icon.py', 'docs/RELEASE_NOTES.md',
           'guide/catalogue.json', 'guide/ar.json', 'guide/en.json')
# Folders copied whole into the program folder (source folder -> folder inside app.dist).
DATA_DIRS = (('web', 'web'), ('guide', 'guide'))


def runtime_files():
    """Every non-Python file the program reads at run time, as (path in the repo, path inside app.dist).

    Compiled modules see the program folder as their own folder, so a data file next to server/x.py
    (for example server/aftelemetry_events.json) must sit at the top of app.dist, and web/ and guide/ keep
    their folder names (ROOT is the program folder when compiled; see server/version.py).
    """
    out = [('licence_keys.txt', 'licence_keys.txt')]
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


def compile_program(v4):
    run([sys.executable, '-m', 'nuitka', '--standalone', '--assume-yes-for-downloads', '--windows-console-mode=attach',
         f'--output-dir={BUILD}', f'--output-filename={EXE}', f'--windows-icon-from-ico={os.path.join(BUILD, "store.ico")}',
         f'--company-name={DEVELOPER}', f'--product-name={PRODUCT}', f'--file-description={PRODUCT}', f'--file-version={v4}',
         f'--product-version={v4}', *nuitka_data_args(),
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
    missing = [dest for _, dest in runtime_files() if not os.path.isfile(os.path.join(DIST, dest))]
    assert not missing, f'runtime files did not reach the program folder: {missing}'
    run([iscc(), f'/DAppVersion={VERSION}', os.path.join('installer', 'store.iss')])
    out = os.path.join(ROOT, 'dist', f'Al-Store-Setup-{VERSION}.exe')
    assert os.path.exists(out), 'the installer was not produced'
    print('Built', out)


if __name__ == '__main__':
    main()
