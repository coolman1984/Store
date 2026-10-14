"""Signed hub calendar only: no unsigned HTTP Date writes; 7-day forward cap (Yousef hub round 6)."""
import base64
import os
import sys
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ids  # noqa: E402
import licence  # noqa: E402
import trial  # noqa: E402
from fake_relay import FakeRelay  # noqa: E402
from harness import HAVE_CRYPTO, PUBLIC, Shop  # noqa: E402
from hub_calendar_sign import sign_calendar_payload  # noqa: E402


def _meta(db, key):
    return db.value('SELECT value FROM meta WHERE key = ?', key)


@unittest.skipUnless(HAVE_CRYPTO, 'cryptography needed')
class HubCalendarTrustTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self.hub_private = Ed25519PrivateKey.generate()
        self.hub_pem = self.hub_private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        self.hub_pub = base64.urlsafe_b64encode(
            self.hub_private.public_key().public_bytes_raw()
        ).decode().rstrip('=')
        os.environ['STORE_LICENCE_KEYS'] = f'{PUBLIC},trial-hub:{self.hub_pub}'
        self.relay = FakeRelay()
        os.environ['STORE_LICENCE_RELAY'] = self.relay.base
        self.shop = Shop(licensed=False)
        self.db = self.shop.db
        self.app = type('App', (), {'db': self.db, 'started': 1.0, 'practice': False, 'cfg': {}})()
        licence._cache.clear()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.shop.dir, ignore_errors=True)
        self.relay.stop()
        os.environ.pop('STORE_LICENCE_RELAY', None)
        if PUBLIC:
            os.environ['STORE_LICENCE_KEYS'] = PUBLIC
        licence._cache.clear()

    def _today(self):
        return date.fromisoformat(ids.local_day())

    def _signed(self, day, kid='trial-hub'):
        return sign_calendar_payload(self.hub_pem, kid, day)[0]

    def test_unsigned_payload_does_not_change_trusted_or_max_seen(self):
        before_trust = _meta(self.db, licence.META_TRUSTED)
        before_seen = _meta(self.db, 'max_seen')
        trial._note_hub_time(self.db, self.relay.base, {'calendar_day': '2099-01-01', 'serverTime': '2099-01-01'})
        self.assertEqual(_meta(self.db, licence.META_TRUSTED), before_trust)
        self.assertEqual(_meta(self.db, 'max_seen'), before_seen)

    def test_bad_signature_does_not_change_trusted_or_max_seen(self):
        before_trust = _meta(self.db, licence.META_TRUSTED)
        before_seen = _meta(self.db, 'max_seen')
        payload = self._signed(self._today().isoformat())
        payload['sig'] = 'A' * 86
        trial._note_hub_time(self.db, self.relay.base, payload)
        self.assertEqual(_meta(self.db, licence.META_TRUSTED), before_trust)
        self.assertEqual(_meta(self.db, 'max_seen'), before_seen)

    def test_signed_with_unknown_kid_does_not_change_trusted(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        other = Ed25519PrivateKey.generate()

        pem = other.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        payload, _ = sign_calendar_payload(pem, 'trial-hub', '2099-06-01')
        before = _meta(self.db, licence.META_TRUSTED)
        trial._note_hub_time(self.db, self.relay.base, payload)
        self.assertEqual(_meta(self.db, licence.META_TRUSTED), before)

    def test_sync_hub_clock_ignores_unsigned_relay(self):
        far = (self._today() + timedelta(days=400)).isoformat()
        self.relay.clock_day = far
        trial.sync_hub_clock(self.app, force=True)
        self.assertIsNone(licence.trusted_day(self.db))

    def test_sync_hub_clock_applies_signed_calendar(self):
        self.relay = FakeRelay(hub_sign_pem=self.hub_pem)
        os.environ['STORE_LICENCE_RELAY'] = self.relay.base
        day = (self._today() + timedelta(days=3)).isoformat()
        self.relay.clock_day = day
        trial.sync_hub_clock(self.app, force=True)
        self.assertEqual(licence.trusted_day(self.db), date.fromisoformat(day))

    def test_forward_jump_capped_at_seven_days(self):
        today = self._today()
        far = (today + timedelta(days=30)).isoformat()
        payload = self._signed(far)
        licence.accept_hub_calendar(self.db, payload)
        self.assertEqual(licence.trusted_day(self.db), today + timedelta(days=licence.HUB_CALENDAR_MAX_JUMP_DAYS))


if __name__ == '__main__':
    unittest.main()
