"""The protected copy outside this PC (Solo plan D1, factory `off_device_cloud_restore`): sealed with the owner's phrase, versioned in a folder
that leaves the PC, never in the way of a sale, and opened again on a different PC that was never set up (server/offsite.py)."""
import os
import shutil
import sqlite3
import tempfile
import unittest

from harness import HAVE_CRYPTO, OWNER, PW, Server, Shop

import offsite


def tiny_db(path, org='shop-1', kind=None, schema='4'):
    c = sqlite3.connect(path)
    c.execute('CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)')
    c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)')
    c.executemany('INSERT INTO meta VALUES (?, ?)', [('schema', schema), ('org_id', org)] + ([('shop_kind', kind)] if kind else []))
    c.execute("INSERT INTO settings VALUES ('shop_name', '\"Test shop\"')")
    c.execute('CREATE TABLE rows(x TEXT)')
    c.executemany('INSERT INTO rows VALUES (?)', [(f'row {i} ' * 20,) for i in range(3000)])
    c.commit()
    c.close()


class Sealing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='offsite-')
        self.db = os.path.join(self.dir, 'store.db')
        tiny_db(self.db)
        self.out = os.path.join(self.dir, 'usb', offsite.FOLDER)
        self.phrase, self.salt = offsite.new_phrase(), offsite.new_salt()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def sealed(self):
        item = offsite.seal(self.db, self.out, self.phrase, self.salt, 'shop-1')
        return os.path.join(self.out, item['name'])

    def test_the_copy_comes_back_byte_for_byte_and_is_not_readable_without_the_phrase(self):
        path = self.sealed()
        with open(path, 'rb') as f:
            data = f.read()
        self.assertNotIn(b'SQLite format 3', data)
        self.assertNotIn(b'row 1', data)
        self.assertNotIn(self.phrase.encode(), data)
        back = os.path.join(self.dir, 'back.db')
        header = offsite.unseal(path, self.phrase, back)
        with open(self.db, 'rb') as a, open(back, 'rb') as b:
            self.assertEqual(a.read(), b.read())
        self.assertEqual(header['org_id'], 'shop-1')
        self.assertEqual(offsite.db_facts(back)['shop_name'], 'Test shop')

    def test_the_phrase_is_read_the_way_a_person_types_it(self):
        path = self.sealed()
        typed = self.phrase.lower().replace('-', ' ')
        offsite.unseal(path, typed, os.path.join(self.dir, 'back.db'))
        self.assertEqual(len(offsite.normal(self.phrase)), 24)
        self.assertEqual(offsite.normal('ab-٢٣ ۴'), 'AB234')
        self.assertFalse(set(offsite.normal(self.phrase)) & set('O0I1L'))

    def test_a_wrong_phrase_a_changed_byte_and_a_cut_file_are_refused_before_anything_is_written(self):
        path = self.sealed()
        back = os.path.join(self.dir, 'back.db')
        with self.assertRaises(offsite.SealError) as e:
            offsite.unseal(path, offsite.new_phrase(), back)
        self.assertEqual(e.exception.key, 'err.offsitePhrase')
        with self.assertRaises(offsite.SealError):
            offsite.unseal(path, '', back)
        with open(path, 'rb') as f:
            data = bytearray(f.read())
        changed = os.path.join(self.out, 'alstore-20200101-000000.alstore')
        data[len(data) // 2] ^= 1
        with open(changed, 'wb') as f:
            f.write(data)
        with self.assertRaises(offsite.SealError) as e:
            offsite.unseal(changed, self.phrase, back)
        self.assertEqual(e.exception.key, 'err.offsitePhrase')
        with open(changed, 'wb') as f:
            f.write(bytes(data[:len(data) // 3]))
        with self.assertRaises(offsite.SealError):
            offsite.unseal(changed, self.phrase, back)
        self.assertFalse(os.path.exists(back))
        self.assertFalse(os.path.exists(back + '.part'))

    def test_a_changed_header_is_refused_before_any_key_is_made(self):
        import json
        import struct
        import time
        path = self.sealed()
        with open(path, 'rb') as f:
            data = f.read()
        start = len(offsite.MAGIC) + 4
        size = struct.unpack('>I', data[len(offsite.MAGIC):start])[0]
        header = json.loads(data[start:start + size])
        for change in ({'iterations': 10 ** 12}, {'iterations': 2 ** 80}, {'iterations': 5}, {'iterations': '200000'}, {'kdf': 'none'},
                       {'salt': 'not base64!'}, {'nonce': 'AAAA'}):
            raw = json.dumps({**header, **change}).encode()
            bad = os.path.join(self.dir, 'bad.alstore')
            with open(bad, 'wb') as f:
                f.write(offsite.MAGIC + struct.pack('>I', len(raw)) + raw + data[start + size:])
            began = time.time()
            with self.assertRaises(offsite.SealError) as e:
                offsite.unseal(bad, self.phrase, os.path.join(self.dir, 'back.db'))
            self.assertEqual(e.exception.key, 'err.offsiteBroken', change)
            self.assertLess(time.time() - began, 5, change)

    def test_an_unplugged_drive_is_not_the_pcs_own_disk_and_does_not_hang(self):
        from unittest import mock
        real_exists = os.path.exists
        # on Windows an unplugged E:\\ has no existing root at all; on this OS the same is made by hiding everything under /
        with mock.patch('offsite.os.path.exists', lambda p: False if p.startswith(os.sep + 'no-such') or p == os.sep else real_exists(p)):
            self.assertFalse(offsite.same_disk(os.path.join(os.sep, 'no-such-root-xyz', 'Al-Store-Backup'), self.dir))

    def test_a_file_that_is_not_ours_is_named_as_such(self):
        other = os.path.join(self.dir, 'notes.alstore')
        with open(other, 'wb') as f:
            f.write(b'hello')
        self.assertIsNone(offsite.peek(other))
        with self.assertRaises(offsite.SealError) as e:
            offsite.unseal(other, self.phrase, os.path.join(self.dir, 'back.db'))
        self.assertEqual(e.exception.key, 'err.offsiteNotOurs')

    def test_every_copy_is_a_new_version_and_the_oldest_go_beyond_the_limit(self):
        names = [offsite.seal(self.db, self.out, self.phrase, self.salt, 'shop-1', keep=4)['name'] for _ in range(6)]
        self.assertEqual(len(set(names)), 6)  # never overwritten, even in the same second
        left = [i['name'] for i in offsite.listing(self.out)]
        self.assertEqual(left, sorted(names, reverse=True)[:4])
        offsite.prune(self.out, keep=1)
        self.assertEqual(len(offsite.listing(self.out)), 3)  # never fewer than three versions
        self.assertFalse([n for n in os.listdir(self.out) if n.endswith('.part')])

    def test_the_folders_are_searched_for_copies(self):
        self.sealed()
        os.environ['STORE_OFFSITE_PLACES'] = os.path.join(self.dir, 'usb')
        try:
            found = offsite.find_copies()
        finally:
            del os.environ['STORE_OFFSITE_PLACES']
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]['path'].endswith('.alstore'))


@unittest.skipUnless(HAVE_CRYPTO, 'needs the cryptography package to sign test licence codes')
class OnTheShopPC(unittest.TestCase):
    def setUp(self):
        self.S = Server()
        self.usb = tempfile.mkdtemp(prefix='usb-')
        self.folder = os.path.join(self.usb, offsite.FOLDER)
        os.environ['STORE_OFFSITE_PLACES'] = self.usb  # the stick this test plugs in
        self.c = self.S.client()
        self.c.login()

    def tearDown(self):
        os.environ.pop('STORE_OFFSITE_PLACES', None)
        self.S.stop()
        shutil.rmtree(self.usb, ignore_errors=True)

    def enable(self, folder=None):
        st, d, _ = self.c.post('/api/offsite/enable', {'dir': folder or self.folder, 'password': OWNER[1]})
        self.assertEqual(st, 200, d)
        return d

    def test_turning_it_on_asks_the_password_shows_the_phrase_once_and_makes_the_first_copy(self):
        st, d, _ = self.c.post('/api/offsite/enable', {'dir': self.folder, 'password': 'wrong'})
        self.assertEqual(d['key'], 'auth.err.wrong')
        self.assertFalse(os.path.exists(self.folder))
        d = self.enable()
        self.assertRegex(d['phrase'], r'^[A-Z2-9]{4}(-[A-Z2-9]{4}){5}$')
        self.assertTrue(d['copy']['ok'])
        self.assertEqual(len(offsite.listing(self.folder)), 1)
        self.assertTrue(d['status']['on'])
        again = self.enable(os.path.join(self.usb, 'other'))
        self.assertIsNone(again['phrase'])  # the paper stays the same when only the folder changes
        st, d, _ = self.c.post('/api/offsite/phrase', {'password': OWNER[1]})
        self.assertEqual((st, d['phrase']), (200, self.S.app.cfg['offsite_phrase']))
        actions = [r['action'] for r in self.S.app.db.all("SELECT action FROM audit WHERE action LIKE 'offsite.%'")]
        self.assertIn('offsite.enable', actions)
        self.assertIn('offsite.phrase', actions)

    def test_every_backup_also_goes_off_the_pc_and_the_home_page_stops_asking(self):
        st, home, _ = self.c.get('/api/home')
        self.assertIn('offsite_off', [a['id'] for a in home['advisor']])
        self.enable()
        st, d, _ = self.c.post('/api/backup/now')
        self.assertEqual(st, 200, d)
        self.assertTrue(d['offsite']['ok'])
        self.S.app.backup_now()  # the automatic copy every few hours
        self.S.app.backup_now('before-restore')  # a restore's safety copy stays on this PC
        self.assertEqual(len(offsite.listing(self.folder)), 3)
        st, home, _ = self.c.get('/api/home')
        self.assertFalse({'offsite_off', 'offsite_old'} & {a['id'] for a in home['advisor']})

    def test_a_missing_usb_stick_never_stops_the_shop(self):
        self.enable()
        blocker = os.path.join(self.usb, 'a-file')
        with open(blocker, 'w') as f:
            f.write('x')
        self.S.app.save_cfg(offsite_dir=os.path.join(blocker, 'gone'))
        st, d, _ = self.c.post('/api/backup/now')
        self.assertEqual(st, 200, d)
        self.assertFalse(d['offsite']['ok'])
        st, s, _ = self.c.get('/api/offsite')
        self.assertFalse(s['reachable'])
        self.assertFalse(s['last']['ok'])
        st, home, _ = self.c.get('/api/home')
        self.assertIn('offsite_old', [a['id'] for a in home['advisor']])

    def test_bad_folders_are_refused_in_words(self):
        elsewhere = tempfile.mkdtemp(prefix='not-a-stick-')
        self.addCleanup(shutil.rmtree, elsewhere, True)
        for folder, key in (('relative/folder', 'err.offsiteFolder'), (os.path.join(self.S.dir, 'backups', 'x'), 'err.offsiteNotOff'), ('', 'err.offsiteFolder'),
                            (elsewhere, 'err.offsiteNotOff')):
            st, d, _ = self.c.post('/api/offsite/enable', {'dir': folder, 'password': OWNER[1]})
            self.assertEqual((st, d['key']), (400, key), folder)

    def test_only_a_person_with_the_settings_permission_may_touch_it(self):
        owner = self.S.client()
        owner.login()
        st, d, _ = owner.post('/api/user/save', {'username': 'cash1', 'full_name': 'Cash', 'role': 'cashier', 'password': PW})
        self.assertEqual(st, 200, d)
        c = self.S.client()
        c.login('cash1', PW)
        for path in ('/api/offsite/enable', '/api/offsite/now', '/api/offsite/phrase', '/api/offsite/restore', '/api/offsite/disable'):
            st, d, _ = c.post(path, {'dir': self.folder, 'password': PW})
            self.assertEqual(st, 403, (path, d))
        self.assertEqual(c.get('/api/offsite')[0], 403)
        self.assertEqual(c.get('/api/offsite/find')[0], 403)

    def test_the_same_shop_goes_back_to_a_protected_copy_after_a_safety_copy(self):
        phrase = self.enable()['phrase']
        name = offsite.listing(self.folder)[0]['name']
        st, d, _ = self.c.post('/api/product/save', {'name': 'After the copy', 'retail': 1000})
        self.assertEqual(st, 200, d)
        path = os.path.join(self.folder, name)
        st, d, _ = self.c.post('/api/offsite/restore', {'path': path, 'phrase': 'WRONG-WRONG', 'password': OWNER[1]})
        self.assertEqual((st, d['key']), (400, 'err.offsitePhrase'))
        st, d, _ = self.c.post('/api/offsite/restore', {'path': path, 'phrase': phrase, 'password': OWNER[1]})
        self.assertEqual(st, 200, d)
        self.assertIsNone(self.S.app.db.value("SELECT 1 FROM products WHERE name = 'After the copy'"))
        self.assertTrue([b for b in os.listdir(self.S.app.backup_dir) if 'before-restore' in b])
        self.assertTrue(self.c.login())

    def test_a_copy_outside_the_places_or_with_another_name_is_not_opened(self):
        phrase = self.enable()['phrase']
        name = offsite.listing(self.folder)[0]['name']
        elsewhere = tempfile.mkdtemp(prefix='not-a-stick-')
        self.addCleanup(shutil.rmtree, elsewhere, True)
        for copy in (os.path.join(elsewhere, name), os.path.join(self.folder, 'renamed.alstore')):
            shutil.copy(os.path.join(self.folder, name), copy)
        for path in (os.path.join(elsewhere, name), os.path.join(self.folder, 'renamed.alstore'), os.path.join(self.folder, '..', '..', name)):
            st, d, _ = self.c.post('/api/offsite/restore', {'path': path, 'phrase': phrase, 'password': OWNER[1]})
            self.assertEqual((st, d['key']), (400, 'err.offsiteNotFound'), path)

    def test_two_restores_at_once_take_turns(self):
        import threading
        phrase = self.enable()['phrase']
        path = os.path.join(self.folder, offsite.listing(self.folder)[0]['name'])
        out = []

        def restore():
            c = self.S.client()
            c.login()
            out.append(c.post('/api/offsite/restore', {'path': path, 'phrase': phrase, 'password': OWNER[1]})[0])

        threads = [threading.Thread(target=restore) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(out, [200, 200, 200])
        self.assertFalse([n for n in os.listdir(os.path.dirname(self.S.app.db.path)) if '.unsealed' in n])

    def test_a_copy_of_another_shop_or_of_the_practice_shop_is_refused(self):
        self.enable()
        work = tempfile.mkdtemp(prefix='other-', dir=self.usb)
        try:
            for org, kind, key in (('someone-else', None, 'err.backupOtherShop'), (self.S.app.org_id, 'practice', 'err.offsitePractice')):
                db = os.path.join(work, f'{org}-{kind}.db')
                tiny_db(db, org, kind)
                item = offsite.seal(db, work, 'ABCD-EFGH', offsite.new_salt(), org)
                st, d, _ = self.c.post('/api/offsite/restore', {'path': os.path.join(work, item['name']), 'phrase': 'abcdefgh', 'password': OWNER[1]})
                self.assertEqual((st, d['key']), (400, key))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_it_keeps_working_while_the_licence_is_locked(self):
        S = Server(licensed=False)
        try:
            c = S.client()
            c.login()
            st, d, _ = c.post('/api/offsite/enable', {'dir': self.folder, 'password': OWNER[1]})
            self.assertEqual(st, 200, d)
            st, d, _ = c.post('/api/offsite/now')
            self.assertEqual(st, 200, d)
            self.assertTrue(d['ok'])
        finally:
            S.stop()


@unittest.skipUnless(HAVE_CRYPTO, 'needs the cryptography package to sign test licence codes')
class OnADifferentPC(unittest.TestCase):
    """The old PC is gone. A new PC, never set up, takes the shop back from the USB stick with the phrase on the paper."""

    def test_the_shop_comes_back_with_its_people_goods_and_paper(self):
        old = Shop()
        usb = tempfile.mkdtemp(prefix='usb-')
        folder = os.path.join(usb, offsite.FOLDER)
        new = Server(setup=False)
        os.environ['STORE_OFFSITE_PLACES'] = usb
        try:
            old.product('Washing machine', qty=4)
            phrase = old.app.offsite_enable(folder)['phrase']
            c = new.client()
            st, d, _ = c.get('/api/offsite/find')
            self.assertEqual(st, 200, d)
            self.assertEqual(len(d['copies']), 1)
            path = d['copies'][0]['path']
            st, d, _ = c.post('/api/offsite/restore-new', {'path': path, 'phrase': 'NOT-THE-PAPER'})
            self.assertEqual((st, d['key']), (400, 'err.offsitePhrase'))
            self.assertTrue(new.app.setup_needed())
            st, d, _ = c.post('/api/offsite/restore-new', {'path': path, 'phrase': phrase.lower()})
            self.assertEqual(st, 200, d)
            self.assertEqual(d['shop_name'], 'Test shop')
            self.assertFalse(new.app.setup_needed())
            self.assertEqual(new.app.org_id, old.app.org_id)
            c.login()  # the same owner and password as on the old PC
            st, d, _ = c.get('/api/boot')
            self.assertEqual(d['shop_name'], 'Test shop')
            self.assertEqual(new.app.db.value("SELECT name FROM products"), 'Washing machine')
            self.assertEqual(new.app.cfg['offsite_phrase'], phrase)  # the same paper keeps working on the new PC
            # a USB stick or a synced folder goes on receiving copies; a folder on the PC's own disk (this test's temp folder) is not kept
            self.assertEqual(new.app.cfg.get('offsite_dir'), None if offsite.same_disk(folder, new.dir) else folder)
            if not new.app.cfg.get('offsite_dir'):
                st, d, _ = c.post('/api/offsite/enable', {'dir': folder, 'password': OWNER[1]})
                self.assertEqual(st, 200, d)
                self.assertIsNone(d['phrase'])
            st, d, _ = c.post('/api/offsite/restore-new', {'path': path, 'phrase': phrase})
            self.assertEqual(st, 409, d)  # only a PC that is not set up yet
            st, d, _ = c.post('/api/backup/now')
            self.assertEqual(st, 200, d)
            self.assertTrue(d['offsite']['ok'])
        finally:
            os.environ.pop('STORE_OFFSITE_PLACES', None)
            new.stop()
            old.cleanup()
            shutil.rmtree(usb, ignore_errors=True)

    def test_a_newer_copy_is_refused_and_the_new_pc_stays_empty(self):
        new = Server(setup=False)
        work = tempfile.mkdtemp(prefix='newer-')
        os.environ['STORE_OFFSITE_PLACES'] = work
        try:
            db = os.path.join(work, 'newer.db')
            tiny_db(db, schema='99')
            item = offsite.seal(db, work, 'ABCD-EFGH', offsite.new_salt(), 'shop-1')
            st, d, _ = new.client().post('/api/offsite/restore-new', {'path': os.path.join(work, item['name']), 'phrase': 'ABCDEFGH'})
            self.assertEqual((st, d['key']), (400, 'err.offsiteNewer'))
            self.assertTrue(new.app.setup_needed())
        finally:
            os.environ.pop('STORE_OFFSITE_PLACES', None)
            new.stop()
            shutil.rmtree(work, ignore_errors=True)


class PracticeShop(unittest.TestCase):
    def test_the_practice_shop_has_no_protected_copy(self):
        S = Server(practice=True)
        try:
            self.assertFalse(S.app.offsite_on())
            from core import Problem
            with self.assertRaises(Problem):
                S.app.offsite_enable(tempfile.gettempdir())
        finally:
            S.stop()


if __name__ == '__main__':
    unittest.main()
