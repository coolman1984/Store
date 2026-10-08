"""Backups the shop can trust: a consistent copy (SQLite online backup), checked, kept in rotation, restorable.

- Automatic copy on start and every few hours; manual copy from Settings; a copy before every restore and migration.
- Every copy is opened and checked (`PRAGMA integrity_check`) before it is counted as a backup.
- A second folder (USB drive / another disk) can receive the same copies.
- Restore replaces the data only after a safety copy of the current data; the program reopens the restored file.
"""
import csv
import io
import os
import re
import sqlite3
import zipfile
from datetime import datetime, timezone

import ids

NAME = re.compile(r'^store-(\d{8}-\d{6})(-[a-z]+)?\.db$')
EXPORT_TABLES = ('products', 'barcodes', 'prices', 'costs', 'locations', 'places', 'stock_moves', 'customers', 'suppliers', 'sales',
                 'sale_lines', 'tenders', 'returns', 'return_lines', 'purchases', 'purchase_lines', 'plans', 'ar_entries',
                 'ap_entries', 'cash_moves', 'shifts', 'transfers', 'counts', 'count_lines', 'categories', 'brands', 'audit')


def _stamp():
    return ids.utcnow().astimezone().strftime('%Y%m%d-%H%M%S')


def make(db, folder, tag='', extra_dirs=()):
    os.makedirs(folder, exist_ok=True)
    name = f'store-{_stamp()}{("-" + tag) if tag else ""}.db'
    path = os.path.join(folder, name)
    target = sqlite3.connect(path)
    try:
        with db.lock:
            db.conn.backup(target)
    finally:
        target.close()
    if not check(path):
        os.remove(path)
        raise IOError('The backup copy failed its check.')
    for extra in extra_dirs or ():
        try:
            os.makedirs(extra, exist_ok=True)
            with open(path, 'rb') as src, open(os.path.join(extra, name), 'wb') as dst:
                dst.write(src.read())
        except OSError:
            pass  # the main copy exists; the page shows the second folder as not reachable
    return {'name': name, 'size': os.path.getsize(path), 'at': ids.iso()}


def check(path):
    try:
        c = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            ok = c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            ok = ok and c.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone() is not None
            return ok
        finally:
            c.close()
    except sqlite3.Error:
        return False


def org_of(path):
    c = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        row = c.execute("SELECT value FROM meta WHERE key = 'org_id'").fetchone()
        return row[0] if row else None
    finally:
        c.close()


def listing(folder):
    if not os.path.isdir(folder):
        return []
    out = []
    for name in sorted(os.listdir(folder), reverse=True):
        if NAME.match(name):
            path = os.path.join(folder, name)
            out.append({'name': name, 'size': os.path.getsize(path),
                        'mtime': ids.iso(datetime.fromtimestamp(os.path.getmtime(path), timezone.utc))})
    return out


def age_hours(folder):
    items = listing(folder)
    if not items:
        return None
    newest = max(os.path.getmtime(os.path.join(folder, i['name'])) for i in items)
    return round((ids.utcnow().timestamp() - newest) / 3600, 1)


def prune(folder, keep=60):
    items = [i for i in listing(folder) if not NAME.match(i['name']).group(2)]  # tagged copies (before-restore...) stay
    for old in items[keep:]:
        try:
            os.remove(os.path.join(folder, old['name']))
        except OSError:
            pass


def export_zip(db):
    """Everything the shop owns, as CSV files in one zip (UTF-8 with BOM so Excel shows Arabic). Formulas neutralised."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for table in EXPORT_TABLES:
            rows = db.all(f'SELECT * FROM {table}')
            out = io.StringIO()
            out.write('﻿')
            w = csv.writer(out)
            cols = list(rows[0].keys()) if rows else [r['name'] for r in db.all(f'PRAGMA table_info({table})')]
            w.writerow(cols)
            for r in rows:
                w.writerow([safe_cell(r[c]) for c in cols])
            z.writestr(f'{table}.csv', out.getvalue())
    return buf.getvalue()


def safe_cell(value):
    """Spreadsheet formula injection: a cell starting with = + - @ is shown as text."""
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value
