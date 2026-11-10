"""Version 1.9: Suche, ZIP-Archiv, Datensicherheit und lokaler Systemcheck."""
import hashlib
import io
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from app.db import transaction
from app.billing import hash_password
from app.main import create_app


class QualityV19Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.client = TestClient(create_app(self.root))
        r = self.client.get('/setup')
        self.assertEqual(r.status_code, 200)
        token = re.search(r'name="_csrf" value="([a-f0-9]+)"', r.text).group(1)
        r = self.client.post('/setup', data={
            '_csrf': token, 'company_name': 'Test Firma AG',
            'email': 'admin@test.ch', 'full_name': 'Test Admin',
            'password': 'Passwort_Sehr_Sicher_12',
            'password2': 'Passwort_Sehr_Sicher_12',
        })
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.db = self.root/'rechnung.sqlite3'

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def csrf(self):
        text = self.client.get('/dashboard').text
        return re.search(r'name="_csrf" value="([a-f0-9]+)"', text).group(1)

    def seed(self, cid=1, name='Licht & Kabel AG', number='RE-2026-1234',
             archived=False, item='Stromkabel 25m'):
        with transaction(self.db, True) as con:
            cur = con.execute('INSERT INTO customers(company_id,number,name,city,email) VALUES(?,?,?,?,?)',
                              (cid, 'K'+str(con.execute('SELECT COUNT(*) FROM customers').fetchone()[0]+1),
                               name,'Bern','kontakt@example.ch'))
            cust_id = cur.lastrowid
            con.execute('INSERT INTO items(company_id,sku,name,category) VALUES(?,?,?,?)',
                        (cid, 'ART'+str(con.execute('SELECT COUNT(*) FROM items').fetchone()[0]+1),item,'Elektro'))
            cur = con.execute('''INSERT INTO invoices(company_id,customer_id,kind,number,invoice_date,due_date,
                status,subject,total,currency) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (cid,cust_id,'invoice',number,'2026-11-08','2026-12-08','sent','Projekt Umbau','125.00','CHF'))
            inv_id = cur.lastrowid
            if archived:
                dest = self.root/'archive'/str(cid)
                dest.mkdir(parents=True,exist_ok=True)
                relative = f'archive/{cid}/{inv_id:08d}.pdf'
                payload = (f'%PDF-1.4 sample invoice {inv_id}').encode()
                (self.root/relative).write_bytes(payload)
                con.execute('UPDATE invoices SET pdf_file=?,pdf_sha256=? WHERE id=?',
                            (relative,hashlib.sha256(payload).hexdigest(),inv_id))
        return inv_id

    def company2(self):
        with transaction(self.db,True) as con:
            con.execute("INSERT INTO companies(name) VALUES('Zweiter Laden')")
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(2,1,'admin')")
        self.client.post('/company/switch',data={'_csrf':self.csrf(),'company_id':'2'})

    def test_global_search_finds_three_types(self):
        rid=self.seed()
        r=self.client.get('/api/search?q=Kabel')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['groups']['customers'][0]['title'],'Licht & Kabel AG')
        self.assertEqual(r.json()['groups']['items'][0]['title'],'Stromkabel 25m')
        r=self.client.get('/api/search?q=RE-2026-1234')
        self.assertEqual(r.json()['groups']['invoices'][0]['url'],f'/invoices/{rid}')
        self.assertIn('Licht &amp; Kabel AG',self.client.get('/search?q=Kabel').text)

    def test_global_search_matches_subject_and_email(self):
        self.seed()
        self.assertEqual(len(self.client.get('/api/search?q=Umbau').json()['groups']['invoices']),1)
        self.assertEqual(len(self.client.get('/api/search?q=kontakt@').json()['groups']['customers']),1)

    def test_short_query_and_literal_sql_wildcards(self):
        self.seed(name='Auto%24 GmbH',item='Schraub_25')
        self.assertFalse(any(self.client.get('/api/search?q=A').json()['groups'].values()))
        self.assertEqual(len(self.client.get('/api/search?q=%25').json()['groups']['customers']),0)
        self.assertEqual(len(self.client.get('/api/search?q=Auto%25%2424').json()['groups']['customers']),0)
        self.assertEqual(len(self.client.get('/api/search?q=%25').json()['groups']['items']),0)
        self.assertEqual(len(self.client.get('/api/search?q=%25').json()['groups']['invoices']),0)
        self.assertEqual(len(self.client.get('/api/search?q=_25').json()['groups']['items']),1)
        # Prozentzeichen sucht nur Datensaetze, die tatsaechlich Prozent enthalten.
        self.assertEqual(len(self.client.get('/api/search?q=%25').json()['groups']['customers']),0)
        self.assertEqual(len(self.client.get('/api/search',params={'q':'%24'}).json()['groups']['customers']),1)

    def test_search_company_isolation(self):
        self.seed(name='Nur Firma Eins',number='A1')
        self.company2()
        self.seed(cid=2,name='Nur Firma Zwei',number='B2')
        self.assertEqual(len(self.client.get('/api/search?q=Firma Eins').json()['groups']['customers']),0)
        self.assertEqual(len(self.client.get('/api/search?q=Firma Zwei').json()['groups']['customers']),1)
        self.assertNotIn('Firma Eins',self.client.get('/search?q=Firma').text)

    def test_html_escapes_untrusted_search_text(self):
        self.seed(name='<script>alert(1)</script> AG')
        r=self.client.get('/search?q=script')
        self.assertNotIn('<script>alert(1)</script>',r.text)
        self.assertIn('&lt;script&gt;',r.text)

    def test_search_requires_login(self):
        other=TestClient(create_app(self.root),follow_redirects=False)
        try:
            self.assertEqual(other.get('/api/search?q=abc').status_code,303)
            self.assertEqual(other.get('/search?q=abc').headers['location'],'/login')
        finally:other.close()

    def test_archive_zip_valid_with_list_and_check_hash(self):
        a=self.seed(archived=True,number='RE-X100')
        b=self.seed(archived=True,number='RE-X101')
        r=self.client.post('/archive/export.zip',data={'_csrf':self.csrf(),'invoice_ids':[str(a),str(b)]})
        self.assertEqual(r.status_code,200,r.text[:200] if r.status_code!=200 else '')
        self.assertEqual(r.headers['content-type'],'application/zip')
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names=z.namelist()
            self.assertIn(f'PDF/{a:08d}-RE-X100.pdf',names)
            self.assertIn(f'PDF/{b:08d}-RE-X101.pdf',names)
            self.assertIn('Belegliste.csv',names)
            self.assertIn('SHA256',z.read('Belegliste.csv').decode('utf-8'))

    def test_archive_zip_rejects_bad_ids_and_invalid_selection(self):
        a=self.seed(archived=True)
        token=self.csrf()
        self.assertEqual(self.client.post('/archive/export.zip',data={'_csrf':token}).status_code,400)
        self.assertEqual(self.client.post('/archive/export.zip',data={'_csrf':token,
            'invoice_ids':[str(a),str(a)]}).status_code,400)
        self.assertEqual(self.client.post('/archive/export.zip',data={'_csrf':token,
            'invoice_ids':['abc']}).status_code,400)
        self.assertEqual(self.client.post('/archive/export.zip',data={'_csrf':token,
            'invoice_ids':[str(i) for i in range(1,27)]}).status_code,400)
        self.assertEqual(self.client.post('/archive/export.zip',data={'invoice_ids':[str(a)]}).status_code,403)

    def test_archive_zip_company_isolation(self):
        a=self.seed(archived=True)
        self.company2()
        r=self.client.post('/archive/export.zip',data={'_csrf':self.csrf(),'invoice_ids':[str(a)]})
        self.assertEqual(r.status_code,404)

    def test_archive_zip_blocks_tamper_and_missing(self):
        a=self.seed(archived=True)
        (self.root/'archive'/'1'/f'{a:08d}.pdf').write_bytes(b'changed')
        r=self.client.post('/archive/export.zip',data={'_csrf':self.csrf(),'invoice_ids':[str(a)]})
        self.assertEqual(r.status_code,409)
        (self.root/'archive'/'1'/f'{a:08d}.pdf').unlink()
        r=self.client.post('/archive/export.zip',data={'_csrf':self.csrf(),'invoice_ids':[str(a)]})
        self.assertEqual(r.status_code,404)

    def test_archive_zip_draft_not_exportable(self):
        a=self.seed()
        self.assertEqual(self.client.post('/archive/export.zip',data={
            '_csrf':self.csrf(),'invoice_ids':[str(a)]}).status_code,400)

    def test_systemcheck_reads_company_and_archives(self):
        self.seed(archived=True)
        r=self.client.get('/systemcheck')
        self.assertEqual(r.status_code,200)
        self.assertIn('SQLite-Datenbank lesbar',r.text)
        self.assertIn('Archiv-PDFs unveraendert',r.text)
        self.assertIn('Keine lokale Sicherung gefunden',r.text)

    def test_systemcheck_detects_tampered_archive(self):
        a=self.seed(archived=True)
        (self.root/'archive'/'1'/f'{a:08d}.pdf').write_bytes(b'changed')
        r=self.client.get('/systemcheck')
        self.assertIn('Archivkontrolle fehlgeschlagen',r.text)
        self.assertIn('stimmt nicht mehr',r.text)

    def test_systemcheck_reports_recent_backup(self):
        backup=self.root/'backups'/'backup-20261108.zip'
        with zipfile.ZipFile(backup,'w') as z:
            z.writestr('rechnung.sqlite3',b'dummy-test-db')
        text=self.client.get('/systemcheck').text
        self.assertIn('Aktuelle lokale Sicherung gefunden',text)
        self.assertIn('backup',text.lower())

    def test_systemcheck_rejects_corrupt_local_backup(self):
        backup=self.root/'backups'/'backup-20261108.zip'
        backup.write_bytes(b'kaputt')
        html=self.client.get('/systemcheck').text
        self.assertIn('Lokales Backup beschaedigt',html)
        self.assertNotIn('Aktuelle lokale Sicherung gefunden',html)

    def test_systemcheck_requires_admin(self):
        with transaction(self.db,True) as con:
            con.execute("INSERT INTO users(email,password_hash,full_name) VALUES(?,?,?)",
                        ('viewer@test.ch',hash_password('SuperPasswort_14'),'Viewer'))
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(1,2,'viewer')")
        viewer=TestClient(create_app(self.root))
        try:
            token=re.search(r'name="_csrf" value="([a-f0-9]+)"',viewer.get('/login').text).group(1)
            viewer.post('/login',data={'_csrf':token,'email':'viewer@test.ch','password':'SuperPasswort_14'})
            self.assertEqual(viewer.get('/systemcheck').status_code,403)
            self.assertEqual(viewer.get('/api/search?q=Test').status_code,200)
            self.assertEqual(viewer.get('/api/search?q=Stromkabel').json()['groups']['items'],[])
        finally:viewer.close()

    def test_systemcheck_company_scoped(self):
        a=self.seed(archived=True,number='AAA111')
        (self.root/'archive'/'1'/f'{a:08d}.pdf').write_bytes(b'bad')
        self.company2()
        self.seed(cid=2,archived=True,number='BBB222')
        r=self.client.get('/systemcheck')
        self.assertIn('Archiv-PDFs unveraendert',r.text)
        self.assertNotIn('Archivkontrolle fehlgeschlagen',r.text)
        self.assertNotIn('AAA111',r.text)


    def test_inventory_reorder_threshold_and_csv(self):
        token=self.csrf()
        data={'_csrf':token,'name':'Kupferdraht','sku':'KUP-1','kind':'product',
              'price':'23.45','cost':'9.00','tax_rate':'0','stock':'2',
              'track_stock':'1','reorder_point':'1'}
        r=self.client.post('/items/save',data=data)
        self.assertIn('Artikel gespeichert',r.text)
        self.assertNotIn('Kupferdraht',self.client.get('/items?low=1').text)
        with transaction(self.db) as con:
            item_id=con.execute('SELECT id FROM items WHERE sku=?',('KUP-1',)).fetchone()[0]
        data['id']=str(item_id)
        data['reorder_point']='3'
        self.client.post('/items/save',data=data)
        r=self.client.get('/items?low=1')
        self.assertIn('Kupferdraht',r.text)
        self.assertIn('Min. 3',r.text)
        self.assertIn('Kupferdraht',self.client.get('/dashboard').text)
        stock_csv=self.client.get('/items/low-stock.csv').text
        self.assertIn('Kupferdraht',stock_csv)
        self.assertIn('Mindestbestand',stock_csv)

    def test_inventory_reorder_rejects_invalid_number(self):
        token=self.csrf()
        for threshold in ('-1','1000001','NaN','kein wert'):
            r=self.client.post('/items/save',data={'_csrf':token,'name':'Ungueltiges Teil',
                 'price':'1','stock':'5','reorder_point':threshold,'track_stock':'1'})
            self.assertIn('error',r.text)
        with transaction(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM items').fetchone()[0],0)

    def test_inventory_reorder_stays_in_company(self):
        self.client.post('/items/save',data={'_csrf':self.csrf(),'name':'Privat Lagerteil',
            'price':'1','stock':'1','reorder_point':'10','track_stock':'1'})
        self.company2()
        self.assertNotIn('Privat Lagerteil',self.client.get('/items?low=1').text)
        self.assertNotIn('Privat Lagerteil',self.client.get('/items/low-stock.csv').text)

    def test_inventory_migration_from_old_schema_keeps_items(self):
        from app.db import initialize
        with transaction(self.db,True) as con:
            con.execute("INSERT INTO items(company_id,sku,name) VALUES(1,'ALT-1','Vorhandenes Material')")
            con.execute('ALTER TABLE items DROP COLUMN reorder_point')
            con.execute('PRAGMA user_version=9')
        initialize(self.db)
        with transaction(self.db) as con:
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],12)
            item=con.execute("SELECT name,reorder_point FROM items WHERE sku='ALT-1'").fetchone()
            self.assertEqual(item['name'],'Vorhandenes Material')
            self.assertEqual(item['reorder_point'],'5')


if __name__=='__main__':
    unittest.main()
