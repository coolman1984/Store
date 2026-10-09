"""Consent gates telemetry. Decline and withdraw delete that person's queued events. Nothing is sent by default."""
import json
import unittest

import aftelemetry
from harness import PW, Server


def _pending(tel):
    return tel.pending()


class Privacy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Server()
        cls.owner = cls.S.client()
        me = cls.owner.login()
        cls.owner_id = me['user']['id']
        st, d, _ = cls.owner.post('/api/user/save', {'username': 'cash', 'full_name': 'Cashier', 'role': 'cashier', 'password': PW})
        assert st == 200, d
        cls.cash_id = d['id']
        cls.cash = cls.S.client()
        cls.cash.login('cash', PW)
        cls.tel = cls.S.app.assist.tel

    def setUp(self):
        self.tel.db.execute('DELETE FROM outbox')
        self.S.app.db.run('DELETE FROM consent_log')
        self.S.app.cfg['telemetry_url'] = ''
        self.S.app.cfg['telemetry_token'] = ''

    @classmethod
    def tearDownClass(cls):
        cls.S.app.assist.close()
        cls.S.stop()

    def test_nothing_is_queued_without_consent_and_forbidden_fields_are_refused(self):
        self.assertEqual(_pending(self.tel), [])
        self.assertIsNone(self.tel.emit('use.page', {'page': 'home'}, user=self.owner_id, role='owner', page='home'))
        self.assertEqual(_pending(self.tel), [])
        with self.assertRaises(aftelemetry.PrivacyError):
            self.tel.emit('use.page', {'page': 'home', 'password': 'secret'}, user=self.owner_id, role='owner', page='home')
        with self.assertRaises(aftelemetry.PrivacyError):
            self.tel.emit('use.page', {'page': 'home', 'name': 'Ali'}, user=self.owner_id, role='owner', page='home')
        self.assertEqual(_pending(self.tel), [])

    def test_decline_and_withdraw_purge_only_that_person(self):
        st, prompt, _ = self.owner.get('/api/consent/prompt?lang=ar')
        self.assertEqual(st, 200)
        self.assertTrue(prompt['ask'])
        self.assertEqual(prompt['scope'], 'install')
        st, status, _ = self.owner.post('/api/consent/decide', {
            'decision': 'agree', 'text_id': prompt['text_id'], 'lang': prompt['lang'], 'scope': 'install'})
        self.assertEqual(st, 200, status)
        self.assertTrue(status['tracking'])
        self.assertIsNotNone(self.tel.emit('use.page', {'page': 'home'}, user=self.owner_id, role='owner', page='home'))

        st, cash_prompt, _ = self.cash.get('/api/consent/prompt?lang=en')
        self.assertTrue(cash_prompt['ask'])
        self.assertEqual(cash_prompt['scope'], 'person')
        st, _, _ = self.cash.post('/api/consent/decide', {
            'decision': 'agree', 'text_id': cash_prompt['text_id'], 'lang': cash_prompt['lang'], 'scope': 'person'})
        self.assertEqual(st, 200)
        out = self.tel.from_browser(
            [{'type': 'use.page', 'data': {'page': 'pos'}, 'page': 'pos', 'user': self.owner_id}],
            self.cash_id, role='cashier')
        self.assertEqual(out['queued'], 1)
        subjects = {ev['subject'] for ev in _pending(self.tel)}
        self.assertIn(self.tel.subject(self.cash_id), subjects)
        self.assertNotEqual(self.tel.subject(self.cash_id), self.tel.subject(self.owner_id))

        st, _, _ = self.owner.post('/api/consent/decide', {
            'decision': 'decline', 'text_id': prompt['text_id'], 'lang': prompt['lang'], 'scope': 'person'})
        self.assertEqual(st, 200)
        left = _pending(self.tel)
        self.assertTrue(left)
        self.assertNotIn(self.tel.subject(self.owner_id), {ev['subject'] for ev in left})
        self.assertIn(self.tel.subject(self.cash_id), {ev['subject'] for ev in left})

        st, _, _ = self.cash.post('/api/consent/decide', {
            'decision': 'withdraw', 'text_id': cash_prompt['text_id'], 'lang': cash_prompt['lang'], 'scope': 'person'})
        self.assertEqual(st, 200)
        self.assertEqual(_pending(self.tel), [])

    def test_browser_batch_ignores_a_user_in_the_body_and_bad_events(self):
        self.owner.post('/api/consent/decide', {
            'decision': 'agree', 'text_id': 'consent.help.remote.ar.v1', 'lang': 'ar', 'scope': 'install'})
        self.cash.post('/api/consent/decide', {
            'decision': 'agree', 'text_id': 'consent.help.remote.en.v1', 'lang': 'en', 'scope': 'person'})
        st, out, _ = self.cash.post('/api/telemetry/events', {'events': [
            {'type': 'use.page', 'data': {'page': 'sales'}, 'page': 'sales', 'user': self.owner_id},
            {'type': 'use.page', 'data': {'page': 'sales', 'password': 'nope'}, 'page': 'sales'},
            {'type': 'hb', 'data': {'people': 1}},
        ]})
        self.assertEqual(st, 200, out)
        self.assertEqual(out['queued'], 1)
        self.assertGreaterEqual(out['rejected'], 1)
        mine = [ev for ev in _pending(self.tel) if ev.get('data', {}).get('page') == 'sales' and ev['type'] == 'use.page']
        self.assertTrue(mine)
        self.assertEqual(mine[0]['subject'], self.tel.subject(self.cash_id))
        blob = json.dumps(_pending(self.tel))
        self.assertNotIn('password', blob)
        self.assertNotIn('nope', blob)

    def test_capture_keeps_the_type_not_the_message(self):
        self.owner.post('/api/consent/decide', {
            'decision': 'agree', 'text_id': 'consent.help.remote.ar.v1', 'lang': 'ar', 'scope': 'install'})
        try:
            raise RuntimeError('customer-phone-01099887766 and the password secret')
        except RuntimeError as e:
            self.S.app.assist.capture(e, '/api/pos/sell')
        blob = json.dumps(_pending(self.tel))
        self.assertIn('RuntimeError', blob)
        self.assertNotIn('01099887766', blob)
        self.assertNotIn('secret', blob)
        self.assertNotIn('customer-phone', blob)

    def test_remote_send_stays_off_until_url_and_token_are_both_set(self):
        info = self.S.app.assist.receiver_public()
        self.assertFalse(info['sending'])
        self.assertEqual(info['url'], '')
        self.assertFalse(info['has_token'])
        n = len(_pending(self.tel))
        self.assertIsNone(self.S.app.assist.flush_remote())
        self.assertEqual(len(_pending(self.tel)), n)
        st, bad, _ = self.owner.post('/api/telemetry/config', {'url': 'http://evil.example/collect'})
        self.assertEqual(st, 400, bad)
        self.assertFalse(self.S.app.assist.receiver_public()['sending'])
        st, ok, _ = self.owner.post('/api/telemetry/config', {'url': 'http://127.0.0.1:9/collect'})
        self.assertEqual(st, 200, ok)
        self.assertFalse(ok['sending'])
        self.assertIsNone(self.S.app.assist.flush_remote())
        st, on, _ = self.owner.post('/api/telemetry/config', {'url': 'http://127.0.0.1:9/collect', 'token': 'shop-token'})
        self.assertEqual(st, 200, on)
        self.assertTrue(on['sending'])
        self.assertNotIn('shop-token', json.dumps(on))
        st, off, _ = self.owner.post('/api/telemetry/config', {'url': '', 'clear_token': True})
        self.assertEqual(st, 200, off)
        self.assertFalse(off['sending'])
        self.assertIsNone(self.S.app.assist.flush_remote())

    def test_cashier_cannot_set_the_receiver(self):
        st, _, _ = self.cash.post('/api/telemetry/config', {'url': 'https://example.com/in'})
        self.assertEqual(st, 403)
        st, d, _ = self.cash.get('/api/telemetry/config')
        self.assertEqual(st, 403, d)


if __name__ == '__main__':
    unittest.main()
