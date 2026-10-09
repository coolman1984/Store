"""Consent gates telemetry. Decline and withdraw delete that person's queued events. Nothing is sent by default."""
import json
import gzip
import threading
import os
import unittest
from unittest import mock

from harness import PW, Server, Shop
import aftelemetry
import app as app_mod


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

    def test_free_text_report_is_redacted_and_confirmed_over_http(self):
        data = {'kind': 'problem', 'page': 'pos',
                'text': 'Sale screen freezes password=fixture-only phone 01000000000'}
        st, preview, _ = self.cash.post('/api/telemetry/feedback/preview', data)
        self.assertEqual(st, 200, preview)
        self.assertEqual(preview['event']['data']['text'],
                         'Sale screen freezes password=[SECRET] phone [PHONE]')
        confirmed = dict(data, confirm=preview['digest'])
        st, _, _ = self.cash.post('/api/telemetry/feedback', confirmed)
        self.assertEqual(st, 400)
        self.owner.post('/api/consent/decide', {'decision': 'agree', 'scope': 'install',
            'text_id': 'consent.help.remote.ar.v1', 'lang': 'ar'})
        st, _, _ = self.cash.post('/api/telemetry/feedback', confirmed)
        self.assertEqual(st, 400)  # shop approval alone never substitutes for this person's choice
        self.cash.post('/api/consent/decide', {'decision': 'agree', 'scope': 'person',
            'text_id': 'consent.help.remote.ar.v1', 'lang': 'ar'})
        st, _, _ = self.cash.post('/api/telemetry/feedback', data)
        self.assertEqual(st, 400)
        self.assertEqual(self.tel.pending(), [])
        st, saved, _ = self.cash.post('/api/telemetry/feedback', confirmed)
        self.assertEqual(st, 200, saved)
        event = next(e for e in self.tel.pending() if e['id'] == saved['id'])
        self.assertEqual(event['data'], preview['event']['data'])
        self.assertEqual(event['subject'], self.tel.subject(self.cash_id))
        self.assertNotIn('fixture-only', json.dumps(event))
        self.assertNotIn('01000000000', json.dumps(event))


class GluePrivacy(unittest.TestCase):
    """Real SQLite and factory APIs, including concurrent sends, without a network server."""

    def setUp(self):
        self.shop = Shop()
        self.app = self.shop.app
        self.assist = self.app.assist
        self.owner = self.shop.users['owner']
        self.cash = self.shop.user('cashier', 'cash')

    def tearDown(self):
        self.assist.close()
        self.shop.cleanup()

    def decide(self, decision='agree', scope='install', user=None):
        return self.assist.decide(user or self.owner, {'decision': decision, 'scope': scope,
            'text_id': 'consent.help.remote.ar.v1', 'lang': 'ar'})

    def configured(self):
        self.assist.save_receiver({'url': 'https://example.invalid/events', 'token': 'test-token'})

    def test_invalid_consent_is_rejected_before_any_write_or_purge(self):
        self.decide()
        self.assist.note_action(self.owner, 'sale.pay', 'pos')
        count = self.app.db.value('SELECT COUNT(*) FROM consent_log')
        queued = self.assist.tel.pending()
        for key in ('decision', 'scope', 'text_id', 'lang'):
            for value in ([], {}, None, 'invalid'):
                with self.subTest(key=key, value=value):
                    data = {'decision': 'agree', 'scope': 'install',
                            'text_id': 'consent.help.remote.ar.v1', 'lang': 'ar'}
                    data[key] = value
                    with self.assertRaises(ValueError):
                        self.assist.decide(self.owner, data)
                    self.assertEqual(self.app.db.value('SELECT COUNT(*) FROM consent_log'), count)
                    self.assertEqual(self.assist.tel.pending(), queued)

    def test_shop_agreement_never_overrides_a_persons_decline_or_withdrawal(self):
        self.decide()
        for decision in ('decline', 'withdraw'):
            self.decide(decision, 'person')
            self.decide('withdraw')
            status = self.decide()
            self.assertFalse(status['tracking'])
            self.assertEqual(status['person']['decision'], decision)
            self.assertFalse(self.assist.prompt_for(self.owner, 'ar')['ask'])
        self.assertTrue(self.assist.prompt_for(self.cash, 'en')['ask'])

    def test_prompt_and_permission_follow_both_consent_levels(self):
        from auth import Forbidden
        self.assertFalse(self.assist.prompt_for(self.cash, 'en')['ask'])
        self.assertEqual(self.assist.prompt_for(self.owner, 'ar')['scope'], 'install')
        with self.assertRaises(Forbidden):
            self.decide(user=self.cash)
        self.decide()
        self.assertTrue(self.assist.prompt_for(self.cash, 'en')['ask'])
        self.decide('decline', 'person', self.cash)
        self.assertFalse(self.assist.prompt_for(self.cash, 'en')['ask'])

    def test_browser_junk_is_rejected_without_a_server_error(self):
        self.decide()
        events = [{'type': [], 'data': {}}, {'type': 'use.page', 'data': []}, None,
                  {'type': 'use.page', 'data': {'page': 'home'}, 'page': 'home'}]
        result = self.assist.browser_events(self.owner, events)
        self.assertEqual(result, {'queued': 1, 'dropped': 0, 'rejected': 3})

    def test_names_cannot_be_disguised_as_context_ids(self):
        self.decide()
        result = self.assist.browser_events(self.owner, [
            {'type': 'use.page', 'data': {'page': 'Alice'}, 'page': 'home'},
            {'type': 'guide.start', 'data': {'guide': 'Alice'}},
            {'type': 'err.client', 'data': {'code': 'Error', 'fingerprint': 'abcdefgh', 'where': 'Alice:7'}},
        ])
        self.assertEqual(result['rejected'], 3)
        self.assertEqual(self.assist.tel.pending(), [])
        with self.assertRaises(aftelemetry.PrivacyError):
            self.assist.preview({'kind': 'problem', 'page': 'Alice'})

    def test_rolled_back_consent_cannot_be_seen_by_a_browser_event_thread(self):
        attempted, finished = threading.Event(), threading.Event()
        errors = []
        def emit():
            attempted.set()
            try:
                self.assist.note_action(self.owner, 'sale.pay', 'pos')
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()
        with self.assertRaises(RuntimeError):
            with self.app.db.tx():
                self.assist.consent.record('install', '', 'agree', 'consent.help.remote.ar.v1', 'ar', self.owner['id'])
                self.assist.consent.record('person', self.owner['id'], 'agree', 'consent.help.remote.ar.v1', 'ar', self.owner['id'])
                worker = threading.Thread(target=emit)
                worker.start()
                self.assertTrue(attempted.wait(1))
                self.assertFalse(finished.wait(.05), 'event thread read an uncommitted decision')
                raise RuntimeError('roll back')
        worker.join(2)
        self.assertTrue(finished.is_set())
        self.assertEqual(errors, [])
        self.assertEqual(self.assist.tel.pending(), [])

    def test_redirects_do_not_forward_receiver_tokens(self):
        self.decide()
        self.configured()
        self.assist.note_action(self.owner, 'sale.pay', 'pos')
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 302
        response.read.return_value = b'{}'
        response.headers.get.return_value = None
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch('assist.urllib.request.build_opener', return_value=opener) as build:
            self.assertEqual(self.assist.flush_remote(), ('failed', 302))
        redirect = build.call_args.args[0]
        self.assertIsNone(redirect.redirect_request(None, None, 302, 'redirect', {}, 'http://evil.invalid'))
        self.assertEqual(opener.open.call_count, 1)

    def test_old_reports_and_events_without_current_consent_are_purged_before_send(self):
        # The factory allowed reports without consent. The product still requires both scopes.
        self.assist.tel.db.execute("INSERT INTO outbox (id, created, type, prio, subject, body, size) VALUES (?,?,?,?,?,?,?)",
            ('legacy', 1, 'fb.problem', 0, None, json.dumps({'type': 'fb.problem', 'data': {'text': 'private'}}), 1))
        self.configured()
        with mock.patch.object(self.assist, '_post_remote') as send:
            self.assertEqual(self.assist.flush_remote(), ('idle', 0))
        send.assert_not_called()
        self.assertEqual(self.assist.tel.pending(), [])

    def test_receiver_hostname_and_type_checks_and_no_partial_config_write(self):
        from core import Problem
        for url in ('http://localhost.evil.invalid/in', 'http://127.0.0.1.evil.invalid/in',
                    'http://localhost@evil.invalid/in', 'https://', 'https://example.invalid:bad/in',
                    'https://example.invalid/#fragment', 'https://example.invalid/\n'):
            with self.subTest(url=url), self.assertRaises(Problem):
                self.assist.save_receiver({'url': url})
        for data in ({'url': []}, {'token': {}}, {'clear_token': 'false'}):
            with self.assertRaises(Problem):
                self.assist.save_receiver(data)
        old = dict(self.app.cfg)
        with mock.patch.object(self.assist, '_write_cfg', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.configured()
        self.assertEqual(self.app.cfg, old)
        self.app.cfg['telemetry_url'] = 42
        self.app.cfg['telemetry_token'] = []
        self.assertFalse(self.assist.receiver_public()['sending'])

    def test_network_send_releases_queue_lock_and_preserves_new_merged_counts(self):
        self.decide()
        self.configured()
        self.assist.note_action(self.owner, 'sale.pay', 'pos')
        entered, release, emitted = threading.Event(), threading.Event(), threading.Event()
        sent = []
        errors = []
        def post(url, body, headers):
            sent.extend(json.loads(gzip.decompress(body)))
            entered.set()
            if not release.wait(3):
                raise AssertionError('test transport did not finish')
            return 200
        def flush():
            try:
                self.assist.flush_remote()
            except Exception as exc:
                errors.append(exc)
        def emit():
            try:
                self.assist.note_action(self.owner, 'sale.pay', 'pos')
                emitted.set()
            except Exception as exc:
                errors.append(exc)
        with mock.patch.object(self.assist, '_post_remote', side_effect=post):
            sender = threading.Thread(target=flush)
            sender.start()
            try:
                self.assertTrue(entered.wait(2))
                worker = threading.Thread(target=emit)
                worker.start()
                self.assertTrue(emitted.wait(1), 'browser event blocked on the network timeout')
                self.assertIsNone(self.assist.flush_remote(), 'two simultaneous sends')
            finally:
                release.set()
                sender.join(3)
                if 'worker' in locals():
                    worker.join(3)
        self.assertFalse(sender.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sent[0]['data']['count'], 1)
        pending = self.assist.tel.pending()
        self.assertEqual(len(pending), 1)
        self.assertNotEqual(sent[0]['id'], pending[0]['id'])
        self.assertEqual(pending[0]['data']['count'], 1)

    def test_failed_send_keeps_batch_and_new_events_for_retry(self):
        self.decide()
        self.configured()
        self.assist.note_action(self.owner, 'sale.pay', 'pos')
        def post(*args):
            self.assist.note_action(self.owner, 'sale.pay', 'pos')
            raise OSError('offline')
        with mock.patch.object(self.assist, '_post_remote', side_effect=post):
            self.assertEqual(self.assist.flush_remote(), ('failed', 0))
        self.assertEqual(sum(e['data']['count'] for e in self.assist.tel.pending()), 2)

    def test_reports_need_consent_confirmation_and_redact_free_text(self):
        data = {'kind': 'problem', 'page': 'pos',
                'text': 'Sale screen freezes password=fixture-only phone 01000000000',
                'diagnostics': {'version': 'browser-supplied'}}
        preview = self.assist.preview(data)
        self.assertNotIn('diagnostics', preview['event']['data'])
        self.assertEqual(preview['event']['data']['text'],
                         'Sale screen freezes password=[SECRET] phone [PHONE]')
        with self.assertRaises(aftelemetry.PrivacyError):
            self.assist.feedback(self.owner, dict(data, confirm=preview['digest']))
        self.decide()
        with self.assertRaises(aftelemetry.PrivacyError):
            self.assist.feedback(self.owner, data)
        safe = dict(data, diagnostics=False, confirm=preview['digest'])
        for changed in ({'text': 'A different problem'}, {'page': 'cash'}, {'confirm': 'forged'}):
            with self.subTest(changed=changed), self.assertRaises(aftelemetry.PrivacyError):
                self.assist.feedback(self.owner, dict(safe, **changed))
        self.assertEqual(self.assist.tel.pending(), [])
        self.assertTrue(self.assist.feedback(self.owner, safe)['id'])
        blob = json.dumps(self.assist.tel.pending())
        self.assertNotIn('browser-supplied', blob)
        self.assertNotIn('fixture-only', blob)
        self.assertNotIn('01000000000', blob)
        self.assertEqual(self.assist.tel.pending()[0]['data'], preview['event']['data'])
        self.decide('withdraw', 'person')
        self.assertEqual(self.assist.tel.pending(), [])

    def test_diagnostic_snapshot_is_exact_and_cannot_be_forged(self):
        self.decide()
        data = {'kind': 'problem', 'page': 'pos', 'text': 'Sale screen freezes', 'diagnostics': True}
        preview = self.assist.preview(data)
        snapshot = preview['event']['data']['diagnostics']
        with mock.patch.object(self.assist, 'diagnostics', side_effect=AssertionError('must use preview')):
            out = self.assist.feedback(self.owner, dict(data, diagnostics=snapshot, confirm=preview['digest']))
        self.assertTrue(out['id'])
        self.assertEqual(self.assist.tel.pending()[0]['data']['diagnostics'], snapshot)
        with self.assertRaises(aftelemetry.PrivacyError):
            self.assist.feedback(self.owner, dict(data, diagnostics={'version': 'Alice'}, confirm=preview['digest']))

    def test_consented_factory_free_text_reports_survive_restart_rebind_and_send(self):
        from assist import Assist
        self.decide()
        preview = self.assist.tel.preview('problem', 'Existing free-text problem', page='pos')
        eid = self.assist.tel.feedback('problem', 'Existing free-text problem', page='pos',
                                       user=self.owner['id'], confirm=preview['digest'])
        self.assist.close()
        self.app.assist = self.assist = Assist(self.app)
        self.assist.rebind()
        self.assertEqual(self.assist.tel.pending()[0]['id'], eid)
        self.configured()
        batches = []
        def post(url, body, headers):
            batches.extend(json.loads(gzip.decompress(body)))
            return 200, None
        with mock.patch.object(self.assist, '_post_remote', side_effect=post):
            self.assertEqual(self.assist.flush_remote(), ('sent', 1))
        self.assertEqual(batches[0]['id'], eid)
        self.assertEqual(batches[0]['data'], preview['event']['data'])
        self.assertEqual(self.assist.tel.pending(), [])

    def test_reports_reject_unknown_context_and_empty_text(self):
        self.decide()
        data = {'kind': 'problem', 'text': 'Sale screen freezes', 'page': 'pos',
                'guide': 'make-sale', 'problem': 'err.noShift'}
        # Valid IDs in the catalogue are used below; every arbitrary context is rejected.
        data['problem'] = self.assist.catalogue['problems'][0]['id']
        for key in ('page', 'guide', 'problem'):
            for value in ('unknown-context', [], '01000000000'):
                with self.subTest(key=key, value=value), self.assertRaises(aftelemetry.PrivacyError):
                    self.assist.preview(dict(data, **{key: value}))
        for text in ('', '   ', [], None):
            empty = dict(data, text=text)
            preview = self.assist.preview(empty)
            with self.subTest(text=text), self.assertRaises(aftelemetry.PrivacyError):
                self.assist.feedback(self.owner, dict(empty, confirm=preview['digest']))
        self.assertEqual(self.assist.tel.pending(), [])

    def test_restore_rebinds_consent_and_purges_outbox_that_no_longer_has_consent(self):
        saved = self.app.backup_now('manual')
        self.decide()
        self.assist.note_action(self.owner, 'sale.pay', 'pos')
        self.assertTrue(self.assist.tel.pending())
        old_connection = self.app.db.conn
        self.app.restore(saved['name'])
        self.assertIsNot(self.app.db.conn, old_connection)
        self.assertIs(self.assist.consent.db, self.app.db.conn)
        self.assertFalse(self.assist.consent_status(self.owner)['tracking'])
        self.assertEqual(self.assist.tel.pending(), [])
        self.assertTrue(self.assist.guide_state(self.owner)['course'])

    def test_restore_copy_or_swap_failure_keeps_the_shop_usable(self):
        saved = self.app.backup_now('manual')
        self.decide()
        with mock.patch('app.shutil.copyfileobj', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.app.restore(saved['name'])
        self.assertTrue(self.assist.consent_status(self.owner)['tracking'])
        replace = os.replace
        def fail_swap(source, target):
            if source.endswith('.restoring'):
                raise OSError('swap failed')
            return replace(source, target)
        with mock.patch('app.os.replace', side_effect=fail_swap):
            with self.assertRaises(OSError):
                self.app.restore(saved['name'])
        self.assertTrue(self.assist.consent_status(self.owner)['tracking'])

    def test_person_cannot_see_other_peoples_sent_events(self):
        self.decide()
        self.decide('agree', 'person', self.cash)
        self.assist.note_action(self.owner, 'sale.pay', 'pos')
        self.assist.note_action(self.cash, 'shift.open', 'cash')
        self.assist.tel.mark_sent([e['id'] for e in self.assist.tel.pending()])
        rows = self.assist.sent_public(self.cash)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['page'], 'cash')

    def test_unknown_request_paths_do_not_leak_customer_identifiers(self):
        self.decide()
        self.assist.capture(RuntimeError('sensitive'), '/api/Alice/01099887766')
        event = self.assist.tel.pending()[0]
        self.assertEqual(event['data']['where'], 'server')

    def test_no_remote_send_inside_a_shop_write(self):
        self.decide()
        self.configured()
        self.assist.note_action(self.owner, 'sale.pay', 'pos')
        with mock.patch.object(self.assist, '_post_remote') as send, self.app.db.tx():
            self.assertIsNone(self.assist.flush_remote())
        send.assert_not_called()

    def test_new_routes_remain_available_when_licence_is_locked(self):
        self.app.db.run("DELETE FROM meta WHERE key = 'licence_code'")
        self.assertFalse(self.app.licence()['full'])
        handler = object.__new__(app_mod.Handler)
        handler.user = lambda: self.owner
        handler.ctx = lambda user: self.shop.ctx(user)
        handler.send = mock.Mock()
        with mock.patch.object(app_mod, 'APP', self.app):
            for path, body in (
                ('/api/guide/progress', {'update': {'op': 'done', 'guide': 'home-today'}}),
                ('/api/consent/decide', {'decision': 'decline', 'scope': 'install',
                    'text_id': 'consent.help.remote.ar.v1', 'lang': 'ar'}),
                ('/api/telemetry/events', {'events': []}),
                ('/api/telemetry/config', {'url': '', 'clear_token': True}),
            ):
                handler.body = lambda maximum, body=body: body
                handler.api_post(path)
                self.assertEqual(handler.send.call_args.args[0], 200)
            handler.body = lambda maximum: {'url': 'https://example.invalid/events', 'token': 'test-token'}
            with self.assertRaises(app_mod.LicenceLocked):
                handler.api_post('/api/telemetry/config')


if __name__ == '__main__':
    unittest.main()
