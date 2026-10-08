"""Products, barcodes, shelves and dated prices.

Prices change often in Egypt (several rises in a few months), so:
- a price is a dated row; a change starts on a chosen day and never rewrites a past sale (factory DATA-07);
- bulk change by brand/category/percentage, rounded to a friendly step, with one batch id so it can be reviewed;
- every product may have a minimum price; selling under it needs a manager's approval.
"""
import ids
from core import NotFound, Problem, money, text, whole

UNITS = ('piece', 'set', 'box', 'dozen', 'meter', 'roll', 'kg', 'pair')


def _name_table(ctx, table, name):
    name = text(name, 'name', 80, True)
    found = ctx.db.one(f'SELECT * FROM {table} WHERE name = ? COLLATE NOCASE', name)
    if found:
        return found['id']
    row = {'id': ids.uuid7(), 'org_id': ctx.org_id, 'name': name, 'active': 1}
    ctx.db.insert(table, row)
    return row['id']


def lookups(db):
    return {'categories': db.all('SELECT id, name FROM categories WHERE active = 1 ORDER BY name'),
            'brands': db.all('SELECT id, name FROM brands WHERE active = 1 ORDER BY name'),
            'locations': db.all('SELECT id, name, kind, sellable FROM locations WHERE active = 1 ORDER BY kind DESC, name'),
            'units': list(UNITS)}


def current_prices(db, product_id, day=None):
    day = day or ids.local_day()
    out = {'retail': 0, 'trade': 0, 'min': 0}
    for row in db.all('SELECT kind, amount FROM (SELECT kind, amount, ROW_NUMBER() OVER (PARTITION BY kind '
                      'ORDER BY starts_on DESC, created_at DESC, id DESC) AS rn FROM prices WHERE product_id = ? AND starts_on <= ?) '
                      'WHERE rn = 1', product_id, day):
        out[row['kind']] = row['amount']
    return out


def current_cost(db, product_id):
    row = db.one('SELECT avg_cost, last_cost FROM costs WHERE product_id = ? ORDER BY created_at DESC, id DESC LIMIT 1',
                 product_id)
    return row or {'avg_cost': 0, 'last_cost': 0}


def set_price(ctx, product_id, kind, amount, starts_on=None, reason='', batch_id=None):
    if kind not in ('retail', 'trade', 'min'):
        raise Problem('err.priceKind', 'Unknown price kind.')
    starts_on = starts_on or ids.local_day()
    if starts_on < ids.local_day():
        raise Problem('err.pastPrice', 'A new price cannot start in the past: past sales keep their price.')
    ctx.db.insert('prices', {'id': ids.uuid7(), 'product_id': product_id, 'kind': kind, 'amount': money(amount, 'price'),
                             'starts_on': starts_on, 'reason': text(reason, 'reason', 200), 'batch_id': batch_id,
                             'created_at': ids.iso(), 'created_by': ctx.uid})


def _clean_barcodes(ctx, codes, product_id=None):
    out = []
    if codes is not None and not isinstance(codes, list):
        raise Problem('err.barcode', 'Barcodes must be a list.')
    for code in codes or []:
        code = str(code).strip()
        if not code:
            continue
        if not (3 <= len(code) <= 40) or any(ch.isspace() for ch in code):
            raise Problem('err.barcode', 'A barcode is 3 to 40 characters without spaces.')
        owner = ctx.db.value('SELECT product_id FROM barcodes WHERE code = ?', code)
        if owner and owner != product_id:
            name = ctx.db.value('SELECT name FROM products WHERE id = ?', owner)
            raise Problem('err.barcodeTaken', f'This barcode belongs to {name}.', name=name)
        out.append(code)
    return list(dict.fromkeys(out))


def _sku(ctx):
    n = (ctx.db.value("SELECT COUNT(*) FROM products") or 0) + 1
    while ctx.db.value('SELECT 1 FROM products WHERE sku = ?', f'{n:05d}'):
        n += 1
    return f'{n:05d}'


def _reorder(value):
    if value is None or value == '':
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value < 0 or value > 1_000_000:
        raise Problem('err.qty', 'Quantity must be a number.')
    return float(value)


def save_product(ctx, data):
    """Create (no id) or edit a product. Prices given here start today."""
    ctx.need('products.edit')
    pid = data.get('id')
    old = ctx.db.one('SELECT * FROM products WHERE id = ?', pid) if pid else None
    if pid and not old:
        raise NotFound('product')
    name = text(data.get('name', old and old['name']), 'name', 120, True)
    unit = data.get('unit', old['unit'] if old else 'piece')
    if unit not in UNITS:
        raise Problem('err.unit', 'Unknown unit.')
    row = {
        'name': name,
        'model': text(data.get('model', old and old['model']), 'model', 60),
        'unit': unit,
        'fractional': 1 if data.get('fractional', old and old['fractional']) else 0,
        'track_serial': 1 if data.get('track_serial', old and old['track_serial']) else 0,
        'warranty_months': max(0, min(120, whole(data.get('warranty_months', old['warranty_months'] if old else 0), 'warranty_months'))),
        'reorder_level': _reorder(data.get('reorder_level', old['reorder_level'] if old else 0)),
        'notes': text(data.get('notes', old and old['notes']), 'notes', 500),
        'category_id': _name_table(ctx, 'categories', data['category']) if data.get('category') else (old and old['category_id']),
        'brand_id': _name_table(ctx, 'brands', data['brand']) if data.get('brand') else (old and old['brand_id']),
        'changed_at': ids.iso(),
    }
    if row['track_serial'] and row['fractional']:
        raise Problem('err.serialFraction', 'A product with serial numbers is sold in whole pieces.')
    if old and row['track_serial'] != old['track_serial'] and ctx.db.value('SELECT 1 FROM stock_moves WHERE product_id = ? LIMIT 1', pid):
        # switching it on or off after goods were received would leave pieces without a serial (or serials without a piece)
        raise Problem('err.serialLocked', 'Serial numbers cannot be switched on or off after goods were received.', 409)
    codes = _clean_barcodes(ctx, data.get('barcodes'), pid) if 'barcodes' in data else None
    sku = text(data.get('sku'), 'sku', 30)
    if old:
        if sku and sku != old['sku']:
            if ctx.db.value('SELECT 1 FROM products WHERE sku = ? AND id != ?', sku, pid):
                raise Problem('err.skuTaken', 'This code is already used by another product.')
            row['sku'] = sku
        sets = ', '.join(f'{k} = ?' for k in row)
        ctx.db.run(f'UPDATE products SET {sets} WHERE id = ?', *row.values(), pid)
        ctx.audit('product.edit', 'product', pid, {k: [old.get(k), v] for k, v in row.items() if old.get(k) != v and k != 'changed_at'})
    else:
        if sku and ctx.db.value('SELECT 1 FROM products WHERE sku = ?', sku):
            raise Problem('err.skuTaken', 'This code is already used by another product.')
        pid = ids.uuid7()
        row.update({'id': pid, 'org_id': ctx.org_id, 'sku': sku or _sku(ctx), 'active': 1,
                    'sample': 1 if data.get('sample') else 0, 'created_at': ids.iso()})
        ctx.db.insert('products', row)
        ctx.audit('product.add', 'product', pid, {'name': name})
    if codes is not None:
        ctx.db.run('DELETE FROM barcodes WHERE product_id = ?', pid)
        for code in codes:
            ctx.db.insert('barcodes', {'code': code, 'product_id': pid})
    prices = current_prices(ctx.db, pid)
    for kind in ('retail', 'trade', 'min'):
        if kind in data and data[kind] is not None and money(data[kind], kind) != prices[kind]:
            ctx.need('prices.change') if old else None
            set_price(ctx, pid, kind, data[kind], reason='product form')
    p = current_prices(ctx.db, pid)
    if p['min'] and p['retail'] and p['min'] > p['retail']:
        raise Problem('err.minAboveRetail', 'The minimum price is higher than the selling price.')
    for place in data.get('places') or []:
        set_place(ctx, pid, place.get('location_id'), place.get('shelf', ''))
    return pid


def set_active(ctx, product_id, active):
    ctx.need('products.edit')
    if not ctx.db.value('SELECT 1 FROM products WHERE id = ?', product_id):
        raise NotFound('product')
    ctx.db.run('UPDATE products SET active = ?, changed_at = ? WHERE id = ?', 1 if active else 0, ids.iso(), product_id)
    ctx.audit('product.active' if active else 'product.hide', 'product', product_id)


def set_place(ctx, product_id, location_id, shelf):
    find(ctx.db, product_id)
    if not ctx.db.value('SELECT 1 FROM locations WHERE id = ?', location_id):
        raise NotFound('location')
    shelf = text(shelf, 'shelf', 20).upper()
    ctx.db.run('INSERT INTO places(product_id, location_id, shelf) VALUES (?, ?, ?) '
               'ON CONFLICT(product_id, location_id) DO UPDATE SET shelf = excluded.shelf', product_id, location_id, shelf)


def bulk_price(ctx, data, apply=False):
    """Raise or lower prices of a brand/category by a percentage, rounded up to a friendly step. Preview unless apply."""
    ctx.need('prices.change')
    pct = data.get('percent') or 0
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise Problem('err.percent', 'Write a percentage between -50 and 200.')
    pct = float(pct)
    if not -50 <= pct <= 200 or pct == 0:
        raise Problem('err.percent', 'Write a percentage between -50 and 200.')
    step = whole(data.get('round_to'), 'round_to') or 100  # piasters: 100 = round to whole pounds
    if step not in (1, 100, 500, 1000, 5000):
        raise Problem('err.roundTo', 'Unknown rounding step.')
    kinds = [k for k in data.get('kinds') or ['retail', 'trade', 'min'] if k in ('retail', 'trade', 'min')]
    starts_on = data.get('starts_on') or ids.local_day()
    where, args = ['active = 1'], []
    if data.get('brand_id'):
        where.append('brand_id = ?')
        args.append(data['brand_id'])
    if data.get('category_id'):
        where.append('category_id = ?')
        args.append(data['category_id'])
    if data.get('product_ids'):
        ids_ = [str(x) for x in data['product_ids']][:2000]
        where.append(f"id IN ({','.join('?' * len(ids_))})")
        args.extend(ids_)
    if len(where) == 1:
        raise Problem('err.bulkScope', 'Choose a brand, a category or products first.')
    rows = ctx.db.all(f"SELECT id, sku, name FROM products WHERE {' AND '.join(where)} ORDER BY name", *args)
    batch = ids.uuid7()
    preview = []
    for p in rows:
        now = current_prices(ctx.db, p['id'])
        new = {}
        for k in kinds:
            if now[k]:
                raw = now[k] * (1 + pct / 100)
                new[k] = int(-(-raw // step) * step) if pct > 0 else int(max(step, round(raw / step) * step))
        if new:
            preview.append({'id': p['id'], 'sku': p['sku'], 'name': p['name'], 'old': now, 'new': new})
    if apply:
        if not preview:
            raise Problem('err.bulkEmpty', 'No product with a price matches this choice.')
        reason = text(data.get('reason'), 'reason', 200) or f'bulk {pct:+g}%'
        for item in preview:
            for k, amount in item['new'].items():
                set_price(ctx, item['id'], k, amount, starts_on, reason, batch)
        ctx.audit('price.bulk', 'batch', batch, {'percent': pct, 'count': len(preview), 'starts_on': starts_on,
                                                 'brand_id': data.get('brand_id'), 'category_id': data.get('category_id')})
    return {'batch_id': batch if apply else None, 'items': preview, 'starts_on': starts_on}


def find(db, product_id):
    p = db.one('SELECT p.*, c.name AS category, b.name AS brand FROM products p LEFT JOIN categories c ON c.id = p.category_id '
               'LEFT JOIN brands b ON b.id = p.brand_id WHERE p.id = ?', product_id)
    if not p:
        raise NotFound('product')
    return p


def search(db, q='', limit=30, with_stock=True, location_id=None, include_hidden=False, filters=None):
    """The fast search behind the sale screen and the products page: barcode first, then code, then words in the name."""
    q = (q or '').strip()
    filters = filters or {}
    where, args = ([] if include_hidden else ['p.active = 1']), []
    exact = None
    if q:
        exact = db.value('SELECT product_id FROM barcodes WHERE code = ?', q) or db.value('SELECT id FROM products WHERE sku = ?', q)
        if exact:
            where.append('p.id = ?')
            args.append(exact)
        else:
            serial_hit = db.value('SELECT product_id FROM stock_moves WHERE serial = ? LIMIT 1', q)
            if serial_hit:
                where.append('p.id = ?')
                args.append(serial_hit)
            else:
                for word in q.split()[:5]:
                    where.append('(p.name LIKE ? OR p.model LIKE ? OR b.name LIKE ? OR p.sku LIKE ?)')
                    args += [f'%{word}%'] * 4
    if filters.get('category_id'):
        where.append('p.category_id = ?')
        args.append(filters['category_id'])
    if filters.get('brand_id'):
        where.append('p.brand_id = ?')
        args.append(filters['brand_id'])
    sql = ('SELECT p.id, p.sku, p.name, p.model, p.unit, p.fractional, p.track_serial, p.warranty_months, p.reorder_level, p.active, '
           'c.name AS category, b.name AS brand FROM products p LEFT JOIN categories c ON c.id = p.category_id '
           'LEFT JOIN brands b ON b.id = p.brand_id' + (' WHERE ' + ' AND '.join(where) if where else '') +
           ' ORDER BY p.name LIMIT ?')
    rows = db.all(sql, *args, max(1, min(int(limit), 500)))
    if not rows:
        return {'items': [], 'exact': False}
    day = ids.local_day()
    pids = [r['id'] for r in rows]
    marks = ','.join('?' * len(pids))
    stock = {}
    for s in db.all(f'SELECT m.product_id, m.location_id, ROUND(SUM(m.qty), 3) AS qty FROM stock_moves m WHERE m.product_id IN ({marks}) '
                    'GROUP BY m.product_id, m.location_id', *pids):
        stock.setdefault(s['product_id'], {})[s['location_id']] = s['qty']
    shelves = {}
    for s in db.all(f'SELECT product_id, location_id, shelf FROM places WHERE product_id IN ({marks})', *pids):
        shelves.setdefault(s['product_id'], {})[s['location_id']] = s['shelf']
    codes = {}
    for b in db.all(f'SELECT product_id, code FROM barcodes WHERE product_id IN ({marks})', *pids):
        codes.setdefault(b['product_id'], []).append(b['code'])
    sellable = {r['id'] for r in db.all('SELECT id FROM locations WHERE sellable = 1')}
    for r in rows:
        r['prices'] = current_prices(db, r['id'], day)
        per = stock.get(r['id'], {})
        r['stock'] = per
        r['on_hand'] = round(sum(v for k, v in per.items() if k in sellable), 3)
        r['here'] = per.get(location_id, 0) if location_id else r['on_hand']
        r['shelves'] = shelves.get(r['id'], {})
        r['barcodes'] = codes.get(r['id'], [])
    return {'items': rows, 'exact': bool(exact)}
