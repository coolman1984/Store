"""The shop database: one SQLite file, write-ahead log, forward-only migrations.

Rules the schema enforces on purpose:
- Money is an integer number of piasters (1 EGP = 100). Never a float.
- Stock, money, customer and supplier balances are never stored: they are sums of append-only rows
  (stock_moves, cash_moves, tenders, ar_entries, ap_entries). A mistake is corrected by a reversing row.
- Every row has a UUIDv7 id and org/branch scope, so a later multi-PC or multi-branch tier never rewrites data.
- The ledger tables refuse UPDATE and DELETE with triggers, so even a bug cannot rewrite money history.
"""
import os
import sqlite3
import threading

import afconsent
import afguide
from version import SCHEMA

LEDGER = ('stock_moves', 'cash_moves', 'tenders', 'ar_entries', 'ap_entries', 'prices', 'costs', 'sale_lines',
          'purchase_lines', 'return_lines', 'audit',
          # the headers of money and goods documents carry the totals: refused too (no code edits them; a mistake is a new, reversing row)
          'sales', 'returns', 'purchases', 'transfers', 'plans')

MIGRATIONS = {1: """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT) STRICT;
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
CREATE TABLE counters (kind TEXT PRIMARY KEY, next INTEGER NOT NULL) STRICT;

CREATE TABLE users (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, username TEXT NOT NULL UNIQUE COLLATE NOCASE, full_name TEXT NOT NULL,
  role TEXT NOT NULL, extra_perms TEXT NOT NULL DEFAULT '[]', denied_perms TEXT NOT NULL DEFAULT '[]',
  max_discount_pct INTEGER NOT NULL DEFAULT 0, pass_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  failed INTEGER NOT NULL DEFAULT 0, locked_until TEXT, created_at TEXT NOT NULL, changed_at TEXT NOT NULL) STRICT;
CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL, last_seen TEXT NOT NULL, ip TEXT NOT NULL,
  ended INTEGER NOT NULL DEFAULT 0) STRICT;

CREATE TABLE locations (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, branch_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL
  CHECK (kind IN ('shop','warehouse','damaged')), sellable INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL) STRICT;
CREATE TABLE categories (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1) STRICT;
CREATE TABLE brands (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1) STRICT;
CREATE TABLE products (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, sku TEXT NOT NULL UNIQUE, name TEXT NOT NULL, category_id TEXT, brand_id TEXT,
  model TEXT NOT NULL DEFAULT '', unit TEXT NOT NULL DEFAULT 'piece', fractional INTEGER NOT NULL DEFAULT 0,
  track_serial INTEGER NOT NULL DEFAULT 0, warranty_months INTEGER NOT NULL DEFAULT 0, reorder_level REAL NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, sample INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, changed_at TEXT NOT NULL) STRICT;
CREATE TABLE barcodes (code TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id)) STRICT;
CREATE TABLE places (product_id TEXT NOT NULL, location_id TEXT NOT NULL, shelf TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (product_id, location_id)) STRICT;
-- dated prices: a change starts on a chosen day and is never retroactive (factory DATA-07)
CREATE TABLE prices (
  id TEXT PRIMARY KEY, product_id TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('retail','trade','min')),
  amount INTEGER NOT NULL CHECK (amount >= 0), starts_on TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', batch_id TEXT,
  created_at TEXT NOT NULL, created_by TEXT NOT NULL) STRICT;
CREATE INDEX prices_product ON prices(product_id, kind, starts_on);
-- moving average cost after each receipt (append-only history; the latest row is the current cost)
CREATE TABLE costs (id TEXT PRIMARY KEY, product_id TEXT NOT NULL, avg_cost INTEGER NOT NULL, last_cost INTEGER NOT NULL,
  ref_type TEXT NOT NULL, ref_id TEXT NOT NULL, created_at TEXT NOT NULL) STRICT;
CREATE INDEX costs_product ON costs(product_id, created_at);

CREATE TABLE stock_moves (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, branch_id TEXT NOT NULL, product_id TEXT NOT NULL, location_id TEXT NOT NULL,
  qty REAL NOT NULL, unit_cost INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL, serial TEXT,
  ref_type TEXT NOT NULL, ref_id TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', at TEXT NOT NULL, by_user TEXT NOT NULL) STRICT;
CREATE INDEX moves_product ON stock_moves(product_id, location_id);
CREATE INDEX moves_serial ON stock_moves(serial) WHERE serial IS NOT NULL;
CREATE INDEX moves_at ON stock_moves(at);

CREATE TABLE suppliers (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL) STRICT;
CREATE TABLE customers (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '', national_id TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
  credit_limit INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, changed_at TEXT NOT NULL) STRICT;
CREATE INDEX customers_phone ON customers(phone);

CREATE TABLE shifts (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, branch_id TEXT NOT NULL, number TEXT NOT NULL, user_id TEXT NOT NULL,
  opened_at TEXT NOT NULL, opening_float INTEGER NOT NULL, closed_at TEXT, closed_by TEXT, expected INTEGER, counted INTEGER,
  close_note TEXT NOT NULL DEFAULT '') STRICT;
CREATE UNIQUE INDEX one_open_shift ON shifts(user_id) WHERE closed_at IS NULL;

CREATE TABLE sales (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, branch_id TEXT NOT NULL, number TEXT NOT NULL UNIQUE, idem_key TEXT NOT NULL UNIQUE,
  at TEXT NOT NULL, by_user TEXT NOT NULL, shift_id TEXT, customer_id TEXT, location_id TEXT NOT NULL,
  subtotal INTEGER NOT NULL, discount INTEGER NOT NULL, fee INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL,
  cost_total INTEGER NOT NULL, approved_by TEXT, note TEXT NOT NULL DEFAULT '', delivery TEXT NOT NULL DEFAULT '') STRICT;
CREATE INDEX sales_at ON sales(at);
CREATE TABLE sale_lines (
  id TEXT PRIMARY KEY, sale_id TEXT NOT NULL REFERENCES sales(id), product_id TEXT NOT NULL, name TEXT NOT NULL,
  qty REAL NOT NULL, list_price INTEGER NOT NULL, unit_price INTEGER NOT NULL, line_total INTEGER NOT NULL,
  unit_cost INTEGER NOT NULL, serial TEXT, warranty_until TEXT) STRICT;
CREATE INDEX sale_lines_sale ON sale_lines(sale_id);
CREATE INDEX sale_lines_serial ON sale_lines(serial) WHERE serial IS NOT NULL;
-- how a sale (or refund) was paid; negative amounts are refunds
CREATE TABLE tenders (
  id TEXT PRIMARY KEY, ref_type TEXT NOT NULL, ref_id TEXT NOT NULL, method TEXT NOT NULL
  CHECK (method IN ('cash','card','wallet','instapay','finance','account','installment')),
  provider TEXT NOT NULL DEFAULT '', amount INTEGER NOT NULL, at TEXT NOT NULL, shift_id TEXT) STRICT;
CREATE INDEX tenders_ref ON tenders(ref_type, ref_id);
CREATE INDEX tenders_at ON tenders(at);

CREATE TABLE plans (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, number TEXT NOT NULL UNIQUE, sale_id TEXT NOT NULL, customer_id TEXT NOT NULL,
  financed INTEGER NOT NULL, months INTEGER NOT NULL, first_due TEXT NOT NULL, monthly INTEGER NOT NULL,
  guarantor_name TEXT NOT NULL DEFAULT '', guarantor_phone TEXT NOT NULL DEFAULT '', guarantor_national_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL) STRICT;
CREATE INDEX plans_customer ON plans(customer_id);
-- what a customer owes the shop: + debt, - payment
CREATE TABLE ar_entries (
  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, plan_id TEXT, amount INTEGER NOT NULL, kind TEXT NOT NULL,
  ref_type TEXT NOT NULL, ref_id TEXT NOT NULL, idem_key TEXT UNIQUE, note TEXT NOT NULL DEFAULT '', at TEXT NOT NULL,
  by_user TEXT NOT NULL, reverses TEXT UNIQUE) STRICT;
CREATE INDEX ar_customer ON ar_entries(customer_id);
-- what the shop owes a supplier: + purchase on credit, - payment
CREATE TABLE ap_entries (
  id TEXT PRIMARY KEY, supplier_id TEXT NOT NULL, amount INTEGER NOT NULL, kind TEXT NOT NULL, ref_type TEXT NOT NULL,
  ref_id TEXT NOT NULL, idem_key TEXT UNIQUE, note TEXT NOT NULL DEFAULT '', at TEXT NOT NULL, by_user TEXT NOT NULL,
  reverses TEXT UNIQUE) STRICT;
CREATE INDEX ap_supplier ON ap_entries(supplier_id);

-- physical cash: the drawer of a shift, or the shop's main safe
CREATE TABLE cash_moves (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, branch_id TEXT NOT NULL, account TEXT NOT NULL CHECK (account IN ('drawer','safe')),
  shift_id TEXT, kind TEXT NOT NULL, amount INTEGER NOT NULL, category TEXT NOT NULL DEFAULT '', ref_type TEXT NOT NULL DEFAULT '',
  ref_id TEXT NOT NULL DEFAULT '', idem_key TEXT UNIQUE, note TEXT NOT NULL DEFAULT '', at TEXT NOT NULL, by_user TEXT NOT NULL,
  reverses TEXT UNIQUE) STRICT;
CREATE INDEX cash_shift ON cash_moves(shift_id);
CREATE INDEX cash_at ON cash_moves(at);

CREATE TABLE purchases (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, branch_id TEXT NOT NULL, number TEXT NOT NULL UNIQUE, idem_key TEXT NOT NULL UNIQUE,
  supplier_id TEXT, supplier_ref TEXT NOT NULL DEFAULT '', location_id TEXT NOT NULL, total INTEGER NOT NULL, at TEXT NOT NULL,
  by_user TEXT NOT NULL, note TEXT NOT NULL DEFAULT '') STRICT;
CREATE TABLE purchase_lines (
  id TEXT PRIMARY KEY, purchase_id TEXT NOT NULL, product_id TEXT NOT NULL, qty REAL NOT NULL, unit_cost INTEGER NOT NULL,
  serials TEXT NOT NULL DEFAULT '[]') STRICT;

CREATE TABLE returns (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, branch_id TEXT NOT NULL, number TEXT NOT NULL UNIQUE, idem_key TEXT NOT NULL UNIQUE,
  sale_id TEXT NOT NULL, at TEXT NOT NULL, by_user TEXT NOT NULL, approved_by TEXT, shift_id TEXT, reason TEXT NOT NULL,
  refund_method TEXT NOT NULL, total INTEGER NOT NULL) STRICT;
CREATE TABLE return_lines (
  id TEXT PRIMARY KEY, return_id TEXT NOT NULL, sale_line_id TEXT NOT NULL, qty REAL NOT NULL, amount INTEGER NOT NULL,
  to_location_id TEXT NOT NULL, condition TEXT NOT NULL CHECK (condition IN ('good','damaged'))) STRICT;
CREATE INDEX return_lines_line ON return_lines(sale_line_id);

CREATE TABLE transfers (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, number TEXT NOT NULL UNIQUE, idem_key TEXT NOT NULL UNIQUE, from_id TEXT NOT NULL,
  to_id TEXT NOT NULL, at TEXT NOT NULL, by_user TEXT NOT NULL, note TEXT NOT NULL DEFAULT '') STRICT;
CREATE TABLE counts (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, number TEXT NOT NULL UNIQUE, location_id TEXT NOT NULL, started_at TEXT NOT NULL,
  started_by TEXT NOT NULL, closed_at TEXT, closed_by TEXT, note TEXT NOT NULL DEFAULT '') STRICT;
CREATE TABLE count_lines (count_id TEXT NOT NULL, product_id TEXT NOT NULL, counted REAL NOT NULL, at TEXT NOT NULL,
  by_user TEXT NOT NULL, PRIMARY KEY (count_id, product_id)) STRICT;

CREATE TABLE watch_reviews (item TEXT PRIMARY KEY, note TEXT NOT NULL, at TEXT NOT NULL, by_user TEXT NOT NULL) STRICT;

CREATE TABLE audit (
  id TEXT PRIMARY KEY, at TEXT NOT NULL, user_id TEXT NOT NULL, user_name TEXT NOT NULL, ip TEXT NOT NULL, action TEXT NOT NULL,
  entity TEXT NOT NULL DEFAULT '', entity_id TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '') STRICT;
CREATE INDEX audit_at ON audit(at);
""", 2: """
CREATE TABLE profiles (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', perms TEXT NOT NULL DEFAULT '[]',
  max_discount_pct INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0, changed_at TEXT NOT NULL) STRICT;
ALTER TABLE users ADD COLUMN perms TEXT;
""", 3: afguide.SQL.rstrip() + ";\n" + afconsent.SQL + "\n", 4: """
-- the part of an instalment fee a return gave back: reports subtract it with the goods (returns made before this kept the whole fee)
ALTER TABLE returns ADD COLUMN fee INTEGER NOT NULL DEFAULT 0;
"""}


def _guards(conn):
    for table in LEDGER:
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
                     f"BEGIN SELECT RAISE(ABORT, 'append-only: {table}'); END")
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
                     f"BEGIN SELECT RAISE(ABORT, 'append-only: {table}'); END")


# Indexes added after 1.0, made every time the database opens (like the guards: a shop that upgrades has them without a migration, and an older
# program still opens the data). Found with 4,000 customers and 20,000 sales: the customers page took 3 s (a full read of the sales for every
# customer), the Today page 1.3 s. Each one answers a page's question without reading a whole table.
SPEED_INDEXES = (
    'CREATE INDEX IF NOT EXISTS sales_customer ON sales(customer_id, at)',      # a customer's sales and "last sale" in the list
    'CREATE INDEX IF NOT EXISTS sales_shift ON sales(shift_id)',                # a shift's sales count and total
    'CREATE INDEX IF NOT EXISTS returns_at ON returns(at)',                     # today's and the period's returns
    'CREATE INDEX IF NOT EXISTS returns_sale ON returns(sale_id)',              # the returns of a sale
    'CREATE INDEX IF NOT EXISTS cash_account ON cash_moves(account, amount)',   # the safe's balance without reading every move
    'CREATE INDEX IF NOT EXISTS cash_ref ON cash_moves(kind, ref_id)',          # the cash that belongs to a collection or a sale
    'CREATE INDEX IF NOT EXISTS ar_at ON ar_entries(at)',                       # the owner's eye: reversals this week
    'CREATE INDEX IF NOT EXISTS tenders_method ON tenders(method, provider)',   # what the finance companies still owe
)


def _speed(conn):
    for sql in SPEED_INDEXES:
        conn.execute(sql)


class NewerData(Exception):
    """The data was written by a newer version of the program: refuse to open instead of damaging it."""


class Database:
    """One connection, one lock. A shop has a handful of devices; correctness beats parallel writes."""

    def __init__(self, path, backup_dir=None):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        fresh = not os.path.exists(path)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        c = self.conn
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=FULL')  # a power cut never loses a sale that was confirmed on screen
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=5000')
        self.migrate(fresh, backup_dir)

    def version(self):
        try:
            row = self.conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            return int(row[0]) if row else 0
        except sqlite3.OperationalError:
            return 0

    def migrate(self, fresh, backup_dir):
        current = self.version()
        if current > SCHEMA:
            raise NewerData(f'data schema {current} is newer than this program ({SCHEMA})')
        if current < SCHEMA and not fresh and backup_dir:  # verified copy before any migration (factory: updates never touch data unsafely)
            import backup  # SQLite's own backup (includes what is still in the write-ahead log), checked, and listed for restore
            backup.make(self, backup_dir, 'before-upgrade')
        for n in range(current + 1, SCHEMA + 1):
            with self.lock:
                self.conn.execute('BEGIN IMMEDIATE')
                try:
                    for statement in _split(MIGRATIONS[n]):
                        self.conn.execute(statement)
                    self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema', ?)", (str(n),))
                    self.conn.execute('COMMIT')
                except Exception:
                    self.conn.execute('ROLLBACK')
                    raise
        _guards(self.conn)
        _speed(self.conn)

    # -- helpers used by every module. Every call holds the lock: one shared connection must never mix a
    #    statement of another thread into an open transaction.
    def one(self, sql, *args):
        _plain(args)
        with self.lock:
            row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def all(self, sql, *args):
        _plain(args)
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def value(self, sql, *args):
        _plain(args)
        with self.lock:
            row = self.conn.execute(sql, args).fetchone()
        return row[0] if row else None

    def run(self, sql, *args):
        _plain(args)
        with self.lock:
            return self.conn.execute(sql, args)

    def insert(self, table, row):
        keys = list(row)
        _plain(row.values())
        with self.lock:
            self.conn.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                              [row[k] for k in keys])
        return row

    def tx(self):
        return _Tx(self)

    def close(self):
        with self.lock:
            self.conn.close()


class _Tx:
    """`with db.tx():` holds the lock and commits all-or-nothing."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        try:
            self.db.conn.execute('BEGIN IMMEDIATE')
        except BaseException:
            # Not entered: __exit__ will not run, so the lock must be given back here. Another program holding the file (a database viewer, a
            # backup or antivirus scan) made this fail once and the lock stayed taken by a finished request: every later request waited for ever.
            self.db.lock.release()
            raise
        return self.db

    def __exit__(self, kind, value, tb):
        try:
            self.db.conn.execute('ROLLBACK' if kind else 'COMMIT')
        finally:
            self.db.lock.release()
        return False


def _plain(values):
    """A request can carry a list or object where an id belongs; refuse it here as bad input, not as a crash."""
    for v in values:
        if v is not None and not isinstance(v, (int, float, str, bytes)):
            raise ValueError(f'a value of type {type(v).__name__} cannot be saved')
        if isinstance(v, int) and abs(v) >= 2 ** 63:
            raise ValueError('a number is too big to be saved')


def _split(script):
    parts, buf = [], []
    for line in script.splitlines():
        if line.strip().startswith('--'):
            continue
        buf.append(line)
        if line.rstrip().endswith(';'):
            parts.append('\n'.join(buf))
            buf = []
    if ''.join(buf).strip():
        parts.append('\n'.join(buf))
    return [p for p in parts if p.strip()]
