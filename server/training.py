"""Hands-on training inside the practice shop: four everyday problems, each set up fresh with made-up goods and money, and checked
from the shop's own books.

A lesson never reads what the person clicked. It reads what the books now say (a return row, a closed shift, a settled count) with
the same tables the reports use, so "done" means the shop really ended up right, not that a button was pressed. Starting or
restarting a lesson only ADDS new made-up rows (a new sale, a new shift, new stock): nothing is edited or deleted (the ledger
tables refuse that), and it only ever runs in the practice shop (`App.practice`; the real shop answers 403 to every call here).

The four problems:
- `return`: a customer brings back a fridge whose door does not shut. The cashier takes it back as defective, a manager approves,
  the cash goes back from the drawer.
- `drawer`: the drawer is 15 pounds short. The cause is a tea-and-coffee payment nobody wrote down. Record it, then close the shift
  with the real count: the difference is zero.
- `count`: the shelf holds two fans fewer than the books say. Count it, close the count with a reason, the books follow the shelf.
- `discount` (the owner's): a cashier gave a 12% discount a manager approved. The owner finds it in the Owner's eye and marks it
  seen with a note of his own. Nothing in the ledger changes; the lesson reads the review row.

The full reset (throw the practice shop away and rebuild it) is `App.reset_practice`.
"""
import json

import ids
import money as cash
import sales
import sample
import stock
from core import Problem

LESSONS = ('return', 'drawer', 'count', 'discount')
ACCOUNT = {'return': 'cashier', 'drawer': 'cashier', 'count': 'store', 'discount': 'owner'}  # whom the person signs in as for this lesson
APPROVER = 'manager'
MISSING_CASH = 1500    # 15 pounds in piasters
MISSING_PIECES = 2
DISCOUNT_PCT = 12      # above the cashier's 5% and inside the manager's 15%: a manager must approve it, and the Owner's eye lists it from 10%
KEY = 'training'

PRODUCT_FRIDGE = 'ثلاجة ديفروست 14 قدم'
PRODUCT_FAN = 'مروحة ستاند 18 بوصة'
CHEAP = ('سلة غسيل بلاستيك', 'علبة حفظ طعام 3 قطع', 'لمبة ليد 12 وات')


def _state(db):
    raw = db.value('SELECT value FROM meta WHERE key = ?', KEY)
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def _save(db, st):
    db.run("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", KEY, json.dumps(st))


def _user(app, username):
    u = app.db.one('SELECT * FROM users WHERE username = ? AND active = 1', username)
    if not u:
        raise Problem('err.trainingUsers', 'The practice accounts are missing. Rebuild the practice shop from the Help page.', 409)
    return u


def _ctx(app, username):
    return sample.ctx_for(app, _user(app, username))


def _place(db, kind):
    row = db.value('SELECT id FROM locations WHERE kind = ? AND active = 1 ORDER BY name LIMIT 1', kind)
    if not row:
        raise Problem('err.trainingUsers', 'The practice shop is missing a place. Rebuild it from the Help page.', 409)
    return row


def _product(db, name, serial=None):
    row = db.one('SELECT id, name FROM products WHERE name = ? AND active = 1', name)
    if not row:  # the person renamed it: any product of the same kind will teach the same thing
        row = db.one('SELECT id, name FROM products WHERE active = 1 AND track_serial = ? ORDER BY name LIMIT 1', 1 if serial else 0)
    if not row:
        raise Problem('err.trainingUsers', 'The practice shop has no products. Rebuild it from the Help page.', 409)
    return row


def _supplier(db):
    return db.value('SELECT id FROM suppliers ORDER BY name LIMIT 1')


def _stock_up(app, product_id, place, qty, serial_prefix=None):
    """Made-up stock so the exercise never fails because earlier attempts used the goods up."""
    keeper = _ctx(app, 'store')
    serials = [f'{serial_prefix}{ids.uuid7()[-8:].upper()}' for _ in range(qty)] if serial_prefix else []
    stock.receive(keeper, {'idem_key': ids.uuid7(), 'location_id': place, 'supplier_id': _supplier(app.db),
                           'lines': [{'product_id': product_id, 'qty': qty, 'unit_cost': 1000000 if serial_prefix else 4000, 'serials': serials}],
                           'paid_now': 0})


def _shift(app, cctx):
    return cash.open_shift_of(app.db, cctx.uid) or {'id': cash.open_shift(cctx, 50000)}


def _sell(cctx, lines, customer_id=None):
    q = sales.quote(cctx, {'lines': lines})
    sale = {'idem_key': ids.uuid7(), 'lines': lines, 'payments': [{'method': 'cash', 'amount': q['subtotal']}]}
    if customer_id:
        sale['customer_id'] = customer_id
    return sales.sell(cctx, sale)


# ------------------------------------------------------------------ setting a lesson up (each adds new rows only)
def _prepare_return(app):
    db = app.db
    cctx = _ctx(app, ACCOUNT['return'])
    _shift(app, cctx)
    product = _product(db, PRODUCT_FRIDGE, serial=True)
    shop = _place(db, 'shop')
    here = stock.serials_in_stock(db, product['id'], shop)
    if not here:
        _stock_up(app, product['id'], shop, 2, 'TRN')
        here = stock.serials_in_stock(db, product['id'], shop)
    serial = here[0]['serial']
    customer = db.one("SELECT id, name FROM customers WHERE active = 1 ORDER BY name LIMIT 1")
    sale = _sell(cctx, [{'product_id': product['id'], 'qty': 1, 'serial': serial}], customer['id'] if customer else None)
    return {'sale_id': sale['id'], 'number': sale['number'], 'total': sale['total'], 'product': product['name'], 'serial': serial,
            'customer': customer['name'] if customer else '', 'approver': APPROVER}


def _prepare_drawer(app):
    db = app.db
    cctx = _ctx(app, ACCOUNT['drawer'])
    old = cash.open_shift_of(db, cctx.uid)
    if old:  # the cashier's earlier shift is closed the normal way (counted = expected), so the drawer starts clean
        cash.close_shift(cctx, old['id'], cash.drawer_expected(db, old['id']), '')
    shift_id = cash.open_shift(cctx, 50000)
    shop = _place(db, 'shop')
    picked = []
    for name in CHEAP:
        p = db.one('SELECT id FROM products WHERE name = ? AND active = 1', name)
        if p and stock.on_hand(db, p['id'], shop) >= 5:
            picked.append(p['id'])
    if len(picked) < 3:  # a renamed or sold-out sample: any three plain products with stock will do
        for r in db.all('SELECT id FROM products WHERE active = 1 AND track_serial = 0 ORDER BY name'):
            if r['id'] not in picked and stock.on_hand(db, r['id'], shop) >= 5:
                picked.append(r['id'])
            if len(picked) == 3:
                break
    for pid in picked[:3]:
        _sell(cctx, [{'product_id': pid, 'qty': 1}])
    expected = cash.drawer_expected(db, shift_id)
    number = db.value('SELECT number FROM shifts WHERE id = ?', shift_id)
    return {'shift_id': shift_id, 'number': number, 'expected': expected, 'physical': expected - MISSING_CASH, 'missing': MISSING_CASH}


def _prepare_count(app):
    db = app.db
    keeper = _ctx(app, ACCOUNT['count'])
    product = _product(db, PRODUCT_FAN, serial=False)
    shop = _place(db, 'shop')
    if stock.on_hand(db, product['id'], shop) < 6:
        _stock_up(app, product['id'], shop, 10)
    open_count = db.value('SELECT id FROM counts WHERE location_id = ? AND closed_at IS NULL', shop)
    if open_count:  # an unfinished sheet from before blocks a new one: close it without touching anything it did not count
        stock.close_count(keeper, open_count, 'تجهيز التدريب')
    onhand = stock.on_hand(db, product['id'], shop)
    place = db.value('SELECT name FROM locations WHERE id = ?', shop)
    return {'product_id': product['id'], 'product': product['name'], 'location_id': shop, 'place': place,
            'expected': onhand, 'physical': onhand - MISSING_PIECES, 'missing': MISSING_PIECES}


def _prepare_discount(app):
    db = app.db
    cctx = _ctx(app, 'cashier')
    _shift(app, cctx)
    product = _product(db, PRODUCT_FAN, serial=False)
    shop = _place(db, 'shop')
    if stock.on_hand(db, product['id'], shop) < 3:
        _stock_up(app, product['id'], shop, 10)
    lines = [{'product_id': product['id'], 'qty': 1}]
    subtotal = sales.quote(cctx, {'lines': lines})['subtotal']
    discount = (subtotal * DISCOUNT_PCT // 100 // 100) * 100
    cctx.approver = _user(app, APPROVER)   # the manager signed it off at the counter; the owner has not seen it yet
    sale = sales.sell(cctx, {'idem_key': ids.uuid7(), 'lines': lines, 'discount': discount,
                             'payments': [{'method': 'cash', 'amount': subtotal - discount}]})
    return {'sale_id': sale['id'], 'number': sale['number'], 'product': product['name'], 'given': discount,
            'pct': round(discount * 100 / subtotal), 'approver': APPROVER, 'approver_name': _user(app, APPROVER)['full_name']}


PREPARE = {'return': _prepare_return, 'drawer': _prepare_drawer, 'count': _prepare_count, 'discount': _prepare_discount}


# ------------------------------------------------------------------ reading the books
def _checks_return(db, d):
    r = db.one('SELECT * FROM returns WHERE sale_id = ? ORDER BY at LIMIT 1', d['sale_id'])
    lines = db.all('SELECT condition FROM return_lines WHERE return_id = ?', r['id']) if r else []
    return [('returned', bool(r)),
            ('damaged', any(x['condition'] == 'damaged' for x in lines)),
            ('approved', bool(r and r['approved_by'] and r['approved_by'] != r['by_user'])),
            ('cash', bool(r and r['refund_method'] == 'cash'))]


def _checks_drawer(db, d):
    s = db.one('SELECT * FROM shifts WHERE id = ?', d['shift_id'])
    spent = db.value("SELECT COALESCE(SUM(-amount), 0) FROM cash_moves WHERE account = 'drawer' AND shift_id = ? AND kind = 'expense' "
                     "AND reverses IS NULL AND id NOT IN (SELECT reverses FROM cash_moves WHERE reverses IS NOT NULL)", d['shift_id'])
    closed = bool(s and s['closed_at'])
    return [('expense', spent == d['missing']), ('closed', closed),
            ('exact', closed and s['counted'] == d['physical'] and s['counted'] == s['expected'])]


def _checks_count(db, d):
    c = db.one('SELECT * FROM counts WHERE location_id = ? AND started_at >= ? ORDER BY started_at DESC LIMIT 1', d['location_id'], d['at'])
    line = db.one('SELECT counted FROM count_lines WHERE count_id = ? AND product_id = ?', c['id'], d['product_id']) if c else None
    closed = bool(c and c['closed_at'])
    moved = db.value("SELECT COALESCE(SUM(qty), 0) FROM stock_moves WHERE ref_type = 'count' AND ref_id = ? AND product_id = ?",
                     c['id'], d['product_id']) if c else 0
    return [('counted', bool(line and line['counted'] == d['physical'])), ('closed', closed), ('settled', closed and moved == -d['missing'])]


def _checks_discount(db, d):
    r = db.one('SELECT r.note FROM watch_reviews r JOIN users u ON u.id = r.by_user WHERE r.item = ? AND u.username = ?',
               'disc:' + d['sale_id'], ACCOUNT['discount'])   # the owner's own review: a manager has the same permission and must not finish the owner's exercise
    return [('seen', bool(r)), ('noted', bool(r and r['note'].strip() not in ('', '✓')))]


CHECK = {'return': _checks_return, 'drawer': _checks_drawer, 'count': _checks_count, 'discount': _checks_discount}


def view(app):
    """Every lesson with where the person stands: new / open / done, and each check on its own, so the screen can say what is still missing."""
    st = _state(app.db)
    out = []
    for lesson in LESSONS:
        entry = st.get(lesson)
        if not entry:
            out.append({'id': lesson, 'state': 'new', 'account': ACCOUNT[lesson], 'checks': []})
            continue
        checks = [{'key': k, 'ok': bool(ok)} for k, ok in CHECK[lesson](app.db, {**entry['data'], 'at': entry['at']})]
        out.append({'id': lesson, 'state': 'done' if all(c['ok'] for c in checks) else 'open', 'account': ACCOUNT[lesson],
                    'attempt': entry['attempt'], 'data': entry['data'], 'checks': checks})
    return {'lessons': out, 'password': sample.DEMO_PASSWORD, 'approver': APPROVER}


def start(app, ctx, lesson, restart=False):
    """Set a lesson up (once), or set it up again from the beginning. Runs inside the caller's transaction."""
    if not app.practice:
        raise Problem('err.practiceOnly', 'Training is available in the practice shop only.', 403)
    if lesson not in LESSONS:
        raise Problem('err.badRequest', 'The request is not understood.', 400)
    st = _state(app.db)
    if lesson in st and not restart:
        return view(app)
    at = ids.iso()
    data = PREPARE[lesson](app)
    st[lesson] = {'attempt': (st.get(lesson) or {}).get('attempt', 0) + 1, 'at': at, 'data': data}
    _save(app.db, st)
    ctx.audit('training.start', 'training', lesson, {'attempt': st[lesson]['attempt'], 'restart': bool(restart)})
    return view(app)
