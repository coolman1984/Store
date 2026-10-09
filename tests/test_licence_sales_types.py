"""The Store must accept all three signed purchase types from Licence Studio."""
import base64
import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1] / 'server'
sys.path.insert(0, str(SERVER))

import afcodes  # noqa: E402
import licence  # noqa: E402
from version import PRODUCT_ID  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402


class SalesTypesTests(unittest.TestCase):
    def setUp(self):
        key = Ed25519PrivateKey.generate()
        self.private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption())
        self.public = base64.urlsafe_b64encode(key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode().rstrip('=')
        self.device = afcodes.device_code('store-sales-types-device')
        self.start = date(2026, 10, 9)

    def code(self, edition, days):
        return afcodes.issue_code(self.private, PRODUCT_ID, edition, self.start, days, self.device)['code']

    def test_trial_and_monthly_expire_without_unlocking_writes(self):
        with patch.dict(os.environ, {'STORE_LICENCE_KEYS': self.public}):
            trial = self.code('trial', 14)
            self.assertTrue(licence._check(trial, self.device, self.start)['full'])
            self.assertFalse(licence._check(trial, self.device, self.start + timedelta(days=14))['full'])
            monthly = self.code('monthly', 30)
            self.assertTrue(licence._check(monthly, self.device, self.start + timedelta(days=29))['full'])
            self.assertFalse(licence._check(monthly, self.device, self.start + timedelta(days=30))['full'])

    def test_lifetime_never_expires_on_licensed_device(self):
        with patch.dict(os.environ, {'STORE_LICENCE_KEYS': self.public}):
            code = self.code('lifetime', 1)
            today = date(9999, 12, 31)
            state = licence._check(code, self.device, today)
            self.assertTrue(state['full'])
            self.assertTrue(state['permanent'])
            self.assertEqual(state['state'], 'active')
            self.assertIsNone(state['days_left'])
            self.assertIsNone(state['last_day'])
            self.assertFalse(licence._check(code, afcodes.device_code('other-pc'), self.start)['full'])


if __name__ == '__main__':
    unittest.main()
