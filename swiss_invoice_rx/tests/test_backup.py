"""Offline-Backup und Wiederherstellung inklusive Pfadschutz."""
import sqlite3
from contextlib import closing
import tempfile
import unittest
import zipfile
from pathlib import Path
from app.db import initialize
from backup_cli import make_backup
from restore_backup import restore

class BackupTests(unittest.TestCase):
    def test_backup_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'storage'
            root.mkdir()
            db=root/'rechnung.sqlite3'
            initialize(db)
            with closing(sqlite3.connect(db)) as con:
                with con: con.execute('INSERT INTO companies(name) VALUES(?)',('Firma Alt',))
            (root/'uploads'/'1').mkdir(parents=True)
            (root/'uploads'/'1'/'img.jpg').write_bytes(b'image fixture')
            zipped=make_backup(root)
            self.assertTrue(zipfile.is_zipfile(zipped))
            with closing(sqlite3.connect(db)) as con:
                with con: con.execute('INSERT INTO companies(name) VALUES(?)',('Firma Neu',))
            (root/'uploads'/'1'/'img.jpg').write_bytes(b'changed image')
            rescue=restore(root,zipped)
            self.assertTrue((rescue/'rechnung.sqlite3').exists())
            with closing(sqlite3.connect(db)) as con:
                names=[x[0] for x in con.execute('SELECT name FROM companies ORDER BY id')]
            self.assertEqual(names,['Firma Alt'])
            self.assertEqual((root/'uploads'/'1'/'img.jpg').read_bytes(),b'image fixture')

    def test_restore_rejects_zip_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'storage'
            root.mkdir()
            dangerous=Path(tmp)/'bad.zip'
            with zipfile.ZipFile(dangerous,'w') as z:
                z.writestr('rechnung.sqlite3','some db')
                z.writestr('../../attack.txt','you should not see this')
            with self.assertRaisesRegex(ValueError,'Unzulaessige Datei'):
                restore(root,dangerous)
            self.assertFalse((Path(tmp)/'attack.txt').exists())
