"""The counter: selling, receipts, returns and exchanges, warranty look-up by serial number.

Rules that protect the owner:
- A sale is saved once (idempotency key): pressing "pay" twice or a network retry never makes two sales.
- Discounts above the seller's personal limit, selling under the minimum price or under cost need a manager's password
  typed on the same screen; the approver is saved on the sale.
- A sale is never edited or deleted. A return is linked to the original sale line and refunds at most what was paid for it.
- Selling more than the recorded stock is allowed (never block the counter) but shown in the owner's eye;
  a serial number must really be in stock.
"""
import catalog
import ids
import money as cash
import stock
from auth import Forbidden
from core import NotFound, Problem, money, obj, quantity, rows, settings, text, whole

PAY_METHODS = ('cash', 'card', 'wallet', 'instapay', 'finance', 'account', 'installment')


def _default_shop(db):
    loc = db.one("SELECT id FROM locations WHERE kind = 'shop' AND active = 1 ORDER BY created_at LIMIT 1")
    if not loc:
        raise Problem('err.noShopPlace', 'Add the shop place first (Settings).')
    return loc['id']


def _damaged_place(ctx):
    loc = ctx.db.one("SELECT id FROM locations WHERE kind = 'damaged' AND active = 1 ORDER BY created_at LIMIT 1")
    if loc:
        return loc['id']
    lid = ids.uuid7()
    ctx.db.insert('locations', {'id': lid, 'org_id': ctx.org_id, 'branch_id': ctx.branch_id, 'name': 'تالف وصيانة', 'kind': 'damaged',
                                'sellable': 0, 'active': 1, 'created_at': ids.iso()})
    return lid


def instalment_fee(financed_base, months, markup_pct):
    return round(financed_base * markup_pct / 100 * months) if financed_base > 0 and months else 0


def _warranty_until(day, months):
    if not months:
        return None
    return ids.add_months(day, months)


def price_check(ctx, lines_in, discount, approval, location_id):
    """Validate lines and work out what needs a manager. Returns (prepared lines, subtotal, list_total, needs)."""
    prepared, subtotal, list_total = [], 0, 0
    needs = set()
    seen_serials = set()
    for line in lines_in:
        product = catalog.find(ctx.db, line.get('product_id'))
        if not product['active']:
            raise Problem('err.hidden', f'{product["name"]} is hidden from sale.', name=product['name'])
        qty = quantity(line.get('qty'), product['fractional'])
        prices = catalog.current_prices(ctx.db, product['id'])
        list_price = prices['retail']
        unit = money(line.get('unit_price', list_price), 'unit_price')
        serial = (str(line.get('serial') or '').strip().upper()) or None
        if product['track_serial']:
            if qty != 1 or not serial:
                raise Problem('err.serialNeeded', f'{product["name"]}: choose the serial number of the piece sold.', name=product['name'])
            if serial in seen_serials:
                raise Problem('err.serialTwice', 'The same serial number is written twice.')
            seen_serials.add(serial)
            st = stock.serial_state(ctx.db, serial)
            if not st or not st['in_stock'] or st['product_id'] != product['id']:
                raise Problem('err.serialNotInStock', f'Serial {serial} is not in stock.', serial=serial)
            if st['location_id'] != location_id:
                raise Problem('err.serialNotHere', f'Serial {serial} is in another place. Move it to the shop first.',
                              serial=serial, place=ctx.db.value('SELECT name FROM locations WHERE id = ?', st['location_id']))
        elif serial:
            raise Problem('err.noSerials', f'{product["name"]} does not use serial numbers.', name=product['name'])
        cost = catalog.current_cost(ctx.db, product['id'])['avg_cost']
        line_total = round(qty * unit)
        if prices['min'] and unit < prices['min']:
            needs.add('under_min')
        if cost and unit < cost:
            needs.add('under_cost')
        if not list_price and not unit:
            raise Problem('err.noPrice', f'{product["name"]} has no price.', name=product['name'])
        prepared.append({'product': product, 'qty': qty, 'list_price': list_price, 'unit_price': unit, 'line_total': line_total,
                         'unit_cost': cost, 'serial': serial})
        subtotal += line_total
        list_total += round(qty * max(list_price, unit))
    discount = money(discount or 0, 'discount')
    if discount > subtotal:
        raise Problem('err.discountTooBig', 'The discount is more than the total.')
    given = list_total - (subtotal - discount)
    pct = (given * 100 / list_total) if list_total else 0
    if given > 0:
        if 'pos.discount' not in ctx.perms:
            needs.add('discount')
        elif pct > ctx.user['max_discount_pct'] + 1e-9:
            needs.add('discount')
    return prepared, subtotal, discount, pct, needs


def _approve(ctx, needs, pct, approval):
    """Returns the approving manager or None. The password was checked before the transaction (ctx.approver)."""
    if not needs:
        return None
    approver = ctx.approver
    if not approver:
        raise Problem('err.needsApproval', 'A manager must approve this sale.', 403, needs=sorted(needs), pct=round(pct, 1))
    if approver['id'] == ctx.uid:
        raise Problem('err.selfApproval', 'Another person must approve.', 403)
    import auth as auth_mod
    perms = set(auth_mod.effective_perms(approver))
    if ('under_min' in needs or 'under_cost' in needs) and 'prices.change' not in perms:
        raise Forbidden('prices.change', 'This person cannot approve selling under the minimum price.')
    if 'discount' in needs and ('pos.discount' not in perms or pct > approver['max_discount_pct'] + 1e-9):
        raise Problem('err.approverLimit', 'This discount is above the approver\'s limit too.', 403, pct=round(pct, 1))
    return approver


def _customer(ctx, data):
    if data.get('customer_id'):
        c = ctx.db.one('SELECT * FROM customers WHERE id = ? AND active = 1', data['customer_id'])
        if not c:
            raise NotFound('customer')
        return c
    new = obj(data.get('customer'), 'customer')
    if (str(new.get('name') or '')).strip():
        cid = cash.save_customer(ctx, new)
        return ctx.db.one('SELECT * FROM customers WHERE id = ?', cid)
    return None


def sell(ctx, data):
    ctx.need('pos.sell')
    key = text(data.get('idem_key'), 'idem_key', 64, True)
    done = ctx.db.one('SELECT id, number FROM sales WHERE idem_key = ?', key)
    if done:
        return {**done, 'repeat': True}
    shift = cash.need_shift(ctx)
    cfg = settings(ctx.db)
    location_id = data.get('location_id') or _default_shop(ctx.db)
    stock.location(ctx.db, location_id, sellable=True)
    lines_in = rows(data.get('lines'))
    if not lines_in or len(lines_in) > 200:
        raise Problem('err.noLines', 'Add at least one product.')
    prepared, subtotal, discount, pct, needs = price_check(ctx, lines_in, data.get('discount'), data.get('approval'), location_id)

    # payments
    payments = rows(data.get('payments'), 'payments')
    if not payments:
        raise Problem('err.noPayment', 'Choose how the customer pays.')
    by_method, providers = {}, {}
    for p in payments:
        method = p.get('method')
        if method not in PAY_METHODS:
            raise Problem('err.method', 'Unknown payment method.')
        amount = money(p.get('amount'), 'amount')
        if not amount:
            continue
        by_method[method] = by_method.get(method, 0) + amount
        if method == 'finance':
            prov = text(p.get('provider'), 'provider', 40, True)
            providers[prov] = providers.get(prov, 0) + amount
    customer = _customer(ctx, data)
    fee, plan_req = 0, None
    if 'installment' in by_method:
        ctx.need('pos.credit')
        plan_req = obj(data.get('instalment'), 'instalment')
        months = whole(plan_req.get('months'), 'months')
        down = sum(v for k, v in by_method.items() if k != 'installment')
        base = subtotal - discount - down
        fee = instalment_fee(base, months, float(cfg['instalment_markup_pct']))
        if base <= 0:
            raise Problem('err.nothingToFinance', 'Nothing is left to pay in instalments.')
        if down * 100 < (subtotal - discount) * float(cfg['min_down_payment_pct']) - 1e-6:
            raise Problem('err.downPayment', f'The down payment must be at least {cfg["min_down_payment_pct"]}%.',
                          pct=cfg['min_down_payment_pct'])
        if by_method['installment'] != base + fee:
            raise Problem('err.totalChanged', 'The instalment amount changed. Check the total again.', 409,
                          expected=base + fee)
    total = subtotal - discount + fee
    paid = sum(by_method.values())
    if paid != total:
        raise Problem('err.paymentsMismatch', 'The payments do not add up to the total.', 400, total=total, paid=paid)
    if ('account' in by_method or 'installment' in by_method):
        ctx.need('pos.credit')
        if not customer:
            raise Problem('err.needCustomer', 'Choose the customer: this sale is on their account.')
        if 'account' in by_method and customer['credit_limit']:
            after = cash.customer_balance(ctx.db, customer['id']) + by_method['account']
            if after > customer['credit_limit']:
                needs.add('credit_limit')
    approver = _approve(ctx, needs - {'credit_limit'}, pct, data.get('approval')) if needs - {'credit_limit'} else None
    if 'credit_limit' in needs:
        approver = approver or _approve_credit(ctx, data.get('approval'))

    # save
    sid, at = ids.uuid7(), ids.iso()
    day = ids.local_day()
    number = ctx.number('sale')
    cost_total = sum(round(l['qty'] * l['unit_cost']) for l in prepared)
    delivery = obj(data.get('delivery'), 'delivery')
    ctx.db.insert('sales', {'id': sid, 'org_id': ctx.org_id, 'branch_id': ctx.branch_id, 'number': number, 'idem_key': key, 'at': at,
                            'by_user': ctx.uid, 'shift_id': shift['id'], 'customer_id': customer['id'] if customer else None,
                            'location_id': location_id, 'subtotal': subtotal, 'discount': discount, 'fee': fee, 'total': total,
                            'cost_total': cost_total, 'approved_by': approver['id'] if approver else None,
                            'note': text(data.get('note'), 'note', 300),
                            'delivery': text(str(delivery.get('address') or '') + ('|' + str(delivery['date']) if delivery.get('date') else ''),
                                             'delivery', 300)})
    for l in prepared:
        ctx.db.insert('sale_lines', {'id': ids.uuid7(), 'sale_id': sid, 'product_id': l['product']['id'], 'name': l['product']['name'],
                                     'qty': l['qty'], 'list_price': l['list_price'], 'unit_price': l['unit_price'],
                                     'line_total': l['line_total'], 'unit_cost': l['unit_cost'], 'serial': l['serial'],
                                     'warranty_until': _warranty_until(day, l['product']['warranty_months'])})
        stock.move(ctx, l['product']['id'], location_id, -l['qty'], 'sale', 'sale', sid, l['unit_cost'], l['serial'], at=at)
    for method, amount in by_method.items():
        if method == 'finance':
            for prov, amt in providers.items():
                cash.tender(ctx, 'sale', sid, 'finance', amt, prov, shift['id'], at)
        else:
            cash.tender(ctx, 'sale', sid, method, amount, '', shift['id'], at)
    if by_method.get('cash'):
        cash.cash_move(ctx, 'drawer', 'sale', by_method['cash'], shift['id'], ref_type='sale', ref_id=sid, note=number, at=at)
    if by_method.get('account'):
        cash.ar_entry(ctx, customer['id'], by_method['account'], 'sale', 'sale', sid, note=number, at=at)
    plan_id = None
    if plan_req is not None:
        financed = by_method['installment']
        first_due = plan_req.get('first_due') or ids.add_months(day, 1)
        plan_id = cash.create_plan(ctx, sid, customer['id'], financed, plan_req.get('months'), first_due,
                                   obj(plan_req.get('guarantor'), 'guarantor'), at)
        cash.ar_entry(ctx, customer['id'], financed, 'instalment', 'sale', sid, plan_id, number, at=at)
    ctx.audit('sale', 'sale', sid, {'number': number, 'total': total, 'discount': discount, 'pct': round(pct, 1),
                                    'methods': by_method, 'approved_by': approver['full_name'] if approver else None,
                                    'needs': sorted(needs)})
    received = data.get('cash_received')
    change = (int(received) - by_method.get('cash', 0)) if isinstance(received, int) and received >= by_method.get('cash', 0) else 0
    return {'id': sid, 'number': number, 'total': total, 'change': change, 'plan_id': plan_id}


def _approve_credit(ctx, approval):
    approver = ctx.approver
    if not approver:
        raise Problem('err.needsApproval', 'This is above the customer\'s credit limit: a manager must approve.', 403, needs=['credit_limit'])
    import auth as auth_mod
    if approver['id'] == ctx.uid:
        raise Problem('err.selfApproval', 'Another person must approve.', 403)
    if 'shifts.manage' not in auth_mod.effective_perms(approver):
        raise Forbidden('shifts.manage', 'This person cannot approve going above a credit limit.')
    return approver


def quote(ctx, data):
    """Totals, instalment fee and what needs approval, without saving. The sale screen asks this before paying."""
    location_id = data.get('location_id') or _default_shop(ctx.db)
    prepared, subtotal, discount, pct, needs = price_check(ctx, rows(data.get('lines')), data.get('discount'), None, location_id)
    cfg = settings(ctx.db)
    plan = obj(data.get('instalment'), 'instalment')
    months = whole(plan.get('months'), 'months')
    down = whole(plan.get('down'), 'down')
    base = subtotal - discount - down
    fee = instalment_fee(base, months, float(cfg['instalment_markup_pct'])) if months else 0
    return {'subtotal': subtotal, 'discount': discount, 'fee': fee, 'total': subtotal - discount + fee, 'discount_pct': round(pct, 2),
            'needs': sorted(needs), 'monthly': cash.instalment_amount(base + fee, months) if months and base > 0 else 0,
            'stock_warnings': [{'name': l['product']['name'], 'have': stock.on_hand(ctx.db, l['product']['id'], location_id)}
                               for l in prepared if not l['serial'] and stock.on_hand(ctx.db, l['product']['id'], location_id) < l['qty']]}


# ------------------------------------------------------------------ viewing
def sale_view(db, sale_id, can_cost=False):
    s = db.one('SELECT s.*, u.full_name AS by_name, a.full_name AS approved_name, c.name AS customer, c.phone AS customer_phone, '
               'l.name AS location FROM sales s JOIN users u ON u.id = s.by_user LEFT JOIN users a ON a.id = s.approved_by '
               'LEFT JOIN customers c ON c.id = s.customer_id JOIN locations l ON l.id = s.location_id WHERE s.id = ? OR s.number = ?',
               sale_id, sale_id)
    if not s:
        raise NotFound('sale')
    s['lines'] = db.all('SELECT sl.*, p.sku, p.unit, COALESCE((SELECT SUM(qty) FROM return_lines r WHERE r.sale_line_id = sl.id), 0) '
                        'AS returned FROM sale_lines sl JOIN products p ON p.id = sl.product_id WHERE sale_id = ? ORDER BY sl.rowid', s['id'])
    s['tenders'] = db.all("SELECT method, provider, amount FROM tenders WHERE ref_type = 'sale' AND ref_id = ?", s['id'])
    s['returns'] = db.all('SELECT r.id, r.number, r.at, r.total, r.reason, r.refund_method, u.full_name AS by_name FROM returns r '
                          'JOIN users u ON u.id = r.by_user WHERE sale_id = ? ORDER BY at', s['id'])
    s['plan'] = db.one('SELECT * FROM plans WHERE sale_id = ?', s['id'])
    if s['plan']:
        s['plan'].update(cash.plan_schedule(db, s['plan']))
    day = ids.local_day(ids.parse(s['at']))
    s['days_since'] = ids.days_between(day, ids.local_day())
    if not can_cost:
        s.pop('cost_total', None)
        for line in s['lines']:
            line.pop('unit_cost', None)
    return s


def sales_list(db, ctx, day_from=None, day_to=None, q='', user_id=None, limit=300):
    day_to = day_to or ids.local_day()
    day_from = day_from or day_to
    start, _ = ids.day_bounds(day_from)
    _, end = ids.day_bounds(day_to)
    where, args = ['s.at >= ?', 's.at < ?'], [start, end]
    if not ctx.can('sales.view_all'):
        where.append('s.by_user = ?')
        args.append(ctx.uid)
    elif user_id:
        where.append('s.by_user = ?')
        args.append(user_id)
    if q:
        where = ['(s.number LIKE ? OR c.name LIKE ? OR c.phone LIKE ? OR EXISTS (SELECT 1 FROM sale_lines x WHERE x.sale_id = s.id AND x.serial = ?))']
        args = [f'%{q}%', f'%{q}%', f'%{q}%', q.upper()]
        if not ctx.can('sales.view_all'):
            where.append('s.by_user = ?')
            args.append(ctx.uid)
    rows = db.all('SELECT s.id, s.number, s.at, s.total, s.discount, s.fee, c.name AS customer, u.full_name AS by_name, '
                  "(SELECT GROUP_CONCAT(DISTINCT method) FROM tenders t WHERE t.ref_type = 'sale' AND t.ref_id = s.id) AS methods, "
                  '(SELECT COUNT(*) FROM returns r WHERE r.sale_id = s.id) AS returns, '
                  '(SELECT COUNT(*) FROM sale_lines l WHERE l.sale_id = s.id) AS items '
                  'FROM sales s JOIN users u ON u.id = s.by_user LEFT JOIN customers c ON c.id = s.customer_id '
                  f"WHERE {' AND '.join(where)} ORDER BY s.at DESC LIMIT ?", *args, limit)
    return rows


def warranty(db, serial):
    serial = (serial or '').strip().upper()
    line = db.one('SELECT sl.*, s.number, s.at, s.id AS sale_id, c.name AS customer, c.phone FROM sale_lines sl JOIN sales s ON '
                  's.id = sl.sale_id LEFT JOIN customers c ON c.id = s.customer_id WHERE sl.serial = ? ORDER BY s.at DESC LIMIT 1', serial)
    state = stock.serial_state(db, serial)
    if not line and not state:
        raise NotFound('serial')
    out = {'serial': serial, 'state': state}
    if state:
        out['product'] = db.value('SELECT name FROM products WHERE id = ?', state['product_id'])
    if line:
        today = ids.local_day()
        out.update({'sale_id': line['sale_id'], 'sale_number': line['number'], 'sold_at': line['at'], 'customer': line['customer'],
                    'phone': line['phone'], 'product': line['name'], 'price': line['unit_price'],
                    'warranty_until': line['warranty_until'],
                    'warranty_days_left': ids.days_between(today, line['warranty_until']) if line['warranty_until'] else None,
                    'days_since_sale': ids.days_between(ids.local_day(ids.parse(line['at'])), today)})
    return out


# ------------------------------------------------------------------ returns
def take_return(ctx, data):
    key = text(data.get('idem_key'), 'idem_key', 64, True)
    done = ctx.db.one('SELECT id, number FROM returns WHERE idem_key = ?', key)
    if done:
        return {**done, 'repeat': True}
    approver = None
    if 'sales.return' not in ctx.perms:
        import auth as auth_mod
        approver = ctx.approver
        if not approver:
            raise Problem('err.needsApproval', 'A manager must approve this return.', 403, needs=['return'])
        if approver['id'] == ctx.uid:
            raise Problem('err.selfApproval', 'Another person must approve.', 403)
        if 'sales.return' not in auth_mod.effective_perms(approver):
            raise Forbidden('sales.return', 'This person cannot approve returns.')
    reason = text(data.get('reason'), 'reason', 300)
    if len(reason) < 3:
        raise Problem('err.reason', 'Write the reason (3 letters or more).')
    sale = sale_view(ctx.db, data.get('sale_id'), True)
    lines = {l['id']: l for l in sale['lines']}
    wanted = rows(data.get('lines'))
    if not wanted:
        raise Problem('err.noLines', 'Choose what is returned.')
    share = (sale['subtotal'] - sale['discount']) / sale['subtotal'] if sale['subtotal'] else 1
    prepared, total = [], 0
    damaged = None
    taken = {}  # the same line written twice in one request must not return more than the sale held
    for w in wanted:
        line = lines.get(w.get('sale_line_id')) if isinstance(w.get('sale_line_id'), str) else None
        if not line:
            raise NotFound('sale line')
        qty = quantity(w.get('qty'), bool(catalog.find(ctx.db, line['product_id'])['fractional']))
        line = {**line, 'returned': line['returned'] + taken.get(line['id'], 0)}
        taken[line['id']] = taken.get(line['id'], 0) + qty
        if qty > line['qty'] - line['returned'] + 1e-9:
            raise Problem('err.returnTooMuch', f'{line["name"]}: only {line["qty"] - line["returned"]:g} can still be returned.',
                          name=line['name'], left=line['qty'] - line['returned'])
        condition = w.get('condition') or 'good'
        if condition not in ('good', 'damaged'):
            raise Problem('err.condition', 'Choose the condition.')
        if condition == 'damaged':
            damaged = damaged or _damaged_place(ctx)
            to = damaged
        else:
            to = w.get('to_location_id') or sale['location_id']
            stock.location(ctx.db, to)
        amount = round(line['unit_price'] * qty * share)
        if qty == line['qty'] - line['returned']:  # the last piece takes what is left, so rounding never refunds a piaster too much
            already = ctx.db.value('SELECT COALESCE(SUM(amount), 0) FROM return_lines WHERE sale_line_id = ?', line['id'])
            already += sum(a for l2, _q, a, _t, _c in prepared if l2['id'] == line['id'])
            amount = round(line['line_total'] * share) - already
        prepared.append((line, qty, amount, to, condition))
        total += amount
    method = data.get('refund_method') or 'cash'
    if method not in ('cash', 'card', 'wallet', 'instapay', 'account', 'finance'):
        raise Problem('err.method', 'Unknown refund method.')
    if method == 'account' and not sale['customer_id']:
        raise Problem('err.needCustomer', 'This sale has no customer account.')
    shift = cash.open_shift_of(ctx.db, ctx.uid)
    if method == 'cash':
        shift = cash.need_shift(ctx)
        if total > cash.drawer_expected(ctx.db, shift['id']):
            raise Problem('err.drawerShort', 'There is not enough cash in the drawer for this refund.')
    rid, at = ids.uuid7(), ids.iso()
    number = ctx.number('return')
    ctx.db.insert('returns', {'id': rid, 'org_id': ctx.org_id, 'branch_id': ctx.branch_id, 'number': number, 'idem_key': key,
                              'sale_id': sale['id'], 'at': at, 'by_user': ctx.uid, 'approved_by': approver['id'] if approver else None,
                              'shift_id': shift['id'] if shift else None, 'reason': reason, 'refund_method': method, 'total': total})
    for line, qty, amount, to, condition in prepared:
        ctx.db.insert('return_lines', {'id': ids.uuid7(), 'return_id': rid, 'sale_line_id': line['id'], 'qty': qty, 'amount': amount,
                                       'to_location_id': to, 'condition': condition})
        stock.move(ctx, line['product_id'], to, qty, 'return', 'return', rid, line['unit_cost'], line['serial'],
                   condition, at)
    if method == 'cash':
        cash.cash_move(ctx, 'drawer', 'refund', -total, shift['id'], ref_type='return', ref_id=rid, note=number, at=at)
        cash.tender(ctx, 'return', rid, 'cash', -total, '', shift['id'], at)
    elif method == 'account':
        plan = ctx.db.one('SELECT id FROM plans WHERE sale_id = ?', sale['id'])
        cash.ar_entry(ctx, sale['customer_id'], -total, 'return', 'return', rid, plan['id'] if plan else None, number, at=at)
    else:
        provider = next((t['provider'] for t in sale['tenders'] if t['method'] == method), '')
        cash.tender(ctx, 'return', rid, method, -total, provider, shift['id'] if shift else None, at)
    ctx.audit('return', 'sale', sale['id'], {'number': number, 'total': total, 'method': method, 'reason': reason,
                                             'approved_by': approver['full_name'] if approver else None,
                                             'days_since_sale': sale['days_since']})
    return {'id': rid, 'number': number, 'total': total}


def return_view(db, return_id):
    r = db.one('SELECT r.*, s.number AS sale_number, u.full_name AS by_name FROM returns r JOIN sales s ON s.id = r.sale_id '
               'JOIN users u ON u.id = r.by_user WHERE r.id = ? OR r.number = ?', return_id, return_id)
    if not r:
        raise NotFound('return')
    r['lines'] = db.all('SELECT rl.*, sl.name, sl.serial, sl.unit_price FROM return_lines rl JOIN sale_lines sl ON sl.id = rl.sale_line_id '
                        'WHERE return_id = ?', r['id'])
    return r

