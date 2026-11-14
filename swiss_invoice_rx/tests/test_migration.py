import sqlite3
import tempfile
import unittest
from pathlib import Path
from app.db import initialize,db_connect

class MigrationTests(unittest.TestCase):
    def test_existing_schema_migrates_without_losing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            filename=Path(folder)/'rechnung.sqlite3'
            con=sqlite3.connect(filename)
            con.execute('''CREATE TABLE payments(id INTEGER PRIMARY KEY,company_id INTEGER,
                invoice_id INTEGER,paid_at TEXT,amount TEXT,method TEXT,note TEXT,
                created_at TEXT)''')
            con.execute('''CREATE TABLE reminders(id INTEGER PRIMARY KEY,company_id INTEGER,
                invoice_id INTEGER,level INTEGER,sent_at TEXT,note TEXT)''')
            con.execute("INSERT INTO payments VALUES(1,1,1,'2026-11-08','75.00','Bank','alt','2026-11-08')")
            con.execute("INSERT INTO reminders VALUES(1,1,1,1,'2026-11-08','alt')")
            con.commit();con.close()
            initialize(filename)
            initialize(filename)
            con=db_connect(filename)
            try:
                self.assertEqual(con.execute('SELECT amount FROM payments WHERE id=1').fetchone()[0], '75.00')
                self.assertEqual(con.execute('SELECT reversed_at FROM payments WHERE id=1').fetchone()[0], '')
                self.assertEqual(con.execute('SELECT balance_at FROM reminders WHERE id=1').fetchone()[0], '')
                self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],15)
            finally:con.close()

if __name__ == '__main__':
    unittest.main()
