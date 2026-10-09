"""Release proofs that need no customer PC (factory core controls).

- DATA-06: data from a newer program is refused untouched; a failed migration rolls back and keeps a checked copy;
  a realistic previous-schema shop (the practice shop's 21 days) upgrades with every money and stock row intact.
- OPS-06: the program killed in the middle of selling or of a backup leaves a consistent database and no fake backup.
- IAM-06: a real shop refuses the practice password and the first passwords people try; demo accounts exist only in practice.
- SEC-07: exported spreadsheets cannot run formulas.
- SEC-02: no private key, token or password-looking secret is committed.
"""
import csv
import hashlib
import io
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

from harness import OWNER, PW, ROOT, Shop
import app as app_mod
import backup
import db as db_mod
import money as cash
import version
from auth import AuthError

WORKER = """
import sys
sys.path.insert(0, {tests!r})
from harness import Shop
import backup, money as cash, sales
s = Shop(licensed=False)
print(s.dir, flush=True)
s.do(cash.open_shift, 10000)
p = s.product('Kettle', retail=50000, cost=40000, qty=1000000)
i = 0
while True:
    if {mode!r} == 'sell':
        s.do(sales.sell, {{'idem_key': 'k%d' % i, 'lines': [{{'product_id': p, 'qty': 1}}],
                          'payments': [{{'method': 'cash', 'amount': 50000}}], 'cash_received': 50000}})
    else:
        backup.make(s.db, s.app.backup_dir, 'manual')
    i += 1
    print(i, flush=True)
"""


def kill_after(mode, count):
    """Starts a worker that sells (or backs up) in a loop and kills it hard (SIGKILL / TerminateProcess) after `count`."""
    tests = os.path.dirname(os.path.abspath(__file__))
    proc = subprocess.Popen([sys.executable, '-c', WORKER.format(tests=tests, mode=mode)], stdout=subprocess.PIPE, text=True)
    home = proc.stdout.readline().strip()
    done = 0
    for line in proc.stdout:
        done = int(line)
        if done >= count:
            break
    proc.kill()
    proc.wait(30)
    return home, done


class DataSafety(unittest.TestCase):
    def test_newer_data_is_refused_and_left_untouched(self):
        s = Shop(licensed=False)
        try:
            s.db.run("UPDATE meta SET value = ? WHERE key = 'schema'", str(version.SCHEMA + 1))
            s.db.close()
            path = os.path.join(s.dir, 'data', 'store.db')
            before = hashlib.sha256(open(path, 'rb').read()).hexdigest()
            with self.assertRaises(db_mod.NewerData):
                app_mod.build(s.dir)
            self.assertEqual(hashlib.sha256(open(path, 'rb').read()).hexdigest(), before)
        finally:
            shutil.rmtree(s.dir, ignore_errors=True)

    def test_a_failed_migration_rolls_back_and_keeps_a_checked_copy(self):
        s = Shop(licensed=False)
        home = s.dir
        try:
            s.product('Fan', qty=3)
            s.db.close()
            next_n = version.SCHEMA + 1
            db_mod.MIGRATIONS[next_n] = 'CREATE TABLE half_done (x INTEGER);\nINSERT INTO no_such_table VALUES (1);'
            old_schema = (version.SCHEMA, db_mod.SCHEMA)
            version.SCHEMA = db_mod.SCHEMA = next_n
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    app_mod.build(home)
            finally:
                version.SCHEMA, db_mod.SCHEMA = old_schema
                del db_mod.MIGRATIONS[next_n]
            app = app_mod.build(home)  # the previous program still opens the shop, as it was
            try:
                self.assertEqual(app.db.version(), version.SCHEMA)
                self.assertIsNone(app.db.value("SELECT name FROM sqlite_master WHERE name = 'half_done'"))
                self.assertEqual(app.db.value("SELECT COUNT(*) FROM products WHERE name = 'Fan'"), 1)
                copies = [b['name'] for b in backup.listing(app.backup_dir) if b['name'].endswith('-before-upgrade.db')]
                self.assertTrue(copies)
                self.assertTrue(backup.check(os.path.join(app.backup_dir, copies[0])))
            finally:
                app.db.close()
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_previous_schema_practice_shop_upgrades_with_every_row(self):
        """N-1 → N on realistic data: three weeks of sales, returns, instalments, shifts and transfers."""
        home = tempfile.mkdtemp(prefix='store-upgrade-')
        try:
            app = app_mod.build(home, practice=True)
            tables = ('sales', 'sale_lines', 'tenders', 'cash_moves', 'stock_moves', 'ar_entries', 'returns', 'plans', 'audit',
                      'users', 'products', 'prices')
            count = {t: app.db.value(f'SELECT COUNT(*) FROM {t}') for t in tables}
            money = (app.db.value('SELECT SUM(total) FROM sales'), app.db.value('SELECT SUM(amount) FROM cash_moves'),
                     app.db.value('SELECT SUM(qty) FROM stock_moves'))
            self.assertGreater(count['sales'], 50)
            app.db.conn.execute('ALTER TABLE returns DROP COLUMN fee')  # what schema 4 added; schema 3 is the previous release's data
            app.db.conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(version.SCHEMA - 1),))
            app.db.close()
            app = app_mod.build(home, practice=True)
            self.assertEqual(app.db.version(), version.SCHEMA)
            self.assertEqual({t: app.db.value(f'SELECT COUNT(*) FROM {t}') for t in tables}, count)
            self.assertEqual((app.db.value('SELECT SUM(total) FROM sales'), app.db.value('SELECT SUM(amount) FROM cash_moves'),
                              app.db.value('SELECT SUM(qty) FROM stock_moves')), money)
            self.assertEqual(app.db.value('PRAGMA integrity_check'), 'ok')
            copies = [b['name'] for b in backup.listing(app.backup_dir) if b['name'].endswith('-before-upgrade.db')]
            self.assertTrue(copies and backup.check(os.path.join(app.backup_dir, copies[0])))
            app.db.close()
        finally:
            shutil.rmtree(home, ignore_errors=True)


class PowerCut(unittest.TestCase):
    """OPS-06 on this machine: a hard kill is what a power cut does to the program (the disk part is SQLite's WAL + FULL sync)."""

    def test_killed_while_selling_leaves_whole_sales_only(self):
        home, done = kill_after('sell', 40)
        try:
            c = sqlite3.connect(os.path.join(home, 'data', 'store.db'))
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            sales = c.execute('SELECT COUNT(*), COALESCE(SUM(total), 0) FROM sales').fetchone()
            self.assertGreaterEqual(sales[0], done)  # every sale the screen confirmed is there
            lines = c.execute('SELECT COUNT(*) FROM sale_lines').fetchone()[0]
            moves = c.execute("SELECT COUNT(*), COALESCE(-SUM(qty), 0) FROM stock_moves WHERE ref_type = 'sale'").fetchone()
            tenders = c.execute("SELECT COALESCE(SUM(amount), 0) FROM tenders WHERE ref_type = 'sale'").fetchone()[0]
            drawer = c.execute("SELECT COALESCE(SUM(amount), 0) FROM cash_moves WHERE ref_type = 'sale'").fetchone()[0]
            self.assertEqual((lines, moves[0], moves[1]), (sales[0], sales[0], sales[0]))  # no sale without its goods
            self.assertEqual((tenders, drawer), (sales[1], sales[1]))  # no sale without its money, and no money without a sale
            numbers = [r[0] for r in c.execute('SELECT number FROM sales ORDER BY number')]
            self.assertEqual(len(numbers), len(set(numbers)))
            c.close()
            app = app_mod.build(home)  # and the program opens the shop again
            self.assertEqual(app.db.value('SELECT COUNT(*) FROM sales'), sales[0])
            app.db.close()
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_killed_while_backing_up_never_lists_a_broken_copy(self):
        home, done = kill_after('backup', 3)
        try:
            folder = os.path.join(home, 'backups')
            listed = backup.listing(folder)
            self.assertGreaterEqual(len(listed), done)
            for item in listed:
                self.assertTrue(backup.check(os.path.join(folder, item['name'])), item['name'])
            c = sqlite3.connect(os.path.join(home, 'data', 'store.db'))
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            c.close()
            for name in os.listdir(folder):  # a copy cut short is cleaned up after an hour
                if name.endswith('.part'):
                    os.utime(os.path.join(folder, name), (0, 0))
            backup.prune(folder)
            self.assertFalse([n for n in os.listdir(folder) if n.endswith('.part')])
        finally:
            shutil.rmtree(home, ignore_errors=True)


    def test_a_copy_that_fails_half_way_is_never_listed(self):
        s = Shop(licensed=False)
        try:
            class Broken:
                def __init__(self, conn):
                    self.conn = conn

                def backup(self, target):
                    target.execute('CREATE TABLE meta (key TEXT, value TEXT)')  # some pages written, then the power goes
                    raise sqlite3.OperationalError('disk I/O error')

            real = s.db.conn
            s.db.conn = Broken(real)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    backup.make(s.db, s.app.backup_dir, 'manual')
            finally:
                s.db.conn = real
            self.assertEqual([b for b in backup.listing(s.app.backup_dir) if b['name'].endswith('-manual.db')], [])
            made = backup.make(s.db, s.app.backup_dir, 'manual')
            self.assertEqual(sorted(n for n in os.listdir(s.app.backup_dir) if made['name'] in n), [made['name']])  # one file
        finally:
            s.cleanup()


class DemoCredentials(unittest.TestCase):
    def test_a_real_shop_refuses_the_practice_password_and_common_ones(self):
        s = Shop(licensed=False)
        try:
            for weak in ('practice-1234', 'PRACTICE-1234', '12345678', 'password1', 'admin1234'):
                with self.assertRaises(AuthError, msg=weak) as e, s.db.tx():
                    s.app.auth.create('helper', 'Helper', 'cashier', weak)
                self.assertEqual(e.exception.key, 'auth.err.weak')
            with self.assertRaises(AuthError), s.db.tx():
                s.app.auth.update(s.users['owner']['id'], {'password': 'practice-1234'})
            with s.db.tx():
                s.app.auth.create('helper', 'Helper', 'cashier', PW)
            demo = [r['username'] for r in s.db.all("SELECT username FROM users WHERE username IN ('owner', 'manager', 'cashier', 'store')")]
            self.assertEqual(demo, [])  # the practice accounts never exist in a real shop
            with self.assertRaises(AuthError):
                s.app.auth.verify('manager', 'practice-1234')
        finally:
            s.cleanup()

    def test_setup_cannot_use_the_practice_password(self):
        home = tempfile.mkdtemp(prefix='store-setup-')
        try:
            app = app_mod.build(home)
            with self.assertRaises(AuthError):
                app.setup({'username': 'boss', 'full_name': 'Boss', 'password': 'practice-1234', 'shop_name': 'Shop'}, '127.0.0.1')
            self.assertTrue(app.setup_needed())
            app.db.close()
        finally:
            shutil.rmtree(home, ignore_errors=True)


class ExportFormulas(unittest.TestCase):
    def test_exported_cells_cannot_start_a_formula(self):
        s = Shop(licensed=False)
        try:
            evil = ['=HYPERLINK("http://x","click")', '+1+1', '-2+3', '@SUM(A1)', '\t=1']
            for i, name in enumerate(evil):
                s.product(name, qty=0)
            with s.db.tx():
                cash.save_customer(s.ctx(), {'name': '=cmd|"/c calc"!A1', 'phone': '01000000000'})
            z = zipfile.ZipFile(io.BytesIO(backup.export_zip(s.db)))
            seen = 0
            for member in ('products.csv', 'customers.csv'):
                text = z.read(member).decode('utf-8-sig')
                for row in csv.reader(io.StringIO(text)):
                    for cell in row:
                        self.assertFalse(cell[:1] in ('=', '+', '@', '\t', '\r'), (member, cell))
                        if cell.startswith("'") and cell[1:2] in ('=', '+', '-', '@', '\t'):
                            seen += 1
            self.assertGreaterEqual(seen, len(evil) + 1)
        finally:
            s.cleanup()


class Secrets(unittest.TestCase):
    PATTERNS = {
        'private key': re.compile(r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----'),
        'GitHub token': re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}'),
        'AWS key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
        'API key': re.compile(r'\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}'),
        'Slack token': re.compile(r'\bxox[abpr]-[A-Za-z0-9-]{10,}'),
        'Telegram bot token': re.compile(r'\b\d{8,10}:AA[A-Za-z0-9_-]{30,}'),
    }
    # The test key that signs licence codes in tests only: generated at test time, never a vendor key.
    ALLOWED = set()

    def test_no_secret_is_committed(self):
        try:
            files = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest('not a git checkout')
        found = []
        for rel in files:
            path = os.path.join(ROOT, rel)
            if rel in self.ALLOWED or not os.path.isfile(path) or os.path.getsize(path) > 2_000_000:
                continue
            try:
                text = open(path, encoding='utf-8').read()
            except (UnicodeDecodeError, OSError):
                continue
            found += [f'{rel}: {what}' for what, rx in self.PATTERNS.items() if rx.search(text)]
        self.assertEqual(found, [])

    def test_licence_keys_file_holds_public_keys_only(self):
        for line in open(os.path.join(ROOT, 'licence_keys.txt'), encoding='utf-8'):
            line = line.split('#', 1)[0].strip()
            if line:
                key = line.split(':', 1)[-1]
                self.assertRegex(key, r'^[A-Za-z0-9_-]{43}$', 'only a 32-byte public key may be listed')

    def test_licence_relay_file_holds_a_public_https_address_only(self):
        lines = [line.split('#', 1)[0].strip() for line in open(os.path.join(ROOT, 'licence_relay.txt'), encoding='utf-8')]
        for line in [x for x in lines if x]:
            self.assertRegex(line, r'^https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~-]*)*$', 'an https address with no user, password, token or query')
            self.assertNotRegex(line, r'(?i)token|secret|key|pass', 'a relay address carries no secret')
        self.assertLessEqual(len([x for x in lines if x]), 1)

    def test_no_large_binary_or_archive_is_committed(self):
        try:
            files = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest('not a git checkout')
        archives = [f for f in files if f.endswith(('.tar.gz', '.zip', '.exe', '.whl', '.msi', '.pem', '.key'))]
        self.assertEqual(archives, [])


if __name__ == '__main__':
    unittest.main()
