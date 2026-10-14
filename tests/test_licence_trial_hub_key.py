"""trial-hub public keys: device-bound trials only, at most 14 days (stolen Worker secret cannot mint paid licences)."""
import base64
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import HAVE_CRYPTO, Shop, code_for  # noqa: E402

import afcodes  # noqa: E402
import licence  # noqa: E402
import ids  # noqa: E402

if HAVE_CRYPTO:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    _HUB = Ed25519PrivateKey.generate()
    HUB_PEM = _HUB.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    HUB_PUB = base64.urlsafe_b64encode(_HUB.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode().rstrip('=')


@unittest.skipUnless(HAVE_CRYPTO, 'cryptography needed')
class TrialHubKeyPolicy(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get('STORE_LICENCE_KEYS')
        os.environ['STORE_LICENCE_KEYS'] = f'trial-hub:{HUB_PUB}'
        self.shop = Shop(licensed=False)
        self.dev = licence.device(self.shop.db)
        self.first = date.fromisoformat(ids.local_day())

    def tearDown(self):
        if self._saved is None:
            os.environ.pop('STORE_LICENCE_KEYS', None)
        else:
            os.environ['STORE_LICENCE_KEYS'] = self._saved
        import shutil
        shutil.rmtree(self.shop.dir, ignore_errors=True)

    def _hub(self, edition='trial', days=14, device=None, grace=0):
        return afcodes.issue_code(HUB_PEM, 'al-store', edition, self.first, days, device or self.dev, grace_days=grace)['code']

    def test_valid_hub_trial_activates(self):
        st = licence.activate(self.shop.db, self._hub())
        self.assertIn(st['state'], ('trial', 'active'))
        self.assertTrue(st['full'])

    def test_hub_key_rejects_monthly(self):
        with self.assertRaises(ValueError) as ctx:
            licence.activate(self.shop.db, self._hub(edition='standard', days=30))
        self.assertEqual(ctx.exception.args[0], 'trial_key_edition')

    def test_hub_key_rejects_perpetual(self):
        with self.assertRaises(ValueError) as ctx:
            licence.activate(self.shop.db, self._hub(edition='perpetual', days=0))
        self.assertEqual(ctx.exception.args[0], 'trial_key_edition')

    def test_hub_key_rejects_long_trial(self):
        with self.assertRaises(ValueError) as ctx:
            licence.activate(self.shop.db, self._hub(days=30))
        self.assertEqual(ctx.exception.args[0], 'trial_key_days')

    def test_hub_key_rejects_grace_on_trial(self):
        with self.assertRaises(ValueError) as ctx:
            licence.activate(self.shop.db, self._hub(days=14, grace=60))
        self.assertEqual(ctx.exception.args[0], 'trial_key_grace')

    def test_hub_key_allows_trial_plus_grace_within_fourteen_total(self):
        st = licence.activate(self.shop.db, self._hub(days=7, grace=7))
        self.assertIn(st['state'], ('trial', 'active'))

    def test_trial_hub_stays_trial_only_when_paid_key_is_also_trusted(self):
        from harness import PRIVATE_PEM, PUBLIC
        os.environ['STORE_LICENCE_KEYS'] = f'trial-hub:{HUB_PUB},paid:{PUBLIC}'
        with self.assertRaises(ValueError) as ctx:
            licence.activate(self.shop.db, self._hub(edition='standard', days=30))
        self.assertEqual(ctx.exception.args[0], 'trial_key_edition')

    def test_paid_hub_key_allows_monthly_and_perpetual(self):
        from harness import PRIVATE_PEM, PUBLIC
        os.environ['STORE_LICENCE_KEYS'] = f'trial-hub:{HUB_PUB},paid:{PUBLIC}'
        monthly = afcodes.issue_code(PRIVATE_PEM, 'al-store', 'standard', self.first, 30, self.dev, grace_days=3)['code']
        st = licence.activate(self.shop.db, monthly)
        self.assertEqual(st['edition'], 'standard')
        self.assertTrue(st['full'])
        perpetual = afcodes.issue_code(PRIVATE_PEM, 'al-store', 'perpetual', self.first, 0, self.dev)['code']
        st2 = licence.activate(self.shop.db, perpetual)
        self.assertEqual(st2['edition'], 'perpetual')
        self.assertTrue(st2['full'])


if __name__ == '__main__':
    unittest.main()
