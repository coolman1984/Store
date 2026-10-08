"""Cash, shifts, customers' accounts and shop instalments, suppliers' accounts.

- The drawer belongs to a shift. Expected cash = opening float + cash in − cash out, computed from cash_moves.
  Closing records what was counted: the difference (over/short) is its own row, then the cash goes to the main safe.
- Card, wallet, InstaPay and finance-company money never enters the drawer: it is a tender of the sale, reported apart.
- A customer's balance and a supplier's balance are sums of their entries. Nothing is ever edited or deleted:
  a mistake is corrected with a reversing entry and a written reason.
- Shop instalments: a plan holds the schedule terms; what is due, paid and late is computed from the plan and the entries.
"""
import ids
from core import NotFound, Problem, money, settings, text

CASH_IN_KINDS = ('float', 'sale', 'collection', 'deposit', 'drop_in', 'over_short')
METHODS = ('cash', 'card', 'wallet', 'instapay', 'finance')


# ------------------------------------------------------------------ shifts and drawer
def open_shift_of(db, user_id):
    return db.one('SELECT * FROM shifts WHERE user_id = ? AND closed_at IS NULL', user_id)


def need_shift(ctx):
    shift = open_shift_of(ctx.db, ctx.uid)
    if not shift:
        raise Problem('err.noShift', 'Open your shift first (Cash page).', 409)
    return shift


def cash_move(ctx, account, kind, amount, shift_id=None, category='', ref_type='', ref_id='', note='', idem_key=None, reverses=None,
              at=None):
    row = {'id': ids.uuid7(), 'org_id': ctx.org_id, 'branch_id': ctx.branch_id, 'account': account, 'shift_id': shift_id,
           'kind': kind, 'amount': int(amount), 'category': category, 'ref_type': ref_type, 'ref_id': ref_id or '',
           'idem_key': idem_key, 'note': note, 'at': at or ids.iso(), 'by_user': ctx.uid, 'reverses': reverses}
    ctx.db.insert('cash_moves', row)
    return row


def drawer_expected(db, shift_id):
    return db.value("SELECT COALESCE(SUM(amount), 0) FROM cash_moves WHERE account = 'drawer' AND shift_id = ?", shift_id)


def safe_balance(db):
    return db.value("SELECT COALESCE(SUM(amount), 0) FROM cash_moves WHERE account = 'safe'")


def open_shift(ctx, opening_float):
    ctx.need('pos.sell')
    if open_shift_of(ctx.db, ctx.uid):
        raise Problem('err.shiftOpen', 'Your shift is already open.')
    amount = money(opening_float, 'opening_float')
    sid = ids.uuid7()
    number = ctx.number('shift')
    ctx.db.insert('shifts', {'id': sid, 'org_id': ctx.org_id, 'branch_id': ctx.branch_id, 'number': number, 'user_id': ctx.uid,
                             'opened_at': ids.iso(), 'opening_float': amount, 'closed_at': None, 'closed_by': None,
                             'expected': None, 'counted': None, 'close_note': ''})
    if amount:
        cash_move(ctx, 'drawer', 'float', amount, sid, note=number)
    ctx.audit('shift.open', 'shift', sid, {'number': number, 'float': amount})
    return sid


def shift_summary(db, shift_id):
    s = db.one('SELECT s.*, u.full_name AS user_name FROM shifts s JOIN users u ON u.id = s.user_id WHERE s.id = ?', shift_id)
    if not s:
        raise NotFound('shift')
    by_kind = {r['kind']: r['amount'] for r in db.all("SELECT kind, SUM(amount) AS amount FROM cash_moves WHERE account = 'drawer' "
                                                        "AND shift_id = ? GROUP BY kind", shift_id)}
    tenders = {r['method']: r['amount'] for r in db.all('SELECT method, SUM(amount) AS amount FROM tenders WHERE shift_id = ? '
                                                         'GROUP BY method', shift_id)}
    s['by_kind'] = by_kind
    s['tenders'] = tenders
    s['expected_now'] = drawer_expected(db, shift_id) if not s['closed_at'] else s['expected']
    s['sales_count'] = db.value('SELECT COUNT(*) FROM sales WHERE shift_id = ?', shift_id)
    s['sales_total'] = db.value('SELECT COALESCE(SUM(total), 0) FROM sales WHERE shift_id = ?', shift_id)
    s['moves'] = db.all("SELECT c.at, c.kind, c.amount, c.category, c.note, c.ref_type, c.ref_id, c.id, c.reverses, u.full_name AS by_name "
                        "FROM cash_moves c LEFT JOIN users u ON u.id = c.by_user WHERE c.account = 'drawer' AND c.shift_id = ? "
                        "ORDER BY c.at DESC", shift_id)
    s['difference'] = None if s['counted'] is None else s['counted'] - s['expected']
    return s


def close_shift(ctx, shift_id, counted, note=''):
    s = ctx.db.one('SELECT * FROM shifts WHERE id = ?', shift_id)
    if not s:
        raise NotFound('shift')
    if s['user_id'] != ctx.uid:
        ctx.need('shifts.manage')
    if s['closed_at']:
        raise Problem('err.shiftClosed', 'This shift is already closed.')
    counted = money(counted, 'counted')
    expected = drawer_expected(ctx.db, shift_id)
    diff = counted - expected
    note = text(note, 'note', 300)
    if diff and len(note) < 3:
        raise Problem('err.diffReason', 'The cash is different from what is expected: write what happened.', diff=diff)
    at = ids.iso()
    if diff:
        cash_move(ctx, 'drawer', 'over_short', diff, shift_id, note=note, at=at)
    if counted:  # everything counted goes to the main safe; the next shift starts with its own float
        cash_move(ctx, 'drawer', 'drop_out', -counted, shift_id, note=s['number'], at=at)
        cash_move(ctx, 'safe', 'drop_in', counted, shift_id, note=s['number'], at=at)
    ctx.db.run('UPDATE shifts SET closed_at = ?, closed_by = ?, expected = ?, counted = ?, close_note = ? WHERE id = ?',
               at, ctx.uid, expected, counted, note, shift_id)
    ctx.audit('shift.close', 'shift', shift_id, {'expected': expected, 'counted': counted, 'difference': diff})
    return {'expected': expected, 'counted': counted, 'difference': diff}


def cash_out(ctx, source, kind, amount, ref_type, ref_id, note, category='', idem_key=None):
    """Money leaving the drawer (needs an open shift) or the safe."""
    amount = money(amount)
    if source == 'drawer':
        shift = need_shift(ctx)
        have = drawer_expected(ctx.db, shift['id'])
        if amount > have:
            raise Problem('err.drawerShort', 'There is not enough cash in the drawer for this.', have=have)
        return cash_move(ctx, 'drawer', kind, -amount, shift['id'], category, ref_type, ref_id, note, idem_key)
    if source == 'safe':
        ctx.need('cash.safe')
        return cash_move(ctx, 'safe', kind, -amount, None, category, ref_type, ref_id, note, idem_key)
    raise Problem('err.source', 'Choose drawer or safe.')


def expense(ctx, data):
    source = data.get('source') or 'drawer'
    ctx.need('cash.expense' if source == 'drawer' else 'cash.safe')
    key = text(data.get('idem_key'), 'idem_key', 64, True)
    done = ctx.db.one('SELECT id FROM cash_moves WHERE idem_key = ?', key)
    if done:
        return done
    cats = settings(ctx.db)['expense_categories']
    category = data.get('category') or 'other'
    if category not in cats:
        raise Problem('err.category', 'Choose a kind of expense.')
    note = text(data.get('note'), 'note', 300)
    if len(note) < 3:
        raise Problem('err.note', 'Write what the money was for.')
    amount = money(data.get('amount'))
    if not amount:
        raise Problem('err.zero', 'Write the amount.')
    row = cash_out(ctx, source, 'expense', amount, 'expense', '', note, category, key)
    ctx.audit('cash.expense', 'cash', row['id'], {'amount': amount, 'category': category, 'source': source, 'note': note})
    return {'id': row['id']}


def safe_move(ctx, data):
    """Owner's safe: withdraw (owner takes money), deposit (owner adds money), or move cash from a drawer to the safe."""
    ctx.need('cash.safe')
    kind = data.get('kind')
    amount = money(data.get('amount'))
    note = text(data.get('note'), 'note', 300)
    if not amount:
        raise Problem('err.zero', 'Write the amount.')
    if kind == 'withdraw':
        if amount > safe_balance(ctx.db):
            raise Problem('err.safeShort', 'The safe does not have this much.')
        row = cash_move(ctx, 'safe', 'withdraw', -amount, note=note)
    elif kind == 'deposit':
        row = cash_move(ctx, 'safe', 'deposit', amount, note=note)
    elif kind == 'drop':
        shift = need_shift(ctx)
        if amount > drawer_expected(ctx.db, shift['id']):
            raise Problem('err.drawerShort', 'There is not enough cash in the drawer for this.')
        at = ids.iso()
        cash_move(ctx, 'drawer', 'drop_out', -amount, shift['id'], note=note, at=at)
        row = cash_move(ctx, 'safe', 'drop_in', amount, shift['id'], note=note, at=at)
    else:
        raise Problem('err.kind', 'Unknown safe action.')
    ctx.audit('cash.safe.' + kind, 'cash', row['id'], {'amount': amount, 'note': note})
    return {'id': row['id']}


def reverse_cash(ctx, move_id, reason):
    """Undo an expense or safe move typed by mistake: a new opposite row, never an edit."""
    reason = text(reason, 'reason', 300)
    if len(reason) < 3:
        raise Problem('err.reason', 'Write the reason (3 letters or more).')
    m = ctx.db.one('SELECT * FROM cash_moves WHERE id = ?', move_id)
    if not m:
        raise NotFound('cash entry')
    if m['kind'] not in ('expense', 'withdraw', 'deposit'):
        raise Problem('err.notReversible', 'Sales, returns and collections are reversed from their own page.')
    if m['reverses'] or ctx.db.value('SELECT 1 FROM cash_moves WHERE reverses = ?', move_id):
        raise Problem('err.alreadyReversed', 'This entry is already reversed.')
    ctx.need('cash.safe' if m['account'] == 'safe' or m['by_user'] != ctx.uid else 'cash.expense')
    shift_id = m['shift_id']
    if m['account'] == 'drawer':
        shift = ctx.db.one('SELECT * FROM shifts WHERE id = ?', shift_id)
        if shift['closed_at']:  # the drawer of a closed shift is counted: the correction goes through the safe
            row = cash_move(ctx, 'safe', 'reversal', -m['amount'], None, m['category'], 'cash', move_id, reason, reverses=move_id)
        else:
            row = cash_move(ctx, 'drawer', 'reversal', -m['amount'], shift_id, m['category'], 'cash', move_id, reason, reverses=move_id)
    else:
        row = cash_move(ctx, 'safe', 'reversal', -m['amount'], None, m['category'], 'cash', move_id, reason, reverses=move_id)
    ctx.audit('cash.reverse', 'cash', move_id, {'amount': m['amount'], 'reason': reason})
    return {'id': row['id']}


def tender(ctx, ref_type, ref_id, method, amount, provider='', shift_id=None, at=None):
    ctx.db.insert('tenders', {'id': ids.uuid7(), 'ref_type': ref_type, 'ref_id': ref_id, 'method': method, 'provider': provider,
                              'amount': int(amount), 'at': at or ids.iso(), 'shift_id': shift_id})


# ------------------------------------------------------------------ customers
def save_customer(ctx, data):
    ctx.need('customers.edit')
    name = text(data.get('name'), 'name', 80, True)
    phone = ''.join(ch for ch in str(data.get('phone') or '') if ch.isdigit() or ch == '+')[:20]
    fields = {'name': name, 'phone': phone, 'address': text(data.get('address'), 'address', 200),
              'notes': text(data.get('notes'), 'notes', 500), 'changed_at': ids.iso()}
    if 'credit_limit' in data:
        ctx.need('pos.credit')
        fields['credit_limit'] = money(data.get('credit_limit') or 0, 'credit_limit')
    if 'national_id' in data and ctx.can('customers.private'):
        nid = ''.join(ch for ch in str(data.get('national_id') or '') if ch.isdigit())
        if nid and len(nid) != 14:
            raise Problem('err.nationalId', 'The national ID has 14 digits.')
        fields['national_id'] = nid
    if data.get('id'):
        old = ctx.db.one('SELECT * FROM customers WHERE id = ?', data['id'])
        if not old:
            raise NotFound('customer')
        sets = ', '.join(f'{k} = ?' for k in fields)
        ctx.db.run(f'UPDATE customers SET {sets} WHERE id = ?', *fields.values(), data['id'])
        ctx.audit('customer.edit', 'customer', data['id'], {k: v for k, v in fields.items() if k != 'national_id'})
        return data['id']
    if phone and ctx.db.value('SELECT 1 FROM customers WHERE phone = ? AND active = 1', phone):
        raise Problem('err.phoneTaken', 'A customer with this phone already exists. Search for them.')
    cid = ids.uuid7()
    ctx.db.insert('customers', {'id': cid, 'org_id': ctx.org_id, 'national_id': fields.pop('national_id', ''),
                                'credit_limit': fields.pop('credit_limit', 0), 'active': 1, 'created_at': ids.iso(), **fields})
    ctx.audit('customer.add', 'customer', cid, {'name': name})
    return cid


def customer_balance(db, customer_id):
    return db.value('SELECT COALESCE(SUM(amount), 0) FROM ar_entries WHERE customer_id = ?', customer_id)


def ar_entry(ctx, customer_id, amount, kind, ref_type, ref_id, plan_id=None, note='', idem_key=None, reverses=None, at=None):
    row = {'id': ids.uuid7(), 'customer_id': customer_id, 'plan_id': plan_id, 'amount': int(amount), 'kind': kind,
           'ref_type': ref_type, 'ref_id': ref_id, 'idem_key': idem_key, 'note': note, 'at': at or ids.iso(), 'by_user': ctx.uid,
           'reverses': reverses}
    ctx.db.insert('ar_entries', row)
    return row


def plan_schedule(db, plan, today=None):
    """Each instalment: due date, amount, paid, state (paid / partial / late / due_today / upcoming)."""
    today = today or ids.local_day()
    paid = -db.value('SELECT COALESCE(SUM(amount), 0) FROM ar_entries WHERE plan_id = ? AND amount < 0', plan['id'])
    paid -= db.value("SELECT COALESCE(SUM(amount), 0) FROM ar_entries WHERE plan_id = ? AND amount > 0 AND kind = 'reversal'",
                     plan['id'])  # a reversed collection gives the debt back
    rows, left = [], paid
    for i in range(plan['months']):
        amount = plan['monthly'] if i < plan['months'] - 1 else plan['financed'] - plan['monthly'] * (plan['months'] - 1)
        due = ids.add_months(plan['first_due'], i)
        got = max(0, min(amount, left))
        left -= got
        if got >= amount:
            state = 'paid'
        elif due < today:
            state = 'late'
        elif due == today:
            state = 'due_today'
        else:
            state = 'partial' if got else 'upcoming'
        rows.append({'n': i + 1, 'due': due, 'amount': amount, 'paid': got, 'state': state})
    late = sum(r['amount'] - r['paid'] for r in rows if r['due'] <= today)
    nxt = next((r for r in rows if r['paid'] < r['amount']), None)
    return {'rows': rows, 'paid': paid, 'remaining': plan['financed'] - paid, 'due_now': max(0, late), 'next': nxt,
            'late_days': (ids.days_between(nxt['due'], today) if nxt and nxt['due'] < today else 0)}


def instalment_amount(financed, months):
    """Monthly instalment rounded up to whole pounds (shops never collect piasters); the last one takes the rest."""
    exact = -(-financed // months)
    whole = -(-exact // 100) * 100
    return whole if whole * (months - 1) < financed else exact


def create_plan(ctx, sale_id, customer_id, financed, months, first_due, guarantor, at):
    cfg = settings(ctx.db)
    from core import whole
    months = whole(months, 'months')
    if not 1 <= months <= int(cfg['max_instalment_months']):
        raise Problem('err.months', f'Choose 1 to {cfg["max_instalment_months"]} months.', max=cfg['max_instalment_months'])
    from core import day as valid_day
    if not first_due or valid_day(first_due, 'first_due') < ids.local_day():
        raise Problem('err.firstDue', 'The first instalment date cannot be in the past.')
    monthly = instalment_amount(financed, months)
    guarantor = guarantor or {}
    nid = ''.join(ch for ch in str(guarantor.get('national_id') or '') if ch.isdigit())
    if nid and len(nid) != 14:
        raise Problem('err.nationalId', 'The national ID has 14 digits.')
    pid = ids.uuid7()
    ctx.db.insert('plans', {'id': pid, 'org_id': ctx.org_id, 'number': ctx.number('plan'), 'sale_id': sale_id,
                            'customer_id': customer_id, 'financed': financed, 'months': months, 'first_due': first_due,
                            'monthly': monthly, 'guarantor_name': text(guarantor.get('name'), 'guarantor', 80),
                            'guarantor_phone': text(guarantor.get('phone'), 'phone', 20),
                            'guarantor_national_id': nid if ctx.can('customers.private') else '', 'created_at': at})
    return pid


def collect(ctx, data):
    """A customer pays toward their account or an instalment plan."""
    ctx.need('installments.collect')
    key = text(data.get('idem_key'), 'idem_key', 64, True)
    done = ctx.db.one('SELECT id, ref_id FROM ar_entries WHERE idem_key = ?', key)
    if done:
        return {'id': done['id'], 'number': done['ref_id']}
    customer = ctx.db.one('SELECT * FROM customers WHERE id = ?', data.get('customer_id'))
    if not customer:
        raise NotFound('customer')
    amount = money(data.get('amount'))
    if not amount:
        raise Problem('err.zero', 'Write the amount.')
    method = data.get('method') or 'cash'
    if method not in ('cash', 'card', 'wallet', 'instapay'):
        raise Problem('err.method', 'Unknown payment method.')
    plan_id = data.get('plan_id') or None
    if plan_id and not ctx.db.value('SELECT 1 FROM plans WHERE id = ? AND customer_id = ?', plan_id, customer['id']):
        raise NotFound('plan')
    owed = customer_balance(ctx.db, customer['id'])
    if amount > owed:
        raise Problem('err.payMoreThanOwed', 'This is more than the customer owes.', owed=owed)
    shift = need_shift(ctx)
    number = ctx.number('collection')
    at = ids.iso()
    entry = ar_entry(ctx, customer['id'], -amount, 'payment', 'collection', number, plan_id, text(data.get('note'), 'note', 200), key, at=at)
    if method == 'cash':
        cash_move(ctx, 'drawer', 'collection', amount, shift['id'], ref_type='collection', ref_id=entry['id'], note=number, at=at)
    tender(ctx, 'collection', entry['id'], method, amount, shift_id=shift['id'], at=at)
    ctx.audit('customer.collect', 'customer', customer['id'], {'amount': amount, 'method': method, 'plan': plan_id, 'number': number})
    return {'id': entry['id'], 'number': number, 'balance': customer_balance(ctx.db, customer['id'])}


def reverse_collection(ctx, entry_id, reason):
    ctx.need('shifts.manage')
    reason = text(reason, 'reason', 300)
    if len(reason) < 3:
        raise Problem('err.reason', 'Write the reason (3 letters or more).')
    e = ctx.db.one("SELECT * FROM ar_entries WHERE id = ? AND kind = 'payment'", entry_id)
    if not e:
        raise NotFound('payment')
    if ctx.db.value('SELECT 1 FROM ar_entries WHERE reverses = ?', entry_id):
        raise Problem('err.alreadyReversed', 'This entry is already reversed.')
    at = ids.iso()
    ar_entry(ctx, e['customer_id'], -e['amount'], 'reversal', 'collection', e['ref_id'], e['plan_id'], reason, reverses=entry_id, at=at)
    paid_cash = ctx.db.one("SELECT * FROM cash_moves WHERE kind = 'collection' AND ref_id = ?", entry_id)
    t = ctx.db.one("SELECT * FROM tenders WHERE ref_type = 'collection' AND ref_id = ?", entry_id)
    if paid_cash:
        shift = ctx.db.one('SELECT * FROM shifts WHERE id = ?', paid_cash['shift_id'])
        if shift and not shift['closed_at']:
            cash_move(ctx, 'drawer', 'reversal', -paid_cash['amount'], shift['id'], ref_type='collection', ref_id=entry_id,
                      note=reason, reverses=paid_cash['id'], at=at)
        else:
            cash_move(ctx, 'safe', 'reversal', -paid_cash['amount'], None, ref_type='collection', ref_id=entry_id, note=reason,
                      reverses=paid_cash['id'], at=at)
    if t:
        tender(ctx, 'collection_reversal', entry_id, t['method'], -t['amount'], at=at)
    ctx.audit('customer.collect.reverse', 'customer', e['customer_id'], {'amount': -e['amount'], 'reason': reason})
    return {'ok': True}


def customer_view(db, customer_id, private=False):
    c = db.one('SELECT * FROM customers WHERE id = ?', customer_id)
    if not c:
        raise NotFound('customer')
    if not private:
        c['national_id'] = '•••' if c['national_id'] else ''
    c['balance'] = customer_balance(db, customer_id)
    c['entries'] = db.all('SELECT a.id, a.at, a.amount, a.kind, a.ref_type, a.ref_id, a.note, a.plan_id, a.reverses, '
                          '(SELECT 1 FROM ar_entries r WHERE r.reverses = a.id) AS reversed, u.full_name AS by_name FROM ar_entries a '
                          'LEFT JOIN users u ON u.id = a.by_user WHERE a.customer_id = ? ORDER BY a.at DESC LIMIT 200', customer_id)
    c['sales'] = db.all('SELECT id, number, at, total FROM sales WHERE customer_id = ? ORDER BY at DESC LIMIT 50', customer_id)
    plans = db.all('SELECT * FROM plans WHERE customer_id = ? ORDER BY created_at DESC', customer_id)
    for p in plans:
        p.update(plan_schedule(db, p))
        if not private:
            p['guarantor_national_id'] = '•••' if p['guarantor_national_id'] else ''
    c['plans'] = plans
    return c


def customers_list(db, q='', only='all', limit=200):
    where, args = ['c.active = 1'], []
    if q:
        where.append('(c.name LIKE ? OR c.phone LIKE ?)')
        args += [f'%{q}%', f'%{q}%']
    rows = db.all('SELECT c.id, c.name, c.phone, c.address, c.credit_limit, COALESCE((SELECT SUM(amount) FROM ar_entries a '
                  'WHERE a.customer_id = c.id), 0) AS balance, (SELECT MAX(at) FROM sales s WHERE s.customer_id = c.id) AS last_sale '
                  f"FROM customers c WHERE {' AND '.join(where)} ORDER BY c.name LIMIT ?", *args, limit)
    if only == 'owing':
        rows = [r for r in rows if r['balance'] > 0]
    return rows


def instalments_due(db, today=None, limit=200):
    """Every plan with money due today or late: the collection list of the day."""
    today = today or ids.local_day()
    out = []
    for p in db.all('SELECT p.*, c.name AS customer, c.phone FROM plans p JOIN customers c ON c.id = p.customer_id'):
        sch = plan_schedule(db, p, today)
        if sch['remaining'] > 0 and sch['due_now'] > 0:
            out.append({'plan_id': p['id'], 'number': p['number'], 'customer_id': p['customer_id'], 'customer': p['customer'],
                        'phone': p['phone'], 'due_now': sch['due_now'], 'remaining': sch['remaining'], 'late_days': sch['late_days'],
                        'next_due': sch['next']['due'] if sch['next'] else None, 'monthly': p['monthly']})
    out.sort(key=lambda r: -r['late_days'])
    return out[:limit]


def instalments_upcoming(db, days=7, today=None):
    today = today or ids.local_day()
    out = []
    for p in db.all('SELECT p.*, c.name AS customer, c.phone FROM plans p JOIN customers c ON c.id = p.customer_id'):
        sch = plan_schedule(db, p, today)
        nxt = sch['next']
        if nxt and today < nxt['due'] and ids.days_between(today, nxt['due']) <= days:
            out.append({'plan_id': p['id'], 'number': p['number'], 'customer_id': p['customer_id'], 'customer': p['customer'],
                        'phone': p['phone'], 'due': nxt['due'], 'amount': nxt['amount'] - nxt['paid']})
    out.sort(key=lambda r: r['due'])
    return out


# ------------------------------------------------------------------ suppliers
def save_supplier(ctx, data):
    ctx.need('stock.receive')
    name = text(data.get('name'), 'name', 80, True)
    fields = {'name': name, 'phone': text(data.get('phone'), 'phone', 20), 'notes': text(data.get('notes'), 'notes', 500)}
    if data.get('id'):
        if not ctx.db.value('SELECT 1 FROM suppliers WHERE id = ?', data['id']):
            raise NotFound('supplier')
        ctx.db.run('UPDATE suppliers SET name = ?, phone = ?, notes = ? WHERE id = ?', *fields.values(), data['id'])
        ctx.audit('supplier.edit', 'supplier', data['id'], fields)
        return data['id']
    sid = ids.uuid7()
    ctx.db.insert('suppliers', {'id': sid, 'org_id': ctx.org_id, 'active': 1, 'created_at': ids.iso(), **fields})
    ctx.audit('supplier.add', 'supplier', sid, {'name': name})
    return sid


def supplier_balance(db, supplier_id):
    return db.value('SELECT COALESCE(SUM(amount), 0) FROM ap_entries WHERE supplier_id = ?', supplier_id)


def pay_supplier(ctx, data, inside=False):
    if not inside:
        ctx.need('suppliers.pay')
    key = text(data.get('idem_key'), 'idem_key', 64, True)
    done = ctx.db.one('SELECT id FROM ap_entries WHERE idem_key = ?', key)
    if done:
        return done
    supplier = ctx.db.one('SELECT * FROM suppliers WHERE id = ?', data.get('supplier_id'))
    if not supplier:
        raise NotFound('supplier')
    amount = money(data.get('amount'))
    if not amount:
        raise Problem('err.zero', 'Write the amount.')
    owed = supplier_balance(ctx.db, supplier['id'])
    if amount > owed:
        raise Problem('err.payMoreThanOwed', 'This is more than the shop owes this supplier.', owed=owed)
    source = data.get('source') or 'safe'
    note = text(data.get('note'), 'note', 200)
    entry = {'id': ids.uuid7(), 'supplier_id': supplier['id'], 'amount': -amount, 'kind': 'payment', 'ref_type': 'payment',
             'ref_id': '', 'idem_key': key, 'note': note, 'at': ids.iso(), 'by_user': ctx.uid, 'reverses': None}
    if source in ('drawer', 'safe'):
        cash_out(ctx, source, 'supplier', amount, 'supplier', supplier['id'], note or supplier['name'])
    elif source != 'bank':
        raise Problem('err.source', 'Choose drawer, safe or bank.')
    ctx.db.insert('ap_entries', entry)
    ctx.audit('supplier.pay', 'supplier', supplier['id'], {'amount': amount, 'source': source})
    return {'id': entry['id'], 'balance': supplier_balance(ctx.db, supplier['id'])}


def suppliers_list(db):
    return db.all('SELECT s.*, COALESCE((SELECT SUM(amount) FROM ap_entries a WHERE a.supplier_id = s.id), 0) AS balance, '
                  '(SELECT MAX(at) FROM purchases p WHERE p.supplier_id = s.id) AS last_purchase FROM suppliers s '
                  'WHERE s.active = 1 ORDER BY s.name')


def supplier_view(db, supplier_id):
    s = db.one('SELECT * FROM suppliers WHERE id = ?', supplier_id)
    if not s:
        raise NotFound('supplier')
    s['balance'] = supplier_balance(db, supplier_id)
    s['entries'] = db.all('SELECT a.at, a.amount, a.kind, a.note, a.ref_type, a.ref_id, u.full_name AS by_name FROM ap_entries a '
                          'LEFT JOIN users u ON u.id = a.by_user WHERE supplier_id = ? ORDER BY a.at DESC LIMIT 200', supplier_id)
    s['purchases'] = db.all('SELECT id, number, at, total, supplier_ref FROM purchases WHERE supplier_id = ? ORDER BY at DESC LIMIT 50',
                            supplier_id)
    return s


def finance_due(db):
    """What each finance company (valU, Aman, ...) still has to pay the shop."""
    return db.all("SELECT provider, SUM(amount) AS amount FROM tenders WHERE method = 'finance' GROUP BY provider "
                  "HAVING SUM(amount) != 0 ORDER BY provider")


def finance_settle(ctx, data):
    ctx.need('cash.safe')
    provider = text(data.get('provider'), 'provider', 40, True)
    amount = money(data.get('amount'))
    due = next((r['amount'] for r in finance_due(ctx.db) if r['provider'] == provider), 0)
    if not amount or amount > due:
        raise Problem('err.payMoreThanOwed', 'This is more than the company still owes.', owed=due)
    tender(ctx, 'settlement', ids.uuid7(), 'finance', -amount, provider)
    ctx.audit('finance.settle', 'finance', provider, {'amount': amount, 'note': text(data.get('note'), 'note', 200)})
    return {'ok': True}

