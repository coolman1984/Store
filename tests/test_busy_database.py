"""Found by reading the database layer with a failure in mind: if BEGIN failed once (another program holding the data file: a database viewer, a
copy or antivirus scan), the global lock stayed taken by a finished request and EVERY later request waited for ever until the program was
restarted. Now the lock is given back and the person reads a calm «busy, try again»."""
import sqlite3
import threading
import time
import unittest

from harness import OWNER, Server, Shop


class FailedBeginGivesTheLockBack(unittest.TestCase):
    def test_a_transaction_that_cannot_start_does_not_freeze_the_shop(self):
        s = Shop()
        try:
            db = s.db
            other = sqlite3.connect(db.path, isolation_level=None)
            other.execute('BEGIN IMMEDIATE')  # another program holds the write lock
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
            other.execute('ROLLBACK')
            other.close()
            got = db.lock.acquire(timeout=2)
            self.assertTrue(got, 'the lock was still held by the finished request: every later request would wait for ever')
            db.lock.release()
            with db.tx():  # and the shop works again at once
                db.run("INSERT INTO meta(key, value) VALUES ('probe', '1')")
            self.assertEqual(db.value("SELECT value FROM meta WHERE key = 'probe'"), '1')
        finally:
            s.cleanup()


class BusyOverHttp(unittest.TestCase):
    def test_a_write_while_another_program_holds_the_file_is_a_calm_503_then_the_next_one_works(self):
        srv = Server()
        try:
            c = srv.client()
            c.login(*OWNER)
            srv.app.db.conn.execute('PRAGMA busy_timeout=150')
            other = sqlite3.connect(srv.app.db.path, isolation_level=None)
            other.execute('BEGIN IMMEDIATE')
            started = time.time()
            status, body, headers = c.post('/api/shift/open', {'opening_float': 0})
            self.assertEqual((status, body['key']), (503, 'err.busy'))
            self.assertEqual(headers.get('Retry-After'), '2')
            self.assertLess(time.time() - started, 5)
            other.execute('ROLLBACK')
            other.close()
            status, body, _ = c.post('/api/shift/open', {'opening_float': 0})   # nothing is stuck
            self.assertEqual(status, 200, body)
            self.assertEqual(c.get('/api/me')[0], 200)
        finally:
            srv.stop()


if __name__ == '__main__':
    unittest.main()
