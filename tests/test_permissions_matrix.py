"""Who may read what, over the real HTTP server (factory IAM-03 deny by default, IAM-11 the server sends no data of a page the person
cannot open; found by the independent review of 2026-10-09).

1. A person with no ticks at all reads nothing: every read route answers 403, except the short list of routes that are the person's
   own (who am I, own shift, own sales) and then they show nothing of the shop.
2. A static guard: every read route written in app.py asks for a permission or is on that short list, so a new route cannot forget it.
3. The three leaks the review found: a return by number, the warranty look-up (customer name and phone), and the export file
   (purchase cost and national IDs for a person who may not see them on screen).
4. The counter works with the counter permission alone (its category buttons too).
"""
import io
import os
import re
import unittest
import zipfile

from harness import PW, Server
import ids

# read routes that need no ticks: they are about the signed-in person themself, or are scoped to what they did
OWN = {'/api/me', '/api/home', '/api/lookups', '/api/sales', '/api/shift', '/api/shifts', '/api/licence', '/api/guide/state',
       '/api/consent/status', '/api/consent/prompt', '/api/telemetry/sent', '/api/boot',
       '/api/practice', '/api/training'}  # the last two: about the practice shop only; the real shop refuses /api/training itself


class Matrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Server()
        cls.owner = cls.S.client()
        cls.owner.login()
        db = cls.S.app.db
        for username, role, perms in (('nobody', 'custom', []), ('seller', 'custom', ['pos.sell']), ('cash', 'cashier', None),
                                      ('boss', 'manager', None), ('adm', 'custom', ['settings.edit'])):
            body = {'username': username, 'full_name': username.title(), 'role': role, 'password': PW}
            if perms is not None:
                body['perms'] = perms
            st, d, _ = cls.owner.post('/api/user/save', body)
            assert st == 200, d
        shop = db.value("SELECT id FROM locations WHERE kind = 'shop'")
        st, d, _ = cls.owner.post('/api/product/save', {'name': 'Fridge', 'category': 'Cold', 'retail': 3000000, 'min': 2500000, 'track_serial': True,
                                                         'warranty_months': 24})
        cls.fridge = d['id']
        st, d, _ = cls.owner.post('/api/product/save', {'name': 'Kettle', 'category': 'Small', 'retail': 115000, 'min': 100000})
        cls.kettle = d['id']
        for pid, serials in ((cls.fridge, ['FR0001', 'FR0002']), (cls.kettle, [])):
            st, d, _ = cls.owner.post('/api/purchase', {'idem_key': 'buy-' + pid, 'location_id': shop, 'lines': [
                {'product_id': pid, 'qty': len(serials) or 10, 'unit_cost': 2000000 if serials else 90000, 'serials': serials}]})
            assert st == 200, d
        st, d, _ = cls.owner.post('/api/customer/save', {'name': 'Sara Ali', 'phone': '01000000077', 'national_id': '29901011234567'})
        cls.customer = d['id']
        cls.owner.post('/api/shift/open', {'opening_float': 500000})
        st, d, _ = cls.owner.post('/api/pos/sell', {'idem_key': 'sale-1', 'customer_id': cls.customer, 'lines': [{'product_id': cls.fridge, 'qty': 1, 'serial': 'FR0001'}],
                                                      'payments': [{'method': 'cash', 'amount': 3000000}]})
        assert st == 200, d
        cls.sale = d['id']
        sale = cls.owner.get('/api/sale?id=' + cls.sale)[1]
        st, d, _ = cls.owner.post('/api/return', {'idem_key': 'ret-1', 'sale_id': cls.sale, 'reason': 'changed mind', 'refund_method': 'cash',
                                                   'lines': [{'sale_line_id': sale['lines'][0]['id'], 'qty': 1}]})
        assert st == 200, d
        cls.ret = d['id']

    @classmethod
    def tearDownClass(cls):
        cls.S.stop()

    def who(self, username):
        c = self.S.client()
        c.login(username, PW)
        return c

    def routes(self):
        return ['/api/products', f'/api/product?id={self.kettle}', '/api/pos/search?q=a', f'/api/serials?product_id={self.fridge}',
                f'/api/sale?id={self.sale}', f'/api/return?id={self.ret}', '/api/warranty?serial=FR0001', '/api/customers',
                f'/api/customer?id={self.customer}', '/api/instalments', '/api/suppliers', '/api/purchases', '/api/stock', '/api/stock/value',
                '/api/counts', '/api/transfers', '/api/safe', '/api/expenses', '/api/reports', '/api/watch', '/api/audit', '/api/users',
                '/api/settings', '/api/support', '/api/telemetry/config', '/api/export', f'/api/shift/view?id={self.owner.get("/api/shift")[1]["id"]}']

    def test_a_person_with_no_ticks_reads_nothing(self):
        c = self.who('nobody')
        for path in self.routes():
            st, d, _ = c.get(path)
            self.assertEqual(st, 403, f'{path} answered {st} to a person with no ticks: {str(d)[:120]}')
        self.assertEqual(c.get('/api/sales')[1], [], 'own sales only: none')
        home = c.get('/api/home')[1]
        self.assertFalse({'summary', 'due', 'week', 'sales_today'} & set(home), 'the home page shows nothing of the shop to a person with no ticks')
        denied = self.S.app.db.value("SELECT COUNT(*) FROM audit WHERE action = 'denied' AND entity = '/api/return'")
        self.assertGreater(denied, 0, 'every refusal is written in the log')

    def test_every_read_route_asks_for_a_permission_or_is_on_the_short_list(self):
        """A new route written without a permission check fails here, before it ships."""
        src = open(os.path.join(os.path.dirname(__file__), '..', 'server', 'app.py'), encoding='utf-8').read()
        body = src[src.index('    def api_get(self, path, qs):'):src.index('    def me(self, u):')]
        branches = re.split(r"\n        (?:if|elif) path == ", body)[1:]
        self.assertGreater(len(branches), 30)
        for b in branches:
            name = re.match(r"'(/api/[^']+)'", b).group(1)
            if name in OWN:
                continue
            guarded = 'ctx.need' in b or 'raise Forbidden' in b or 'ctx.can(' in b
            self.assertTrue(guarded, f'{name} reads data and asks for no permission: add ctx.need(...) (or put it on the short list OWN, with a reason)')

    def test_a_return_is_for_the_people_it_concerns(self):
        seller = self.who('seller')
        self.assertEqual(seller.get(f'/api/return?id={self.ret}')[0], 403, 'a return of someone else\'s sale')
        self.assertEqual(self.who('boss').get(f'/api/return?id={self.ret}')[0], 200, 'a manager (sales.return) sees every return')
        self.assertEqual(self.owner.get(f'/api/return?id={self.ret}')[0], 200)
        # the seller's own sale and the return taken for it (a manager types the password on the seller's screen)
        self.assertEqual(seller.post('/api/shift/open', {'opening_float': 100000})[0], 200)
        st, d, _ = seller.post('/api/pos/sell', {'idem_key': 'sale-own', 'lines': [{'product_id': self.kettle, 'qty': 1}], 'payments': [{'method': 'cash', 'amount': 115000}]})
        self.assertEqual(st, 200, d)
        line = seller.get('/api/sale?id=' + d['id'])[1]['lines'][0]['id']
        st, r, _ = seller.post('/api/return', {'idem_key': 'ret-own', 'sale_id': d['id'], 'reason': 'wrong colour', 'refund_method': 'cash',
                                               'lines': [{'sale_line_id': line, 'qty': 1}], 'approval': {'username': 'boss', 'password': PW}})
        self.assertEqual(st, 200, r)
        self.assertEqual(seller.get(f'/api/return?id={r["id"]}')[0], 200, 'the return of one\'s own sale')
        self.assertEqual(self.who('cash').get(f'/api/return?id={r["id"]}')[0], 403, 'another cashier\'s sale and return')

    def test_the_warranty_lookup_shows_the_customer_only_to_people_who_may_see_customers(self):
        self.assertEqual(self.who('nobody').get('/api/warranty?serial=FR0001')[0], 403)
        st, d, _ = self.who('seller').get('/api/warranty?serial=FR0001')
        self.assertEqual(st, 200)
        self.assertEqual((d['product'], d['sale_number'].startswith('S-'), d['customer'], d['phone'], d['customer_hidden']), ('Fridge', True, None, None, True))
        st, d, _ = self.who('cash').get('/api/warranty?serial=FR0001')
        self.assertEqual((d['customer'], d['phone'], d['customer_hidden']), ('Sara Ali', '01000000077', False))
        self.assertEqual(self.who('cash').get('/api/warranty?serial=NOPE')[0], 404)

    def test_the_export_leaves_out_what_the_person_may_not_see_on_screen(self):
        def files(client):
            st, body, _ = client.get('/api/export')
            self.assertEqual(st, 200)
            z = zipfile.ZipFile(io.BytesIO(body))
            return {n[:-4]: z.read(n).decode('utf-8-sig') for n in z.namelist()}
        full = files(self.owner)
        self.assertIn('29901011234567', full['customers'])
        self.assertRegex(full['costs'], r'\d{5,}')
        self.assertIn('cost_total', full['sales'].splitlines()[0])
        part = files(self.who('adm'))  # may export (settings.edit) but sees neither cost nor national IDs
        self.assertNotIn('29901011234567', part['customers'])
        self.assertEqual(part['customers'].splitlines()[0], full['customers'].splitlines()[0], 'the file keeps its shape: the column is there, empty')
        cost_rows = [line.split(',') for line in part['costs'].splitlines()[1:]]
        self.assertTrue(cost_rows)
        self.assertTrue(all(not cell or not cell.isdigit() or len(cell) < 2 for row in cost_rows for cell in row[2:4]), 'no cost amounts in costs.csv')
        header = part['sales'].splitlines()[0].split(',')
        first = [x for x in part['sales'].splitlines()[1].split(',')]
        self.assertEqual(first[header.index('cost_total')], '')
        self.assertNotIn('2000000', part['sale_lines'], 'no unit cost')
        self.assertNotIn('90000,', part['purchase_lines'].replace('"', ''), 'no unit cost in purchase lines')
        audit = [r for r in self.owner.get('/api/audit?limit=50')[1] if r['action'] == 'export'][0]
        self.assertIn('left_out', audit['detail'], 'the log says what was left out')

    def test_the_counter_works_with_the_counter_permission_alone(self):
        seller = self.who('seller')
        cat = self.owner.get('/api/lookups')[1]['categories']
        cold = next(c['id'] for c in cat if c['name'] == 'Cold')
        st, d, _ = seller.get(f'/api/pos/search?category_id={cold}&limit=24')
        self.assertEqual(st, 200)
        self.assertEqual([x['name'] for x in d['items']], ['Fridge'])
        self.assertEqual(seller.get('/api/products')[0], 403, 'the products page itself stays closed')
        st, d, _ = seller.get('/api/pos/search?limit=100000')
        self.assertEqual(st, 200)
        self.assertLessEqual(len(d['items']), 60)
        self.assertEqual(seller.get('/api/pos/search?limit=abc')[0], 200, 'a junk limit is not a crash')


class ExportUnit(unittest.TestCase):
    def test_hidden_columns_are_empty_not_missing(self):
        import backup
        from harness import Shop
        sh = Shop()
        try:
            sh.product('Fan', retail=100000, cost=70000, qty=3)
            plain = zipfile.ZipFile(io.BytesIO(backup.export_zip(sh.db, cost=False, private=False)))
            full = zipfile.ZipFile(io.BytesIO(backup.export_zip(sh.db)))
            for name in full.namelist():
                self.assertEqual(plain.read(name).decode('utf-8-sig').splitlines()[0], full.read(name).decode('utf-8-sig').splitlines()[0], name)
            self.assertIn('70000', full.read('costs.csv').decode('utf-8-sig'))
            self.assertNotIn('70000', plain.read('costs.csv').decode('utf-8-sig'))
            self.assertNotIn('70000', plain.read('stock_moves.csv').decode('utf-8-sig'))
        finally:
            sh.cleanup()

    def test_a_purchase_cost_does_not_leave_through_the_supplier_ledger_cash_or_audit(self):
        """Review of PR #14: blanking purchases.total was not enough, the same total sat in ap_entries, cash_moves and the audit line."""
        import backup
        import ids
        import money
        import stock
        from harness import Shop
        sh = Shop()
        try:
            sid = sh.do(money.save_supplier, {'name': 'Supplier'})
            pid = sh.product('Fan', qty=0)
            sh.do(money.open_shift, 500000)
            sh.do(stock.receive, {'idem_key': ids.uuid7(), 'location_id': sh.shop, 'supplier_id': sid, 'paid_now': 31313,
                                  'lines': [{'product_id': pid, 'qty': 3, 'unit_cost': 73131}]})
            sh.do(stock.receive, {'idem_key': ids.uuid7(), 'location_id': sh.shop, 'paid_now': 4 * 52127,  # no supplier: paid from the drawer
                                  'lines': [{'product_id': pid, 'qty': 4, 'unit_cost': 52127}]})
            total, cash_paid = '219393', '208508'
            full = zipfile.ZipFile(io.BytesIO(backup.export_zip(sh.db)))
            plain = zipfile.ZipFile(io.BytesIO(backup.export_zip(sh.db, cost=False)))
            self.assertIn(total, full.read('ap_entries.csv').decode('utf-8-sig'))
            self.assertIn(total, full.read('audit.csv').decode('utf-8-sig'))
            self.assertIn(cash_paid, full.read('cash_moves.csv').decode('utf-8-sig'))
            for name in plain.namelist():
                text = plain.read(name).decode('utf-8-sig')
                self.assertNotIn(total, text, name)
                self.assertNotIn('73131', text, name)
                self.assertNotIn(cash_paid, text, name)  # the whole cost of the second purchase, paid from the drawer
                self.assertNotIn('52127', text, name)
            self.assertIn('supplier.add', plain.read('audit.csv').decode('utf-8-sig'), 'other audit lines stay whole')
        finally:
            sh.cleanup()


if __name__ == '__main__':
    unittest.main()
