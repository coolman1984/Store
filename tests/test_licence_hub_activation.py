"""Hub-shaped trial codes activate a temp shop; wrong device or signature is refused (keys generated in-process only)."""
import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import afcodes  # noqa: E402
import licence  # noqa: E402
from harness import Shop  # noqa: E402


def _hub_trial(device=''):
    script = os.path.join(ROOT, 'licence-hub', 'test', 'export_code.mjs')
    env = {**os.environ, **({'HUB_TEST_DEVICE': device} if device else {})}
    out = subprocess.check_output(['node', script], cwd=ROOT, text=True, env=env)
    return json.loads(out)


class LicenceHubActivationTest(unittest.TestCase):
    def setUp(self):
        self._saved_keys = os.environ.get('STORE_LICENCE_KEYS')
        self.shop = Shop(licensed=False)
        dev = licence.device(self.shop.db)
        self.payload = _hub_trial(dev)
        os.environ['STORE_LICENCE_KEYS'] = self.payload['public']

    def tearDown(self):
        if self._saved_keys is None:
            os.environ.pop('STORE_LICENCE_KEYS', None)
        else:
            os.environ['STORE_LICENCE_KEYS'] = self._saved_keys
        shutil.rmtree(self.shop.dir, ignore_errors=True)

    def test_happy_path_activates_this_device(self):
        dev = licence.device(self.shop.db)
        self.assertEqual(self.payload['device'], dev)
        st = licence.activate(self.shop.db, self.payload['code'])
        self.assertIn(st['state'], ('trial', 'active'))
        self.assertTrue(st['full'])

    def test_other_device_is_refused(self):
        other = Shop(licensed=False)
        try:
            os.environ['STORE_LICENCE_KEYS'] = self.payload['public']
            with self.assertRaises(ValueError) as ctx:
                licence.activate(other.db, self.payload['code'])
            self.assertEqual(ctx.exception.args[0], 'other_device')
        finally:
            shutil.rmtree(other.dir, ignore_errors=True)

    def test_flipped_character_is_refused(self):
        code = list(self.payload['code'])
        for i, ch in enumerate(code):
            if ch in afcodes.ALPHABET:
                code[i] = '0' if ch != '0' else '1'
                break
        bad = ''.join(code)
        with self.assertRaises(ValueError) as ctx:
            licence.activate(self.shop.db, bad)
        self.assertIn(ctx.exception.args[0], ('bad_signature', 'wrong_length', 'bad_character', 'unknown_version'))


if __name__ == '__main__':
    unittest.main()
