"""Numbers that drive decisions: today, the advisor ("do this now"), reports, and the owner's eye.

The owner's eye lists what deserves a look (big discounts, selling under cost, returns, drawer differences, big expenses,
price changes, stock losses, sales after hours, selling more than stock, reversed payments). Each item can be marked
reviewed with a note; nothing in the ledger changes.
"""
from datetime import timedelta

import ids
import money as cash
import stock
from core import settings


def _range(day_from, day_to):
    start, _ = ids.day_bounds(day_from)
    _, end = ids.day_bounds(day_to)
    return start, end


def summary(db, day_from, day_to, can_cost=False):
    start, end = _range(day_from, day_to)
    s = db.one('SELECT COUNT(*) AS count, COALESCE(SUM(total), 0) AS total, COALESCE(SUM(discount), 0) AS discount, '
               'COALESCE(SUM(fee), 0) AS fee, COALESCE(SUM(cost_total), 0) AS cost FROM sales WHERE at >= ? AND at < ?', start, end)
    r = db.one('SELECT COUNT(*) AS count, COALESCE(SUM(total), 0) AS total FROM returns WHERE at >= ? AND at < ?', start, end)
    returned_cost = db.value('SELECT COALESCE(SUM(rl.qty * sl.unit_cost), 0) FROM return_lines rl JOIN returns r ON r.id = rl.return_id '
                             'JOIN sale_lines sl ON sl.id = rl.sale_line_id WHERE r.at >= ? AND r.at < ?', start, end)
    methods = {m['method']: m['amount'] for m in db.all("SELECT method, SUM(amount) AS amount FROM tenders WHERE ref_type IN ('sale', 'return') "
                                                         'AND at >= ? AND at < ? GROUP BY method', start, end)}
    expenses = -db.value("SELECT COALESCE(SUM(amount), 0) FROM cash_moves WHERE kind = 'expense' AND at >= ? AND at < ?", start, end)
    expenses -= db.value("SELECT COALESCE(SUM(c.amount), 0) FROM cash_moves c JOIN cash_moves o ON o.id = c.reverses "
                         "WHERE o.kind = 'expense' AND c.at >= ? AND c.at < ?", start, end)
    collections = -db.value("SELECT COALESCE(SUM(amount), 0) FROM ar_entries WHERE kind IN ('payment', 'reversal') AND ref_type = 'collection' "
                            'AND at >= ? AND at < ?', start, end)
    out = {'from': day_from, 'to': day_to, 'sales_count': s['count'], 'sales': s['total'], 'discount': s['discount'],
           'fee': s['fee'], 'returns_count': r['count'], 'returns': r['total'], 'net': s['total'] - r['total'],
           'methods': methods, 'expenses': expenses, 'collections': collections,
           'average_sale': (s['total'] // s['count']) if s['count'] else 0}
    if can_cost:
        out['cost'] = s['cost'] - round(returned_cost)
        out['gross_profit'] = out['net'] - out['cost']
        out['margin_pct'] = round(out['gross_profit'] * 100 / out['net'], 1) if out['net'] else 0
    return out


def daily_series(db, days=30, can_cost=False):
    today = ids.local_day()
    first = (ids.utcnow() - timedelta(days=days - 1)).astimezone().date().isoformat()
    start, end = _range(first, today)
    by_day = {}
    for row in db.all('SELECT at, total, cost_total FROM sales WHERE at >= ? AND at < ?', start, end):
        d = ids.local_day(ids.parse(row['at']))
        b = by_day.setdefault(d, {'sales': 0, 'cost': 0, 'count': 0})
        b['sales'] += row['total']
        b['cost'] += row['cost_total']
        b['count'] += 1
    for row in db.all('SELECT at, total FROM returns WHERE at >= ? AND at < ?', start, end):
        d = ids.local_day(ids.parse(row['at']))
        by_day.setdefault(d, {'sales': 0, 'cost': 0, 'count': 0})['sales'] -= row['total']
    out = []
    for i in range(days):
        d = (ids.utcnow() - timedelta(days=days - 1 - i)).astimezone().date().isoformat()
        b = by_day.get(d, {'sales': 0, 'cost': 0, 'count': 0})
        item = {'day': d, 'sales': b['sales'], 'count': b['count']}
        if can_cost:
            item['profit'] = b['sales'] - b['cost']
        out.append(item)
    return out


def by_group(db, day_from, day_to, group='category', can_cost=False, limit=50):
    start, end = _range(day_from, day_to)
    col = {'category': 'COALESCE(c.name, "—")', 'brand': 'COALESCE(b.name, "—")', 'product': 'sl.name',
           'user': 'u.full_name'}[group]
    col = col.replace('"—"', "'—'")
    rows = db.all(f'SELECT {col} AS name, ROUND(SUM(sl.qty), 3) AS qty, SUM(sl.line_total) AS sales, '
                  'SUM(ROUND(sl.qty * sl.unit_cost)) AS cost FROM sale_lines sl JOIN sales s ON s.id = sl.sale_id '
                  'JOIN products p ON p.id = sl.product_id LEFT JOIN categories c ON c.id = p.category_id '
                  'LEFT JOIN brands b ON b.id = p.brand_id JOIN users u ON u.id = s.by_user '
                  f'WHERE s.at >= ? AND s.at < ? GROUP BY {col} ORDER BY sales DESC LIMIT ?', start, end, limit)
    for r in rows:
        if can_cost:
            r['profit'] = r['sales'] - r['cost']
        else:
            r.pop('cost')
    return rows


def year_turnover(db, year=None):
    """Sales minus returns of a calendar year: what the simplified tax regime (law 6/2025) is measured on."""
    year = year or int(ids.local_day()[:4])
    start, _ = ids.day_bounds(f'{year}-01-01')
    _, end = ids.day_bounds(f'{year}-12-31')
    sales = db.value('SELECT COALESCE(SUM(total), 0) FROM sales WHERE at >= ? AND at < ?', start, end)
    rets = db.value('SELECT COALESCE(SUM(total), 0) FROM returns WHERE at >= ? AND at < ?', start, end)
    return {'year': year, 'sales': sales, 'returns': rets, 'turnover': sales - rets}


def balances(db):
    return {'customers_owe': db.value('SELECT COALESCE(SUM(amount), 0) FROM ar_entries'),
            'shop_owes_suppliers': db.value('SELECT COALESCE(SUM(amount), 0) FROM ap_entries'),
            'safe': cash.safe_balance(db),
            'drawers': db.value("SELECT COALESCE(SUM(c.amount), 0) FROM cash_moves c JOIN shifts s ON s.id = c.shift_id "
                                "WHERE c.account = 'drawer' AND s.closed_at IS NULL"),
            'finance_due': sum(r['amount'] for r in cash.finance_due(db))}


# ------------------------------------------------------------------ the owner's eye
def watch(db, days=7, include_reviewed=False):
    cfg = settings(db)
    since = ids.iso(ids.utcnow() - timedelta(days=days))
    reviewed = {r['item']: r for r in db.all('SELECT * FROM watch_reviews')}
    items = []

    def add(key, kind, at, who, amount=0, detail=None, ref=None, level='warn'):
        r = reviewed.get(key)
        if r and not include_reviewed:
            return
        items.append({'key': key, 'kind': kind, 'at': at, 'who': who, 'amount': amount, 'detail': detail or {}, 'ref': ref,
                      'level': level, 'reviewed': r})

    for s in db.all('SELECT s.*, u.full_name AS who, u.max_discount_pct, a.full_name AS approver FROM sales s JOIN users u ON u.id = s.by_user '
                    'LEFT JOIN users a ON a.id = s.approved_by WHERE s.at >= ?', since):
        listed = db.value('SELECT COALESCE(SUM(ROUND(qty * MAX(list_price, unit_price))), 0) FROM sale_lines WHERE sale_id = ?', s['id'])
        given = listed - (s['subtotal'] - s['discount'])
        pct = given * 100 / listed if listed else 0
        if given > 0 and (pct >= 10 or s['approved_by']):
            add('disc:' + s['id'], 'discount', s['at'], s['who'], given, {'number': s['number'], 'pct': round(pct, 1),
                                                                         'approver': s['approver']}, {'sale': s['id']},
                'bad' if pct >= 15 else 'warn')
        if s['cost_total'] and s['total'] < s['cost_total']:
            add('cost:' + s['id'], 'under_cost', s['at'], s['who'], s['cost_total'] - s['total'], {'number': s['number']},
                {'sale': s['id']}, 'bad')
        hour = ids.parse(s['at']).astimezone().hour
        if hour < int(cfg['opening_hour']) or hour >= int(cfg['closing_hour']):
            add('late:' + s['id'], 'after_hours', s['at'], s['who'], s['total'], {'number': s['number'], 'hour': hour}, {'sale': s['id']})
    for r in db.all('SELECT r.*, u.full_name AS who, s.number AS sale_number, s.by_user AS seller, s.at AS sold_at FROM returns r '
                    'JOIN users u ON u.id = r.by_user JOIN sales s ON s.id = r.sale_id WHERE r.at >= ?', since):
        same_day = ids.local_day(ids.parse(r['at'])) == ids.local_day(ids.parse(r['sold_at']))
        add('ret:' + r['id'], 'return', r['at'], r['who'], r['total'], {'number': r['number'], 'sale': r['sale_number'], 'reason': r['reason'],
                                                                       'same_day': same_day, 'same_person': r['seller'] == r['by_user'],
                                                                       'method': r['refund_method']},
            {'sale': r['sale_id']}, 'bad' if same_day and r['refund_method'] == 'cash' else 'warn')
    for s in db.all('SELECT s.*, u.full_name AS who FROM shifts s JOIN users u ON u.id = s.user_id WHERE s.closed_at >= ? '
                    'AND s.counted != s.expected', since):
        diff = s['counted'] - s['expected']
        add('shift:' + s['id'], 'drawer_short' if diff < 0 else 'drawer_over', s['closed_at'], s['who'], abs(diff),
            {'number': s['number'], 'note': s['close_note']}, {'shift': s['id']}, 'bad' if diff < 0 else 'warn')
    for e in db.all("SELECT c.*, u.full_name AS who FROM cash_moves c JOIN users u ON u.id = c.by_user WHERE c.at >= ? AND "
                    "((c.kind = 'expense' AND -c.amount >= ?) OR c.kind IN ('reversal', 'withdraw'))", since, int(cfg['large_expense'])):
        add('cash:' + e['id'], {'expense': 'big_expense', 'reversal': 'reversal', 'withdraw': 'withdraw'}[e['kind']], e['at'], e['who'],
            abs(e['amount']), {'note': e['note'], 'category': e['category']}, None, 'warn' if e['kind'] != 'reversal' else 'bad')
    for p in db.all('SELECT pr.batch_id, pr.reason, MIN(pr.created_at) AS at, COUNT(DISTINCT pr.product_id) AS products, u.full_name AS who, '
                    'MIN(pr.starts_on) AS starts_on FROM prices pr JOIN users u ON u.id = pr.created_by WHERE pr.created_at >= ? '
                    "AND pr.reason != 'product form' GROUP BY COALESCE(pr.batch_id, pr.id)", since):
        add('price:' + (p['batch_id'] or p['at']), 'price_change', p['at'], p['who'], 0,
            {'products': p['products'], 'reason': p['reason'], 'starts_on': p['starts_on']}, None, 'info')
    for c in db.all("SELECT c.id, c.number, c.closed_at, u.full_name AS who, l.name AS place FROM counts c JOIN users u ON u.id = c.closed_by "
                    'JOIN locations l ON l.id = c.location_id WHERE c.closed_at >= ?', since):
        loss = db.value("SELECT COALESCE(SUM(ROUND(-qty * unit_cost)), 0) FROM stock_moves WHERE ref_id = ? AND kind = 'adjust' AND qty < 0",
                        c['id'])
        if loss:
            add('count:' + c['id'], 'stock_loss', c['closed_at'], c['who'], loss, {'number': c['number'], 'place': c['place']},
                {'count': c['id']}, 'bad')
    for m in db.all("SELECT m.product_id, m.location_id, p.name, MAX(m.at) AS at FROM stock_moves m JOIN products p ON p.id = m.product_id "
                    "WHERE m.kind = 'sale' AND m.at >= ? GROUP BY m.product_id, m.location_id", since):
        have = stock.on_hand(db, m['product_id'], m['location_id'])
        if have < 0:
            add(f'neg:{m["product_id"]}:{m["location_id"]}:{ids.local_day()}', 'negative_stock', m['at'], '', 0,
                {'name': m['name'], 'qty': have}, {'product': m['product_id']}, 'warn')
    for a in db.all("SELECT * FROM ar_entries WHERE kind = 'reversal' AND at >= ?", since):
        who = db.value('SELECT full_name FROM users WHERE id = ?', a['by_user'])
        add('arrev:' + a['id'], 'payment_reversed', a['at'], who, a['amount'], {'note': a['note'], 'number': a['ref_id']},
            {'customer': a['customer_id']}, 'bad')
    for d in db.all("SELECT * FROM audit WHERE action = 'denied' AND at >= ?", since):
        add('deny:' + d['id'], 'denied', d['at'], d['user_name'], 0, {'what': d['entity']}, None, 'info')
    order = {'bad': 0, 'warn': 1, 'info': 2}
    items.sort(key=lambda i: i['at'], reverse=True)
    items.sort(key=lambda i: order[i['level']])
    return items


def review(ctx, key, note):
    ctx.need('watch.view')
    note = (note or '').strip()[:300] or '✓'
    ctx.db.run('INSERT INTO watch_reviews(item, note, at, by_user) VALUES (?, ?, ?, ?) ON CONFLICT(item) DO UPDATE SET '
               'note = excluded.note, at = excluded.at, by_user = excluded.by_user', key, note, ids.iso(), ctx.uid)
    ctx.audit('watch.review', 'watch', key, {'note': note})


# ------------------------------------------------------------------ advisor
def advisor(db, ctx, licence_state=None, backup_age_hours=None):
    """Ranked "do this now" items for the home page, each with a target page."""
    out = []
    shift = cash.open_shift_of(db, ctx.uid)
    if ctx.can('pos.sell') and not shift:
        out.append({'id': 'open_shift', 'level': 'info', 'go': 'cash'})
    if not db.value('SELECT 1 FROM products LIMIT 1') and ctx.can('products.edit'):
        out.append({'id': 'add_products', 'level': 'info', 'go': 'products'})
    if ctx.can('installments.collect'):
        due = cash.instalments_due(db)
        if due:
            out.append({'id': 'late_instalments', 'level': 'bad', 'go': 'customers', 'n': len(due), 'amount': sum(d['due_now'] for d in due)})
    if ctx.can('stock.receive') or ctx.can('products.edit'):
        low = stock.low_stock(db)
        if low:
            out.append({'id': 'low_stock', 'level': 'warn', 'go': 'stock', 'n': len(low), 'names': [r['name'] for r in low[:3]]})
    if ctx.can('watch.view'):
        n = len(watch(db, 7))
        if n:
            out.append({'id': 'watch', 'level': 'warn', 'go': 'watch', 'n': n})
    upcoming = db.value('SELECT COUNT(DISTINCT product_id) FROM prices WHERE starts_on > ?', ids.local_day())
    if upcoming and ctx.can('prices.change'):
        out.append({'id': 'upcoming_prices', 'level': 'info', 'go': 'products', 'n': upcoming})
    if ctx.can('settings.edit') and (backup_age_hours is None or backup_age_hours > 30):
        out.append({'id': 'backup', 'level': 'warn', 'go': 'settings', 'hours': backup_age_hours})
    if licence_state and licence_state.get('state') in ('trial', 'active') and licence_state.get('days_left') is not None \
            and licence_state['days_left'] <= 3:
        out.append({'id': 'licence_soon', 'level': 'warn', 'go': 'settings', 'days': licence_state['days_left']})
    if ctx.can('cost.view'):
        slow = stock.slow_movers(db, 60, 5)
        if slow:
            out.append({'id': 'slow_stock', 'level': 'info', 'go': 'reports', 'n': len(slow), 'value': sum(r['value'] for r in slow)})
    rank = {'bad': 0, 'warn': 1, 'info': 2}
    out.sort(key=lambda a: rank[a['level']])
    return out


def home(db, ctx, licence_state=None, backup_age_hours=None):
    today = ids.local_day()
    can_cost = ctx.can('cost.view')
    data = {'today': today, 'advisor': advisor(db, ctx, licence_state, backup_age_hours)}
    if ctx.can('reports.view'):
        data['summary'] = summary(db, today, today, can_cost)
        yesterday = (ids.utcnow() - timedelta(days=1)).astimezone().date().isoformat()
        data['yesterday'] = summary(db, yesterday, yesterday, can_cost)
        data['series'] = daily_series(db, 14, can_cost)
        data['balances'] = balances(db)
        data['top'] = by_group(db, today, today, 'product', can_cost, 5)
    shift = cash.open_shift_of(db, ctx.uid)
    data['shift'] = cash.shift_summary(db, shift['id']) if shift else None
    if data['shift']:
        data['shift'].pop('moves', None)
    if ctx.can('installments.collect'):
        data['due'] = cash.instalments_due(db)[:6]
    return data

