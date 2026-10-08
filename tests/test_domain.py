"""The shop's rules, tested without HTTP: money, stock, approvals, returns, instalments, shifts, prices, counts."""
import sqlite3
import unittest

from harness import PW, Shop, day
import catalog
import ids
import money as cash
import reports
import sales
import stock
from auth import Forbidden
from core import Problem


def sale(shop, lines, payments=None, user=None, **extra):
    total = None
    if payments is None:
        q = shop.do(sales.quote, {'lines': lines, 'discount': extra.get('discount', 0)}, user=user)
        total = q['total']
        payments = [{'method': 'cash', 'amount': total}]
    return shop.do(sales.sell, {'idem_key': extra.pop('key', ids.uuid7()), 'lines': lines, 'payments': payments, **extra}, user=user)


class Base(unittest.TestCase):
    def setUp(self):
        self.s = Shop()
        self.s.do(cash.open_shift, 10000)

    def tearDown(self):
        self.s.cleanup()


class SellingTests(Base):
    def test_cash_sale_moves_stock_drawer_and_is_idempotent(self):
        pid = self.s.product(qty=5)
        key = ids.uuid7()
        first = sale(self.s, [{'product_id': pid, 'qty': 2}], key=key)
        again = sale(self.s, [{'product_id': pid, 'qty': 2}], key=key)
        self.assertEqual(first['id'], again['id'])
        self.assertTrue(again['repeat'])
        self.assertEqual(stock.on_hand(self.s.db, pid), 3)
        shift = cash.open_shift_of(self.s.db, self.s.users['owner']['id'])
        self.assertEqual(cash.drawer_expected(self.s.db, shift['id']), 10000 + 200000)
        self.assertEqual(self.s.db.value('SELECT COUNT(*) FROM sales'), 1)

    def test_payments_must_add_up(self):
        pid = self.s.product()
        with self.assertRaises(Problem) as e:
            sale(self.s, [{'product_id': pid, 'qty': 1}], [{'method': 'cash', 'amount': 90000}])
        self.assertEqual(e.exception.key, 'err.paymentsMismatch')

    def test_split_payment_cash_and_card(self):
        pid = self.s.product()
        r = sale(self.s, [{'product_id': pid, 'qty': 1}], [{'method': 'cash', 'amount': 40000}, {'method': 'card', 'amount': 60000}],
                 cash_received=50000)
        self.assertEqual(r['change'], 10000)
        t = {x['method']: x['amount'] for x in self.s.db.all("SELECT method, amount FROM tenders WHERE ref_id = ?", r['id'])}
        self.assertEqual(t, {'cash': 40000, 'card': 60000})

    def test_no_sale_without_open_shift(self):
        pid = self.s.product()
        cashier = self.s.user('cashier')
        with self.assertRaises(Problem) as e:
            sale(self.s, [{'product_id': pid, 'qty': 1}], user=cashier)
        self.assertEqual(e.exception.key, 'err.noShift')

    def test_serial_rules(self):
        pid = self.s.product('Fridge', 3000000, 2500000, qty=2, serial=True)
        with self.assertRaises(Problem) as e:
            sale(self.s, [{'product_id': pid, 'qty': 1}])
        self.assertEqual(e.exception.key, 'err.serialNeeded')
        with self.assertRaises(Problem) as e:
            sale(self.s, [{'product_id': pid, 'qty': 1, 'serial': 'NOPE1'}])
        self.assertEqual(e.exception.key, 'err.serialNotInStock')
        r = sale(self.s, [{'product_id': pid, 'qty': 1, 'serial': 'FRI0001'}])
        w = sales.warranty(self.s.db, 'fri0001')
        self.assertEqual(w['sale_number'], r['number'])
        self.assertEqual(w['warranty_until'], ids.add_months(ids.local_day(), 12))
        with self.assertRaises(Problem):
            sale(self.s, [{'product_id': pid, 'qty': 1, 'serial': 'FRI0001'}])  # already sold

    def test_selling_beyond_stock_is_allowed_but_watched(self):
        pid = self.s.product(qty=1)
        sale(self.s, [{'product_id': pid, 'qty': 3}])
        self.assertEqual(stock.on_hand(self.s.db, pid), -2)
        kinds = {i['kind'] for i in reports.watch(self.s.db)}
        self.assertIn('negative_stock', kinds)

    def test_discount_limits_and_manager_approval(self):
        pid = self.s.product(retail=100000)
        cashier = self.s.user('cashier', 'cash1')  # 5 % limit
        manager = self.s.user('manager', 'man1')  # 15 % limit
        self.s.do(cash.open_shift, 0, user=cashier)
        lines = [{'product_id': pid, 'qty': 1, 'unit_price': 90000}]  # 10 %
        with self.assertRaises(Problem) as e:
            sale(self.s, lines, [{'method': 'cash', 'amount': 90000}], user=cashier)
        self.assertEqual(e.exception.key, 'err.needsApproval')
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(Problem) as e:
            sale(self.s, lines, [{'method': 'cash', 'amount': 90000}], user=cashier,
                 approval={'username': 'cash1', 'password': PW})
        self.assertEqual(e.exception.key, 'err.selfApproval')
        r = sale(self.s, lines, [{'method': 'cash', 'amount': 90000}], user=cashier, approval={'username': 'man1', 'password': PW})
        approved = self.s.db.value('SELECT approved_by FROM sales WHERE id = ?', r['id'])
        self.assertEqual(approved, manager['id'])
        big = [{'product_id': pid, 'qty': 1, 'unit_price': 70000}]  # 30 %: above the manager's limit too
        with self.assertRaises(Problem) as e:
            sale(self.s, big, [{'method': 'cash', 'amount': 70000}], user=cashier, approval={'username': 'man1', 'password': PW})
        self.assertEqual(e.exception.key, 'err.approverLimit')

    def test_under_minimum_price_needs_price_permission(self):
        pid = self.s.product(retail=100000, minimum=95000)
        cashier = self.s.user('cashier', 'cash2', max_discount_pct=20)
        self.s.user('storekeeper', 'keeper')
        self.s.do(cash.open_shift, 0, user=cashier)
        lines = [{'product_id': pid, 'qty': 1, 'unit_price': 90000}]
        with self.assertRaises(Problem):
            sale(self.s, lines, [{'method': 'cash', 'amount': 90000}], user=cashier)
        with self.assertRaises(Forbidden):
            sale(self.s, lines, [{'method': 'cash', 'amount': 90000}], user=cashier, approval={'username': 'keeper', 'password': PW})
        self.assertTrue(sale(self.s, lines, [{'method': 'cash', 'amount': 90000}], user=cashier,
                             approval={'username': 'owner1', 'password': 'Owner Pass 1'})['id'])

    def test_wrong_approval_password_counts_as_failed_login(self):
        pid = self.s.product()
        cashier = self.s.user('cashier', 'cash3')
        self.s.user('manager', 'man3')
        self.s.do(cash.open_shift, 0, user=cashier)
        from auth import AuthError
        for _ in range(2):
            with self.assertRaises(AuthError):
                sale(self.s, [{'product_id': pid, 'qty': 1, 'unit_price': 50000}], [{'method': 'cash', 'amount': 50000}], user=cashier,
                     approval={'username': 'man3', 'password': 'wrong'})
        self.assertEqual(self.s.db.value("SELECT failed FROM users WHERE username = 'man3'"), 2)


class CreditTests(Base):
    def setUp(self):
        super().setUp()
        self.s.do(lambda ctx: __import__('core').set_setting(ctx.db, 'instalment_markup_pct', 2))
        self.cust = self.s.do(cash.save_customer, {'name': 'Customer', 'phone': '01000000000'})
        self.tv = self.s.product('TV', 1000000, 800000, qty=3)

    def test_instalment_plan_fee_schedule_and_collection(self):
        lines = [{'product_id': self.tv, 'qty': 1}]
        q = self.s.do(sales.quote, {'lines': lines, 'instalment': {'months': 10, 'down': 200000}})
        self.assertEqual(q['fee'], 160000)  # 800,000 financed × 2 % × 10 months
        self.assertEqual(q['total'], 1160000)
        r = sale(self.s, lines, [{'method': 'cash', 'amount': 200000}, {'method': 'installment', 'amount': 960000}],
                 customer_id=self.cust, instalment={'months': 10, 'first_due': day(30), 'guarantor': {'name': 'G'}})
        plan = self.s.db.one('SELECT * FROM plans WHERE id = ?', r['plan_id'])
        sch = cash.plan_schedule(self.s.db, plan)
        self.assertEqual(sum(x['amount'] for x in sch['rows']), 960000)
        self.assertEqual(sch['remaining'], 960000)
        self.assertEqual(cash.customer_balance(self.s.db, self.cust), 960000)
        late = cash.plan_schedule(self.s.db, plan, today=ids.add_months(day(30), 2))
        self.assertEqual(late['due_now'], 96000 * 3)
        self.s.do(cash.collect, {'idem_key': 'k1', 'customer_id': self.cust, 'amount': 96000, 'plan_id': plan['id']})
        self.s.do(cash.collect, {'idem_key': 'k1', 'customer_id': self.cust, 'amount': 96000, 'plan_id': plan['id']})  # retry
        self.assertEqual(cash.customer_balance(self.s.db, self.cust), 864000)
        sch = cash.plan_schedule(self.s.db, plan)
        self.assertEqual(sch['rows'][0]['state'], 'paid')

    def test_down_payment_minimum_and_tampered_amount(self):
        lines = [{'product_id': self.tv, 'qty': 1}]
        with self.assertRaises(Problem) as e:
            sale(self.s, lines, [{'method': 'cash', 'amount': 100000}, {'method': 'installment', 'amount': 900000}],
                 customer_id=self.cust, instalment={'months': 1, 'first_due': day(30)})
        self.assertEqual(e.exception.key, 'err.downPayment')
        with self.assertRaises(Problem) as e:
            sale(self.s, lines, [{'method': 'cash', 'amount': 200000}, {'method': 'installment', 'amount': 800000}],
                 customer_id=self.cust, instalment={'months': 10, 'first_due': day(30)})
        self.assertEqual(e.exception.key, 'err.totalChanged')

    def test_account_sale_needs_customer_and_credit_limit_approval(self):
        lines = [{'product_id': self.tv, 'qty': 1}]
        with self.assertRaises(Problem) as e:
            sale(self.s, lines, [{'method': 'account', 'amount': 1000000}])
        self.assertEqual(e.exception.key, 'err.needCustomer')
        self.s.do(cash.save_customer, {'id': self.cust, 'name': 'Customer', 'phone': '01000000000', 'credit_limit': 500000})
        cashier = self.s.user('cashier', 'c9')
        self.s.do(cash.open_shift, 0, user=cashier)
        with self.assertRaises(Problem) as e:
            sale(self.s, lines, [{'method': 'account', 'amount': 1000000}], customer_id=self.cust, user=cashier)
        self.assertEqual(e.exception.vars['needs'], ['credit_limit'])
        sale(self.s, lines, [{'method': 'account', 'amount': 1000000}], customer_id=self.cust, user=cashier,
             approval={'username': 'owner1', 'password': 'Owner Pass 1'})
        self.assertEqual(cash.customer_balance(self.s.db, self.cust), 1000000)

    def test_collection_reversal_restores_debt_and_drawer(self):
        sale(self.s, [{'product_id': self.tv, 'qty': 1}], [{'method': 'account', 'amount': 1000000}], customer_id=self.cust)
        r = self.s.do(cash.collect, {'idem_key': 'c1', 'customer_id': self.cust, 'amount': 300000})
        shift = cash.open_shift_of(self.s.db, self.s.users['owner']['id'])
        before = cash.drawer_expected(self.s.db, shift['id'])
        with self.assertRaises(Problem):
            self.s.do(cash.collect, {'idem_key': 'c2', 'customer_id': self.cust, 'amount': 900000})
        self.s.do(cash.reverse_collection, r['id'], 'typed twice')
        self.assertEqual(cash.customer_balance(self.s.db, self.cust), 1000000)
        self.assertEqual(cash.drawer_expected(self.s.db, shift['id']), before - 300000)
        with self.assertRaises(Problem):
            self.s.do(cash.reverse_collection, r['id'], 'again')


class ReturnTests(Base):
    def test_return_refunds_paid_share_and_restocks(self):
        pid = self.s.product(retail=100000, qty=5)
        r = sale(self.s, [{'product_id': pid, 'qty': 3}], discount=30000)  # paid 270,000
        s = sales.sale_view(self.s.db, r['id'])
        line = s['lines'][0]
        one = self.s.do(sales.take_return, {'idem_key': 'r1', 'sale_id': r['id'], 'reason': 'changed mind', 'refund_method': 'cash',
                                            'lines': [{'sale_line_id': line['id'], 'qty': 1}]})
        self.assertEqual(one['total'], 90000)
        self.assertEqual(stock.on_hand(self.s.db, pid), 3)
        with self.assertRaises(Problem) as e:
            self.s.do(sales.take_return, {'idem_key': 'r2', 'sale_id': r['id'], 'reason': 'again', 'refund_method': 'cash',
                                          'lines': [{'sale_line_id': line['id'], 'qty': 3}]})
        self.assertEqual(e.exception.key, 'err.returnTooMuch')
        rest = self.s.do(sales.take_return, {'idem_key': 'r3', 'sale_id': r['id'], 'reason': 'broken', 'refund_method': 'cash',
                                             'lines': [{'sale_line_id': line['id'], 'qty': 2, 'condition': 'damaged'}]})
        self.assertEqual(one['total'] + rest['total'], 270000)  # never more than was paid
        self.assertEqual(stock.on_hand(self.s.db, pid, self.s.damaged), 2)
        self.assertEqual(stock.on_hand(self.s.db, pid), 3)  # damaged pieces are not for sale

    def test_same_line_twice_in_one_return_cannot_refund_twice(self):
        pid = self.s.product(retail=100000, qty=5)
        r = sale(self.s, [{'product_id': pid, 'qty': 2}])
        line = sales.sale_view(self.s.db, r['id'])['lines'][0]
        with self.assertRaises(Problem) as e:
            self.s.do(sales.take_return, {'idem_key': 'dbl', 'sale_id': r['id'], 'reason': 'twice', 'refund_method': 'cash',
                                          'lines': [{'sale_line_id': line['id'], 'qty': 2}, {'sale_line_id': line['id'], 'qty': 2}]})
        self.assertEqual(e.exception.key, 'err.returnTooMuch')
        ok = self.s.do(sales.take_return, {'idem_key': 'dbl2', 'sale_id': r['id'], 'reason': 'two halves', 'refund_method': 'cash',
                                           'lines': [{'sale_line_id': line['id'], 'qty': 1}, {'sale_line_id': line['id'], 'qty': 1}]})
        self.assertEqual(ok['total'], 200000)  # the two halves add up to exactly what was paid

    def test_bad_setting_values_are_refused(self):
        import core
        for key, bad in (('instalment_markup_pct', 'abc'), ('shop_name', 5), ('finance_providers', 'valU'), ('onboarded', 'yes')):
            with self.assertRaises(Problem, msg=key) as e:
                core.set_setting(self.s.db, key, bad)
            self.assertEqual(e.exception.key, 'err.settingType')

    def test_cashier_return_needs_approval_by_someone_else(self):
        pid = self.s.product()
        cashier = self.s.user('cashier', 'rc')
        self.s.user('manager', 'rm')
        self.s.do(cash.open_shift, 50000, user=cashier)
        r = sale(self.s, [{'product_id': pid, 'qty': 1}], user=cashier)
        line = sales.sale_view(self.s.db, r['id'])['lines'][0]
        body = {'idem_key': 'x', 'sale_id': r['id'], 'reason': 'defect', 'refund_method': 'cash',
                'lines': [{'sale_line_id': line['id'], 'qty': 1}]}
        with self.assertRaises(Problem):
            self.s.do(sales.take_return, body, user=cashier)
        out = self.s.do(sales.take_return, {**body, 'approval': {'username': 'rm', 'password': PW}}, user=cashier)
        self.assertEqual(out['total'], 100000)
        self.assertIn('return', {i['kind'] for i in reports.watch(self.s.db)})

    def test_serial_comes_back_to_stock(self):
        pid = self.s.product('Washer', 2000000, 1500000, qty=1, serial=True)
        r = sale(self.s, [{'product_id': pid, 'qty': 1, 'serial': 'WAS0000'}])
        line = sales.sale_view(self.s.db, r['id'])['lines'][0]
        self.s.do(sales.take_return, {'idem_key': 'w', 'sale_id': r['id'], 'reason': 'exchange', 'refund_method': 'card',
                                      'lines': [{'sale_line_id': line['id'], 'qty': 1}]})
        self.assertTrue(stock.serial_state(self.s.db, 'WAS0000')['in_stock'])


class CashTests(Base):
    def test_close_shift_with_difference_needs_reason_and_goes_to_safe(self):
        shift = cash.open_shift_of(self.s.db, self.s.users['owner']['id'])
        with self.assertRaises(Problem):
            self.s.do(cash.close_shift, shift['id'], 9000)
        out = self.s.do(cash.close_shift, shift['id'], 9000, 'short 10')
        self.assertEqual(out['difference'], -1000)
        self.assertEqual(cash.safe_balance(self.s.db), 9000)
        self.assertEqual(cash.drawer_expected(self.s.db, shift['id']), 0)
        self.assertIn('drawer_short', {i['kind'] for i in reports.watch(self.s.db)})

    def test_float_comes_out_of_the_safe_so_the_safe_never_grows_from_nothing(self):
        owner = self.s.users['owner']['id']
        first = cash.open_shift_of(self.s.db, owner)
        self.s.do(cash.close_shift, first['id'], 10000)  # the 100 EGP float goes to the safe
        self.assertEqual(cash.safe_balance(self.s.db), 10000)
        second = self.s.do(cash.open_shift, 10000)  # taken from the safe: nothing is added from thin air
        self.assertEqual(cash.safe_balance(self.s.db), 0)
        self.s.do(cash.close_shift, second, 10000)
        self.assertEqual(cash.safe_balance(self.s.db), 10000)  # still exactly the money that exists
        third = self.s.do(cash.open_shift, 30000)  # more than the safe holds: the owner adds the rest
        self.assertEqual(cash.safe_balance(self.s.db), 0)
        self.assertEqual(cash.drawer_expected(self.s.db, third), 30000)

    def test_expense_rules_and_reversal(self):
        with self.assertRaises(Problem):
            self.s.do(cash.expense, {'idem_key': 'e0', 'amount': 500, 'category': 'other', 'note': ''})
        with self.assertRaises(Problem) as e:
            self.s.do(cash.expense, {'idem_key': 'e1', 'amount': 50000, 'category': 'other', 'note': 'too much'})
        self.assertEqual(e.exception.key, 'err.drawerShort')
        r = self.s.do(cash.expense, {'idem_key': 'e2', 'amount': 2000, 'category': 'hospitality', 'note': 'tea'})
        self.s.do(cash.reverse_cash, r['id'], 'typed by mistake')
        shift = cash.open_shift_of(self.s.db, self.s.users['owner']['id'])
        self.assertEqual(cash.drawer_expected(self.s.db, shift['id']), 10000)
        with self.assertRaises(Problem):
            self.s.do(cash.reverse_cash, r['id'], 'again')

    def test_ledger_rows_cannot_be_edited_or_deleted(self):
        pid = self.s.product()
        sale(self.s, [{'product_id': pid, 'qty': 1}])
        for sql in ('UPDATE cash_moves SET amount = 0', 'DELETE FROM stock_moves', 'UPDATE tenders SET amount = 1',
                    'UPDATE sale_lines SET unit_price = 1', 'UPDATE prices SET amount = 1', 'DELETE FROM audit', 'DELETE FROM costs'):
            self.assertTrue(self.s.db.value(f'SELECT COUNT(*) FROM {sql.split()[1] if sql.startswith("UPDATE") else sql.split()[2]}'))
            with self.assertRaises(sqlite3.DatabaseError):
                self.s.db.run(sql)


class StockTests(Base):
    def test_moving_average_cost(self):
        pid = self.s.product(cost=100, qty=10)
        self.s.do(stock.receive, {'idem_key': 'p2', 'location_id': self.s.shop, 'lines': [{'product_id': pid, 'qty': 10, 'unit_cost': 200}]})
        self.assertEqual(catalog.current_cost(self.s.db, pid), {'avg_cost': 150, 'last_cost': 200})

    def test_purchase_on_credit_and_supplier_payment(self):
        pid = self.s.product(qty=0)
        sup = self.s.do(cash.save_supplier, {'name': 'Supplier'})
        with self.assertRaises(Problem):
            self.s.do(stock.receive, {'idem_key': 'p1', 'location_id': self.s.store, 'lines': [{'product_id': pid, 'qty': 5, 'unit_cost': 1000}],
                                      'paid_now': 1000})  # owing money without a supplier
        self.s.do(stock.receive, {'idem_key': 'p1', 'location_id': self.s.store, 'supplier_id': sup,
                                  'lines': [{'product_id': pid, 'qty': 5, 'unit_cost': 1000}], 'paid_now': 2000, 'pay_from': 'drawer'})
        self.assertEqual(cash.supplier_balance(self.s.db, sup), 3000)
        self.s.do(cash.safe_move, {'kind': 'deposit', 'amount': 5000})
        self.s.do(cash.pay_supplier, {'idem_key': 'sp', 'supplier_id': sup, 'amount': 3000, 'source': 'safe'})
        self.assertEqual(cash.supplier_balance(self.s.db, sup), 0)
        self.assertEqual(cash.safe_balance(self.s.db), 2000)

    def test_transfer_and_serial_location(self):
        pid = self.s.product('Heater', 500000, 400000, qty=2, serial=True, place=self.s.store)
        with self.assertRaises(Problem) as e:
            sale(self.s, [{'product_id': pid, 'qty': 1, 'serial': 'HEA0000'}])
        self.assertEqual(e.exception.key, 'err.serialNotHere')
        self.s.do(stock.transfer, {'idem_key': 't1', 'from_id': self.s.store, 'to_id': self.s.shop,
                                   'lines': [{'product_id': pid, 'qty': 1, 'serials': ['HEA0000']}]})
        self.assertTrue(sale(self.s, [{'product_id': pid, 'qty': 1, 'serial': 'HEA0000'}])['id'])
        plain = self.s.product('Cup', 1000, 500, qty=3, place=self.s.store)
        with self.assertRaises(Problem) as e:
            self.s.do(stock.transfer, {'idem_key': 't2', 'from_id': self.s.store, 'to_id': self.s.shop,
                                       'lines': [{'product_id': plain, 'qty': 5}]})
        self.assertEqual(e.exception.key, 'err.notEnough')

    def test_count_settles_differences_with_reason(self):
        pid = self.s.product(qty=10, cost=500)
        cid = self.s.do(stock.start_count, self.s.shop)
        self.s.do(stock.count_line, cid, pid, 7)
        view = stock.count_view(self.s.db, cid, True)
        line = next(x for x in view['lines'] if x['id'] == pid)
        self.assertEqual(line['diff'], -3)
        self.assertEqual(line['diff_value'], -1500)
        with self.assertRaises(Problem):
            self.s.do(stock.close_count, cid, '')
        self.s.do(stock.close_count, cid, 'monthly count')
        self.assertEqual(stock.on_hand(self.s.db, pid), 7)
        self.assertIn('stock_loss', {i['kind'] for i in reports.watch(self.s.db)})


    def test_sale_after_counting_a_product_is_not_a_false_surplus(self):
        pid = self.s.product(qty=10, cost=500)
        cid = self.s.do(stock.start_count, self.s.shop)
        self.s.do(stock.count_line, cid, pid, 10)       # counted all 10 on the shelf
        sale(self.s, [{'product_id': pid, 'qty': 2}])   # then 2 are sold while the count is still open
        self.s.do(stock.close_count, cid, 'busy day')
        self.assertEqual(stock.on_hand(self.s.db, pid), 8)  # the books stay right: no phantom +2


class ProductTests(Base):
    def test_serial_tracking_cannot_change_once_goods_were_received(self):
        pid = self.s.product('Fan', qty=3)
        with self.assertRaises(Problem) as e:
            self.s.do(catalog.save_product, {'id': pid, 'track_serial': True})
        self.assertEqual(e.exception.key, 'err.serialLocked')
        fresh = self.s.product('New fan', qty=0)
        self.s.do(catalog.save_product, {'id': fresh, 'track_serial': True})  # nothing received yet: fine

    def test_reorder_level_must_be_a_number(self):
        pid = self.s.product('Fan2', qty=0)
        for junk in ('abc', [1], {}, True, -1, float('nan')):
            with self.assertRaises(Problem):
                self.s.do(catalog.save_product, {'id': pid, 'reorder_level': junk})


class PriceTests(Base):
    def test_bulk_price_preview_apply_and_dated_start(self):
        a = self.s.product('A', retail=123400, brand='Fresh')
        self.s.product('B', retail=99900, brand='Other')
        brand = self.s.db.value("SELECT id FROM brands WHERE name = 'Fresh'")
        preview = self.s.do(catalog.bulk_price, {'brand_id': brand, 'percent': 10, 'round_to': 500})
        self.assertEqual(len(preview['items']), 1)
        self.assertEqual(preview['items'][0]['new']['retail'], 136000)  # 1,357.40 rounded up to the next 5 EGP
        self.assertEqual(catalog.current_prices(self.s.db, a)['retail'], 123400)  # preview changes nothing
        self.s.do(catalog.bulk_price, {'brand_id': brand, 'percent': 10, 'round_to': 500, 'starts_on': day(2)}, apply=True)
        self.assertEqual(catalog.current_prices(self.s.db, a)['retail'], 123400)
        self.assertEqual(catalog.current_prices(self.s.db, a, day(2))['retail'], 136000)
        with self.assertRaises(Problem) as e:
            self.s.do(catalog.set_price, a, 'retail', 1, day(-1))
        self.assertEqual(e.exception.key, 'err.pastPrice')

    def test_cashier_cannot_change_prices(self):
        pid = self.s.product()
        cashier = self.s.user('cashier', 'pc')
        with self.assertRaises(Forbidden):
            self.s.do(catalog.save_product, {'id': pid, 'retail': 1}, user=cashier)
        keeper = self.s.user('storekeeper', 'pk')
        with self.assertRaises(Forbidden):
            self.s.do(catalog.save_product, {'id': pid, 'retail': 1}, user=keeper)
        self.s.do(catalog.save_product, {'id': pid, 'name': 'Renamed'}, user=keeper)
        self.assertEqual(catalog.find(self.s.db, pid)['name'], 'Renamed')

    def test_barcode_and_search(self):
        pid = self.s.product('Blender Moulinex', barcodes=['6221234567890'])
        other = self.s.product('Kettle')
        with self.assertRaises(Problem):
            self.s.do(catalog.save_product, {'id': other, 'barcodes': ['6221234567890']})
        hit = catalog.search(self.s.db, '6221234567890')
        self.assertTrue(hit['exact'])
        self.assertEqual(hit['items'][0]['id'], pid)
        self.assertEqual(catalog.search(self.s.db, 'moul blen')['items'][0]['id'], pid)


class ReportTests(Base):
    def test_summary_profit_and_year_turnover(self):
        pid = self.s.product(retail=100000, cost=70000, qty=5)
        sale(self.s, [{'product_id': pid, 'qty': 2}])
        s = reports.summary(self.s.db, ids.local_day(), ids.local_day(), True)
        self.assertEqual(s['sales'], 200000)
        self.assertEqual(s['gross_profit'], 60000)
        self.assertEqual(reports.year_turnover(self.s.db)['turnover'], 200000)
        self.assertNotIn('gross_profit', reports.summary(self.s.db, ids.local_day(), ids.local_day(), False))


if __name__ == '__main__':
    unittest.main()
