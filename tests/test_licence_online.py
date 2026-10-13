"""Online hub calendar + local clock rules (Teachers PR #35 standard, adapted for Al-Store meta storage)."""
import os
import shutil
import unittest
from datetime import date, timedelta

import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import afcodes  # noqa: E402
import licence  # noqa: E402
import trial  # noqa: E402
from fake_relay import FakeRelay  # noqa: E402
from harness import HAVE_CRYPTO, OWNER, PW, Server, Shop, code_for  # noqa: E402


class LicenceOnlineTests(unittest.TestCase):
    def setUp(self):
        self.shop = Shop(licensed=False)
        self.dev = licence.device(self.shop.db)
        self.today = date.fromisoformat(__import__('ids').local_day())
        licence._cache.clear()

    def tearDown(self):
        shutil.rmtree(self.shop.dir, ignore_errors=True)
        licence._cache.clear()

    def activate(self, last, grace=3, edition='standard', first=None):
        first = first or self.today
        days = (last - first).days + 1
        code = code_for(self.dev, days, first, edition=edition, grace=grace)
        return licence.activate(self.shop.db, code)

    def test_online_hub_date_past_until_locks(self):
        last = self.today
        self.activate(last)
        st = licence.status(self.shop.db)
        self.assertIn(st['state'], ('active', 'trial', 'grace'))
        licence.note_online(self.shop.db, (last + timedelta(days=10)).isoformat())
        licence._cache.clear()
        st = licence.status(self.shop.db)
        self.assertEqual(st['state'], 'expired')
        self.assertFalse(st['full'])

    def test_offline_failure_does_not_add_a_hub_lock(self):
        last = self.today + timedelta(days=20)
        self.activate(last)
        licence.note_online(self.shop.db, None)
        self.assertIsNone(licence.probe_http_date('https://invalid.invalid', timeout=1))
        self.assertIsNone(licence.trusted_day(self.shop.db))
        self.assertIn(licence.status(self.shop.db)['state'], ('active', 'trial'))

    def test_weekend_without_internet_stays_ok(self):
        last = self.today + timedelta(days=30)
        self.activate(last)
        st = licence.status(self.shop.db)
        self.assertTrue(st['full'])

    def test_hub_trusted_date_blocks_local_rollback(self):
        last = self.today + timedelta(days=30)
        self.activate(last)
        licence.note_online(self.shop.db, (self.today + timedelta(days=5)).isoformat())
        licence._cache.clear()
        st = licence.status(self.shop.db)
        self.assertEqual(st['state'], 'clock_back')
        self.assertFalse(st['full'])

    def test_until_in_the_signed_code_is_not_extended_online(self):
        last = self.today + timedelta(days=10)
        first = last - timedelta(days=29)
        code = code_for(self.dev, 30, first, edition='standard', grace=3)
        licence.activate(self.shop.db, code)
        licence.note_online(self.shop.db, '2029-06-01')
        r = afcodes.read_code(code, licence.trusted_keys(), 'al-store', self.dev, date(2029, 6, 1))
        self.assertEqual(r.terms['last_day'], last.isoformat())


@unittest.skipUnless(HAVE_CRYPTO, 'cryptography needed to sign test codes')
class HubClockAfterActivationTests(unittest.TestCase):
    def setUp(self):
        self.relay = FakeRelay()
        os.environ['STORE_LICENCE_RELAY'] = self.relay.base
        self.S = Server(licensed=False)
        self.app = self.S.app
        self.client = self.S.client()
        self.client.login()
        self.dev = licence.device(self.app.db)
        licence._cache.clear()

    def tearDown(self):
        self.S.stop()
        self.relay.stop()
        os.environ.pop('STORE_LICENCE_RELAY', None)
        licence._cache.clear()

    def test_sync_hub_clock_after_activation_expires_when_pc_clock_lags(self):
        last = date.fromisoformat(__import__('ids').local_day())
        code = code_for(self.dev, 30, last, edition='standard', grace=3)
        self.assertEqual(self.client.post('/api/licence/activate', {'code': code})[0], 200)
        self.assertTrue(self.client.get('/api/licence')[1]['full'])
        self.relay.clock_day = (last + timedelta(days=10)).isoformat()
        trial.sync_hub_clock(self.app, force=True)
        lic = self.client.get('/api/licence')[1]
        self.assertEqual(lic['state'], 'expired')
        self.assertFalse(lic['full'])
        self.assertEqual(self.client.get('/api/products')[0], 200)
        self.assertEqual(self.client.get('/api/export')[0], 200)
        self.assertEqual(self.client.post('/api/backup/now')[0], 200)
        self.assertEqual(self.client.post('/api/product/save', {'name': 'Blocked', 'retail': 1})[0], 402)

    def test_sync_hub_clock_once_per_session(self):
        self.relay.clock_day = date.fromisoformat(__import__('ids').local_day()).isoformat()
        trial.sync_hub_clock(self.app)
        n = len([x for x in self.relay.log if x == ('GET', '/licence/clock')])
        trial.sync_hub_clock(self.app)
        self.assertEqual(len([x for x in self.relay.log if x == ('GET', '/licence/clock')]), n)


if __name__ == '__main__':
    unittest.main()
