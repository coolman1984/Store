"""Draw the map from what a person sees to what the database holds, from the source itself (no guessing, no running program).

    python tools/review_map.py [clickmap_A.json clickmap_B.json ...] > docs/review/UI-MAP.md

For every address the screens call (`/api/...`): the screen code that calls it (file:line), the server branch that answers it (app.py:line),
the permission it asks for, the business function it runs (file:line) and the tables that function writes. With click-map files (one row per
control clicked in a real browser: the request it sent, whether a dialog opened) it also lists the controls of every page.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, 'server')
VIEWS = os.path.join(ROOT, 'web', 'js')
MODULES = {'sales': 'sales', 'stock': 'stock', 'cash': 'money', 'catalog': 'catalog', 'core': 'core', 'reports': 'reports', 'backup': 'backup',
           'trial': 'trial', 'training': 'training', 'support': 'support', 'licence': 'licence', 'auth_mod': 'auth', 'practice_mod': 'practice'}
WRITES = [(re.compile(r"db\.insert\('(\w+)'"), 1), (re.compile(r"INSERT (?:OR \w+ )?INTO (\w+)"), 1), (re.compile(r"UPDATE (\w+) SET"), 1),
          (re.compile(r"DELETE FROM (\w+)"), 1)]
HELPERS = [(re.compile(r"(?<![\w])(?:stock\.)?move\("), 'stock_moves'), (re.compile(r"\bcash_move\(|\bcash_out\("), 'cash_moves'),
           (re.compile(r"\bar_entry\("), 'ar_entries'), (re.compile(r"ctx\.audit\("), 'audit'), (re.compile(r"\bset_setting\("), 'settings')]


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read().splitlines()


def ui_calls():
    """address -> [(file:line, 'GET'|'POST')]"""
    out = {}
    for dp, _, files in os.walk(VIEWS):
        for name in sorted(files):
            if not name.endswith('.js'):
                continue
            path = os.path.join(dp, name)
            for n, line in enumerate(read(path), 1):
                for m in re.finditer(r"api\.(get|post)\(\s*'(/api/[\w/-]+)'", line):
                    out.setdefault(m.group(2), []).append((f'{os.path.relpath(path, ROOT).replace(os.sep, "/")}:{n}', m.group(1).upper()))
    return out


def server_branches():
    """(method, address) -> dict(line, perms, calls) from the `if path == '/api/x'` branches of app.py"""
    lines = read(os.path.join(SERVER, 'app.py'))
    out, i = {}, 0
    head = re.compile(r"^(\s*)(?:if|elif) path (?:==|in) (.+):\s*(?:#.*)?$")
    method = 'GET'
    while i < len(lines):
        if lines[i].startswith('    def api_get'):
            method = 'GET'
        elif lines[i].startswith('    def api_post') or lines[i].startswith('    def write'):
            method = 'POST'
        m = head.match(lines[i])
        if m:
            indent, addrs = len(m.group(1)), re.findall(r"'(/api/[\w/-]+)'", m.group(2))
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent):
                j += 1
            body = '\n'.join(lines[i:j])
            perms = sorted(set(re.findall(r"ctx\.need\('([\w.]+)'", body)) | set(re.findall(r"need_any\(([^)]*)\)", body)) | set(re.findall(r"ctx\.can\('([\w.]+)'", body)))
            calls = [(mod, fn) for mod, fn in re.findall(r"\b(" + '|'.join(MODULES) + r")\.(\w+)\(", body) if not fn.startswith('_')]
            for a in addrs:
                out.setdefault((method, a), {'line': i + 1, 'perms': perms, 'calls': calls, 'method': method})
        i += 1
    return out


_cache = {}


def functions(module):
    if module not in _cache:
        path = os.path.join(SERVER, MODULES[module] + '.py')
        lines = read(path) if os.path.exists(path) else []
        defs = {}
        for n, line in enumerate(lines):
            m = re.match(r"def (\w+)\(", line)
            if m:
                defs[m.group(1)] = n
        order = sorted(defs.values()) + [len(lines)]
        _cache[module] = (lines, defs, {name: order[order.index(n) + 1] for name, n in defs.items()})
    return _cache[module]


def analyse(module, fn, depth=2, seen=None):
    """tables written, permissions asked, (file:line) of a business function, following same-file helpers a little way"""
    lines, defs, ends = functions(module)
    if fn not in defs:
        return None
    seen = seen or set()
    key = (module, fn)
    if key in seen:
        return None
    seen.add(key)
    body = '\n'.join(lines[defs[fn]:ends[fn]])
    tables = set()
    for rx, g in WRITES:
        tables |= {m.group(g) for m in rx.finditer(body)}
    tables |= {t for rx, t in HELPERS if rx.search(body)}
    perms = set(re.findall(r"need\('([\w.]+)'", body))
    if depth:
        for name in set(re.findall(r"\b(\w+)\(", body)):
            if name in defs and name != fn:
                sub = analyse(module, name, depth - 1, seen)
                if sub:
                    tables |= sub[0]
                    perms |= sub[1]
    return tables, perms, f'server/{MODULES[module]}.py:{defs[fn] + 1}'


def main(argv):
    ui, srv = ui_calls(), server_branches()
    keys = sorted(set(srv) | {(m, a) for a, calls in ui.items() for _f, m in calls})
    print('# From the screen to the database (generated by `tools/review_map.py`)\n')
    print('Each row: an address the screens call, where the screen calls it, which branch of `server/app.py` answers it, what it asks for, the business '
          'function it runs and the tables that function (and its helpers) write. `audit` means a row in the audit trail. Read routes write nothing.\n')
    print('| Method | Address | Screen code | Server branch | Permission asked | Business function | Writes |')
    print('|---|---|---|---|---|---|---|')
    for method, a in keys:
        u = '<br>'.join(f for f, m in ui.get(a, []) if m == method)[:200] or '—'
        s = srv.get((method, a))
        if not s:
            print(f'| {method} | `{a}` | {u} | — | — | — | — |')
            continue
        funcs, tables, perms = [], set(), set(s['perms'])
        for mod, fn in s['calls']:
            res = analyse(mod, fn)
            if res and f'{mod}.{fn}' not in [f.split(' ')[0] for f in funcs]:
                funcs.append(f'{mod}.{fn} ({res[2]})')
                tables |= res[0]
                perms |= res[1]
        write = ', '.join(sorted(tables)) if method == 'POST' else '—'
        print(f"| {method} | `{a}` | {u} | app.py:{s['line']} | {', '.join(sorted(perms)) or '—'} | {'<br>'.join(funcs[:3]) or '—'} | {write or '—'} |")
    clicks = []
    for path in argv:
        with open(path, encoding='utf-8') as f:
            clicks += json.load(f)
    if clicks:
        done = [c for c in clicks if 'route' in c and 'result' not in c]
        failed = [c for c in clicks if 'result' in c]
        print('\n## Controls clicked in a real browser\n')
        print(f'{len(done)} controls clicked on {len({c["route"] for c in done})} pages. «Request» is what the browser really sent when the control was clicked; '
              '«Dialog» says the click opened a dialog (its fields were then checked). «—» means the click only changed the screen (a tab, a theme, '
              f'the search palette) or opened an outside link. {len(failed)} more were not clickable at that moment (hidden behind another control or scrolled '
              'away) and were reached by their own steps in the browser tests.\n')
        by = {}
        for c in done:
            by.setdefault(c['route'], []).append(c)
        for route in sorted(by):
            print(f'\n### `{route}`\n')
            print('| Control | Data attribute | Request | Dialog |')
            print('|---|---|---|---|')
            for c in by[route]:
                req = '<br>'.join(r for r in c.get('requests', []) if not r.endswith('/api/guide/progress')) or ('link' if c.get('href') else '—')
                text = (c['text'] or c.get('href') or '').replace('|', '/')[:40]
                print(f"| {text} | {c.get('attrs') or ''} | {req} | {'yes' if c.get('dialog') else ''} |")


if __name__ == '__main__':
    main(sys.argv[1:])
