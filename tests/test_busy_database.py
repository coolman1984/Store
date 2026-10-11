"""Found by reading the database layer with a failure in mind: if BEGIN failed once (another program holding the data file: a database viewer, a
copy or antivirus scan), the global lock stayed taken by a finished request and EVERY later request waited for ever until the program was
restarted. Then (review of the first fix): the lock was still held through the whole wait, so five devices froze the shop for a minute, a COMMIT
that failed left the transaction open, and even reading waited on the "last seen" write.
Now: the lock is given back; one request waits at most 2 s, the others are told «busy» at once; a failed COMMIT is rolled back; reading is served."""
import sqlite3
import threading
import time
import unittest

from harness import OWNER, Server, Shop


class Holder:
    """Another program that holds the shop's data file for writing (a database viewer, a copy tool, an antivirus scan)."""

    def __init__(self, path):
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute('BEGIN IMMEDIATE')

    def release(self):
        try:
            self.conn.execute('ROLLBACK')
        except sqlite3.Error:
            pass
        self.conn.close()


class OneRuleForABusyFile(unittest.TestCase):
    def test_only_sqlites_locked_and_busy_messages_are_a_busy_file(self):
        """Review of PR #21: three places had three rules («lock», «locked», «locked or busy»); a read-only file or a column named lock_x was taken for a busy file."""
        from db import is_busy_error
        for text in ('database is locked', 'database table is locked', 'database is busy', 'DATABASE IS LOCKED'):
            self.assertTrue(is_busy_error(sqlite3.OperationalError(text)), text)
        for text in ('attempt to write a readonly database', 'disk I/O error', 'database or disk is full', 'no such column: lock_state', 'unable to open database file'):
            self.assertFalse(is_busy_error(sqlite3.OperationalError(text)), text)


class OnlyABusyFileMarksTheShopBusy(unittest.TestCase):
    """Review of PR #21: any OperationalError on the «last seen» write was taken for «another program holds the file»: a full or failing disk then made
    the shop refuse every write with a message about another program, and the real fault left no trace."""

    def test_a_disk_error_on_last_seen_is_not_a_busy_file(self):
        s = Shop()
        auth = s.app.auth
        token = auth.start_session(s.users['owner'], '127.0.0.1')
        real = s.db.run

        def failing(message):
            def run(sql, *a, **k):
                if 'last_seen' in sql and sql.lstrip().upper().startswith('UPDATE'):
                    raise sqlite3.OperationalError(message)
                return real(sql, *a, **k)
            return run
        s.db.run = failing('disk I/O error')
        try:
            self.assertIsNotNone(auth.session(token))
        finally:
            s.db.run = real
        self.assertFalse(s.db.busy(), 'a disk error is not a busy file')
        s.db.run = failing('database is locked')
        try:
            self.assertIsNotNone(auth.session(token))
        finally:
            s.db.run = real
        self.assertTrue(s.db.busy(), 'a locked file still is')


class FailedBeginGivesTheLockBack(unittest.TestCase):
    def test_a_transaction_that_cannot_start_does_not_freeze_the_shop(self):
        s = Shop()
        other = Holder(s.db.path)
        try:
            db = s.db
            db.conn.execute('PRAGMA busy_timeout=150')
            errors = []

            def request():
                try:
                    with db.tx():
                        pass
                except sqlite3.OperationalError as e:
                    errors.append(str(e))
            t = threading.Thread(target=request)
            t.start()
            t.join(10)
            self.assertEqual(errors, ['database is locked'])
        finally:
            other.release()
        try:
            db.busy_until = 0.0
            got = db.lock.acquire(timeout=2)
            self.assertTrue(got, 'the lock was still held by the finished request: every later request would wait for ever')
            db.lock.release()
            with db.tx():  # and the shop works again at once
                db.run("INSERT INTO meta(key, value) VALUES ('probe', '1')")
            self.assertEqual(db.value("SELECT value FROM meta WHERE key = 'probe'"), '1')
        finally:
            s.cleanup()

    def test_after_one_busy_failure_the_others_are_refused_at_once_not_after_their_own_wait(self):
        s = Shop()
        other = Holder(s.db.path)
        try:
            db = s.db
            db.conn.execute('PRAGMA busy_timeout=400')
            took = []

            def request():
                t0 = time.monotonic()
                try:
                    with db.tx():
                        pass
                except sqlite3.OperationalError:
                    pass
                took.append(time.monotonic() - t0)
            threads = [threading.Thread(target=request) for _ in range(6)]
            t0 = time.monotonic()
            [t.start() for t in threads]
            [t.join(15) for t in threads]
            total = time.monotonic() - t0
            self.assertEqual(len(took), 6)
            self.assertLess(total, 400 / 1000 * 3, f'six requests took {total:.1f} s: each waited its own turn for the file (6 x 0.4 s)')
        finally:
            other.release()
            s.cleanup()


    def test_the_busy_window_ends_by_itself_even_while_requests_keep_coming(self):
        s = Shop()
        other = Holder(s.db.path)
        try:
            db = s.db
            db.conn.execute('PRAGMA busy_timeout=100')
            with self.assertRaises(sqlite3.OperationalError):
                with db.tx():
                    pass
            end = db.busy_until
            for _ in range(5):  # refused at once; they must not push the end of the window further away
                with self.assertRaises(sqlite3.OperationalError):
                    with db.tx():
                        pass
            self.assertEqual(db.busy_until, end)
        finally:
            other.release()
            s.cleanup()


class FailedCommitIsRolledBack(unittest.TestCase):
    def test_a_commit_that_fails_does_not_leave_the_connection_inside_a_transaction(self):
        s = Shop()
        try:
            db = s.db
            real = db.conn

            class Proxy:
                def __init__(self, conn):
                    self._c = conn
                    self.fail = True

                def execute(self, sql, *a):
                    if sql == 'COMMIT' and self.fail:
                        self.fail = False
                        raise sqlite3.OperationalError('database or disk is full')
                    return self._c.execute(sql, *a)

                def __getattr__(self, name):
                    return getattr(self._c, name)
            db.conn = Proxy(real)
            with self.assertRaises(sqlite3.OperationalError):
                with db.tx():
                    db.run("INSERT INTO meta(key, value) VALUES ('half', '1')")
            self.assertFalse(real.in_transaction, 'the failed commit left a transaction open on the shared connection')
            self.assertIsNone(db.value("SELECT value FROM meta WHERE key = 'half'"))
            with db.tx():  # the next request is fine
                db.run("INSERT INTO meta(key, value) VALUES ('whole', '1')")
            self.assertEqual(db.value("SELECT value FROM meta WHERE key = 'whole'"), '1')
        finally:
            db.conn = real
            s.cleanup()

    def test_a_failing_rollback_does_not_hide_the_error_the_caller_must_see(self):
        s = Shop()
        try:
            db = s.db
            with self.assertRaises(ValueError):
                with db.tx():
                    db.conn.execute('ROLLBACK')  # the transaction is already gone
                    raise ValueError('the real problem')
        finally:
            s.cleanup()


class BusyOverHttp(unittest.TestCase):
    def test_a_write_while_another_program_holds_the_file_is_a_calm_503_and_reading_is_still_served(self):
        srv = Server()
        other = None
        try:
            c = srv.client()
            c.login(*OWNER)
            srv.app.db.conn.execute('PRAGMA busy_timeout=200')
            other = Holder(srv.app.db.path)
            started = time.time()
            status, body, headers = c.post('/api/shift/open', {'opening_float': 0})
            self.assertEqual((status, body['key']), (503, 'err.busy'))
            self.assertEqual(headers.get('Retry-After'), '2')
            # while it lasts, a read is answered at once (the "last seen" write is skipped), and so is the next write
            t0 = time.time()
            self.assertEqual(c.get('/api/me')[0], 200)
            self.assertEqual(c.post('/api/shift/open', {'opening_float': 0})[0], 503)
            self.assertLess(time.time() - t0, 1.5)
            self.assertLess(time.time() - started, 5)
            other.release()
            other = None
            srv.app.db.busy_until = 0.0
            status, body, _ = c.post('/api/shift/open', {'opening_float': 0})   # nothing is stuck
            self.assertEqual(status, 200, body)
        finally:
            if other:
                other.release()
            srv.stop()

    def test_four_devices_reading_at_the_same_moment_do_not_queue_behind_the_wait(self):
        srv = Server()
        other = None
        try:
            clients = [srv.client() for _ in range(4)]
            for c in clients:
                c.login(*OWNER)
            srv.app.db.conn.execute('PRAGMA busy_timeout=500')
            other = Holder(srv.app.db.path)
            codes = []
            t0 = time.time()
            threads = [threading.Thread(target=lambda c=c: codes.append(c.get('/api/me')[0])) for c in clients]
            [t.start() for t in threads]
            [t.join(15) for t in threads]
            self.assertEqual(sorted(codes), [200, 200, 200, 200], 'reading is served even while another program holds the file')
            self.assertLess(time.time() - t0, 2.5, 'four devices waited one after another')
        finally:
            if other:
                other.release()
            srv.stop()


if __name__ == '__main__':
    unittest.main()
