"""The practice shop: a realistic, entirely made-up appliance shop with three weeks of history.

Runs only in practice mode (its own folder, port and banner; receipts say PRACTICE). Prices are invented for training and
are not market prices. The accounts below are demo-only and exist in no real shop (factory AGENTS rule: tagged DEMO,
synthetic data, never in a production build).
"""
import random
from datetime import date, timedelta

import auth as auth_mod
import catalog
import core
import ids
import money as cash
import reports  # noqa: F401  (keeps import order identical to the server)
import sales
import stock
from core import Ctx

DEMO_PASSWORD = 'practice-1234'
DEMO_USERS = [('owner', 'صاحب المحل (تدريب)', 'owner'), ('manager', 'المدير (تدريب)', 'manager'),
              ('cashier', 'الكاشير (تدريب)', 'cashier'), ('store', 'أمين المخزن (تدريب)', 'storekeeper')]

# name, category, brand, model, unit, serial, warranty months, retail EGP, cost EGP, reorder, shelf
PRODUCTS = [
    ('ثلاجة نوفروست 16 قدم', 'ثلاجات', 'Sharp', 'SJ-GV58', 'piece', 1, 24, 32500, 28900, 2, 'A-1'),
    ('ثلاجة ديفروست 14 قدم', 'ثلاجات', 'Kiriazi', 'E 380', 'piece', 1, 24, 21900, 19300, 2, 'A-1'),
    ('ديب فريزر 7 أدراج', 'ثلاجات', 'Fresh', 'FNF-7D', 'piece', 1, 24, 19800, 17600, 1, 'A-2'),
    ('غسالة أوتوماتيك 8 كيلو', 'غسالات', 'Zanussi', 'ZWF8240', 'piece', 1, 24, 23900, 21000, 2, 'B-1'),
    ('غسالة أوتوماتيك 7 كيلو', 'غسالات', 'Fresh', 'FWT-7', 'piece', 1, 24, 17400, 15300, 2, 'B-1'),
    ('غسالة نصف أوتوماتيك 10 كيلو', 'غسالات', 'Tornado', 'TWH-Z10', 'piece', 1, 12, 9800, 8450, 2, 'B-2'),
    ('بوتاجاز 5 شعلة 90 سم', 'بوتاجازات', 'Fresh', 'Plaza 90', 'piece', 1, 24, 16800, 14700, 2, 'C-1'),
    ('بوتاجاز 4 شعلة 60 سم', 'بوتاجازات', 'Unionaire', 'C6060', 'piece', 1, 24, 10900, 9500, 2, 'C-1'),
    ('تكييف 1.5 حصان بارد ساخن', 'تكييفات', 'Sharp', 'AY-X12', 'piece', 1, 36, 31900, 28400, 1, 'D-1'),
    ('تكييف 2.25 حصان بارد', 'تكييفات', 'Carrier', 'Optimax 18', 'piece', 1, 36, 41500, 37200, 1, 'D-1'),
    ('شاشة 43 بوصة سمارت', 'شاشات', 'Toshiba', '43V35', 'piece', 1, 24, 13900, 12100, 2, 'E-1'),
    ('شاشة 55 بوصة 4K', 'شاشات', 'Samsung', 'UA55', 'piece', 1, 24, 27900, 24800, 1, 'E-1'),
    ('سخان غاز 10 لتر', 'سخانات', 'Olympic', 'OEG-10', 'piece', 1, 12, 5200, 4450, 3, 'F-1'),
    ('سخان كهرباء 50 لتر', 'سخانات', 'Tornado', 'EWH-50', 'piece', 1, 24, 6400, 5550, 3, 'F-1'),
    ('مروحة ستاند 18 بوصة', 'أجهزة صغيرة', 'Fresh', 'Jumbo 18', 'piece', 0, 12, 1650, 1350, 5, 'G-1'),
    ('خلاط 1.5 لتر', 'أجهزة صغيرة', 'Moulinex', 'LM2', 'piece', 0, 12, 2350, 1950, 4, 'G-2'),
    ('مكواة بخار', 'أجهزة صغيرة', 'Philips', 'GC1740', 'piece', 0, 24, 1490, 1220, 4, 'G-2'),
    ('كبة لحمة', 'أجهزة صغيرة', 'Kenwood', 'MG510', 'piece', 0, 12, 4300, 3700, 2, 'G-3'),
    ('غلاية مياه 1.7 لتر', 'أجهزة صغيرة', 'Tefal', 'KO33', 'piece', 0, 12, 1150, 920, 6, 'G-3'),
    ('مكنسة كهربائية 2000 وات', 'أجهزة صغيرة', 'Black+Decker', 'VM2040', 'piece', 1, 24, 4950, 4200, 2, 'G-4'),
    ('ميكروويف 25 لتر', 'أجهزة صغيرة', 'Fresh', 'FMW-25', 'piece', 1, 12, 4700, 4000, 2, 'G-4'),
    ('طقم حلل جرانيت 10 قطع', 'أدوات مطبخ', 'Tefal', 'Granite 10', 'set', 0, 0, 3850, 3100, 3, 'H-1'),
    ('طقم حلل استانلس 7 قطع', 'أدوات مطبخ', 'Zahran', 'ST-7', 'set', 0, 0, 2950, 2380, 3, 'H-1'),
    ('طاسة تيفال 28 سم', 'أدوات مطبخ', 'Tefal', 'Day by Day 28', 'piece', 0, 0, 690, 520, 8, 'H-2'),
    ('طقم سكاكين 6 قطع', 'أدوات مطبخ', 'Zahran', 'K6', 'set', 0, 0, 450, 330, 6, 'H-2'),
    ('طقم صيني 72 قطعة', 'أطقم وصيني', 'Royal', 'Classic 72', 'set', 0, 0, 3600, 2850, 2, 'H-3'),
    ('طقم كوبايات 6 قطع', 'أطقم وصيني', 'Pasabahce', 'Bistro', 'set', 0, 0, 260, 185, 10, 'H-3'),
    ('سلة غسيل بلاستيك', 'بلاستيك', 'El Helal', 'L-40', 'piece', 0, 0, 95, 62, 15, 'J-1'),
    ('علبة حفظ طعام 3 قطع', 'بلاستيك', 'Lock&Lock', 'Set3', 'set', 0, 0, 240, 170, 12, 'J-1'),
    ('مشترك كهرباء 4 مخارج', 'كهرباء', 'Sonai', 'S4', 'piece', 0, 6, 135, 92, 20, 'K-1'),
    ('لمبة ليد 12 وات', 'كهرباء', 'Philips', 'LED12', 'piece', 0, 12, 65, 44, 50, 'K-2'),
    ('سلك كهرباء 2 مم', 'كهرباء', 'El Sewedy', '2mm', 'meter', 0, 0, 18, 13, 100, 'K-3'),
]
SUPPLIERS = [('شركة النور للتوزيع (تدريب)', '01000000001'), ('مؤسسة الأمل للأدوات المنزلية (تدريب)', '01000000002'),
             ('وكيل الأجهزة الكبرى (تدريب)', '01000000003')]
CUSTOMERS = [('أم أحمد (تدريب)', '01100000001'), ('محمود عبد الله (تدريب)', '01100000002'), ('سارة علي (تدريب)', '01100000003'),
             ('كريم حسن (تدريب)', '01100000004'), ('عم سيد الكهربائي (تدريب)', '01100000005')]


class _Clock:
    """Moves the program's clock back while the history is generated, then restores it."""

    def __init__(self):
        self.real = ids.utcnow
        self.now = None

    def set(self, moment):
        self.now = moment
        ids.utcnow = lambda: self.now

    def restore(self):
        ids.utcnow = self.real


def load(app, days=21, seed=7):
    rnd = random.Random(seed)
    clock = _Clock()
    real_now = ids.utcnow()
    start = (real_now - timedelta(days=days)).astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    clock.set(start)
    db = app.db
    try:
        with db.tx():
            users = {}
            for username, name, role in DEMO_USERS:
                users[role] = app.auth.create(username, name, role, DEMO_PASSWORD)
            owner = users['owner']
            ctx = Ctx(db, owner, auth_mod.effective_perms(owner), '127.0.0.1', app.org_id, app.branch_id)
            core.set_setting(db, 'shop_name', 'الستور – محل تدريب')
            core.set_setting(db, 'shop_address', 'شارع التدريب، بني سويف')
            core.set_setting(db, 'instalment_markup_pct', 2)
            shop = stock.save_location(ctx, {'name': 'المعرض', 'kind': 'shop'})
            store = stock.save_location(ctx, {'name': 'المخزن', 'kind': 'warehouse'})
            stock.save_location(ctx, {'name': 'تالف وصيانة', 'kind': 'damaged'})
            sup_ids = [cash.save_supplier(ctx, {'name': n, 'phone': p}) for n, p in SUPPLIERS]
            cust_ids = [cash.save_customer(ctx, {'name': n, 'phone': p, 'address': 'بني سويف'}) for n, p in CUSTOMERS]
            products = []
            for i, (name, cat, brand, model, unit, serial, warranty, retail, cost, reorder, shelf) in enumerate(PRODUCTS):
                pid = catalog.save_product(ctx, {'name': name, 'category': cat, 'brand': brand, 'model': model, 'unit': unit,
                                                 'fractional': unit == 'meter', 'track_serial': bool(serial),
                                                 'warranty_months': warranty, 'reorder_level': reorder, 'retail': retail * 100,
                                                 'trade': round(retail * 0.95) * 100 if not serial else None,
                                                 'min': round(retail * 0.94) * 100, 'barcodes': [f'622{100000000 + i * 7919:09d}'],
                                                 'sample': True})
                catalog.set_place(ctx, pid, shop, shelf)
                catalog.set_place(ctx, pid, store, 'M-' + shelf.split('-')[0])
                products.append({'id': pid, 'name': name, 'serial': serial, 'cost': cost * 100, 'unit': unit, 'retail': retail * 100,
                                 'prefix': (model.replace(' ', '').replace('-', '')[:5].upper() or 'SN')})
            serial_no = 1000
            for p in products:
                for place, qty in ((store, 6 if p['serial'] else 30), (shop, 3 if p['serial'] else 18)):
                    if p['unit'] == 'meter':
                        qty *= 10
                    serials = []
                    if p['serial']:
                        for _ in range(qty):
                            serial_no += 1
                            serials.append(f'{p["prefix"]}{serial_no}')
                    stock.receive(ctx, {'idem_key': ids.uuid7(), 'location_id': place, 'supplier_id': rnd.choice(sup_ids),
                                        'lines': [{'product_id': p['id'], 'qty': qty, 'unit_cost': p['cost'], 'serials': serials}],
                                        'paid_now': 0})
                    clock.set(clock.now + timedelta(seconds=40))
        for d in range(days - 14, days + 1):
            day_start = (start + timedelta(days=d)).replace(hour=10, minute=5)
            if day_start > real_now:
                break
            clock.set(day_start)
            cashier = users['cashier'] if d % 3 else users['manager']
            cctx = Ctx(db, cashier, auth_mod.effective_perms(cashier), '192.168.1.20', app.org_id, app.branch_id)
            with db.tx():
                cash.open_shift(cctx, 50000)
            with db.tx():  # the storekeeper refills the shop from the store each morning
                sctx = Ctx(db, users['storekeeper'], auth_mod.effective_perms(users['storekeeper']), '192.168.1.22', app.org_id,
                           app.branch_id)
                refill = []
                for p in products:
                    if p['serial']:
                        here = len(stock.serials_in_stock(db, p['id'], shop))
                        if here < 2:
                            back = [x['serial'] for x in stock.serials_in_stock(db, p['id'], store)][:2]
                            if back:
                                refill.append({'product_id': p['id'], 'qty': len(back), 'serials': back})
                    else:
                        here = stock.on_hand(db, p['id'], shop)
                        need = (100 if p['unit'] == 'meter' else 10)
                        if here < need / 2 and stock.on_hand(db, p['id'], store) >= need:
                            refill.append({'product_id': p['id'], 'qty': need})
                if refill:
                    stock.transfer(sctx, {'idem_key': ids.uuid7(), 'from_id': store, 'to_id': shop, 'lines': refill})
            for n in range(rnd.randint(4, 9)):
                clock.set(clock.now + timedelta(minutes=rnd.randint(20, 70)))
                if clock.now > real_now:
                    break
                lines = []
                for p in rnd.sample(products, rnd.randint(1, 3)):
                    if p['serial']:
                        left = stock.serials_in_stock(db, p['id'], shop)
                        if not left:
                            continue
                        lines.append({'product_id': p['id'], 'qty': 1, 'serial': left[0]['serial']})
                    else:
                        lines.append({'product_id': p['id'], 'qty': (rnd.randint(2, 12) * 5) if p['unit'] == 'meter' else rnd.randint(1, 3)})
                if not lines:
                    continue
                q = sales.quote(cctx, {'lines': lines})
                total = q['subtotal']
                discount = (total * 3 // 100 // 100) * 100 if rnd.random() < 0.3 else 0
                big = total - discount > 1500000
                kind = rnd.random()
                with db.tx():
                    if big and kind < 0.4:
                        months = rnd.choice([6, 10, 12])
                        down = ((total - discount) * 30 // 100 // 100) * 100
                        q2 = sales.quote(cctx, {'lines': lines, 'discount': discount, 'instalment': {'months': months, 'down': down}})
                        sales.sell(cctx, {'idem_key': ids.uuid7(), 'lines': lines, 'discount': discount,
                                          'customer_id': rnd.choice(cust_ids[:4]),
                                          'payments': [{'method': 'cash', 'amount': down},
                                                       {'method': 'installment', 'amount': q2['total'] - down}],
                                          'instalment': {'months': months, 'first_due': (date.fromisoformat(ids.local_day()) + timedelta(days=7)).isoformat(),
                                                         'guarantor': {'name': 'ضامن (تدريب)', 'phone': '01200000000'}}})
                    elif big and kind < 0.6:
                        sales.sell(cctx, {'idem_key': ids.uuid7(), 'lines': lines, 'discount': discount,
                                          'payments': [{'method': 'finance', 'provider': 'valU', 'amount': total - discount}]})
                    elif kind < 0.7:
                        sales.sell(cctx, {'idem_key': ids.uuid7(), 'lines': lines, 'discount': discount,
                                          'payments': [{'method': 'instapay', 'amount': total - discount}]})
                    elif kind < 0.78:
                        sales.sell(cctx, {'idem_key': ids.uuid7(), 'lines': lines, 'discount': discount, 'customer_id': cust_ids[4],
                                          'payments': [{'method': 'account', 'amount': total - discount}]})
                    else:
                        sales.sell(cctx, {'idem_key': ids.uuid7(), 'lines': lines, 'discount': discount,
                                          'payments': [{'method': 'cash', 'amount': total - discount}]})
            clock.set(clock.now + timedelta(minutes=30))
            if clock.now > real_now:
                clock.set(real_now - timedelta(minutes=1))
            if d == days:  # today's shift stays open, so the practice starts with a working counter
                break
            with db.tx():
                if d % 5 == 0:
                    cash.expense(cctx, {'idem_key': ids.uuid7(), 'category': 'hospitality', 'amount': 15000, 'note': 'شاي وقهوة'})
                shift = cash.open_shift_of(db, cashier['id'])
                expected = cash.drawer_expected(db, shift['id'])
                short = 5000 if d == days - 3 else 0
                cash.close_shift(cctx, shift['id'], expected - short, 'عجز في الفكة' if short else '')
        clock.set(real_now - timedelta(minutes=2))
        with db.tx():
            mctx = Ctx(db, users['manager'], auth_mod.effective_perms(users['manager']), '192.168.1.21', app.org_id, app.branch_id)
            any_sale = db.one("SELECT s.id FROM sales s JOIN tenders t ON t.ref_id = s.id AND t.method = 'cash' "
                              "JOIN sale_lines l ON l.sale_id = s.id WHERE l.unit_price <= 20000 ORDER BY s.at DESC LIMIT 1")
            if any_sale and cash.open_shift_of(db, users['manager']['id']) is None:
                cash.open_shift(mctx, 20000)
            if any_sale:
                sale = sales.sale_view(db, any_sale['id'], True)
                line = min(sale['lines'], key=lambda x: x['unit_price'])
                try:
                    sales.take_return(mctx, {'idem_key': ids.uuid7(), 'sale_id': sale['id'], 'reason': 'الزبون غيّر رأيه',
                                             'refund_method': 'cash',
                                             'lines': [{'sale_line_id': line['id'], 'qty': 1, 'condition': 'good'}]})
                except core.Problem:
                    pass
            brand = db.value("SELECT id FROM brands WHERE name = 'Fresh'")
            catalog.bulk_price(ctx_for(app, users['owner']), {'brand_id': brand, 'percent': 7, 'round_to': 500,
                                                               'starts_on': ids.local_day(), 'reason': 'زيادة أسعار الشركة'}, True)
        app.backup_now('practice')
    finally:
        clock.restore()


def ctx_for(app, user):
    return Ctx(app.db, user, auth_mod.effective_perms(user), '127.0.0.1', app.org_id, app.branch_id)
