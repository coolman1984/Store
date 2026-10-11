"""People, profiles, pages and permissions (factory standard docs/ACCESS_AND_ADMINISTRATION_STANDARD.md, controls IAM-08..12).

The catalogue passes the factory gate (afaccess) with the words of both dictionaries; the menu and the server use the same
page table; nobody can lock the shop out of its people screen; profiles can be made, changed, applied and deleted; every
change is in the audit with what was added and removed; a 1.0 shop keeps exactly the rights it had."""
import json
import os
import re
import unittest

from harness import OWNER, PW, Server, Shop
import afaccess
import auth

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAIR = re.compile(r"""'([\w.]+)':\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")


def words(lang):
    with open(os.path.join(ROOT, 'web', 'i18n', lang + '.js'), encoding='utf-8') as f:
        return {k: a or b for k, a, b in PAIR.findall(f.read())}


LABELS = {'ar': words('ar')}


class Catalogue(unittest.TestCase):
    def test_factory_gate_passes_with_both_languages(self):
        found = afaccess.check(auth.catalogue(labels=LABELS))
        self.assertEqual([f for f in found if f.level == 'error'], [])
        self.assertEqual([f.code for f in found], [], 'warnings are worth a look too')

    def test_gate_would_catch_a_missing_arabic_word(self):
        labels = {'ar': {k: v for k, v in LABELS['ar'].items() if k != 'perm.stock.view'}}
        self.assertIn('label-missing', {f.code for f in afaccess.errors(auth.catalogue(labels=labels))})

    def test_menu_and_server_use_the_same_page_table(self):
        with open(os.path.join(ROOT, 'web', 'js', 'app.js'), encoding='utf-8') as f:
            js = f.read()
        routes = {}
        for name, body in re.findall(r"^  (\w+): \{ icon: '[\w-]+'(.*?)load:", js, re.M):
            m = re.search(r"perm: \[([^\]]*)\]", body)
            routes[name] = sorted(re.findall(r"'([\w.]+)'", m.group(1))) if m else '*'
        self.assertEqual(routes, {k: v if v == '*' else sorted(v) for k, v in auth.PAGES.items()})

    def test_ready_made_profile_names_match_the_dictionaries(self):
        en = words('en')
        for pid, (english, arabic) in auth.BUILTIN_NAMES.items():
            self.assertEqual((en['role.' + pid], LABELS['ar']['role.' + pid]), (english, arabic))
        self.assertEqual(set(auth.BUILTIN_NAMES), set(auth.ROLES))

    def test_owner_profile_has_everything_and_admin_rights_are_apart(self):
        self.assertEqual(set(auth.ROLES['owner']['perms']), set(auth.PERMISSIONS))
        self.assertEqual(auth.ADMIN_PERMS, {'users.manage', 'settings.edit'})
        for role in ('manager', 'cashier', 'storekeeper'):
            self.assertFalse(auth.ADMIN_PERMS & set(auth.ROLES[role]['perms']), role)


class Guards(unittest.TestCase):
    def setUp(self):
        self.S = Shop()
        self.owner = self.S.users['owner']
        self.boss = self.S.user('manager', 'boss')

    def tearDown(self):
        self.S.cleanup()

    def update(self, user, changes, actor):
        with self.S.db.tx():
            return self.S.app.auth.update(user['id'], changes, actor['id'])

    def test_the_1_0_lockout_is_refused(self):
        """1.0 let a removed tick take users.manage away from the only owner: the shop could no longer manage people."""
        for changes in ({'denied_perms': ['users.manage']}, {'role': 'manager'}, {'perms': ['pos.sell'], 'role': 'custom'},
                        {'active': False}):
            with self.subTest(changes=changes):
                with self.assertRaises(auth.AuthError) as e:
                    self.update(self.owner, changes, self.owner)
                self.assertEqual(e.exception.key, 'auth.err.selfLockout')
        self.assertIn('users.manage', auth.effective_perms(self.S.app.auth.get(self.owner['id'])))

    def test_last_manager_is_kept_even_without_a_person_saving(self):
        with self.assertRaises(auth.AuthError) as e:
            with self.S.db.tx():
                self.S.app.auth.update(self.owner['id'], {'role': 'manager'}, None)  # e.g. a tool, not a person
        self.assertEqual(e.exception.key, 'auth.err.lastManager')

    def test_a_second_manager_makes_it_safe(self):
        self.update(self.boss, {'role': 'owner'}, self.owner)
        out = self.update(self.owner, {'role': 'manager'}, self.boss)
        self.assertNotIn('users.manage', auth.effective_perms(out))

    def test_ticks_choose_the_profile_name(self):
        out = self.update(self.boss, {'perms': auth.ROLES['cashier']['perms'], 'role': 'manager'}, self.owner)
        self.assertEqual(out['role'], 'cashier')  # exactly the cashier ticks: shown as Cashier
        out = self.update(self.boss, {'perms': auth.ROLES['cashier']['perms'] + ['cost.view'], 'role': 'cashier'}, self.owner)
        self.assertEqual(out['role'], 'custom')
        out = self.update(self.boss, {'role': 'owner'}, self.owner)
        self.assertEqual((out['role'], auth.effective_perms(out)), ('owner', sorted(auth.PERMISSIONS)))
        out = self.update(self.boss, {'role': 'owner', 'perms': ['pos.sell']}, self.owner)
        self.assertEqual((out['role'], auth.effective_perms(out)), ('custom', ['pos.sell']))  # fewer ticks than the owner: Custom


class Profiles(unittest.TestCase):
    def setUp(self):
        self.S = Shop()
        self.A = self.S.app.auth
        self.owner = self.S.users['owner']

    def tearDown(self):
        self.S.cleanup()

    def save(self, data):
        with self.S.db.tx():
            return self.A.save_profile(data, self.owner['id'])

    def test_new_profile_assign_change_apply_delete(self):
        prof, before, n = self.save({'name': 'Senior cashier', 'perms': auth.ROLES['cashier']['perms'] + ['sales.return'],
                                     'max_discount_pct': 10})
        self.assertIsNone(before)
        with self.S.db.tx():
            u = self.A.create('sara', 'Sara', prof['id'], PW)
        self.assertEqual((u['role'], u['max_discount_pct']), (prof['id'], 10))
        self.assertIn('sales.return', auth.effective_perms(u))
        _, _, n = self.save({'id': prof['id'], 'name': 'Senior cashier', 'perms': auth.ROLES['cashier']['perms'] + ['cost.view']})
        self.assertEqual(n, 1)
        u = self.A.get(u['id'])
        self.assertIn('cost.view', auth.effective_perms(u))
        self.assertNotIn('sales.return', auth.effective_perms(u))
        _, _, n = self.save({'id': prof['id'], 'name': 'Senior', 'perms': ['pos.sell'], 'apply': False})
        self.assertEqual(n, 0)
        u = self.A.get(u['id'])
        self.assertEqual(u['role'], 'custom')  # kept the ticks, which no longer match the changed profile
        self.assertIn('cost.view', auth.effective_perms(u))
        with self.S.db.tx():
            self.A.update(u['id'], {'role': prof['id']}, self.owner['id'])
            _, n = self.A.delete_profile(prof['id'])
        self.assertEqual(n, 1)
        u = self.A.get(u['id'])
        self.assertEqual((u['role'], auth.effective_perms(u)), ('custom', ['pos.sell']))
        self.assertNotIn(prof['id'], [p['id'] for p in self.A.profiles()])

    def test_ready_made_profiles_can_be_renamed_changed_and_deleted_but_not_the_owner(self):
        prof, _, _ = self.save({'id': 'storekeeper', 'name': 'Warehouse', 'perms': ['products.view', 'stock.view', 'stock.count']})
        self.assertEqual((prof['name'], prof['builtin']), ('Warehouse', True))
        with self.S.db.tx():
            self.A.delete_profile('cashier')
        self.assertNotIn('cashier', [p['id'] for p in self.A.profiles()])
        for bad in ({'id': 'owner', 'name': 'Boss', 'perms': []}, {'name': '', 'perms': []}, {'name': 'Custom', 'perms': []},
                    {'name': 'warehouse', 'perms': []}, {'id': 'nope', 'name': 'X', 'perms': []},
                    {'name': 'Manager', 'perms': []}, {'name': 'مدير', 'perms': []}):
            with self.subTest(bad=bad), self.assertRaises(auth.AuthError):
                self.save(bad)
        with self.assertRaises(auth.AuthError), self.S.db.tx():
            self.A.delete_profile('owner')

    def test_gate_passes_with_the_shops_own_profiles(self):
        self.save({'name': 'Night shift', 'perms': ['pos.sell', 'pos.discount']})
        cat = auth.catalogue(self.A.profiles(), LABELS)
        self.assertEqual(afaccess.errors(cat), [])

    def test_applying_a_profile_cannot_lock_the_shop_out(self):
        with self.S.db.tx():
            self.A.update(self.owner['id'], {'perms': sorted(auth.PERMISSIONS), 'role': 'manager'}, self.owner['id'])
        self.assertEqual(self.A.get(self.owner['id'])['role'], 'custom')  # manager ticks + admin rights
        self.save({'id': 'manager', 'name': '', 'perms': auth.ROLES['manager']['perms'] + ['users.manage', 'settings.edit']})
        with self.S.db.tx():
            self.A.update(self.owner['id'], {'role': 'manager'}, self.owner['id'])
        with self.assertRaises(auth.AuthError) as e:
            self.save({'id': 'manager', 'name': '', 'perms': auth.ROLES['manager']['perms']})
        self.assertEqual(e.exception.key, 'auth.err.selfLockout')


class CarryOver(unittest.TestCase):
    def test_1_0_people_keep_their_rights_and_a_locked_out_shop_is_repaired(self):
        S = Shop()
        try:
            cashier = S.user('cashier', 'cash1')
            keeper = S.user('storekeeper', 'keep1')
            db = S.db
            # write them back as 1.0 stored them: a role and own extra/removed ticks, no ticks of their own
            db.run("UPDATE users SET perms = NULL, extra_perms = '[\"cost.view\"]', denied_perms = '[\"pos.credit\"]' WHERE id = ?", cashier['id'])
            db.run("UPDATE users SET perms = NULL WHERE id = ?", keeper['id'])
            db.run("UPDATE users SET perms = NULL, denied_perms = '[\"users.manage\"]' WHERE id = ?", S.users['owner']['id'])
            A = auth.Auth(db, S.app.org_id)
            c, k, o = (A.get(x['id']) for x in (cashier, keeper, S.users['owner']))
            self.assertEqual(c['role'], 'custom')
            self.assertEqual(set(auth.effective_perms(c)), set(auth.ROLES['cashier']['perms']) - {'pos.credit'} | {'cost.view'})
            self.assertEqual((k['role'], auth.effective_perms(k)), ('storekeeper', sorted(auth.ROLES['storekeeper']['perms'])))
            self.assertEqual(o['role'], 'owner')  # nobody could manage people any more: the 1.0 owner gets everything back
            self.assertIn('users.manage', auth.effective_perms(o))
            auth.Auth(db, S.app.org_id)  # once only: a second start changes nothing
            self.assertEqual(A.get(c['id'])['perms'], c['perms'])
        finally:
            S.cleanup()


class Upgrade(unittest.TestCase):
    def test_a_1_0_database_gets_a_checked_restorable_copy_before_schema_2(self):
        """The copy is made with SQLite's backup (it includes rows still in the write-ahead log) under a backup name, so
        Settings lists it and a restore can use it."""
        import app as app_mod
        import backup
        S = Shop()
        try:
            home, db = S.dir, S.db
            S.user('cashier', 'late1')  # a fresh row, possibly still only in the WAL file
            db.conn.execute('DROP TABLE profiles')
            db.conn.execute('ALTER TABLE users DROP COLUMN perms')
            db.conn.execute('ALTER TABLE returns DROP COLUMN fee')  # schema 4 added it
            db.conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema'")
            db.close()
            app = app_mod.build(home)
            names = [b['name'] for b in backup.listing(app.backup_dir)]
            copy = next(n for n in names if n.endswith('-before-upgrade.db'))
            self.assertTrue(backup.NAME.match(copy))
            path = os.path.join(app.backup_dir, copy)
            self.assertTrue(backup.check(path))
            import sqlite3
            with sqlite3.connect(path) as old:
                self.assertEqual(old.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()[0], '1')
                self.assertTrue(old.execute("SELECT 1 FROM users WHERE username = 'late1'").fetchone())
            import version
            self.assertEqual(app.db.version(), version.SCHEMA)
            self.assertEqual(app.db.value("SELECT name FROM sqlite_master WHERE type='table' AND name='guide_progress'"), 'guide_progress')
            self.assertEqual(app.db.value("SELECT name FROM sqlite_master WHERE type='table' AND name='consent_log'"), 'consent_log')
            S.db = app.db
        finally:
            S.cleanup()


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Server()
        cls.owner = cls.S.client()
        cls.owner.login()
        for username, role in (('cash', 'cashier'), ('keeper', 'storekeeper')):
            st, d, _ = cls.owner.post('/api/user/save', {'username': username, 'full_name': username, 'role': role, 'password': PW})
            assert st == 200, d
            setattr(cls, username + '_id', d['id'])

    @classmethod
    def tearDownClass(cls):
        cls.S.stop()

    def client(self, username):
        c = self.S.client()
        c.login(username, PW)
        return c

    def test_pages_follow_the_ticks_on_the_server(self):
        keeper = self.client('keeper')
        for path in ('/api/customers', '/api/customer?id=x', '/api/instalments', '/api/reports'):
            self.assertEqual(keeper.get(path)[0], 403, path)
        self.assertEqual(keeper.get('/api/stock')[0], 200)
        cash = self.client('cash')
        self.assertEqual(cash.get('/api/customers')[0], 200)
        st, d, _ = self.owner.post('/api/user/save', {'id': self.cash_id, 'full_name': 'cash', 'role': 'custom',
                                                      'perms': ['pos.sell', 'pos.discount']})
        self.assertEqual((st, d['role']), (200, 'custom'))
        for path in ('/api/stock', '/api/products', '/api/customer?id=x', '/api/counts'):
            self.assertEqual(cash.get(path)[0], 403, path)  # takes effect at once, without signing in again
        self.assertEqual(cash.get('/api/customers')[0], 200)  # the counter still picks the customer of a credit sale
        self.assertEqual(cash.get('/api/me')[1]['perms'], ['pos.discount', 'pos.sell'])
        home = cash.get('/api/home')[1]  # the home page only points to pages the person can open
        self.assertNotIn('due', home)
        self.assertFalse({'low_stock', 'upcoming_prices', 'late_instalments', 'add_products', 'slow_stock'} & {x['id'] for x in home['advisor']})

    def test_people_screen_data_and_audit(self):
        st, d, _ = self.owner.get('/api/users')
        self.assertEqual(st, 200)
        self.assertEqual({p['id'] for p in d['profiles']} >= {'owner', 'manager', 'cashier', 'storekeeper'}, True)
        self.assertEqual(d['groups'][-1], 'admin')
        self.assertTrue(all(p['admin'] == (p['group'] == 'admin') for p in d['permissions']))
        st, prof, _ = self.owner.post('/api/profile/save', {'name': 'Helper', 'perms': ['products.view', 'stock.view']})
        self.assertEqual(st, 200)
        st, out, _ = self.owner.post('/api/user/save', {'id': self.keeper_id, 'full_name': 'keeper', 'role': prof['profile']['id'],
                                                        'perms': ['products.view', 'stock.view']})
        self.assertEqual(out['role'], prof['profile']['id'])
        row = self.S.app.db.one("SELECT detail FROM audit WHERE action = 'user.edit' AND entity_id = ? ORDER BY at DESC LIMIT 1", self.keeper_id)
        detail = json.loads(row['detail'])
        self.assertEqual(detail['removed'], ['products.edit', 'stock.count', 'stock.receive', 'stock.transfer'])
        self.assertEqual(detail['added'], [])
        self.assertNotIn(PW, row['detail'])
        st, d, _ = self.owner.post('/api/profile/save', {'id': 'owner', 'name': 'x', 'perms': []})
        self.assertEqual((st, d.get('key')), (400, 'auth.err.lockedProfile'))
        st, d, _ = self.owner.post('/api/profile/delete', {'id': prof['profile']['id']})
        self.assertEqual((st, d['people']), (200, 1))
        st, d, _ = self.owner.post('/api/user/save', {'id': self.S.app.db.value('SELECT id FROM users WHERE username = ?', OWNER[0]),
                                                      'full_name': 'Owner', 'role': 'manager'})
        self.assertEqual((st, d.get('key')), (400, 'auth.err.selfLockout'))

    def test_cashier_cannot_touch_profiles(self):
        cash = self.client('cash')
        self.assertEqual(cash.post('/api/profile/save', {'name': 'Mine', 'perms': list(auth.PERMISSIONS)})[0], 403)
        self.assertEqual(cash.post('/api/profile/delete', {'id': 'cashier'})[0], 403)


if __name__ == '__main__':
    unittest.main()
