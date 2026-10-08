"""Robustness: every write route must answer junk with a calm 4xx, never a crash (500).

For each POST route we send the same junk value in every common field, at top level and inside nested lists,
as the owner (so no permission check hides a later crash). Reads get junk query strings too.
"""
import unittest
from urllib.parse import quote

from harness import Server

JUNK = [None, '', 'abc', '<script>alert(1)</script>', "' OR 1=1 --", -1, 0, 1.5, 10 ** 30, True, [], {}, [1, 2], {'a': 1},
        '9999-99-99', '2020-01-01', 'x' * 1500, '\u0000', 'NaN']
KEYS = ['product_id', 'location_id', 'from_location_id', 'to_location_id', 'sale_id', 'sale_line_id', 'customer_id', 'supplier_id',
        'plan_id', 'shift_id', 'id', 'idem_key', 'qty', 'unit_price', 'unit_cost', 'amount', 'discount', 'months', 'down', 'first_due',
        'name', 'username', 'password', 'full_name', 'role', 'phone', 'retail', 'min', 'cost', 'serial', 'serials', 'barcodes', 'sku',
        'reason', 'note', 'method', 'provider', 'kind', 'day', 'from', 'to', 'q', 'pct', 'percent', 'opening', 'counted', 'expected',
        'refund_method', 'condition', 'cash_received', 'account', 'category', 'group', 'unit', 'warranty_months', 'credit_limit',
        'effective', 'price_kind', 'value', 'settings', 'active', 'fractional', 'track_serial', 'shelf', 'review', 'key']
NESTED = ['lines', 'payments', 'instalment', 'customer', 'delivery', 'guarantor', 'items', 'values', 'prices', 'products']
SKIP = {'/api/setup', '/api/backup/now', '/api/logout', '/api/password', '/api/backup/restore', '/api/licence/activate', '/api/login', '/api/user/save'}


def bodies(junk):
    flat = {k: junk for k in KEYS}
    yield flat
    nested = dict(flat)
    for n in NESTED:
        nested[n] = [dict(flat)]
    yield nested
    obj = dict(flat)
    for n in NESTED:
        obj[n] = dict(flat)
    yield obj
    yield junk


class FuzzTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Server()
        cls.c = cls.S.client()
        cls.c.login()
        db = cls.S.app.db
        shop = db.value("SELECT id FROM locations WHERE kind = 'shop'")
        st, d, _ = cls.c.post('/api/product/save', {'name': 'Fan', 'retail': 100000, 'min': 90000})
        cls.pid = d['id']
        cls.c.post('/api/purchase', {'idem_key': 'seed', 'location_id': shop, 'lines': [{'product_id': cls.pid, 'qty': 5, 'unit_cost': 70000}]})
        cls.c.post('/api/shift/open', {'opening': 100000})
        import re
        src = open(__import__('os').path.join(__import__('os').path.dirname(__file__), '..', 'server', 'app.py'), encoding='utf-8').read()
        cls.posts = sorted(set(re.findall(r"path == '(/api/[a-z/_-]+)'", src)) - SKIP)

    @classmethod
    def tearDownClass(cls):
        cls.S.stop()

    def test_no_route_crashes_on_junk_writes(self):
        crashes = []
        for path in self.posts:
            for junk in JUNK:
                for body in bodies(junk):
                    try:
                        st, d, _ = self.c.call('POST', path, body)
                    except OSError as e:  # the server hung up: only fine for a body that is too large
                        crashes.append((path, 'hung-up', str(junk)[:30], repr(e)))
                        break
                    if st >= 500:
                        crashes.append((path, st, str(junk)[:30], d.get('error') if isinstance(d, dict) else d))
                        break
                else:
                    continue
                break
        self.assertEqual(crashes, [], '\n'.join(map(str, crashes)))

    def test_approval_junk_is_refused_calmly(self):
        for junk in JUNK:
            for approval in (junk, {'username': junk, 'password': junk}, {'username': 'nobody', 'password': junk}):
                for path in ('/api/pos/sell', '/api/return'):
                    st, d, _ = self.c.call('POST', path, {'approval': approval, 'idem_key': 'k', 'lines': [], 'payments': []})
                    self.assertLess(st, 500, (path, str(approval)[:40], d))

    def test_no_route_crashes_on_junk_reads(self):
        crashes = []
        for path in self.posts:
            for junk in ('abc', "' OR 1=1", '-1', '99999999999999999999', '%00', '9999-99-99', 'x' * 3000, ''):
                qs = '&'.join(f'{k}={quote(junk)}' for k in ('id', 'q', 'from', 'to', 'day', 'limit', 'kind', 'serial', 'product_id', 'customer_id',
                                                       'location_id', 'sale_id', 'status', 'month', 'user_id', 'barcode'))
                st, d, _ = self.c.get(f'{path}?{qs}')
                if st >= 500:
                    crashes.append((path, st, junk[:20], d.get('error') if isinstance(d, dict) else d))
                    break
        self.assertEqual(crashes, [], '\n'.join(map(str, crashes)))


def paths(node, prefix=()):
    """Every place in a valid payload where a value can be swapped for junk."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield prefix + (k,)
            yield from paths(v, prefix + (k,))
    elif isinstance(node, list) and node:
        yield from paths(node[0], prefix + (0,))


def mutate(node, path, value):
    import copy
    out = copy.deepcopy(node)
    cur = out
    for step in path[:-1]:
        cur = cur[step]
    cur[path[-1]] = value
    return out


class MutationTests(unittest.TestCase):
    """Start from a payload the page really sends, change one field at a time to junk: the deep code paths run."""

    @classmethod
    def setUpClass(cls):
        cls.S = Server()
        cls.c = cls.S.client()
        cls.c.login()
        db = cls.S.app.db
        cls.shop = db.value("SELECT id FROM locations WHERE kind = 'shop'")
        cls.store = db.value("SELECT id FROM locations WHERE kind = 'warehouse'")
        _, d, _ = cls.c.post('/api/product/save', {'name': 'Fan', 'retail': 100000, 'min': 90000})
        cls.pid = d['id']
        _, d, _ = cls.c.post('/api/product/save', {'name': 'TV', 'retail': 900000, 'min': 800000, 'track_serial': True})
        cls.tv = d['id']
        _, d, _ = cls.c.post('/api/customer/save', {'name': 'Client', 'phone': '01000000000'})
        cls.cust = d['id']
        _, d, _ = cls.c.post('/api/supplier/save', {'name': 'Supplier'})
        cls.sup = d['id']
        for i in range(3):
            cls.c.post('/api/purchase', {'idem_key': f'seed{i}', 'location_id': cls.shop,
                                         'lines': [{'product_id': cls.pid, 'qty': 50, 'unit_cost': 70000}]})
        cls.c.post('/api/purchase', {'idem_key': 'seedtv', 'location_id': cls.shop, 'supplier_id': cls.sup,
                                     'lines': [{'product_id': cls.tv, 'qty': 3, 'unit_cost': 700000,
                                                'serials': ['TV1', 'TV2', 'TV3']}]})
        cls.c.post('/api/shift/open', {'opening_float': 100000})
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        cls.S.stop()

    def templates(self):
        P = self
        return {
            '/api/pos/quote': {'lines': [{'product_id': P.pid, 'qty': 1, 'unit_price': 100000}], 'discount': 0,
                               'instalment': {'months': 6, 'down': 20000}},
            '/api/pos/sell': {'idem_key': 'm', 'lines': [{'product_id': P.pid, 'qty': 1, 'unit_price': 100000}],
                              'payments': [{'method': 'cash', 'amount': 100000}], 'customer_id': P.cust, 'cash_received': 100000,
                              'delivery': {'address': 'Street 1', 'date': '2030-01-01'}, 'note': 'n'},
            '/api/pos/sell#plan': {'idem_key': 'p', 'lines': [{'product_id': P.pid, 'qty': 1, 'unit_price': 100000}],
                                   'payments': [{'method': 'cash', 'amount': 20000}, {'method': 'installment', 'amount': 80000}],
                                   'customer_id': P.cust, 'instalment': {'months': 4, 'first_due': '2030-01-01',
                                                                         'guarantor': {'name': 'G', 'phone': '010', 'national_id': '29001010101010'}}},
            '/api/purchase': {'idem_key': 'b', 'location_id': P.shop, 'supplier_id': P.sup, 'paid': 10000, 'invoice_no': 'A1',
                              'lines': [{'product_id': P.pid, 'qty': 2, 'unit_cost': 70000}]},
            '/api/transfer': {'idem_key': 't', 'from_id': P.shop, 'to_id': P.store, 'note': 'x',
                              'lines': [{'product_id': P.pid, 'qty': 1}]},
            '/api/product/save': {'name': 'Kettle', 'retail': 50000, 'min': 40000, 'barcodes': ['12345'], 'sku': 'K1',
                                  'warranty_months': 12, 'track_serial': False, 'reorder_level': 2, 'fractional': False, 'unit': 'piece',
                                  'brand': 'B', 'category': 'C', 'places': [{'location_id': P.shop, 'shelf': 'A'}]},
            '/api/customer/save': {'name': 'New', 'phone': '01111111111', 'credit_limit': 100000, 'national_id': '29001010101010'},
            '/api/supplier/save': {'name': 'Sup2', 'phone': '0100'},
            '/api/cash/expense': {'idem_key': 'e', 'source': 'drawer', 'amount': 1000, 'category': 'other', 'note': 'x'},
            '/api/cash/safe': {'idem_key': 's', 'kind': 'deposit', 'amount': 1000, 'note': 'x'},
            '/api/collect': {'idem_key': 'c', 'customer_id': P.cust, 'amount': 1000, 'method': 'cash'},
            '/api/supplier/pay': {'idem_key': 'sp', 'supplier_id': P.sup, 'amount': 1000, 'method': 'cash'},
            '/api/finance/settle': {'idem_key': 'f', 'provider': 'valU', 'amount': 1000, 'note': 'x'},
            '/api/prices/bulk': {'percent': 5, 'round_to': 100, 'apply': False},
            '/api/location/save': {'name': 'Shelf room', 'kind': 'warehouse', 'sellable': False},
            '/api/product/place': {'product_id': P.pid, 'location_id': P.shop, 'shelf': 'A1'},
            '/api/count/start': {'location_id': P.shop, 'note': 'x'},
            '/api/settings/save': {'settings': {'shop_name': 'S', 'return_days': 14}},
            '/api/watch/review': {'key': 'k', 'note': 'n'},
        }

    def test_user_routes_with_junk(self):
        _, staff, _ = self.c.post('/api/user/save', {'username': 'staff1', 'full_name': 'Staff', 'role': 'cashier', 'password': 'Strong Pass 9'})
        add = {'username': 'new', 'full_name': 'New', 'role': 'cashier', 'password': 'Strong Pass 9', 'max_discount_pct': 5,
               'extra_perms': ['pos.credit'], 'denied_perms': []}
        edit = {'id': staff['id'], 'full_name': 'Staff', 'role': 'cashier', 'max_discount_pct': 5, 'extra_perms': [], 'denied_perms': [],
                'active': True, 'password': 'Another Pass 7'}
        crashes = []
        for name, template in (('add', add), ('edit', edit)):
            for where in paths(template) if False else [(k,) for k in template]:
                for junk in JUNK:
                    body = mutate(template, where, junk)
                    if name == 'add' and where != ('username',):
                        self.__class__.n += 1
                        body['username'] = f'new{self.n}'
                    st, d, _ = self.c.call('POST', '/api/user/save', body)
                    if st >= 500:
                        crashes.append((name, where, str(junk)[:20], d.get('error') if isinstance(d, dict) else d))
        self.assertEqual(crashes, [], '\n'.join(map(str, crashes)))

    def test_one_junk_field_at_a_time(self):
        crashes = []
        for route, template in self.templates().items():
            path = route.split('#')[0]
            for where in paths(template):
                for junk in JUNK:
                    body = mutate(template, where, junk)
                    self.__class__.n += 1
                    if isinstance(body.get('idem_key'), str):
                        body['idem_key'] = f'{body["idem_key"]}-{self.n}'
                    try:
                        st, d, _ = self.c.call('POST', path, body)
                    except OSError as e:
                        crashes.append((route, where, str(junk)[:20], repr(e)))
                        continue
                    if st >= 500:
                        crashes.append((route, where, str(junk)[:20], d.get('error') if isinstance(d, dict) else d))
        self.assertEqual(crashes, [], '\n'.join(map(str, crashes)))

    def test_return_and_count_flow_with_junk(self):
        _, sale, _ = self.c.post('/api/pos/sell', {'idem_key': 'rs1', 'lines': [{'product_id': self.pid, 'qty': 3, 'unit_price': 100000}],
                                                   'payments': [{'method': 'cash', 'amount': 300000}]})
        _, view, _ = self.c.get(f'/api/sale?id={sale["id"]}')
        line = view['lines'][0]['id']
        template = {'idem_key': 'ret', 'sale_id': sale['id'], 'reason': 'changed mind', 'refund_method': 'cash',
                    'lines': [{'sale_line_id': line, 'qty': 1, 'condition': 'good', 'to_location_id': self.shop}]}
        crashes = []
        for where in paths(template):
            for junk in JUNK:
                body = mutate(template, where, junk)
                if isinstance(body.get('idem_key'), str):
                    self.__class__.n += 1
                    body['idem_key'] = f'ret-{self.n}'
                st, d, _ = self.c.call('POST', '/api/return', body)
                if st >= 500:
                    crashes.append((where, str(junk)[:20], d.get('error') if isinstance(d, dict) else d))
        self.assertEqual(crashes, [], '\n'.join(map(str, crashes)))


if __name__ == '__main__':
    unittest.main()
