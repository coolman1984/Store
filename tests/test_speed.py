"""Found with 4,000 customers and 20,000 sales (a few busy years): the Customers page took 3 seconds because each customer's «last sale» read
every sale. The question each page asks must be answered through an index, and an upgraded shop gets the indexes when its database opens."""
import os
import unittest

from harness import Shop
import db as dbmod
from db import Database


def plan(db, sql, *args):
    return ' | '.join(r[-1] for r in db.conn.execute('EXPLAIN QUERY PLAN ' + sql, args).fetchall())


class PagesAnswerThroughIndexes(unittest.TestCase):
    def setUp(self):
        self.s = Shop()

    def tearDown(self):
        self.s.cleanup()

    def test_the_questions_that_grow_with_the_shop_use_an_index(self):
        db = self.s.db
        questions = {
            "SELECT MAX(at) FROM sales s WHERE s.customer_id = 'x'": 'sales_customer',                     # the customers list
            "SELECT id FROM sales WHERE customer_id = 'x' ORDER BY at DESC LIMIT 50": 'sales_customer',    # one customer's sales
            "SELECT COUNT(*) FROM sales WHERE shift_id = 'x'": 'sales_shift',                              # a shift's summary
            "SELECT COALESCE(SUM(amount), 0) FROM cash_moves WHERE account = 'safe'": 'cash_account',      # the safe's balance
            "SELECT COUNT(*) FROM returns WHERE at >= 'a' AND at < 'b'": 'returns_at',                     # today's returns
            "SELECT * FROM returns WHERE sale_id = 'x'": 'returns_sale',
            "SELECT * FROM ar_entries WHERE kind = 'reversal' AND at >= 'a'": 'ar_at',                     # the owner's eye
            "SELECT * FROM cash_moves WHERE kind = 'collection' AND ref_id = 'x'": 'cash_ref',
            "SELECT provider, SUM(amount) FROM tenders WHERE method = 'finance' GROUP BY provider": 'tenders_method',
        }
        for sql, index in questions.items():
            self.assertIn(index, plan(db, sql), sql)

    def test_an_older_database_gets_them_when_it_opens(self):
        for sql in dbmod.SPEED_INDEXES:
            self.s.db.run('DROP INDEX ' + sql.split('EXISTS ')[1].split(' ON ')[0])  # what a 1.7.0 database looks like
        self.assertNotIn('sales_customer', plan(self.s.db, "SELECT MAX(at) FROM sales WHERE customer_id = 'x'"))
        reopened = Database(os.path.join(self.s.dir, 'data', 'store.db'))
        try:
            self.assertIn('sales_customer', plan(reopened, "SELECT MAX(at) FROM sales WHERE customer_id = 'x'"))
            for sql in dbmod.SPEED_INDEXES:
                name = sql.split('EXISTS ')[1].split(' ON ')[0]
                self.assertTrue(reopened.value("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?", name), name)
        finally:
            reopened.close()

    def test_opening_twice_is_harmless_and_the_data_is_the_same(self):
        path = os.path.join(self.s.dir, 'data', 'store.db')
        a = Database(path)
        a.close()
        b = Database(path)
        try:
            self.assertEqual(b.value('SELECT value FROM meta WHERE key = ?', 'schema'), str(dbmod.SCHEMA), 'no schema change: an older program still opens the data')
        finally:
            b.close()


if __name__ == '__main__':
    unittest.main()
