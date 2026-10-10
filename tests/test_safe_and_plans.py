"""Found by an independent review that drove random shop days against the books and checked them after every step:
the safe could go below zero (an expense, a supplier payment or a purchase paid from an empty safe; the undoing of a deposit or of a cash
collection that had been spent) and a payment tagged to an instalment plan could pay more than the plan owed. Both are refused now."""
import unittest

from harness import Shop, day
import ids
import money as cash
import sales
import stock
from core import Problem


class SafeNeverGoesBelowZero(unittest.TestCase):
    def setUp(self):
        self.s = Shop()
        self.s.all_pay()
        self.s.do(cash.open_shift, 10000)  # the float comes out of the safe: the owner adds the rest, so the safe starts at 0

    def tearDown(self):
        self.s.cleanup()

    def refused(self, fn, *args):
        with self.assertRaises(Problem) as e:
            self.s.do(fn, *args)
        self.assertEqual(e.exception.key, 'err.safeShort')
        self.assertGreaterEqual(cash.safe_balance(self.s.db), 0)

    def test_the_safe_starts_empty_and_an_expense_from_it_is_refused(self):
        self.assertEqual(cash.safe_balance(self.s.db), 0)
        self.refused(cash.expense, {'idem_key': 'e1', 'source': 'safe', 'amount': 5000, 'category': 'other', 'note': 'tea and sugar'})
        self.s.do(cash.safe_move, {'kind': 'deposit', 'amount': 5000, 'note': 'owner adds'})
        self.s.do(cash.expense, {'idem_key': 'e2', 'source': 'safe', 'amount': 5000, 'category': 'other', 'note': 'tea and sugar'})
        self.assertEqual(cash.safe_balance(self.s.db), 0)

    def test_paying_a_supplier_or_a_purchase_from_an_empty_safe_is_refused(self):
        sup = self.s.do(cash.save_supplier, {'name': 'Supplier'})
        pid = self.s.product(qty=0)
        self.s.do(stock.receive, {'idem_key': 'p1', 'location_id': self.s.store, 'supplier_id': sup, 'lines': [{'product_id': pid, 'qty': 5, 'unit_cost': 10000}]})
        self.refused(cash.pay_supplier, {'idem_key': 'sp', 'supplier_id': sup, 'amount': 10000, 'source': 'safe'})
        self.assertEqual(cash.supplier_balance(self.s.db, sup), 50000, 'nothing was recorded as paid')
        self.refused(stock.receive, {'idem_key': 'p2', 'location_id': self.s.store, 'supplier_id': sup, 'paid_now': 10000, 'pay_from': 'safe',
                                     'lines': [{'product_id': pid, 'qty': 1, 'unit_cost': 10000}]})
        self.assertEqual(stock.on_hand(self.s.db, pid, self.s.store), 5, 'and the goods of the refused purchase did not arrive')
        # the drawer is a way too, and the refusal names the way out in plain words
        self.s.do(cash.safe_move, {'kind': 'deposit', 'amount': 10000})
        self.s.do(cash.pay_supplier, {'idem_key': 'sp2', 'supplier_id': sup, 'amount': 10000, 'source': 'safe'})

    def test_undoing_a_deposit_that_was_spent_is_refused_until_the_money_is_back(self):
        d = self.s.do(cash.safe_move, {'kind': 'deposit', 'amount': 1000, 'note': 'in'})
        self.s.do(cash.safe_move, {'kind': 'withdraw', 'amount': 1000, 'note': 'out'})
        self.refused(cash.reverse_cash, d['id'], 'typed by mistake')
        self.s.do(cash.safe_move, {'kind': 'deposit', 'amount': 1000, 'note': 'back'})
        self.s.do(cash.reverse_cash, d['id'], 'typed by mistake')
        self.assertEqual(cash.safe_balance(self.s.db), 0)

    def test_the_automatic_deposit_of_an_opening_float_is_not_a_loophole(self):
        s = self.s
        owner = s.users['owner']
        s.do(cash.close_shift, cash.open_shift_of(s.db, owner['id'])['id'], 10000, '')
        self.assertEqual(cash.safe_balance(s.db), 10000)
        s.do(cash.safe_move, {'kind': 'withdraw', 'amount': 10000, 'note': 'owner takes it'})
        auto = s.db.one("SELECT id FROM cash_moves WHERE account = 'safe' AND kind = 'deposit' ORDER BY at LIMIT 1")  # added when the float was short
        self.refused(cash.reverse_cash, auto['id'], 'not needed')

    def test_undoing_a_cash_collection_taken_in_a_closed_shift_needs_the_money_in_the_safe(self):
        s = self.s
        owner = s.users['owner']
        cust = s.do(cash.save_customer, {'name': 'Customer', 'phone': '01000000000'})
        pid = s.product(qty=3)
        s.do(sales.sell, {'idem_key': 'a1', 'lines': [{'product_id': pid, 'qty': 1}], 'customer_id': cust,
                          'payments': [{'method': 'account', 'amount': 100000}]})
        got = s.do(cash.collect, {'idem_key': 'c1', 'customer_id': cust, 'amount': 60000})
        shift = cash.open_shift_of(s.db, owner['id'])
        s.do(cash.close_shift, shift['id'], cash.drawer_expected(s.db, shift['id']), '')
        s.do(cash.safe_move, {'kind': 'withdraw', 'amount': cash.safe_balance(s.db), 'note': 'owner takes it all'})
        self.assertEqual(cash.safe_balance(s.db), 0)
        self.refused(cash.reverse_collection, got['id'], 'typed twice')
        self.assertEqual(cash.customer_balance(s.db, cust), 40000, 'the debt was not given back by a refused undo')
        s.do(cash.safe_move, {'kind': 'deposit', 'amount': 60000, 'note': 'back'})
        s.do(cash.reverse_collection, got['id'], 'typed twice')
        self.assertEqual(cash.customer_balance(s.db, cust), 100000)
        self.assertEqual(cash.safe_balance(s.db), 0)


class PlanPaymentsCannotExceedThePlan(unittest.TestCase):
    def setUp(self):
        self.s = Shop()
        self.s.all_pay()
        self.s.do(cash.open_shift, 10000)
        self.cust = self.s.do(cash.save_customer, {'name': 'Customer', 'phone': '01000000000'})
        tv = self.s.product('TV', 1000000, 800000, qty=3)
        r = self.s.do(sales.sell, {'idem_key': 'plan1', 'lines': [{'product_id': tv, 'qty': 1}], 'customer_id': self.cust,
                                   'payments': [{'method': 'cash', 'amount': 200000}, {'method': 'installment', 'amount': 800000}],
                                   'instalment': {'months': 2, 'first_due': day(30), 'guarantor': {'name': 'G'}}})
        self.plan = self.s.db.one('SELECT * FROM plans WHERE id = ?', r['plan_id'])
        fan = self.s.product('Fan', 100000, 80000, qty=3)  # the same customer also owes on an open account
        self.s.do(sales.sell, {'idem_key': 'acc1', 'lines': [{'product_id': fan, 'qty': 1}], 'customer_id': self.cust,
                               'payments': [{'method': 'account', 'amount': 100000}]})

    def tearDown(self):
        self.s.cleanup()

    def test_a_payment_tagged_to_a_plan_is_limited_to_what_the_plan_still_owes(self):
        self.assertEqual(cash.customer_balance(self.s.db, self.cust), 900000)
        with self.assertRaises(Problem) as e:
            self.s.do(cash.collect, {'idem_key': 'k0', 'customer_id': self.cust, 'amount': 800100, 'plan_id': self.plan['id']})
        self.assertEqual((e.exception.key, e.exception.vars['left']), ('err.payMoreThanPlan', 800000))
        self.s.do(cash.collect, {'idem_key': 'k1', 'customer_id': self.cust, 'amount': 800000, 'plan_id': self.plan['id']})
        sch = cash.plan_schedule(self.s.db, self.plan)
        self.assertEqual((sch['remaining'], sch['paid']), (0, 800000))
        with self.assertRaises(Problem) as e:   # the plan is paid off, but the customer still owes 1,000 on the account
            self.s.do(cash.collect, {'idem_key': 'k2', 'customer_id': self.cust, 'amount': 20000, 'plan_id': self.plan['id']})
        self.assertEqual((e.exception.key, e.exception.vars['left']), ('err.payMoreThanPlan', 0))
        self.s.do(cash.collect, {'idem_key': 'k3', 'customer_id': self.cust, 'amount': 100000})  # the account is paid without the plan
        self.assertEqual(cash.customer_balance(self.s.db, self.cust), 0)

    def test_a_reversed_collection_gives_the_room_on_the_plan_back(self):
        got = self.s.do(cash.collect, {'idem_key': 'k1', 'customer_id': self.cust, 'amount': 800000, 'plan_id': self.plan['id']})
        self.s.do(cash.reverse_collection, got['id'], 'typed twice')
        self.assertEqual(cash.plan_schedule(self.s.db, self.plan)['remaining'], 800000)
        self.s.do(cash.collect, {'idem_key': 'k2', 'customer_id': self.cust, 'amount': 800000, 'plan_id': self.plan['id']})

    def test_a_retry_with_the_same_key_is_still_the_same_payment(self):
        a = self.s.do(cash.collect, {'idem_key': 'k1', 'customer_id': self.cust, 'amount': 800000, 'plan_id': self.plan['id']})
        b = self.s.do(cash.collect, {'idem_key': 'k1', 'customer_id': self.cust, 'amount': 800000, 'plan_id': self.plan['id']})
        self.assertEqual(a['id'], b['id'])


if __name__ == '__main__':
    unittest.main()
