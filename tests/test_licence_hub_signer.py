"""Cross-check: a code from licence-hub Node signer verifies in server/afcodes (same bytes as licence.activate)."""
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))
import afcodes  # noqa: E402


class LicenceHubSignerTest(unittest.TestCase):
    def test_node_signed_code_is_valid(self):
        script = os.path.join(ROOT, 'licence-hub', 'test', 'export_code.mjs')
        out = subprocess.check_output(['node', script], cwd=ROOT, text=True)
        data = json.loads(out)
        cairo_today = datetime.now(ZoneInfo('Africa/Cairo')).date()
        result = afcodes.read_code(data['code'], [data['public']], 'al-store', device=data['device'], today=cairo_today)
        self.assertTrue(result.valid)
        self.assertEqual(result.state, 'active')
        self.assertEqual(result.terms.get('edition'), 'trial')

    def test_node_signed_paid_monthly_code_is_valid(self):
        script = os.path.join(ROOT, 'licence-hub', 'test', 'export_paid_code.mjs')
        out = subprocess.check_output(['node', script], cwd=ROOT, text=True)
        data = json.loads(out)
        cairo_today = datetime.now(ZoneInfo('Africa/Cairo')).date()
        result = afcodes.read_code(data['code'], [data['public']], 'al-store', device=data['device'], today=cairo_today)
        self.assertTrue(result.valid)
        self.assertEqual(result.state, 'active')
        self.assertEqual(result.terms.get('edition'), 'standard')

    def test_yousef_shared_hub_trial_for_al_store(self):
        """Same bytes as coolman1984/Yousef-Transportation licence-hub/test/export_code.mjs (round 6) with product al-store."""
        script = os.path.join(ROOT, 'tests', 'shared_hub', 'yousef_round6_export.mjs')
        out = subprocess.check_output(['node', script], cwd=ROOT, text=True, env={**os.environ, 'HUB_PRODUCT': 'al-store'})
        data = json.loads(out)
        cairo_today = datetime.now(ZoneInfo('Africa/Cairo')).date()
        result = afcodes.read_code(data['code'], [data['public']], 'al-store', device=data['device'], today=cairo_today)
        self.assertTrue(result.valid)
        self.assertEqual(result.terms.get('edition'), 'trial')

    def test_wrong_product_id_rejected(self):
        script = os.path.join(ROOT, 'tests', 'shared_hub', 'yousef_round6_export.mjs')
        out = subprocess.check_output(['node', script], cwd=ROOT, text=True, env={**os.environ, 'HUB_PRODUCT': 'trip-orders'})
        data = json.loads(out)
        cairo_today = datetime.now(ZoneInfo('Africa/Cairo')).date()
        result = afcodes.read_code(data['code'], [data['public']], 'al-store', device=data['device'], today=cairo_today)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, 'wrong_product')


if __name__ == '__main__':
    unittest.main()
