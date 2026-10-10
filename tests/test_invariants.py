"""Random shop days with the books checked after every step (an independent audit that found the negative safe and the over-paid plan).

Each seed plays a few hundred random operations: goods in (cash, credit, from the safe), sales (cash, split, card, on account, instalments, with
a manager's approval), returns (good, damaged, to cash, to the account, to a card), customer payments and their undoing, expenses and their undoing,
safe moves, shifts, transfers, supplier payments, counts. A refusal by the rules is fine. After EVERY step the invariants must hold:
no negative safe or drawer, a closed shift's drawer is empty, no serial is lost, no supplier is overpaid, no plan is over-paid, and each ledger
equals the documents it comes from (sale tenders, customer accounts, collections, refunds, returns).
Non-serial stock may go below zero on purpose (the Owner's eye reports "sold beyond stock")."""
import random
import traceback
import unittest

from harness import Shop, PW
import catalog, ids, money as cash, sales, stock  # noqa: E401
from core import Problem
from auth import Forbidden

class World:
    def __init__(self, seed):
        self.r = random.Random(seed)
        self.s = Shop()
        self.s.all_pay()
        self.mgr = self.s.user('manager', 'mgr1')
        self.cashier = self.s.user('cashier', 'cas1')
        self.keeper = self.s.user('storekeeper', 'sk1')
        self.s.do(cash.open_shift, 500000)
        self.s.do(cash.open_shift, 100000, user=self.cashier)
        self.products = []
        self.cust = [self.s.do(cash.save_customer, {'name': f'C{i}', 'phone': f'0100000000{i}', 'credit_limit': 0}) for i in range(3)]
        self.sup = [self.s.do(cash.save_supplier, {'name': f'S{i}'}) for i in range(2)]
        self.sup = [x if isinstance(x, str) else x['id'] for x in self.sup]
        self.cust = [x if isinstance(x, str) else x['id'] for x in self.cust]
        for i in range(4):
            serial = i % 2 == 0
            pid = self.s.product(f'P{i}', retail=100000 + i * 50000, cost=60000 + i * 20000, qty=0, serial=serial)
            self.products.append((pid, serial))
        self.n = 0
        self.log = []

    def key(self):
        self.n += 1
        return f'k{self.n}'

    # ---- operations (a calm refusal by the rules is fine)
    def op_receive(self):
        pid, serial = self.r.choice(self.products)
        qty = self.r.randint(1, 4)
        place = self.r.choice([self.s.shop, self.s.store])
        sup = self.r.choice(self.sup)
        paid = self.r.choice([0, 0, 50000])
        lines = [{'product_id': pid, 'qty': qty, 'unit_cost': self.r.choice([60000, 70000, 90000]),
                  'serials': [f'S{self.n}x{i}' for i in range(qty)] if serial else []}]
        self.s.do(stock.receive, {'idem_key': self.key(), 'location_id': place, 'supplier_id': sup, 'lines': lines, 'paid_now': paid,
                                  'pay_from': self.r.choice(['drawer', 'safe'])}, user=self.r.choice([self.s.users['owner'], self.keeper]))

    def op_sell(self):
        pid, serial = self.r.choice(self.products)
        user = self.r.choice([self.s.users['owner'], self.cashier])
        if serial:
            left = stock.serials_in_stock(self.s.db, pid, self.s.shop)
            if not left:
                return
            line = {'product_id': pid, 'qty': 1, 'serial': self.r.choice(left)['serial']}
        else:
            line = {'product_id': pid, 'qty': self.r.randint(1, 3)}
        discount = self.r.choice([0, 0, 0, 10000])
        q = self.s.do(sales.quote, {'lines': [line], 'discount': discount}, user=user)
        total = q['total']
        kind = self.r.choice(['cash', 'cash', 'split', 'card', 'account', 'installment'])
        cust = self.r.choice(self.cust)
        body = {'idem_key': self.key(), 'lines': [line], 'discount': discount}
        if kind == 'cash':
            body['payments'] = [{'method': 'cash', 'amount': total}]
        elif kind == 'card':
            body['payments'] = [{'method': 'card', 'amount': total}]
        elif kind == 'split':
            a = (total // 2 // 100) * 100
            body['payments'] = [{'method': 'cash', 'amount': a}, {'method': 'instapay', 'amount': total - a}]
        elif kind == 'account':
            body['customer_id'] = cust
            body['payments'] = [{'method': 'account', 'amount': total}]
        else:
            down = (total * 40 // 100 // 100) * 100
            months = self.r.choice([3, 6])
            q2 = self.s.do(sales.quote, {'lines': [line], 'discount': discount, 'instalment': {'months': months, 'down': down}}, user=user)
            body['customer_id'] = cust
            body['payments'] = [{'method': 'cash', 'amount': down}, {'method': 'installment', 'amount': q2['total'] - down}]
            body['instalment'] = {'months': months, 'first_due': ids.add_months(ids.local_day(), 1), 'guarantor': {'name': 'G'}}
        body['approval'] = {'username': 'mgr1', 'password': PW}
        self.s.do(sales.sell, body, user=user)

    def op_return(self):
        rows = self.s.db.all('SELECT id FROM sales ORDER BY at DESC LIMIT 30')
        if not rows:
            return
        sale = sales.sale_view(self.s.db, self.r.choice(rows)['id'], True)
        line = self.r.choice(sale['lines'])
        left = line['qty'] - line['returned']
        if left <= 0:
            return
        qty = 1 if line['serial'] else self.r.randint(1, max(1, int(left)))
        method = self.r.choice(['cash', 'cash', 'account', 'card'])
        body = {'idem_key': self.key(), 'sale_id': sale['id'], 'reason': 'sim return', 'refund_method': method,
                'lines': [{'sale_line_id': line['id'], 'qty': qty, 'condition': self.r.choice(['good', 'damaged'])}],
                'approval': {'username': 'mgr1', 'password': PW}}
        user = self.r.choice([self.s.users['owner'], self.cashier])
        self.s.do(sales.take_return, body, user=user)

    def op_collect(self):
        cust = self.r.choice(self.cust)
        owed = cash.customer_balance(self.s.db, cust)
        if owed <= 0:
            return
        plans = self.s.db.all('SELECT id FROM plans WHERE customer_id = ?', cust)
        body = {'idem_key': self.key(), 'customer_id': cust, 'amount': min(owed, self.r.choice([20000, 50000, 100000])),
                'method': self.r.choice(['cash', 'cash', 'instapay'])}
        if plans and self.r.random() < 0.7:
            body['plan_id'] = self.r.choice(plans)['id']
        self.s.do(cash.collect, body, user=self.r.choice([self.s.users['owner'], self.cashier]))

    def op_reverse_collection(self):
        rows = self.s.db.all("SELECT id FROM ar_entries WHERE kind = 'payment' ORDER BY at DESC LIMIT 10")
        if rows:
            self.s.do(cash.reverse_collection, self.r.choice(rows)['id'], 'sim reverse')

    def op_expense(self):
        self.s.do(cash.expense, {'idem_key': self.key(), 'source': self.r.choice(['drawer', 'safe']), 'amount': self.r.choice([5000, 20000, 90000]),
                                 'category': 'other', 'note': 'sim expense'}, user=self.r.choice([self.s.users['owner'], self.cashier]))

    def op_reverse_cash(self):
        rows = self.s.db.all("SELECT id FROM cash_moves WHERE kind IN ('expense','withdraw','deposit') ORDER BY at DESC LIMIT 10")
        if rows:
            self.s.do(cash.reverse_cash, self.r.choice(rows)['id'], 'sim reverse')

    def op_safe(self):
        self.s.do(cash.safe_move, {'kind': self.r.choice(['withdraw', 'deposit', 'drop', 'deposit']), 'amount': self.r.choice([10000, 100000, 300000]),
                                   'note': 'sim safe'}, user=self.r.choice([self.s.users['owner'], self.cashier]))

    def op_close_open_shift(self):
        user = self.r.choice([self.s.users['owner'], self.cashier])
        sh = cash.open_shift_of(self.s.db, user['id'])
        if sh:
            exp = cash.drawer_expected(self.s.db, sh['id'])
            counted = exp + self.r.choice([0, 0, -2000, 3000])
            self.s.do(cash.close_shift, sh['id'], max(0, counted), 'sim diff', user=user)
        else:
            self.s.do(cash.open_shift, self.r.choice([0, 100000, 400000]), user=user)

    def op_transfer(self):
        pid, serial = self.r.choice(self.products)
        a, b = self.r.choice([(self.s.store, self.s.shop), (self.s.shop, self.s.store)])
        if serial:
            left = stock.serials_in_stock(self.s.db, pid, a)
            if not left:
                return
            line = {'product_id': pid, 'qty': 1, 'serials': [left[0]['serial']]}
        else:
            line = {'product_id': pid, 'qty': self.r.randint(1, 3)}
        self.s.do(stock.transfer, {'idem_key': self.key(), 'from_id': a, 'to_id': b, 'lines': [line]}, user=self.keeper)

    def op_pay_supplier(self):
        sup = self.r.choice(self.sup)
        owed = cash.supplier_balance(self.s.db, sup)
        if owed > 0:
            self.s.do(cash.pay_supplier, {'idem_key': self.key(), 'supplier_id': sup, 'amount': min(owed, 30000),
                                          'source': self.r.choice(['safe', 'drawer', 'bank'])})

    def op_count(self):
        pid, serial = self.r.choice([x for x in self.products if not x[1]])
        place = self.r.choice([self.s.shop, self.s.store])
        cid = self.s.do(stock.start_count, place, user=self.keeper)
        have = stock.on_hand(self.s.db, pid, place)
        self.s.do(stock.count_line, cid, pid, max(0, have + self.r.choice([0, 0, -1, 1])), user=self.keeper)
        self.s.do(stock.close_count, cid, 'sim count', user=self.keeper)

    def op_spend_what_came_in(self):
        """The sneaky order that once broke the drawer: collect cash, spend it from the drawer, then undo the collection."""
        cust = self.r.choice(self.cust)
        owed = cash.customer_balance(self.s.db, cust)
        if owed <= 0:
            return
        user = self.s.users['owner']
        amount = min(owed, 30000)
        got = self.s.do(cash.collect, {'idem_key': self.key(), 'customer_id': cust, 'amount': amount, 'method': 'cash'}, user=user)
        shift = cash.open_shift_of(self.s.db, user['id'])
        self.s.do(cash.expense, {'idem_key': self.key(), 'amount': cash.drawer_expected(self.s.db, shift['id']), 'category': 'other', 'note': 'sim drain'}, user=user)
        self.s.do(cash.reverse_collection, got['id'], 'sim undo')

    OPS = ['receive'] * 4 + ['sell'] * 8 + ['return'] * 3 + ['collect'] * 3 + ['reverse_collection'] + ['expense'] * 2 + ['reverse_cash'] + \
          ['safe'] * 2 + ['spend_what_came_in'] * 2 + ['close_open_shift'] * 2 + ['transfer'] * 2 + ['pay_supplier'] + ['count']

    def step(self):
        name = self.r.choice(self.OPS)
        try:
            getattr(self, 'op_' + name)()
            return name, 'ok'
        except (Problem, Forbidden) as e:
            return name, 'refused:' + getattr(e, 'key', e.__class__.__name__)
        except Exception:
            return name, 'CRASH:' + traceback.format_exc().splitlines()[-1]

    # ---- invariants
    def check(self):
        db = self.s.db
        bad = []
        for pid, serial in self.products:
            for loc in (self.s.shop, self.s.store, self.s.damaged):
                n = stock.on_hand(db, pid, loc)
                if n < -1e-9 and serial:
                    bad.append(f'negative stock {pid[:6]}@{loc[:6]} = {n}')
        if cash.safe_balance(db) < 0:
            bad.append(f'negative safe {cash.safe_balance(db)}')
        for sh in db.all('SELECT id, closed_at FROM shifts'):
            exp = cash.drawer_expected(db, sh['id'])
            if exp < 0:
                bad.append(f'negative drawer {exp} (shift {sh["id"][:6]})')
            if sh['closed_at'] and exp != 0:
                bad.append(f'closed shift drawer not zero {exp}')
        for sid in db.all('SELECT id, total FROM sales'):
            t = db.value("SELECT COALESCE(SUM(amount),0) FROM tenders WHERE ref_type = 'sale' AND ref_id = ?", sid['id'])
            if t != sid['total']:
                bad.append(f'sale tenders {t} != total {sid["total"]}')
        # cash tender of sales == cash_moves 'sale' (per shift)
        cm = db.value("SELECT COALESCE(SUM(amount),0) FROM cash_moves WHERE kind = 'sale' AND account = 'drawer'")
        ct = db.value("SELECT COALESCE(SUM(amount),0) FROM tenders WHERE ref_type = 'sale' AND method = 'cash'")
        if cm != ct:
            bad.append(f'cash sale moves {cm} != cash tenders {ct}')
        # an instalment plan is never paid more than it owes
        for c in self.cust:
            plans = db.all('SELECT id, financed FROM plans WHERE customer_id = ?', c)
            for p in plans:
                sch = cash.plan_schedule(db, dict(db.one('SELECT * FROM plans WHERE id = ?', p['id'])))
                if sch['remaining'] < 0:
                    bad.append(f'plan overpaid: remaining {sch["remaining"]}')
        # suppliers never overpaid
        for sp in self.sup:
            if cash.supplier_balance(db, sp) < 0:
                bad.append(f'supplier balance negative {cash.supplier_balance(db, sp)}')
        # a serial is in exactly one place or sold
        for r in db.all("SELECT DISTINCT serial FROM stock_moves WHERE serial IS NOT NULL"):
            st = stock.serial_state(db, r['serial'])
            if st is None:
                bad.append(f'serial {r["serial"]} has no state')
        # ledgers against the documents they come from
        v = lambda q, *a: db.value(q, *a)
        if v("SELECT COALESCE(SUM(amount),0) FROM ar_entries WHERE kind = 'sale'") != v("SELECT COALESCE(SUM(amount),0) FROM tenders WHERE ref_type = 'sale' AND method = 'account'"):
            bad.append('AR sale entries != account tenders')
        if v("SELECT COALESCE(SUM(amount),0) FROM ar_entries WHERE kind = 'instalment'") != v('SELECT COALESCE(SUM(financed),0) FROM plans'):
            bad.append('AR instalment entries != plans financed')
        coll_t = v("SELECT COALESCE(SUM(amount),0) FROM tenders WHERE ref_type IN ('collection', 'collection_reversal')")
        coll_a = -v("SELECT COALESCE(SUM(amount),0) FROM ar_entries WHERE kind IN ('payment','reversal') AND ref_type = 'collection'")
        if coll_t != coll_a:
            bad.append(f'collections: tenders {coll_t} != AR {coll_a}')
        if v("SELECT COALESCE(SUM(amount),0) FROM cash_moves WHERE kind = 'refund'") != v("SELECT COALESCE(SUM(amount),0) FROM tenders WHERE ref_type = 'return' AND method = 'cash'"):
            bad.append('cash refunds != cash return tenders')
        for r in db.all('SELECT id, total, fee FROM returns'):
            paid = -v("SELECT COALESCE(SUM(amount),0) FROM tenders WHERE ref_type = 'return' AND ref_id = ?", r['id'])
            acct = -v("SELECT COALESCE(SUM(amount),0) FROM ar_entries WHERE ref_type = 'return' AND ref_id = ?", r['id'])
            if paid + acct != r['total'] + r['fee']:
                bad.append(f'return {r["id"][:6]}: paid {paid} + account {acct} != total {r["total"]} + fee {r["fee"]}')
        return bad, None


class RandomDays(unittest.TestCase):
    SEEDS, STEPS = range(4), 90

    def test_the_books_hold_after_every_step(self):
        crashes, broken, done = [], [], 0
        for seed in self.SEEDS:
            w = World(seed)
            try:
                for i in range(self.STEPS):
                    name, res = w.step()
                    done += res == 'ok'
                    if res.startswith('CRASH'):
                        crashes.append((seed, i, name, res))
                    bad, _ = w.check()
                    broken += [(seed, i, name, b) for b in bad]
            finally:
                w.s.cleanup()
        self.assertEqual(crashes, [], 'an operation crashed instead of answering calmly')
        self.assertEqual(broken[:5], [], 'the books broke')
        self.assertGreater(done, 100, 'the simulation must really do things, not only be refused')


if __name__ == '__main__':
    unittest.main()
