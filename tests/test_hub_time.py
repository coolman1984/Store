"""Signed hub calendar verification (shared multi-product licence hub)."""
import base64
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hub_time  # noqa: E402
from harness import HAVE_CRYPTO  # noqa: E402
from hub_calendar_sign import sign_calendar_payload  # noqa: E402


@unittest.skipUnless(HAVE_CRYPTO, 'cryptography needed to sign test hub time')
class HubTimeTests(unittest.TestCase):
    def test_signed_calendar_accepted(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization

        private = Ed25519PrivateKey.generate()
        pem = private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        day = '2026-10-14'
        payload, pub = sign_calendar_payload(pem, 'trial-hub', day)
        trusted = {'trial-hub': pub}
        self.assertEqual(hub_time.verify_hub_calendar(payload, trusted), day)

    def test_unsigned_calendar_rejected(self):
        pub = base64.urlsafe_b64encode(b'x' * 32).decode().rstrip('=')
        self.assertIsNone(hub_time.verify_hub_calendar({'calendar_day': '2026-10-14'}, {'trial-hub': pub}))

    def test_wrong_kid_rejected(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization

        private = Ed25519PrivateKey.generate()
        pem = private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        payload, pub = sign_calendar_payload(pem, 'trial-hub', '2026-10-14')
        self.assertIsNone(hub_time.verify_hub_calendar(payload, {'paid': pub}))


if __name__ == '__main__':
    unittest.main()
