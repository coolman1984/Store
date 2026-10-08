"""Shared pieces of the shop logic: the request context, keyed problems, numbers, settings, audit, money parsing."""
import json

import ids
from auth import Forbidden, PERMISSIONS

DEFAULT_SETTINGS = {
    'shop_name': 'الستور',
    'shop_phone': '',
    'shop_address': '',
    'tax_number': '',
    'receipt_footer': 'شكرًا لزيارتكم',
    'receipt_width': '80',            # 80 | 58 mm
    'return_days': 14,                # consumer protection law 181/2018 art. 17: return without a reason
    'defect_days': 30,                # art. 21: return or exchange of a defective product
    'tax_rate_pct': 0,                # shown on the receipt only when > 0
    'wallet_number': '',              # InstaPay / wallet number printed on the receipt
    'min_down_payment_pct': 20,       # shop instalments
    'instalment_markup_pct': 0,       # added once per month of the plan, on the financed part
    'max_instalment_months': 24,
    'finance_providers': ['valU', 'Aman', 'Contact', 'Souhoola', 'Sympl'],
    'expense_categories': ['rent', 'electricity', 'salaries', 'transport', 'maintenance', 'hospitality', 'other'],
    'large_expense': 100000,          # 1,000 EGP in piasters: shown in the owner's eye
    'opening_hour': 9,
    'closing_hour': 23,
    'onboarded': False,
}
NUMBER_PREFIX = {'sale': 'S', 'purchase': 'P', 'return': 'R', 'transfer': 'T', 'count': 'C', 'shift': 'SH', 'plan': 'I',
                 'collection': 'K', 'expense': 'E'}


class Problem(ValueError):
    """A rule the person broke. `key` is a dictionary key in the page; `text` is the English fallback."""

    def __init__(self, key, text, status=400, **vars):
        super().__init__(text)
        self.key, self.vars, self.status = key, vars, status


class NotFound(Problem):
    def __init__(self, what='record'):
        super().__init__('err.notFound', f'The {what} was not found.', 404, what=what)


class Ctx:
    """Who is acting, from where, with which rights. Every service function takes one."""

    def __init__(self, db, user, perms, ip, org_id, branch_id):
        self.db, self.user, self.perms, self.ip = db, user, set(perms), ip
        self.org_id, self.branch_id = org_id, branch_id
        self.approver = None  # a manager whose password was checked *before* the transaction (so wrong tries are counted)

    @property
    def uid(self):
        return self.user['id']

    @property
    def name(self):
        return self.user['full_name']

    def can(self, perm):
        return perm in self.perms

    def need(self, *perms):
        for p in perms:
            if p not in self.perms:
                raise Forbidden(p)

    def audit(self, action, entity='', entity_id='', detail=None):
        self.db.insert('audit', {'id': ids.uuid7(), 'at': ids.iso(), 'user_id': self.uid, 'user_name': self.name,
                                 'ip': self.ip, 'action': action, 'entity': entity, 'entity_id': entity_id or '',
                                 'detail': json.dumps(detail, ensure_ascii=False) if detail is not None else ''})

    def number(self, kind):
        """Readable document numbers per shop (S-000123). Must run inside the write transaction."""
        nxt = self.db.value('SELECT next FROM counters WHERE kind = ?', kind) or 1
        self.db.run('INSERT INTO counters(kind, next) VALUES (?, ?) ON CONFLICT(kind) DO UPDATE SET next = excluded.next',
                    kind, nxt + 1)
        return f'{NUMBER_PREFIX[kind]}-{nxt:06d}'


def settings(db):
    out = dict(DEFAULT_SETTINGS)
    for row in db.all('SELECT key, value FROM settings'):
        out[row['key']] = json.loads(row['value'])
    return out


def set_setting(db, key, value):
    if key not in DEFAULT_SETTINGS:
        raise Problem('err.unknownSetting', 'Unknown setting.')
    db.run('INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
           key, json.dumps(value, ensure_ascii=False))


def money(value, field='amount', allow_negative=False):
    """Piasters from the page. The page always sends integers in piasters; anything else is refused."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise Problem('err.money', f'{field}: send whole piasters.', field=field)
    if value < 0 and not allow_negative:
        raise Problem('err.negative', f'{field} cannot be negative.', field=field)
    if abs(value) > 10_000_000_000:  # 100 million EGP: a typing mistake, not a sale
        raise Problem('err.tooBig', f'{field} is too big.', field=field)
    return value


def quantity(value, fractional=False, field='qty'):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Problem('err.qty', 'Quantity must be a number.', field=field)
    value = round(float(value), 3)
    if value <= 0 or value > 1_000_000:
        raise Problem('err.qty', 'Quantity must be more than zero.', field=field)
    if not fractional and value != int(value):
        raise Problem('err.qtyWhole', 'This product is sold in whole units.', field=field)
    return value


def text(value, field, max_len=200, required=False):
    value = '' if value is None else str(value).strip()
    if required and not value:
        raise Problem('err.required', f'{field} is required.', field=field)
    return value[:max_len]


def perm_list():
    return [{'id': k, 'group': g, 'label': label} for k, (g, label) in PERMISSIONS.items()]
