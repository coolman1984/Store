"""Asking the company for a trial from the licence screen, and switching on with the answer (server/trial.py). The relay is a stand-in
(tests/fake_relay.py) that speaks the same protocol as the vendor's relay; the signed codes are real (the test key the program trusts).

What must hold: nothing leaves except the listed fields; a request that is repeated creates nothing new; the answer is checked like a
pasted code (a code for another PC or a forged one is refused and the relay is not told it was received); offline is a visible state
with a growing wait and a button, never an error page; only a person who may edit settings can ask; the manual way always works."""
import json
import os
import unittest

from harness import HAVE_CRYPTO, OWNER, PW, Server, code_for  # noqa: E402  (first: it puts server/ on the path)
import ids  # noqa: E402
import licence  # noqa: E402
import trial  # noqa: E402
from fake_relay import FakeRelay  # noqa: E402

DAY = '2026-10-09'


@unittest.skipUnless(HAVE_CRYPTO, 'cryptography needed to sign test codes')
class Asking(unittest.TestCase):
    def setUp(self):
        self.relay = FakeRelay()
        os.environ['STORE_LICENCE_RELAY'] = self.relay.base
        self.S = Server(licensed=False)  # a shop with no code yet: reading and backups only
        self.app = self.S.app
        self.owner = self.S.client()
        self.owner.login()
        self.device = licence.device(self.app.db)

    def tearDown(self):
        self.S.stop()
        self.relay.stop()
        os.environ.pop('STORE_LICENCE_RELAY', None)

    def ask(self, kind='trial', **extra):
        return self.owner.post('/api/licence/request', {'kind': kind, **extra})

    def state(self):
        return self.owner.get('/api/licence/request')[1]

    def step(self):
        return self.owner.post('/api/licence/request/retry')[1]

    def test_the_relay_is_not_set_up_so_only_the_manual_way_is_offered(self):
        os.environ.pop('STORE_LICENCE_RELAY')
        self.assertEqual(self.state()['available'], False)
        st, d, _ = self.ask()
        self.assertEqual((st, d['key']), (409, 'err.trialOff'))
        self.assertEqual(self.owner.post('/api/licence/activate', {'code': code_for(self.device)})[0], 200, 'the manual way works')

    def test_the_whole_chain_asks_waits_and_switches_on_by_itself(self):
        st, preview, _ = self.owner.get('/api/licence/preview?kind=trial')
        self.assertEqual(st, 200)
        self.assertEqual(sorted(preview['sends']), sorted(trial.SENT_FIELDS))
        self.assertEqual(self.relay.requests, {}, 'looking at what would be sent sends nothing')
        st, d, _ = self.ask()
        self.assertEqual(st, 200)
        self.assertEqual(d['status'], 'waiting')
        self.assertNotIn('poll_token', json.dumps(d))
        self.assertNotIn('nonce', d)
        sent = self.relay.last()['body']
        self.assertEqual(sorted(sent), sorted(trial.SENT_FIELDS), 'exactly the listed fields leave the PC, nothing else')
        self.assertEqual((sent['product'], sent['kind'], sent['device'], sent['version']), ('al-store', 'trial', self.device, trial.VERSION))
        self.assertEqual(sent['machine'], trial.machine_tag())
        self.assertRegex(sent['machine'], r'^[0-9a-f]{64}$')
        self.assertEqual(sent['shop'], 'Test shop')
        for forbidden in ('01000000', 'Owner Pass', 'owner1'):
            self.assertNotIn(forbidden, json.dumps(sent))
        again = self.ask()[1]  # pressing the button twice is the same request
        self.assertEqual(again['status'], 'waiting')
        self.assertEqual(len(self.relay.requests), 1)
        self.assertEqual(self.owner.get('/api/licence')[1]['state'], 'none')
        self.assertEqual(self.owner.post('/api/customer/save', {'name': 'Too early'})[0], 402, 'until the code is in, changes are refused')
        # the owner's program answers; the next look switches the program on
        self.relay.issue(self.relay.last(), code_for(self.device))
        self.assertEqual(self.step()['status'], 'activated')
        lic = self.owner.get('/api/licence')[1]
        self.assertEqual((lic['state'], lic['full'], lic['edition']), ('trial', True, 'trial'))
        self.assertTrue(self.relay.last()['acked'], 'the relay is told it was received and can forget the code')
        self.assertEqual(self.owner.post('/api/customer/save', {'name': 'First customer'})[0], 200, 'changes are open again (they were refused with 402)')
        actions = [r['action'] for r in self.owner.get('/api/audit')[1]]
        self.assertIn('licence.request', actions)
        self.assertIn('licence.auto', actions)
        self.assertNotIn(self.relay.last()['token'], json.dumps(self.owner.get('/api/audit')[1]))
        self.assertIsNone(trial._meta(self.app.db)['poll_token'], 'the secret is dropped once the code is in')

    def test_a_code_for_another_pc_or_a_forged_one_is_refused_and_not_acknowledged(self):
        self.ask()
        r = self.relay.last()
        good = code_for(self.device)
        forged = good[:40] + ('A' if good[40] != 'A' else 'B') + good[41:]  # one letter changed
        for code, reason in ((code_for(licence.afcodes.device_code('somebody-else', 'x')), 'other_device'), (forged, 'bad_signature')):
            self.relay.issue(r, code)
            st = self.owner.post('/api/licence/request/retry')[1]
            self.assertEqual((st['status'], st['reason']), ('failed', reason))
            self.assertFalse(r['acked'], 'a code that does not work is never acknowledged')
            self.assertEqual(self.owner.get('/api/licence')[1]['state'], 'none')
            trial._meta(self.app.db, {**trial._meta(self.app.db), 'next_try': None})  # do not wait the 15 minutes
        self.relay.issue(r, code_for(self.device))
        self.assertEqual(self.step()['status'], 'activated', 'and the right code is accepted afterwards')

    def test_offline_is_a_visible_state_with_a_growing_wait_and_a_retry_button(self):
        self.relay.stop()
        st = self.ask()[1]
        self.assertEqual(st['status'], 'failed')
        self.assertTrue(st['error'].startswith('offline'))
        self.assertTrue(st['next_try'])
        waits = []
        for _ in range(4):
            before = ids.utcnow()
            trial._meta(self.app.db, {**trial._meta(self.app.db), 'next_try': None})
            st = self.step()
            waits.append(round((ids.parse(st['next_try']) - before).total_seconds() / 10) * 10)
        self.assertEqual(waits, [300, 900, 3600, 3600], 'it waits longer each time and stops growing at an hour')
        self.assertEqual(st['status'], 'failed')
        self.assertEqual(self.owner.get('/api/licence')[1]['full'], False)
        self.assertEqual(self.owner.post('/api/licence/activate', {'code': code_for(self.device)})[0], 200, 'the manual way works while offline')

    def test_the_connection_comes_back_and_the_request_goes_through(self):
        port = self.relay.port
        self.relay.stop()
        self.assertEqual(self.ask()[1]['status'], 'failed')
        self.relay = FakeRelay(port)  # the company is reachable again
        st = self.step()
        self.assertEqual(st['status'], 'waiting')
        self.relay.issue(self.relay.last(), code_for(self.device))
        self.assertEqual(self.step()['status'], 'activated')

    def test_a_lost_answer_is_a_new_request_and_never_two_activations(self):
        self.relay.drop_next_answer = True
        self.assertEqual(self.ask()[1]['status'], 'failed')  # the relay stored it, the answer never arrived
        first = self.relay.last()
        trial._meta(self.app.db, {**trial._meta(self.app.db), 'next_try': None})
        st = self.step()  # the same nonce again: a replay that cannot be read; a new nonce makes a request that can
        self.assertEqual(st['status'], 'failed' if len(self.relay.requests) == 1 else 'waiting')
        trial._meta(self.app.db, {**trial._meta(self.app.db), 'next_try': None})
        self.step()
        trial._meta(self.app.db, {**trial._meta(self.app.db), 'next_try': None})
        self.step()
        mine = self.relay.last()
        self.assertNotEqual(mine['body']['nonce'], first['body']['nonce'])
        self.relay.issue(mine, code_for(self.device))
        self.assertEqual(self.step()['status'], 'activated')
        self.assertEqual(self.app.db.value("SELECT COUNT(*) FROM audit WHERE action = 'licence.auto'"), 1)

    def test_a_refusal_shows_why_and_a_new_request_can_follow(self):
        self.relay.auto = lambda r: ('refuse', 'already_used')
        st = self.ask()[1]
        self.assertEqual((st['status'], st['reason']), ('refused', 'already_used'))
        self.assertEqual(self.owner.post('/api/licence/request/clear')[1]['status'], 'none')
        self.relay.auto = None
        self.assertEqual(self.ask('monthly', ref='InstaPay 55')[1]['status'], 'waiting')
        self.assertEqual(self.relay.last()['body']['ref'], 'InstaPay 55')

    def test_who_may_ask(self):
        self.owner.post('/api/licence/activate', {'code': code_for(self.device)})  # people can only be added with a working licence
        self.owner.post('/api/user/save', {'username': 'cash', 'full_name': 'Cash', 'role': 'cashier', 'password': PW})
        cashier = self.S.client()
        cashier.login('cash', PW)
        for method, path in (('get', '/api/licence/request'), ('get', '/api/licence/preview'), ('post', '/api/licence/request'),
                             ('post', '/api/licence/request/retry'), ('post', '/api/licence/request/clear')):
            self.assertEqual(getattr(cashier, method)(path)[0], 403, path)
        for path in ('/api/licence/request', '/api/licence/preview'):
            self.assertEqual(self.S.client().get(path)[0], 401, path)
        self.assertEqual(self.S.client().post('/api/licence/request', {'kind': 'trial'})[0], 401)
        self.assertEqual(self.relay.requests, {})

    def test_junk_input_is_a_calm_answer(self):
        for body in ({'kind': 'free'}, {'kind': None}, {'kind': ['trial']}, {}, {'kind': 'trial', 'ref': {'a': 1}}, {'kind': 'trial', 'ref': 'x' * 3000}):
            st, d, _ = self.owner.post('/api/licence/request', body)
            self.assertLess(st, 500, body)
            self.owner.post('/api/licence/request/clear')
        self.assertLessEqual(len(json.dumps(self.relay.last()['body'])) if self.relay.requests else 0, 1200)

    def test_a_working_licence_does_not_ask_for_a_trial(self):
        self.owner.post('/api/licence/activate', {'code': code_for(self.device)})
        st, d, _ = self.ask('trial')
        self.assertEqual((st, d['key']), (409, 'err.trialHave'))
        self.assertEqual(self.ask('monthly')[0], 200, 'but a subscription can be asked for at any time')

    def test_the_machine_tag_survives_a_reinstall_but_the_device_code_does_not(self):
        """A reinstall is a new database, so a new device code; the tag is what lets the company see it is the same PC."""
        from harness import Shop
        a, b = Shop(licensed=False), Shop(licensed=False)
        try:
            self.assertNotEqual(licence.device(a.db), licence.device(b.db))
            self.assertEqual(trial.machine_tag(), trial.machine_tag())
            self.assertNotIn(licence._machine_id(), trial.machine_tag())
        finally:
            a.cleanup()
            b.cleanup()

    def test_the_relay_address_rules(self):
        for bad in ('http://example.com', 'ftp://x', 'https://user:pw@example.com', 'example.com'):
            os.environ['STORE_LICENCE_RELAY'] = bad
            self.assertEqual(trial.relay_url(self.app), '', bad)
        os.environ['STORE_LICENCE_RELAY'] = 'https://relay.example.workers.dev/'
        self.assertEqual(trial.relay_url(self.app), 'https://relay.example.workers.dev')
        os.environ.pop('STORE_LICENCE_RELAY')
        self.app.cfg['licence_relay'] = 'https://from-config.example'
        self.assertEqual(trial.relay_url(self.app), 'https://from-config.example')
        self.app.practice = True
        try:
            self.assertEqual(trial.relay_url(self.app), '', 'the practice shop never asks the company')
        finally:
            self.app.practice = False

    def test_the_telegram_contact_for_the_manual_way_is_a_link_or_nothing(self):
        import app as app_mod
        self.assertEqual(app_mod.vendor_telegram('@alstore_support'), 'https://t.me/alstore_support')
        self.assertEqual(app_mod.vendor_telegram('https://t.me/alstore_support'), 'https://t.me/alstore_support')
        for bad in ('', None, 'javascript:alert(1)', 'https://evil.example/t.me/abc12', '@a', 'https://t.me/', '@bad name'):
            self.assertEqual(app_mod.vendor_telegram(bad), '', bad)
        self.app.cfg['vendor_telegram'] = '@alstore_support'
        self.assertEqual(self.owner.get('/api/licence')[1]['vendor_telegram'], 'https://t.me/alstore_support')


if __name__ == '__main__':
    unittest.main()
