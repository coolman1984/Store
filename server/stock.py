"""Where every piece is: stock by location and shelf, serial numbers, receiving, transfers and stock counts.

Stock is never stored: it is the sum of append-only moves. A serial number's state is its latest move.
Receiving updates the moving average cost (append-only cost history) so profit uses the real cost of goods.
"""
import json
import math
from datetime import timedelta

import catalog
import ids
from core import NotFound, Problem, money, quantity, text, rows


def move(ctx, product_id, location_id, qty, kind, ref_type, ref_id, unit_cost=0, serial=None, note='', at=None):
    ctx.db.insert('stock_moves', {'id': ids.uuid7(), 'org_id': ctx.org_id, 'branch_id': ctx.branch_id, 'product_id': product_id,
                                  'location_id': location_id, 'qty': round(qty, 3), 'unit_cost': int(unit_cost), 'kind': kind,
                                  'serial': serial, 'ref_type': ref_type, 'ref_id': ref_id, 'note': note,
                                  'at': at or ids.iso(), 'by_user': ctx.uid})


def on_hand(db, product_id, location_id=None):
    if location_id:
        return round(db.value('SELECT COALESCE(SUM(qty), 0) FROM stock_moves WHERE product_id = ? AND location_id = ?',
                              product_id, location_id), 3)
    return round(db.value('SELECT COALESCE(SUM(m.qty), 0) FROM stock_moves m JOIN locations l ON l.id = m.location_id '
                          'WHERE m.product_id = ? AND l.sellable = 1', product_id), 3)


def serial_state(db, serial):
    """None, or {product_id, location_id, in_stock, last kind, at} from the latest move of this serial."""
    last = db.one('SELECT * FROM stock_moves WHERE serial = ? ORDER BY at DESC, id DESC LIMIT 1', serial)
    if not last:
        return None
    return {'product_id': last['product_id'], 'location_id': last['location_id'], 'in_stock': last['qty'] > 0,
            'kind': last['kind'], 'at': last['at'], 'ref_type': last['ref_type'], 'ref_id': last['ref_id']}


def serials_in_stock(db, product_id, location_id=None):
    rows = db.all('SELECT serial, location_id, qty, at FROM stock_moves m WHERE product_id = ? AND serial IS NOT NULL AND '
                  'id = (SELECT id FROM stock_moves n WHERE n.serial = m.serial ORDER BY at DESC, id DESC LIMIT 1) '
                  'ORDER BY at', product_id)
    return [r for r in rows if r['qty'] > 0 and (not location_id or r['location_id'] == location_id)]


def location(db, location_id, sellable=None):
    loc = db.one('SELECT * FROM locations WHERE id = ? AND active = 1', location_id)
    if not loc:
        raise NotFound('location')
    if sellable and not loc['sellable']:
        raise Problem('err.notSellable', 'Goods in this place cannot be sold. Move them to the shop first.')
    return loc


def save_location(ctx, data):
    ctx.need('settings.edit')
    kind = data.get('kind')
    if kind not in ('shop', 'warehouse', 'damaged'):
        raise Problem('err.locationKind', 'Unknown kind of place.')
    name = text(data.get('name'), 'name', 60, True)
    if data.get('id'):
        location(ctx.db, data['id'])
        ctx.db.run('UPDATE locations SET name = ? WHERE id = ?', name, data['id'])
        ctx.audit('location.edit', 'location', data['id'], {'name': name})
        return data['id']
    row = {'id': ids.uuid7(), 'org_id': ctx.org_id, 'branch_id': ctx.branch_id, 'name': name, 'kind': kind,
           'sellable': 1 if kind == 'shop' or (kind == 'warehouse' and data.get('sellable')) else 0, 'active': 1,
           'created_at': ids.iso()}
    ctx.db.insert('locations', row)
    ctx.audit('location.add', 'location', row['id'], {'name': name, 'kind': kind})
    return row['id']


def _update_cost(ctx, product_id, qty, unit_cost, ref_type, ref_id):
    """Moving average: (stock before × old average + received × price) / stock after."""
    before = max(0.0, ctx.db.value('SELECT COALESCE(SUM(qty), 0) FROM stock_moves WHERE product_id = ?', product_id) - qty)
    old = catalog.current_cost(ctx.db, product_id)['avg_cost']
    avg = unit_cost if before <= 0 or not old else round((before * old + qty * unit_cost) / (before + qty))
    ctx.db.insert('costs', {'id': ids.uuid7(), 'product_id': product_id, 'avg_cost': int(avg), 'last_cost': int(unit_cost),
                            'ref_type': ref_type, 'ref_id': ref_id, 'created_at': ids.iso()})


def _serials(raw, qty, product):
    serials = [str(s).strip().upper() for s in (raw or []) if str(s).strip()]
    if len(set(serials)) != len(serials):
        raise Problem('err.serialTwice', 'The same serial number is written twice.')
    if product['track_serial'] and len(serials) != int(qty):
        raise Problem('err.serialCount', f'{product["name"]}: write one serial number for each piece ({int(qty)}).',
                      name=product['name'], n=int(qty))
    if not product['track_serial'] and serials:
        raise Problem('err.noSerials', f'{product["name"]} does not use serial numbers.', name=product['name'])
    return serials


def receive(ctx, data):
    """Goods from a supplier (or opening stock without a supplier). Paid now from the drawer/safe, or owed to the supplier."""
    ctx.need('stock.receive')
    key = text(data.get('idem_key'), 'idem_key', 64, True)
    done = ctx.db.one('SELECT id, number FROM purchases WHERE idem_key = ?', key)
    if done:
        return done
    loc = location(ctx.db, data.get('location_id'))
    supplier_id = data.get('supplier_id') or None
    if supplier_id and not ctx.db.value('SELECT 1 FROM suppliers WHERE id = ?', supplier_id):
        raise NotFound('supplier')
    lines = rows(data.get('lines'))
    if not lines or len(lines) > 500:
        raise Problem('err.noLines', 'Add at least one product.')
    pid = ids.uuid7()
    total, prepared, seen = 0, [], set()
    for line in lines:
        product = catalog.find(ctx.db, line.get('product_id'))
        qty = quantity(line.get('qty'), product['fractional'])
        cost = money(line.get('unit_cost'), 'unit_cost')
        serials = _serials(line.get('serials'), qty, product)
        for s in serials:
            if s in seen:  # the same serial on two lines of one invoice would put one piece in stock twice
                raise Problem('err.serialTwice', 'The same serial number is written twice.')
            seen.add(s)
            st = serial_state(ctx.db, s)
            if st and st['in_stock']:
                raise Problem('err.serialInStock', f'Serial {s} is already in stock.', serial=s)
        total += round(qty * cost)
        prepared.append((product, qty, cost, serials))
    paid = money(data.get('paid_now', 0), 'paid_now')
    if paid > total:
        raise Problem('err.paidTooMuch', 'The amount paid is more than the invoice.')
    if not supplier_id and paid not in (0, total):  # no supplier: opening stock (nothing owed) or fully paid goods
        raise Problem('err.needSupplier', 'Choose the supplier to record what the shop still owes.')
    kind = 'opening' if not supplier_id and not paid else 'purchase'
    at = ids.iso()
    number = ctx.number('purchase')
    ctx.db.insert('purchases', {'id': pid, 'org_id': ctx.org_id, 'branch_id': ctx.branch_id, 'number': number, 'idem_key': key,
                                'supplier_id': supplier_id, 'supplier_ref': text(data.get('supplier_ref'), 'supplier_ref', 40),
                                'location_id': loc['id'], 'total': total, 'at': at, 'by_user': ctx.uid,
                                'note': text(data.get('note'), 'note', 300)})
    for product, qty, cost, serials in prepared:
        ctx.db.insert('purchase_lines', {'id': ids.uuid7(), 'purchase_id': pid, 'product_id': product['id'], 'qty': qty,
                                         'unit_cost': cost, 'serials': json.dumps(serials)})
        if serials:
            for s in serials:
                move(ctx, product['id'], loc['id'], 1, kind, 'purchase', pid, cost, s, at=at)
        else:
            move(ctx, product['id'], loc['id'], qty, kind, 'purchase', pid, cost, at=at)
        _update_cost(ctx, product['id'], qty, cost, 'purchase', pid)
        if data.get('shelf') and not ctx.db.value('SELECT shelf FROM places WHERE product_id = ? AND location_id = ?',
                                                  product['id'], loc['id']):
            catalog.set_place(ctx, product['id'], loc['id'], data['shelf'])
    if supplier_id:
        ctx.db.insert('ap_entries', {'id': ids.uuid7(), 'supplier_id': supplier_id, 'amount': total, 'kind': 'purchase',
                                     'ref_type': 'purchase', 'ref_id': pid, 'idem_key': None, 'note': number, 'at': at,
                                     'by_user': ctx.uid, 'reverses': None})
    if paid:
        import money as cash  # local import: money.py imports this module
        cash.pay_supplier(ctx, {'supplier_id': supplier_id, 'amount': paid, 'source': data.get('pay_from') or 'drawer',
                                'idem_key': key + ':pay', 'note': number}, inside=True) if supplier_id else \
            cash.cash_out(ctx, data.get('pay_from') or 'drawer', 'purchase', paid, 'purchase', pid, number)
    ctx.audit('purchase.receive', 'purchase', pid, {'number': number, 'total': total, 'lines': len(prepared), 'paid': paid})
    return {'id': pid, 'number': number}


def transfer(ctx, data):
    ctx.need('stock.transfer')
    key = text(data.get('idem_key'), 'idem_key', 64, True)
    done = ctx.db.one('SELECT id, number FROM transfers WHERE idem_key = ?', key)
    if done:
        return done
    src, dst = location(ctx.db, data.get('from_id')), location(ctx.db, data.get('to_id'))
    if src['id'] == dst['id']:
        raise Problem('err.samePlace', 'Choose two different places.')
    lines = rows(data.get('lines'))
    if not lines:
        raise Problem('err.noLines', 'Add at least one product.')
    tid, at = ids.uuid7(), ids.iso()
    number = ctx.number('transfer')
    ctx.db.insert('transfers', {'id': tid, 'org_id': ctx.org_id, 'number': number, 'idem_key': key, 'from_id': src['id'],
                                'to_id': dst['id'], 'at': at, 'by_user': ctx.uid, 'note': text(data.get('note'), 'note', 300)})
    for line in lines:
        product = catalog.find(ctx.db, line.get('product_id'))
        qty = quantity(line.get('qty'), product['fractional'])
        serials = _serials(line.get('serials'), qty, product)
        cost = catalog.current_cost(ctx.db, product['id'])['avg_cost']
        if serials:
            for s in serials:
                st = serial_state(ctx.db, s)
                if not st or not st['in_stock'] or st['location_id'] != src['id'] or st['product_id'] != product['id']:
                    raise Problem('err.serialNotHere', f'Serial {s} is not in {src["name"]}.', serial=s, place=src['name'])
                move(ctx, product['id'], src['id'], -1, 'transfer_out', 'transfer', tid, cost, s, at=at)
                move(ctx, product['id'], dst['id'], 1, 'transfer_in', 'transfer', tid, cost, s, at=at)
        else:
            have = on_hand(ctx.db, product['id'], src['id'])
            if have < qty:
                raise Problem('err.notEnough', f'Only {have:g} of {product["name"]} in {src["name"]}.',
                              have=have, name=product['name'], place=src['name'])
            move(ctx, product['id'], src['id'], -qty, 'transfer_out', 'transfer', tid, cost, at=at)
            move(ctx, product['id'], dst['id'], qty, 'transfer_in', 'transfer', tid, cost, at=at)
        if line.get('shelf'):
            catalog.set_place(ctx, product['id'], dst['id'], line['shelf'])
    ctx.audit('stock.transfer', 'transfer', tid, {'number': number, 'from': src['name'], 'to': dst['name'], 'lines': len(lines)})
    return {'id': tid, 'number': number}


# ------------------------------------------------------------------ stock count
def start_count(ctx, location_id, note=''):
    ctx.need('stock.count')
    loc = location(ctx.db, location_id)
    if ctx.db.value('SELECT 1 FROM counts WHERE location_id = ? AND closed_at IS NULL', loc['id']):
        raise Problem('err.countOpen', 'A count of this place is already open. Continue it.')
    cid = ids.uuid7()
    ctx.db.insert('counts', {'id': cid, 'org_id': ctx.org_id, 'number': ctx.number('count'), 'location_id': loc['id'],
                             'started_at': ids.iso(), 'started_by': ctx.uid, 'closed_at': None, 'closed_by': None,
                             'note': text(note, 'note', 300)})
    ctx.audit('count.start', 'count', cid, {'location': loc['name']})
    return cid


def count_line(ctx, count_id, product_id, counted):
    ctx.need('stock.count')
    c = ctx.db.one('SELECT * FROM counts WHERE id = ?', count_id)
    if not c or c['closed_at']:
        raise Problem('err.countClosed', 'This count is closed.')
    product = catalog.find(ctx.db, product_id)
    if isinstance(counted, bool) or not isinstance(counted, (int, float)) or not math.isfinite(counted):
        raise Problem('err.qty', 'Write the number you counted.')
    counted = float(counted)
    if counted < 0 or (not product['fractional'] and counted != int(counted)):
        raise Problem('err.qty', 'Write the number you counted.')
    ctx.db.run('INSERT INTO count_lines(count_id, product_id, counted, at, by_user) VALUES (?, ?, ?, ?, ?) '
               'ON CONFLICT(count_id, product_id) DO UPDATE SET counted = excluded.counted, at = excluded.at, by_user = excluded.by_user',
               count_id, product_id, round(counted, 3), ids.iso(), ctx.uid)


def count_view(db, count_id, can_cost=False):
    c = db.one('SELECT c.*, l.name AS location FROM counts c JOIN locations l ON l.id = c.location_id WHERE c.id = ?', count_id)
    if not c:
        raise NotFound('count')
    # "expected" is what the books said at the moment this product was counted: a sale made after counting it
    # must not turn into a false surplus when the count is closed
    rows = db.all('SELECT p.id, p.sku, p.name, p.unit, pl.shelf, ROUND(COALESCE((SELECT SUM(qty) FROM stock_moves m WHERE '
                  'm.product_id = p.id AND m.location_id = ? AND (cl.at IS NULL OR m.at <= cl.at)), 0), 3) AS expected, '
                  'cl.counted FROM products p '
                  'LEFT JOIN count_lines cl ON cl.count_id = ? AND cl.product_id = p.id '
                  'LEFT JOIN places pl ON pl.product_id = p.id AND pl.location_id = ? '
                  'WHERE p.active = 1 OR cl.counted IS NOT NULL ORDER BY pl.shelf IS NULL, pl.shelf, p.name',
                  c['location_id'], count_id, c['location_id'])
    rows = [r for r in rows if r['expected'] or r['counted'] is not None]
    for r in rows:
        r['diff'] = None if r['counted'] is None else round(r['counted'] - r['expected'], 3)
        if can_cost and r['diff']:
            r['diff_value'] = round(r['diff'] * catalog.current_cost(db, r['id'])['avg_cost'])
    c['lines'] = rows
    c['done'] = sum(1 for r in rows if r['counted'] is not None)
    return c


def close_count(ctx, count_id, reason):
    """Settle every difference with an adjustment move. Lines not counted are left as they are."""
    ctx.need('stock.count')
    reason = text(reason, 'reason', 300)
    if len(reason) < 3:
        raise Problem('err.reason', 'Write the reason (3 letters or more).')
    c = count_view(ctx.db, count_id)
    if c['closed_at']:
        raise Problem('err.countClosed', 'This count is closed.')
    at = ids.iso()
    changed = 0
    for line in c['lines']:
        if line['diff']:
            product = catalog.find(ctx.db, line['id'])
            if product['track_serial'] and line['diff'] > 0:
                raise Problem('err.countSerialFound', f'{product["name"]}: receive found pieces with their serial numbers instead.',
                              name=product['name'])
            if product['track_serial']:
                missing = serials_in_stock(ctx.db, product['id'], c['location_id'])[: int(-line['diff'])]
                for s in missing:  # the oldest serials are marked missing; the owner can review them in the moves
                    move(ctx, product['id'], c['location_id'], -1, 'adjust', 'count', count_id,
                         catalog.current_cost(ctx.db, product['id'])['avg_cost'], s['serial'], reason, at)
            else:
                move(ctx, product['id'], c['location_id'], line['diff'], 'adjust', 'count', count_id,
                     catalog.current_cost(ctx.db, product['id'])['avg_cost'], None, reason, at)
            changed += 1
    ctx.db.run('UPDATE counts SET closed_at = ?, closed_by = ?, note = ? WHERE id = ?', at, ctx.uid, reason, count_id)
    ctx.audit('count.close', 'count', count_id, {'changed': changed, 'reason': reason})
    return {'changed': changed}


def detail(db, product_id, can_cost=False):
    p = catalog.find(db, product_id)
    p['barcodes'] = [r['code'] for r in db.all('SELECT code FROM barcodes WHERE product_id = ?', product_id)]
    p['prices'] = catalog.current_prices(db, product_id)
    p['price_history'] = db.all('SELECT pr.kind, pr.amount, pr.starts_on, pr.reason, pr.created_at, u.full_name AS by_name '
                                'FROM prices pr LEFT JOIN users u ON u.id = pr.created_by WHERE product_id = ? '
                                'ORDER BY pr.starts_on DESC, pr.created_at DESC LIMIT 60', product_id)
    p['upcoming'] = [h for h in p['price_history'] if h['starts_on'] > ids.local_day()]
    p['places'] = db.all('SELECT l.id AS location_id, l.name, l.kind, l.sellable, COALESCE(pl.shelf, \'\') AS shelf, '
                         'ROUND(COALESCE((SELECT SUM(qty) FROM stock_moves m WHERE m.product_id = ? AND m.location_id = l.id), 0), 3) AS qty '
                         'FROM locations l LEFT JOIN places pl ON pl.location_id = l.id AND pl.product_id = ? WHERE l.active = 1 '
                         'ORDER BY l.kind DESC, l.name', product_id, product_id)
    p['on_hand'] = round(sum(x['qty'] for x in p['places'] if x['sellable']), 3)
    p['serials'] = serials_in_stock(db, product_id) if p['track_serial'] else []
    p['moves'] = db.all('SELECT m.at, m.kind, m.qty, m.serial, m.ref_type, m.ref_id, m.note, l.name AS place, u.full_name AS by_name '
                        + (', m.unit_cost ' if can_cost else '') +
                        'FROM stock_moves m JOIN locations l ON l.id = m.location_id LEFT JOIN users u ON u.id = m.by_user '
                        'WHERE m.product_id = ? ORDER BY m.at DESC, m.id DESC LIMIT 80', product_id)
    if can_cost:
        p['cost'] = catalog.current_cost(db, product_id)
    since = ids.iso(ids.utcnow().replace(microsecond=0) - timedelta(days=30))
    p['sold_30d'] = round(db.value('SELECT COALESCE(SUM(-qty), 0) FROM stock_moves WHERE product_id = ? AND kind = \'sale\' AND at >= ?',
                                   product_id, since), 3)
    return p


def overview(db, can_cost=False, q='', only='all', location_id=None, limit=300):
    """The stock page: every product with quantity per place, low stock and value."""
    found = catalog.search(db, q, limit=limit, location_id=location_id)['items'] if q else \
        catalog.search(db, '', limit=limit, location_id=location_id)['items']
    if only == 'low':
        found = [r for r in found if r['reorder_level'] and r['on_hand'] <= r['reorder_level']]
    elif only == 'out':
        found = [r for r in found if r['on_hand'] <= 0]
    if can_cost:
        for r in found:
            r['avg_cost'] = catalog.current_cost(db, r['id'])['avg_cost']
    return found


def low_stock(db, limit=20):
    rows = db.all('SELECT p.id, p.name, p.sku, p.reorder_level, ROUND(COALESCE((SELECT SUM(m.qty) FROM stock_moves m JOIN locations l '
                  'ON l.id = m.location_id WHERE m.product_id = p.id AND l.sellable = 1), 0), 3) AS on_hand FROM products p '
                  'WHERE p.active = 1 AND p.reorder_level > 0')
    rows = [r for r in rows if r['on_hand'] <= r['reorder_level']]
    rows.sort(key=lambda r: (r['on_hand'] > 0, r['on_hand'] - r['reorder_level']))
    return rows[:limit]


def stock_value(db):
    total = 0
    for r in db.all('SELECT m.product_id, SUM(m.qty) AS qty FROM stock_moves m JOIN locations l ON l.id = m.location_id '
                    'GROUP BY m.product_id HAVING SUM(m.qty) > 0'):
        total += round(r['qty'] * catalog.current_cost(db, r['product_id'])['avg_cost'])
    return total


def slow_movers(db, days=60, limit=20):
    """Products in stock that did not sell for `days` days: money sleeping on the shelf."""
    since = ids.iso(ids.utcnow() - timedelta(days=days))
    rows = db.all("SELECT p.id, p.name, p.sku, ROUND(SUM(m.qty), 3) AS on_hand, MAX(CASE WHEN m.kind = 'sale' THEN m.at END) AS last_sale, "
                  'MIN(m.at) AS first_in FROM products p JOIN stock_moves m ON m.product_id = p.id WHERE p.active = 1 '
                  'GROUP BY p.id HAVING SUM(m.qty) > 0 AND (last_sale IS NULL OR last_sale < ?) AND first_in < ? '
                  'ORDER BY COALESCE(last_sale, first_in) LIMIT ?', since, since, limit)
    for r in rows:
        r['value'] = round(r['on_hand'] * catalog.current_cost(db, r['id'])['avg_cost'])
    return rows
