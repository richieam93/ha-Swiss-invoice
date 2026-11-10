"""1.4: Editor-Komfort, Live-Nummern, unverbindliche Vorschau, Migration."""
import io
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.db import db_connect, initialize
from app.main import create_app


class EditorVersion14Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.client=TestClient(create_app(self.tmp.name),follow_redirects=True)
        self.client.get('/setup')
        self.client.post('/setup',data={
            '_csrf':self.token('/setup'),'company_name':'Test GmbH','email':'test@example.ch',
            'full_name':'Test Person','password':'SehrSicheresPasswort_13','password2':'SehrSicheresPasswort_13'})
        self.client.post('/settings',data={
            '_csrf':self.token('/settings'),'name':'Test GmbH','street':'Bahnhofplatz','building':'1',
            'zip':'3011','city':'Bern','country':'CH','iban':'CH9300762011623852957',
            'default_due_days':'30','qr_reference_type':'SCOR','qr_message':'Rechnung {number}',
            'currency':'CHF','number_prefix':'RE'})
        self.client.post('/customers/save',data={
            '_csrf':self.token('/customers/new'),'name':'Kunde Muster AG',
            'street':'Hauptweg','building':'4','zip':'8000','city':'Zuerich','country':'CH'})

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def token(self,url='/invoices/new'):
        response=self.client.get(url)
        match=re.search(r'name="_csrf"\s+(?:type="hidden"\s+)?value="([a-f0-9]+)"',response.text)
        self.assertIsNotNone(match,response.text[:500])
        return match.group(1)

    def data(self, **kw):
        base={'_csrf':self.token(),'kind':'invoice','customer_id':'1','invoice_date':'2026-11-08',
              'service_date':'2026-11-08','due_date':'2026-12-08','currency':'CHF',
              'subject':'Projekt Modernisierung', 'notes':'Vielen Dank','discount':'0',
              'description[]':['Arbeit'], 'qty[]':['2'], 'unit[]':['Std.'],
              'price[]':['100.00'], 'tax_rate[]':['0'], 'tax_mode[]':['taxable'],
              'discount[]':['0'], 'item_id[]':['']}
        base.update(kw)
        return base

    def rows(self,query):
        con=db_connect(Path(self.tmp.name)/'rechnung.sqlite3')
        try:return [tuple(x) for x in con.execute(query)]
        finally:con.close()

    def test_unsaved_preview_no_new_invoice_and_no_qr_payment_page(self):
        response=self.client.post('/invoices/preview.pdf',data=self.data(),follow_redirects=False)
        self.assertEqual(response.status_code,200,response.text[:500] if response.status_code!=200 else '')
        self.assertEqual(response.headers['content-type'],'application/pdf')
        pdf=PdfReader(io.BytesIO(response.content))
        self.assertEqual(len(pdf.pages),1)
        text=pdf.pages[0].extract_text()
        self.assertIn('ENTWURF - NICHT VERSENDEN',text)
        self.assertIn('Projekt Modernisierung',text)
        self.assertIn('Kunde Muster AG',text)
        self.assertEqual(self.rows('SELECT count(*) FROM invoices'),[(0,)])
        self.assertEqual(self.rows('SELECT next_invoice FROM companies'),[(1,)])

    def test_new_customer_preview_does_not_create_customer(self):
        data=self.data(customer_id='',new_customer_name='Fiktiver Neukunde',
                       new_customer_city='Thun',new_customer_zip='3600',new_customer_country='CH')
        response=self.client.post('/invoices/preview.pdf',data=data)
        self.assertEqual(response.status_code,200)
        self.assertIn('Fiktiver Neukunde',PdfReader(io.BytesIO(response.content)).pages[0].extract_text())
        self.assertEqual(self.rows('SELECT count(*) FROM customers'),[(1,)])

    def test_preview_auth_and_csrf(self):
        response=self.client.post('/invoices/preview.pdf',data={'kind':'invoice'})
        self.assertEqual(response.status_code,403)
        c=TestClient(create_app(self.tmp.name),follow_redirects=False)
        try:self.assertEqual(c.post('/invoices/preview.pdf',data=self.data()).status_code,303)
        finally:c.close()

    def test_valid_and_occupied_number_checker(self):
        r=self.client.get('/api/invoices/check-number?number=RE-2026-555')
        self.assertTrue(r.json()['available'])
        r=self.client.get('/api/invoices/check-number?number=BAD%2FNO')
        self.assertFalse(r.json()['available'])
        self.client.post('/invoices/save',data=self.data(number='RE-2026-555'))
        self.assertFalse(self.client.get('/api/invoices/check-number?number=re-2026-555').json()['available'])
        self.assertTrue(self.client.get('/api/invoices/check-number?number=RE-2026-555&exclude_id=1').json()['available'])
        self.assertEqual(self.rows('SELECT subject FROM invoices'),[('Projekt Modernisierung',)])

    def test_subject_copied_to_new_draft(self):
        self.client.post('/invoices/save',data=self.data())
        self.client.post('/invoices/1/copy',data={'_csrf':self.token('/invoices/1'),'action':'copy'})
        self.assertEqual(self.rows('SELECT subject FROM invoices ORDER BY id'),
                         [('Projekt Modernisierung',),('Projekt Modernisierung',)])

    def test_saved_draft_pdf_is_marked_issued_is_not(self):
        self.client.post('/invoices/save',data=self.data())
        pdf=PdfReader(io.BytesIO(self.client.get('/invoices/1/pdf').content))
        self.assertGreaterEqual(len(pdf.pages),2)
        self.assertIn('ENTWURF - NICHT VERSENDEN',pdf.pages[0].extract_text())
        self.assertIn('ENTWURF - NICHT VERSENDEN',pdf.pages[-1].extract_text())
        self.client.post('/invoices/1/issue',data={'_csrf':self.token('/invoices/1')})
        issued=PdfReader(io.BytesIO(self.client.get('/invoices/1/pdf').content))
        self.assertNotIn('ENTWURF - NICHT VERSENDEN',issued.pages[0].extract_text())
        self.assertIn('Projekt Modernisierung',issued.pages[0].extract_text())

    def test_preview_disallows_cross_company_invoice_id(self):
        self.client.post('/invoices/save',data=self.data())
        self.client.post('/companies/new',data={'_csrf':self.token('/companies/new'),'name':'Zweite Firma'})
        r=self.client.post('/invoices/preview.pdf',data=self.data(id='1',customer_id=''))
        self.assertEqual(r.status_code,404)

    def test_live_ux_and_diagnostics_present(self):
        html=self.client.get('/invoices/new').text
        for element in ('id="item-search"','id="undo-row"','id="preview-invoice-pdf"',
                        'id="invoice-subject"','id="number-availability"','id="tax-buckets-live"'):
            self.assertIn(element,html)
        self.assertIn('QR-Diagnose',self.client.get('/settings').text)
        self.client.post('/invoices/save',data=self.data())
        self.assertIn('Vor der Freigabe pruefen',self.client.get('/invoices/1').text)

    def test_invalid_document_fields_cannot_preview(self):
        bad=self.data(**{'qty[]':['0']})
        self.assertEqual(self.client.post('/invoices/preview.pdf',data=bad).status_code,422)
        self.assertEqual(self.rows('SELECT count(*) FROM invoices'),[(0,)])


class Migration14Tests(unittest.TestCase):
    def test_additive_migration_keeps_old_invoice_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'rechnung.sqlite3'
            # Create a v1.3 database by dropping the new 1.4 column from schema using sqlite3.
            initialize(path)
            con=db_connect(path)
            try:
                con.execute("INSERT INTO users(email,password_hash,full_name) VALUES('a@b.ch','hash','A')")
                con.execute("INSERT INTO companies(name) VALUES('ALT GmbH')")
                con.execute("INSERT INTO customers(company_id,name) VALUES(1,'Bestehender Kunde')")
                con.execute("INSERT INTO invoices(company_id,kind,number,customer_id,invoice_date,due_date) VALUES(1,'invoice','ALT-200',1,'2026-11-07','2026-11-30')")
                con.commit()
                con.execute('ALTER TABLE invoices DROP COLUMN subject')
                con.execute('PRAGMA user_version=4')
                con.commit()
            finally:con.close()
            initialize(path)
            con=db_connect(path)
            try:
                self.assertEqual([tuple(row) for row in con.execute('SELECT number,subject FROM invoices')],[('ALT-200','')])
                self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],11)
            finally:con.close()
