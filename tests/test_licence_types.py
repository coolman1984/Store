"""The three kinds of licence code (14-day trial, monthly subscription, permanent) from the shop's side, and what never changes whatever the code says:
the shop's data stays readable, exportable and backed up, and a backup can always be put back.

Part 1 pins the wire format with codes signed by the factory's own module (Apps-Factory packages/af-license) with a fixed test key: if the vendored
verifier ever stops reading them, every licence already sold stops working. Part 2 drives a whole shop through renewal, expiry, a changed PC and a moved clock."""
import json
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402,F401  (sets the test environment)
from harness import HAVE_CRYPTO, OWNER, Server, code_for  # noqa: E402

import afcodes  # noqa: E402
import ids  # noqa: E402
import licence  # noqa: E402

# made once with Apps-Factory packages/af-license (issue_code), seed = bytes(range(32)), all starting 2026-01-01; never regenerate to make a test pass
KEY = 'A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg'
DEVICE = 'BJRW0-N1973'
TRIAL = ('0716ZV-HZ041D-P0PV0B-M0085W-BEWDS8-NZ6FT6-00AP8W-6GBSGK-P35QD9-AE1SAT-F0NDP5-A79M1N-T1CYCH-H33YME-Z396Q5-47TQ1N-DDDM81-TFQ9P9-Z06956-TTBK9X-'
         'SZRG80-6MEWYX-SV71X0-6CB685')
MONTHLY = ('0716ZV-HZ081D-P0PV0B-W0685W-BEWDS8-PBCCPB-Y0AP8Z-1M2CDY-VW29CR-VTNTSK-BFWZR9-SSHZBR-FDHCS4-J7NE12-ZY1Z2A-DCV9TB-PENBQN-3NBV0F-9K863V-'
           'QMRP23-D2HN7M-4ARRSZ-XHCR0W-FEZC84')
PRO_UNBOUND = ('0716ZV-HZ0C1D-P0PV0H-3G0000-000000-31RN37-M0AP8Y-TW4YM8-QAZHE6-XA54HA-XJFM0J-4T2GRM-1GJAYE-W26EH2-3KKTAA-EMP9CP-EG9C7R-9AWYXQ-AQPZYQ-'
               'BQ1NHF-7TFDKP-9BF2PG-ZFNRRC-54EPGC')
PERPETUAL = ('0716ZV-HZ0G1D-P0PVZZ-ZG085W-BEWDS8-PXMDVW-Y0AP8Z-D8VZ0G-RTMP75-12R0CV-N7H71H-EKMXAE-CRPTM5-FGSE4T-ETJ4X9-C8V76W-HZKBJ2-R3SGP5-A8HRDH-'
             'SZE6A4-2QHT87-VM90E8-95KB4V-W6SXG4')
OTHER_PC = 'AAAAA-BBBBB'


def read(text, today, device=DEVICE, product='al-store', keys=(KEY,)):
    return afcodes.read_code(text, list(keys), product, device, today)


class WireFormat(unittest.TestCase):
    def test_trial_lasts_fourteen_days_then_stops(self):
        d = lambda n: date(2026, 1, 1) + timedelta(days=n)  # noqa: E731
        self.assertEqual(read(TRIAL, d(0)).state, 'active')
        self.assertEqual(read(TRIAL, d(13)).state, 'active')                     # 2026-01-14 is the last day
        self.assertEqual(read(TRIAL, d(13)).terms['days_left'], 1)
        self.assertEqual(read(TRIAL, d(14)).state, 'expired')                    # a trial has no grace
        self.assertFalse(read(TRIAL, d(14)).full_access)
        self.assertEqual(read(TRIAL, d(-1)).state, 'not_yet_valid')

    def test_monthly_runs_thirty_days_then_three_grace_days_then_read_only(self):
        d = lambda n: date(2026, 1, 1) + timedelta(days=n)  # noqa: E731
        first, last = read(MONTHLY, d(0)), read(MONTHLY, d(29))
        self.assertEqual((first.state, first.terms['days_left'], first.terms['edition']), ('active', 30, 'standard'))
        self.assertEqual((last.state, last.terms['days_left']), ('active', 1))   # 2026-01-30
        for n in (30, 31, 32):                                                   # 01-31 .. 02-02: still sells, with a reminder
            self.assertEqual((read(MONTHLY, d(n)).state, read(MONTHLY, d(n)).full_access), ('grace', True), n)
        self.assertEqual((read(MONTHLY, d(33)).state, read(MONTHLY, d(33)).full_access), ('expired', False))
        self.assertEqual(read(MONTHLY, d(33)).terms['grace_days'], 3)

    def test_permanent_never_ends_and_has_no_end_date(self):
        for day in (date(2026, 1, 1), date(2030, 6, 1), date(2100, 1, 1), date(2999, 12, 31)):
            r = read(PERPETUAL, day)
            self.assertEqual((r.state, r.full_access, r.terms['last_day'], r.terms['days_left']), ('active', True, None, None), day)
        self.assertEqual(read(PERPETUAL, date(2025, 12, 31)).state, 'not_yet_valid')

    def test_a_code_tied_to_a_pc_works_on_that_pc_only(self):
        for text in (TRIAL, MONTHLY, PERPETUAL):
            self.assertEqual(read(text, date(2026, 1, 2)).state, 'active')
            wrong = read(text, date(2026, 1, 2), device=OTHER_PC)
            self.assertEqual((wrong.state, wrong.reason, wrong.full_access), ('invalid', 'other_device', False))
            self.assertEqual(read(text, date(2026, 1, 2), device=None).reason, 'other_device')

    def test_a_code_without_a_pc_still_reads_on_any_pc_and_a_permanent_one_never_does(self):
        """The codes sold before device binding was added carry no PC: they keep working. A permanent code without a PC is refused."""
        for device in (DEVICE, OTHER_PC, None):
            r = read(PRO_UNBOUND, date(2026, 6, 1), device=device)
            self.assertEqual((r.state, r.terms['device_bound'], r.terms['edition']), ('active', False, 'pro'))
        self.assertEqual(read(PRO_UNBOUND, date(2027, 1, 1)).state, 'expired')

    def test_a_code_nobody_signed_or_with_one_changed_character_is_never_accepted(self):
        for text in (TRIAL, MONTHLY, PRO_UNBOUND, PERPETUAL):
            self.assertTrue(read(text, date(2026, 1, 2)).full_access)
            raw = text.replace('-', '')
            for i in (0, 20, len(raw) // 2, len(raw) - 1):                       # the version, the terms, the middle, the signature
                other = 'A' if raw[i] != 'A' else 'B'
                r = read(raw[:i] + other + raw[i + 1:], date(2026, 1, 2))
                self.assertFalse(r.full_access, (text[:6], i))
        self.assertEqual(read(MONTHLY, date(2026, 1, 2), keys=('x' * 43,)).full_access, False)   # a key that is not the vendor's
        self.assertEqual(read(MONTHLY, date(2026, 1, 2), product='hessa-centre').reason, 'wrong_product')
        self.assertEqual(read('', date(2026, 1, 2)).state, 'invalid')
        self.assertEqual(read(MONTHLY[:-5], date(2026, 1, 2)).state, 'invalid')   # a code cut short in the paste


@unittest.skipUnless(HAVE_CRYPTO, 'cryptography needed')
class ShopLifecycle(unittest.TestCase):
    def setUp(self):
        self.S = Server(licensed=False)
        self.c = self.S.client()
        self.c.login()
        self.today = date.fromisoformat(ids.local_day())
        self.device = self.c.get('/api/licence')[1]['device']

    def tearDown(self):
        self.S.stop()

    def activate(self, code):
        return self.c.post('/api/licence/activate', {'code': code})

    def save(self, name):
        return self.c.post('/api/product/save', {'name': name, 'retail': 100})[0]

    def put_in_the_shop(self, code):
        """What passing time does: the stored code stays, the date moves on."""
        self.S.app.db.run("UPDATE meta SET value = ? WHERE key = 'licence_code'", code)
        licence._cache.clear()

    def test_a_monthly_renewal_replaces_the_old_code_and_brings_back_full_access(self):
        st, d, _ = self.activate(code_for(self.device, 30, self.today, 'standard', grace=3))
        self.assertEqual((st, d['state'], d['days_left']), (200, 'active', 30))
        self.put_in_the_shop(code_for(self.device, 30, self.today - timedelta(days=40), 'standard', grace=3))   # the month ran out
        self.assertEqual(self.c.get('/api/licence')[1]['state'], 'expired')
        self.assertEqual(self.save('Locked'), 402)
        st, d, _ = self.activate(code_for(self.device, 30, self.today, 'standard', grace=3))                      # the renewal code
        self.assertEqual((st, d['state'], d['days_left'], d['full']), (200, 'active', 30, True))
        self.assertEqual(self.save('Back at work'), 200)

    def test_an_expired_or_empty_or_wrong_renewal_never_wipes_the_working_code(self):
        self.activate(code_for(self.device, 30, self.today, 'standard', grace=3))
        before = self.c.get('/api/licence')[1]
        for bad in ('', '   ', 'not a code', code_for(self.device, 14, self.today - timedelta(days=30)), code_for(OTHER_PC, 30, self.today)):
            st, d, _ = self.activate(bad)
            self.assertEqual(st, 400, bad)
            now = self.c.get('/api/licence')[1]
            self.assertEqual((now['state'], now['serial'], now['full']), (before['state'], before['serial'], True), bad)
        self.assertEqual(self.save('Still works'), 200)

    def test_a_permanent_code_survives_a_far_future_date_without_an_end_date(self):
        st, d, _ = self.activate(code_for(self.device, 1, self.today, 'perpetual'))
        self.assertEqual((st, d['edition'], d['last_day'], d['days_left']), (200, 'perpetual', None, None))
        code = self.S.app.db.value("SELECT value FROM meta WHERE key = 'licence_code'")
        for year in (2040, 2100, 2500):
            r = licence._check(code, self.device, date(year, 6, 1))
            self.assertEqual((r['state'], r['full'], r['last_day']), ('active', True, None), year)
        self.assertNotIn('null null', json.dumps(self.c.get('/api/licence')[1]))   # the screen gets a real null, never the word

    def test_a_reinstall_or_a_new_pc_needs_a_new_code_but_loses_no_data(self):
        self.activate(code_for(self.device, 365, self.today, 'standard'))
        self.assertEqual(self.save('Kept product'), 200)
        self.S.app.db.run("UPDATE meta SET value = 'a-different-install' WHERE key = 'install_id'")   # the same data on a different install
        licence._cache.clear()
        lic = self.c.get('/api/licence')[1]
        self.assertNotEqual(lic['device'], self.device)
        self.assertEqual((lic['state'], lic['reason'], lic['full']), ('invalid', 'other_device', False))
        self.assertEqual(self.save('Refused'), 402)
        names = [p['name'] for p in self.c.get('/api/products?q=Kept')[1]['items']]
        self.assertEqual(names, ['Kept product'])                                # reading is open
        self.assertEqual(self.c.get('/api/export')[0], 200)
        self.assertEqual(self.c.post('/api/backup/now')[0], 200)
        self.assertEqual(self.activate(code_for(lic['device'], 30, self.today, 'standard'))[0], 200)   # the new code for the new device
        self.assertEqual(self.save('Back'), 200)

    def test_a_moved_clock_is_noticed_in_both_directions_and_never_hides_data(self):
        self.activate(code_for(self.device, 365, self.today, 'standard'))
        db = self.S.app.db
        ahead = ids.iso(ids.utcnow() + timedelta(days=5))
        db.run("UPDATE meta SET value = ? WHERE key = 'max_seen'", ahead)        # the PC has shown a date five days ahead ...
        st, lic, _ = self.c.get('/api/licence')                                  # ... and now shows today again
        self.assertEqual((lic['state'], lic['full']), ('clock_back', False))
        self.assertEqual(self.save('Refused'), 402)
        self.assertEqual(self.c.get('/api/products')[0], 200)
        self.assertEqual(self.c.get('/api/export')[0], 200)
        self.assertEqual(self.c.post('/api/backup/now')[0], 200)
        db.run("UPDATE meta SET value = ? WHERE key = 'max_seen'", ids.iso(ids.utcnow() + timedelta(hours=3)))   # a few hours: normal drift, not tampering
        self.assertEqual(self.c.get('/api/licence')[1]['full'], True)
        self.assertEqual(self.save('Fine'), 200)

    def test_after_the_licence_ends_the_data_can_be_read_exported_backed_up_and_put_back(self):
        """«Never let an expired licence hide, lock or delete data»: the backup is the customer's way back to his own data."""
        self.activate(code_for(self.device, 30, self.today, 'standard', grace=3))
        self.assertEqual(self.save('Before the end'), 200)
        self.put_in_the_shop(code_for(self.device, 30, self.today - timedelta(days=60), 'standard', grace=3))
        self.assertEqual(self.c.get('/api/licence')[1]['state'], 'expired')
        self.assertEqual(self.save('Locked'), 402)
        st, b, _ = self.c.post('/api/backup/now')
        self.assertEqual(st, 200, b)
        self.assertEqual(self.c.get('/api/export')[0], 200)
        self.S.app.db.run("UPDATE products SET name = 'Spoiled'")               # something goes wrong with the data after the end
        st, d, _ = self.c.post('/api/backup/restore', {'name': b['name'], 'password': OWNER[1]})
        self.assertEqual(st, 200, d)
        names = [p['name'] for p in self.c.get('/api/products?q=Before')[1]['items']]
        self.assertEqual(names, ['Before the end'])
        self.assertEqual(self.c.get('/api/licence')[1]['state'], 'expired')      # putting data back never revives the licence


if __name__ == '__main__':
    unittest.main()
