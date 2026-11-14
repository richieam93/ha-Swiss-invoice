"""Version 1.6: Listen, Zahlungsziele, Excel-Eingabe, Sicherheit und Migration."""
import csv
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.db import db_connect, initialize
from app.main import create_app


class Workflow16Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = TestClient(create_app(self.root), follow_redirects=True)
        self.client.post('/setup', data={
            '_csrf': self.token('/setup'), 'company_name': 'Alpenlicht AG',
            'email': 'admin@example.ch', 'full_name': 'Administrator',
            'password': 'Passwort!2026Sicher', 'password2': 'Passwort!2026Sicher'})
        self.client.post('/settings', data={
            '_csrf': self.token('/settings'), 'name': 'Alpenlicht AG',
            'street':'Gasse','building':'8','zip':'3000','city':'Bern','country':'CH',
            'default_due_days':'30','tax_registered':'1','default_tax':'8.1',
            'currency':'CHF','number_prefix':'RE'})
        self.customer('Alpenkunde AG', 14)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def token(self, path):
        response = self.client.get(path)
        hit = re.search(r'name="_csrf"[^>]*value="([a-f0-9]+)"', response.text)
        self.assertIsNotNone(hit, response.text[:700])
        return hit.group(1)

    def customer(self, name, days=0):
        return self.client.post('/customers/save', data={
            '_csrf': self.token('/customers/new'), 'name': name,
            'street':'Seestrasse','building':'2','zip':'8000','city':'Zuerich','country':'CH',
            'payment_days':str(days)})

    def invoice(self, number, currency='CHF', when='2026-11-08', subject='Projekt Alpenblick', kind='invoice'):
        return self.client.post('/invoices/save',data={
            '_csrf':self.token('/invoices/new'), 'kind':kind, 'number':number,
            'customer_id':'1','invoice_date':when,'service_date':when,
            'due_date':'2026-12-08','currency':currency,'subject':subject,
            'discount':'0','description[]':['Beratung'],'qty[]':['2'],'unit[]':['Std.'],
            'price[]':['100.00'],'tax_rate[]':['8.1'], 'tax_mode[]':['taxable'],
            'discount[]':['0'],'item_id[]':['']})

    def test_customer_payment_days_are_saved_and_shown(self):
        self.assertEqual(self.db_value('SELECT payment_days FROM customers WHERE id=1'),14)
        html = self.client.get('/customers/1/edit').text
        self.assertIn('name="payment_days"',html)
        self.assertIn('value="14"',html)
        editor = self.client.get('/invoices/new').text
        self.assertIn('id="apply-customer-due"',editor)
        self.assertIn('data-default-due="30"',editor)
        self.assertIn('payment_days&#34;: 14',editor)

    def test_customer_payment_days_update_and_default(self):
        r = self.client.post('/customers/save',data={
            '_csrf':self.token('/customers/1/edit'),'id':'1','name':'Alpenkunde AG',
            'payment_days':'21','country':'CH'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.db_value('SELECT payment_days FROM customers WHERE id=1'),21)
        self.customer('Neuer Kunde',0)
        self.assertEqual(self.db_value('SELECT payment_days FROM customers WHERE id=2'),0)

    def db_value(self,sql,args=()):
        con=db_connect(self.root/'rechnung.sqlite3')
        try:return con.execute(sql,args).fetchone()[0]
        finally: con.close()

    def test_invalid_customer_payment_days_rolls_back(self):
        response=self.client.post('/customers/save',data={
            '_csrf':self.token('/customers/1/edit'),'id':'1',
            'name':'Nicht speichern','payment_days':'366'})
        self.assertIn('Zahlungsziel',response.text)
        self.assertEqual(self.db_value('SELECT name FROM customers WHERE id=1'),'Alpenkunde AG')
        self.assertEqual(self.db_value('SELECT payment_days FROM customers WHERE id=1'),14)
        response=self.client.post('/customers/save',data={
            '_csrf':self.token('/customers/new'),'name':'Böser Wert','payment_days':'-7'})
        self.assertIn('Zahlungsziel',response.text)
        self.assertEqual(self.db_value('SELECT count(*) FROM customers'),1)

    def test_invoice_list_filters_and_export_match(self):
        self.invoice('RE-26-1',subject='Gartenservice')
        self.invoice('RE-26-2',currency='EUR',subject='Schweiz Import')
        self.invoice('RE-26-3',when='2026-10-01',subject='Altauftrag')
        link='/invoices?kind=invoice&currency=CHF&date_from=2026-11-01&q=Gartenservice'
        html=self.client.get(link).text
        self.assertIn('RE-26-1',html)
        self.assertNotIn('RE-26-2',html)
        self.assertNotIn('RE-26-3',html)
        self.assertIn('1 Treffer',html)
        res=self.client.get('/invoices/list.csv?kind=invoice&currency=CHF&date_from=2026-11-01&q=Gartenservice')
        self.assertEqual(res.status_code,200)
        self.assertTrue(res.content.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.reader(io.StringIO(res.content.decode('utf-8-sig')), delimiter=';'))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1][0],'RE-26-1')
        self.assertIn('Gartenservice', rows[1])

    def test_literal_like_search_and_invalid_filters(self):
        self.invoice('RE-2026-01')
        self.assertIn('1 Treffer', self.client.get('/invoices?q=2026').text)
        self.assertIn('0 Treffer', self.client.get('/invoices?q=%25').text)
        self.assertIn('0 Treffer', self.client.get('/invoices?q=_').text)
        for suffix in ('status=unknown', 'currency=USD','date_from=2026-13-45',
                       'date_from=2026-12-31&date_to=2026-01-01','sort=evil'):
            self.assertEqual(self.client.get('/invoices?'+suffix).status_code,400,suffix)

    def test_status_filter_before_pagination(self):
        self.invoice('RE-DRAFT')
        self.client.post('/invoices/1/issue',data={'_csrf':self.token('/invoices/1')})
        self.invoice('RE-NEW-DRAFT')
        issued=self.client.get('/invoices?status=sent').text
        draft=self.client.get('/invoices?status=draft').text
        self.assertIn('RE-DRAFT',issued)
        self.assertNotIn('RE-NEW-DRAFT',issued)
        self.assertIn('RE-NEW-DRAFT',draft)
        self.assertNotIn('RE-DRAFT',draft)
        self.assertIn('Weiterbearbeiten',self.client.get('/dashboard').text)

    def test_pagination_limit_and_page_links(self):
        con=db_connect(self.root/'rechnung.sqlite3')
        try:
            con.execute('BEGIN IMMEDIATE')
            for n in range(33):
                con.execute('''INSERT INTO invoices(company_id,kind,number,customer_id,invoice_date,due_date)
                    VALUES(1,'invoice',?,1,'2026-10-01','2026-11-01')''',(f'RE-TEST-{n:02d}',))
            con.commit()
        finally:con.close()
        html1=self.client.get('/invoices?status=draft&page=1').text
        html2=self.client.get('/invoices?status=draft&page=2').text
        self.assertIn('33 Treffer',html1)
        self.assertIn('Seite 1 von 2',html1)
        self.assertIn('Seite 2 von 2',html2)
        self.assertEqual(html1.count('title="Neuen Entwurf aus diesem Beleg erstellen"'),25)
        self.assertEqual(html2.count('title="Neuen Entwurf aus diesem Beleg erstellen"'),8)
        self.assertEqual(self.client.get('/invoices?page=10000').status_code,200)

    def test_quick_actions_and_bulk_controls_present(self):
        self.invoice('RE-AKTION')
        listing=self.client.get('/invoices').text
        self.assertIn('/invoices/1/edit',listing)
        self.assertIn('/invoices/1/pdf',listing)
        self.assertIn('action="/invoices/1/copy"',listing)
        editor=self.client.get('/invoices/1/edit').text
        for part in ('id="bulk-import-panel"','id="bulk-lines-input"','id="bulk-check"',
                     'id="bulk-add"','id="bulk-undo"','/static/bulk_lines.js'):
            self.assertIn(part,editor)
        self.assertEqual(self.client.get('/static/bulk_lines.js').status_code,200)

    def test_company_isolation_for_list_and_export(self):
        self.invoice('FIRMA-1')
        self.client.post('/companies/new',data={'_csrf':self.token('/companies/new'),'name':'Zweiter Mandant'})
        self.customer('Zweiter Kunde',35)
        self.assertNotIn('FIRMA-1',self.client.get('/invoices').text)
        self.assertNotIn('FIRMA-1',self.client.get('/invoices/list.csv').text)
        self.assertEqual(self.db_value('SELECT payment_days FROM customers WHERE company_id=2'),35)
        self.client.post('/company/switch',data={'_csrf':self.token('/settings'),'company_id':'1'})
        self.assertIn('FIRMA-1',self.client.get('/invoices').text)

    def test_export_stays_separate_from_full_export(self):
        self.invoice('CHF-RE',currency='CHF')
        self.invoice('EUR-RE',currency='EUR')
        self.assertIn('EUR-RE',self.client.get('/export/invoices.csv').text)
        chf=self.client.get('/invoices/list.csv?currency=CHF').text
        self.assertIn('CHF-RE',chf)
        self.assertNotIn('EUR-RE',chf)


    def test_new_customer_inside_invoice_keeps_payment_terms(self):
        r=self.client.post('/invoices/save',data={
            '_csrf':self.token('/invoices/new'),'kind':'invoice','invoice_date':'2026-11-08',
            'due_date':'2026-12-08','currency':'CHF','discount':'0',
            'new_customer_name':'Direktkunde AG','new_customer_zip':'6000',
            'new_customer_city':'Luzern','new_customer_country':'CH','new_customer_payment_days':'45',
            'description[]':['Planung'],'qty[]':['1'],'unit[]':['Std.'],
            'price[]':['100.00'],'tax_rate[]':['8.1'],'tax_mode[]':['taxable'],
            'item_id[]':[''],'discount[]':['0']})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.db_value("SELECT payment_days FROM customers WHERE name='Direktkunde AG'"),45)
        self.assertEqual(self.db_value("SELECT count(*) FROM invoices WHERE company_id=1"),1)

    def test_csv_customer_import_with_payment_days(self):
        sample=self.client.get('/import/sample/customers.csv').text
        self.assertIn('payment_days',sample)
        data='name;street;zip;city;country;payment_days\nCSV Kunde;Ringstrasse;4000;Basel;CH;28\n'
        r=self.client.post('/import/customers',data={'_csrf':self.token('/import/customers')},
              files={'file':('kunde.csv',data.encode(),'text/csv')})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.db_value("SELECT payment_days FROM customers WHERE name='CSV Kunde'"),28)



class BulkParser16Tests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node.js fuer optionale JS-Parser-Tests nicht installiert')
    def test_bulk_parses_excel_and_swiss_numbers(self):
        source=Path(__file__).resolve().parents[1]/'app/static/bulk_lines.js'
        js='''const p=require(process.argv[1]);const lines=p.parse('Montage\\t2\\tStd.\\t1\\'234,50\\t8,1\\t5\\nMaterial\\t1\\tStk.\\t2.50\\t2.6\\t0','invoice','8.1');console.log(JSON.stringify(lines));'''
        result=subprocess.run(['node','-e',js,str(source)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        rows=json.loads(result.stdout)
        self.assertEqual(rows[0]['price'],'1234.5')
        self.assertEqual(rows[0]['tax'],'8.1')
        self.assertEqual(rows[1]['price'],'2.5')
        self.assertEqual(len(rows),2)

    @unittest.skipUnless(shutil.which('node'),'Node.js fuer optionale JS-Parser-Tests nicht installiert')
    def test_bulk_rejects_invalid_quantities(self):
        source=Path(__file__).resolve().parents[1]/'app/static/bulk_lines.js'
        js="""const p=require(process.argv[1]);let count=0; for(const text of ['Ware;0;Stk.;2','Ware;1;Stk.;abc','Ware;2;Stk.;1;101','Ware;2;Stk.;1;8.1;120']){try{p.parse(text,'invoice','0')}catch(e){count++}}console.log(count)"""
        r=subprocess.run(['node','-e',js,str(source)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(r.stdout.strip(),'4')

    @unittest.skipUnless(shutil.which('node'),'Node.js fuer optionale JS-Parser-Tests nicht installiert')
    def test_bulk_limit_and_quoted_description(self):
        source=Path(__file__).resolve().parents[1]/'app/static/bulk_lines.js'
        js="""const p=require(process.argv[1]); const x=p.parse('"Montage; Wartung";2;Std.;99,50','invoice','8.1'); let oversized=false;try{p.parse('Ware;1;3\\n'.repeat(151),'invoice','0')}catch(e){oversized=true}console.log(JSON.stringify({description:x[0].description,oversized}));"""
        result=subprocess.run(['node','-e',js,str(source)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        parsed=json.loads(result.stdout)
        self.assertEqual(parsed['description'],'Montage; Wartung')
        self.assertTrue(parsed['oversized'])

    def test_migrate_old_customer_without_payment_days(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'rechnung.sqlite3'
            initialize(path)
            con=db_connect(path)
            try:
                con.execute("INSERT INTO companies(id,name) VALUES(1,'Alt')")
                con.execute("INSERT INTO customers(id,company_id,name,number) VALUES(1,1,'Alt Kunde','K1')")
                con.execute('ALTER TABLE customers DROP COLUMN payment_days')
                con.execute('PRAGMA user_version=6')
                con.commit()
            finally:con.close()
            initialize(path)
            con=db_connect(path)
            try:
                self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],14)
                self.assertEqual(tuple(con.execute('SELECT name,payment_days FROM customers WHERE id=1').fetchone()),('Alt Kunde',0))
            finally:con.close()
