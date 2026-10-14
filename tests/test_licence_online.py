"""Online hub calendar + local clock rules (Teachers PR #35 standard, adapted for Al-Store meta storage)."""
import base64
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
from harness import HAVE_CRYPTO, PUBLIC, Server, Shop, code_for  # noqa: E402
from hub_calendar_sign import trust_signed_hub_day  # noqa: E402


@unittest.skipUnless(HAVE_CRYPTO, 'cryptography needed to sign test hub time')
class LicenceOnlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        cls._hub_private = Ed25519PrivateKey.generate()
        cls.hub_pem = cls._hub_private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        cls.hub_pub = base64.urlsafe_b64encode(
            cls._hub_private.public_key().public_bytes_raw()
        ).decode().rstrip('=')

    def setUp(self):
        os.environ['STORE_LICENCE_KEYS'] = f'{PUBLIC},trial-hub:{self.hub_pub},paid:{self.hub_pub}'
        self.shop = Shop(licensed=False)
        self.dev = licence.device(self.shop.db)
        self.today = date.fromisoformat(__import__('ids').local_day())
        licence._cache.clear()

    def tearDown(self):
        shutil.rmtree(self.shop.dir, ignore_errors=True)
        if PUBLIC:
            os.environ['STORE_LICENCE_KEYS'] = PUBLIC
        licence._cache.clear()

    def _trust_hub_day(self, day):
        trust_signed_hub_day(self.shop.db, self.hub_pem, 'trial-hub', day.isoformat() if isinstance(day, date) else day)

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
        self._trust_hub_day(last + timedelta(days=10))
        licence._cache.clear()
        st = licence.status(self.shop.db)
        self.assertEqual(st['state'], 'expired')
        self.assertFalse(st['full'])

    def test_offline_failure_does_not_add_a_hub_lock(self):
        last = self.today + timedelta(days=20)
        self.activate(last)
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
        self._trust_hub_day(self.today + timedelta(days=5))
        licence._cache.clear()
        st = licence.status(self.shop.db)
        self.assertEqual(st['state'], 'clock_back')
        self.assertFalse(st['full'])

    def test_until_in_the_signed_code_is_not_extended_online(self):
        last = self.today + timedelta(days=10)
        first = last - timedelta(days=29)
        code = code_for(self.dev, 30, first, edition='standard', grace=3)
        licence.activate(self.shop.db, code)
        r = afcodes.read_code(code, licence.trusted_keys(), 'al-store', self.dev, date(2029, 6, 1))
        self.assertEqual(r.terms['last_day'], last.isoformat())


@unittest.skipUnless(HAVE_CRYPTO, 'cryptography needed to sign test codes')
class HubClockAfterActivationTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self._hub_private = Ed25519PrivateKey.generate()
        pem = self._hub_private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        pub = base64.urlsafe_b64encode(self._hub_private.public_key().public_bytes_raw()).decode().rstrip('=')
        os.environ['STORE_LICENCE_KEYS'] = f'{PUBLIC},trial-hub:{pub},paid:{pub}'
        self.relay = FakeRelay(hub_sign_pem=pem)
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
        if PUBLIC:
            os.environ['STORE_LICENCE_KEYS'] = PUBLIC
        licence._cache.clear()

    def test_sync_hub_clock_after_activation_expires_when_pc_clock_lags(self):
        last = date.fromisoformat(__import__('ids').local_day())
        first = last - timedelta(days=29)
        code = code_for(self.dev, 30, first, edition='standard', grace=3)
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
