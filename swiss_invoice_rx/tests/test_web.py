import io
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from pypdf import PdfReader
from app.main import create_app

class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.client=TestClient(create_app(self.tmp.name), follow_redirects=True)
        self.client.get('/setup')
        self.setup_token=self.csrf()
        r=self.client.post('/setup',data={'_csrf':self.setup_token,'company_name':'Meine Firma AG',
                   'email':'admin@example.ch','full_name':'Admin User','password':'Passwort_Mindestens_10','password2':'Passwort_Mindestens_10'})
        self.assertEqual(r.status_code,200,r.text[:500])
        self.save_settings()

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def csrf(self):
        # SessionMiddleware signiertes Cookie, CSRF-Token im sichtbaren Form-HTML
        import re,html
        r=self.client.get('/settings') if self.client.cookies.get('helvetic_session') else self.client.get('/setup')
        if r.status_code==403:
            r=self.client.get('/dashboard')
        match=re.search(r'name="_csrf" value="([a-f0-9]+)"',r.text)
        self.assertIsNotNone(match, r.text[:700])
        return match.group(1)

    def save_settings(self):
        token=self.csrf()
        r=self.client.post('/settings',data={
            '_csrf':token,'name':'Meine Firma AG','street':'Talstrasse','building':'11',
            'zip':'3011','city':'Bern','country':'CH','iban':'CH9300762011623852957',
            'currency':'CHF','tax_registered':'1','default_tax':'8.1','color':'#2563eb','number_prefix':'RE',
            'payment_terms':'Zahlbar innert {days} Tagen','default_due_days':'30'},follow_redirects=True)
        self.assertEqual(r.status_code,200,r.text[:300])

    def create_customer(self,name='Kunde AG'):
        token=self.csrf()
        r=self.client.post('/customers/save',data={'_csrf':token,'name':name,
            'street':'Hauptstrasse','building':'1','zip':'8000','city':'Zuerich','country':'CH'})
        self.assertEqual(r.status_code,200,r.text[:300])

    def make_invoice(self):
        token=self.csrf()
        r=self.client.post('/invoices/save',data={
            '_csrf':token,'kind':'invoice','customer_id':'1','invoice_date':'2026-11-08',
            'service_date':'2026-11-08','due_date':'2026-12-08','currency':'CHF','discount':'0',
            'description[]':['Beratung','Material'], 'qty[]':['2','1'],'unit[]':['Std.','Stk.'],
            'price[]':['120.00','50.00'],'tax_rate[]':['8.1','2.6'],
            'item_id[]':['',''], 'discount[]':['0','0']})
        self.assertEqual(r.status_code,200,r.text[:300])
        self.assertIn('RE-2026-00001',r.text)

    def test_creation_pdf_payment_copy(self):
        self.create_customer(); self.make_invoice()
        r=self.client.get('/invoices/1/pdf')
        self.assertEqual(r.status_code,200,r.text[:300] if r.status_code!=200 else '')
        self.assertEqual(r.content[:4],b'%PDF')
        reader=PdfReader(io.BytesIO(r.content))
        self.assertGreaterEqual(len(reader.pages),2)
        self.assertIn('RE-2026-00001',reader.pages[0].extract_text())
        r=self.client.post('/invoices/1/issue',data={'_csrf':self.csrf()})
        self.assertIn('Beleg freigegeben',r.text)
        r=self.client.get('/invoices/1/pdf')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.content[:4],b'%PDF')
        r=self.client.post('/invoices/1/payment',data={'_csrf':self.csrf(),
           'paid_at':'2026-11-08','amount':'100.00','method':'Bank'})
        self.assertIn('Zahlung erfasst',r.text)
        r=self.client.post('/invoices/1/copy',data={'_csrf':self.csrf(),'action':'copy'})
        self.assertIn('RE-2026-00002',r.text)
        r=self.client.post('/invoices/1/copy',data={'_csrf':self.csrf(),'action':'credit'})
        self.assertIn('GS-2026-00001',r.text)
        r=self.client.post('/invoices/1/payment',data={'_csrf':self.csrf(),
           'paid_at':'2026-11-08','amount':'1000.00','method':'Bank'})
        self.assertIn('Zahlung uebersteigt',r.text)

    def test_company_isolation_and_csrf(self):
        self.create_customer();self.make_invoice()
        self.client.post('/companies/new',data={'_csrf':self.csrf(),'name':'Zweite Firma'})
        r=self.client.get('/customers')
        self.assertNotIn('Kunde AG',r.text)
        r=self.client.get('/invoices/1')
        self.assertEqual(r.status_code,404)
        r=self.client.get('/invoices/1/pdf')
        self.assertEqual(r.status_code,404)
        r=self.client.post('/customers/save',data={'name':'Bad Without CSRF'})
        self.assertEqual(r.status_code,403)
        # Wechsel zum ersten Mandanten
        self.client.post('/company/switch',data={'_csrf':self.csrf(),'company_id':'1'})
        self.assertIn('Kunde AG',self.client.get('/customers').text)

    def test_not_issued_if_qr_address_invalid(self):
        self.create_customer();self.make_invoice()
        # Kundenadresse nachträglich entfernen
        token=self.csrf()
        self.client.post('/customers/save',data={'_csrf':token,'id':'1','name':'Kunde AG',
                     'street':'Weg','country':'CH','city':'','zip':''})
        r=self.client.post('/invoices/1/issue',data={'_csrf':self.csrf()})
        self.assertIn('strukturierte Adresse',r.text)
        self.assertIn('Entwurf',self.client.get('/invoices/1').text)

    def test_stock_movements_issue_and_cancel(self):
        from app.db import db_connect
        self.create_customer()
        r=self.client.post('/items/save',data={
            '_csrf':self.csrf(), 'sku':'KABEL-7','name':'Netzwerkkabel',
            'kind':'product','price':'10.00','cost':'4.00','tax_rate':'8.1',
            'tax_mode':'taxable','stock':'7','track_stock':'1'})
        self.assertIn('Artikel gespeichert',r.text)
        r=self.client.post('/invoices/save',data={
            '_csrf':self.csrf(),'kind':'invoice','customer_id':'1',
            'invoice_date':'2026-11-08','service_date':'2026-11-08','due_date':'2026-12-08',
            'currency':'CHF','discount':'0',
            'description[]':['Netzwerkkabel'],'qty[]':['2'], 'unit[]':['Stk.'],
            'price[]':['10'], 'tax_rate[]':['8.1'], 'tax_mode[]':['taxable'],
            'item_id[]':['1'],'discount[]':['0']})
        self.assertIn('RE-2026-00001',r.text)
        self.client.post('/invoices/1/issue',data={'_csrf':self.csrf()})
        conn=db_connect(Path(self.tmp.name)/'rechnung.sqlite3')
        try:
            self.assertEqual(conn.execute('SELECT stock FROM items WHERE id=1').fetchone()['stock'],'5')
            self.assertEqual(conn.execute('SELECT quantity FROM stock_movements WHERE invoice_id=1').fetchone()['quantity'],'-2')
        finally:conn.close()
        self.client.post('/invoices/1/cancel',data={'_csrf':self.csrf()})
        conn=db_connect(Path(self.tmp.name)/'rechnung.sqlite3')
        try:
            self.assertEqual(conn.execute('SELECT stock FROM items WHERE id=1').fetchone()['stock'],'7')
            movements=conn.execute('SELECT quantity,note FROM stock_movements ORDER BY id').fetchall()
            self.assertEqual(len(movements),2)
            self.assertEqual([m['quantity'] for m in movements],['-2','2'])
            self.assertTrue(movements[1]['note'].startswith('Storno '))
        finally:conn.close()

    def test_recurring_templates_and_pdf_tamper_detection(self):
        self.create_customer(); self.make_invoice()
        self.client.post('/invoices/1/recurring',data={
            '_csrf':self.csrf(),'interval_months':'1','next_date':'2026-11-30'})
        r=self.client.post('/recurring/1/generate',data={'_csrf':self.csrf()})
        self.assertIn('RE-2026-00002',r.text)
        from app.db import db_connect
        conn=db_connect(Path(self.tmp.name)/'rechnung.sqlite3')
        try:
            self.assertEqual(conn.execute('SELECT next_date FROM recurrings WHERE id=1').fetchone()[0],'2026-12-30')
        finally:conn.close()
        r=self.client.post('/templates',data={
            '_csrf':self.csrf(),'template_style':'classic','template_accent':'#e13278',
            'template_title':'Ihre Dienstleistungsrechnung','template_footer':'Herzlichen Dank',
            'template_show_logo':'1'})
        self.assertIn('Rechnungsvorlage gespeichert',r.text)
        r=self.client.get('/invoices/2/pdf')
        self.assertEqual(r.content[:4],b'%PDF')
        self.assertIn('Ihre Dienstleistungsrechnung',PdfReader(io.BytesIO(r.content)).pages[0].extract_text())
        self.client.post('/invoices/1/issue',data={'_csrf':self.csrf()})
        archived=Path(self.tmp.name)/'archive'/'1'/'00000001.pdf'
        self.assertTrue(archived.exists())
        archived.write_bytes(archived.read_bytes()+b'altered')
        self.assertEqual(self.client.get('/invoices/1/pdf').status_code,409)

    def test_currency_reports_are_separate(self):
        self.create_customer(); self.make_invoice()
        r=self.client.post('/invoices/1/copy',data={'_csrf':self.csrf(),'action':'copy'})
        self.assertIn('RE-2026-00002',r.text)
        r=self.client.post('/invoices/save',data={
            '_csrf':self.csrf(),'id':'2','kind':'invoice','customer_id':'1',
            'invoice_date':'2026-11-08','service_date':'2026-11-08',
            'due_date':'2026-12-08','currency':'EUR','discount':'0',
            'description[]':['EU-Service'],'qty[]':['1'],'unit[]':['Stk.'],
            'price[]':['100'],'tax_rate[]':['0'],'tax_mode[]':['taxable'],
            'discount[]':['0'], 'item_id[]':['']})
        self.assertEqual(r.status_code,200)
        self.client.post('/invoices/1/issue',data={'_csrf':self.csrf()})
        self.client.post('/invoices/2/issue',data={'_csrf':self.csrf()})
        chf=self.client.get('/reports?currency=CHF').text
        eur=self.client.get('/reports?currency=EUR').text
        self.assertIn("<small>CHF</small>",chf)
        self.assertIn("<small>EUR</small>",eur)
        self.assertIn("<div class=\"metric-value\">100.00 <small>EUR</small>",eur)
        self.assertNotIn("<div class=\"metric-value\">100.00 <small>CHF</small>",chf)
        self.assertIn('100.00',self.client.get('/dashboard?currency=EUR').text)

    def test_viewer_permissions_and_company_switch_script(self):
        self.create_customer(); self.make_invoice()
        r=self.client.post('/team',data={'_csrf':self.csrf(),'email':'viewer@example.ch',
            'full_name':'Leserin','role':'viewer','password':'SicheresPasswort123'})
        self.assertIn('Zugang gespeichert',r.text)
        self.client.post('/logout',data={'_csrf':self.csrf()})
        r=self.client.get('/login')
        self.assertIn('Anmelden',r.text)
        self.client.post('/login',data={'_csrf':self.csrf(),'email':'viewer@example.ch',
            'password':'SicheresPasswort123'})
        self.assertEqual(self.client.get('/settings').status_code,403)
        self.assertEqual(self.client.get('/customers').status_code,200)
        self.assertEqual(self.client.get('/invoices/1').status_code,200)
        self.assertNotIn('Freigeben &amp; archivieren',self.client.get('/invoices/1').text)
        self.assertEqual(self.client.post('/customers/save',data={
            '_csrf':self.csrf(),'name':'Nicht erlaubt'}).status_code,403)
        dashboard=self.client.get('/dashboard').text
        self.assertNotIn('href="/invoices/new"',dashboard)
        self.assertIn('id="company-switch"',dashboard)
        self.assertNotIn('onchange="this.form.submit()"',dashboard)

    def test_password_change_and_team_revocation(self):
        r=self.client.get('/account')
        self.assertIn('Passwort ändern',r.text)
        r=self.client.post('/account/password',data={
            '_csrf':self.csrf(),'password_old':'Passwort_Mindestens_10',
            'password_new':'NeuesSicheresPasswort22','password_confirm':'NeuesSicheresPasswort22'})
        self.assertIn('Passwort wurde geaendert',r.text)
        self.client.post('/logout',data={'_csrf':self.csrf()})
        r=self.client.post('/login',data={'_csrf':self.csrf(),'email':'admin@example.ch',
            'password':'Passwort_Mindestens_10'})
        self.assertIn('Anmeldung fehlgeschlagen',r.text)
        r=self.client.post('/login',data={'_csrf':self.csrf(),'email':'admin@example.ch',
            'password':'NeuesSicheresPasswort22'})
        self.assertIn('Dashboard',r.text)
        self.client.post('/team',data={'_csrf':self.csrf(),'email':'helper@example.ch',
            'full_name':'Helfer','role':'editor','password':'SicheresPasswort123'})
        r=self.client.get('/team')
        self.assertIn('helper@example.ch',r.text)
        r=self.client.post('/team/2/remove',data={'_csrf':self.csrf()})
        self.assertIn('Benutzerzugriff fuer dieses Geschaeft entfernt',r.text)
        self.assertNotIn('helper@example.ch',self.client.get('/team').text)

    def test_customer_history(self):
        self.create_customer();self.make_invoice()
        r=self.client.get('/customers/1')
        self.assertEqual(r.status_code,200)
        self.assertIn('KUNDENHISTORIE',r.text)
        self.assertIn('RE-2026-00001',r.text)
        self.assertIn('Kunde AG',r.text)
        r=self.client.get('/customers/123456')
        self.assertEqual(r.status_code,404)

    def test_csv_import_is_atomic_and_idempotent(self):
        data=('name;email;street;building;zip;city;country\n'
              'Alpha GmbH;office@alpha.ch;Weg;3;3000;Bern;CH\n'
              'Beta AG;beta@example.ch;Strasse;2;8000;Zurich;CH\n').encode('utf-8')
        r=self.client.post('/import/customers',data={'_csrf':self.csrf()},
                           files={'file':('kunden.csv',io.BytesIO(data),'text/csv')})
        self.assertIn('2 neu',r.text)
        self.assertIn('Alpha GmbH',r.text)
        r=self.client.post('/import/customers',data={'_csrf':self.csrf()},
                           files={'file':('kunden.csv',io.BytesIO(data),'text/csv')})
        self.assertIn('2 Duplikate',r.text)
        csv_file=self.client.get('/export/customers.csv').content.decode('utf-8-sig')
        self.assertIn('Alpha GmbH',csv_file)
        self.assertIn('K00001',csv_file)
        self.assertIn('K00002',csv_file)
        invalid=('name;city\nNeu AG;Bern\n;Zuerich\n').encode()
        r=self.client.post('/import/customers',data={'_csrf':self.csrf()},
                           files={'file':('kaputt.csv',io.BytesIO(invalid),'text/csv')})
        self.assertIn('CSV Zeile 3',r.text)
        self.assertNotIn('Neu AG',self.client.get('/customers').text)
        items=('sku;name;kind;category;cost;price;tax_rate;stock;track_stock\n'
               'K1;Kabel;product;Technik;5.00;10.50;8.1;8;1\n'
               'SERV1;Beratung;service;Dienstleistung;0;125;8.1;0;0\n').encode()
        r=self.client.post('/import/items',data={'_csrf':self.csrf()},
                           files={'file':('artikel.csv',io.BytesIO(items),'text/csv')})
        self.assertIn('2 neu',r.text)
        self.assertIn('Kabel',self.client.get('/items').text)
        r=self.client.post('/import/items',data={'_csrf':self.csrf()},
                           files={'file':('artikel.csv',io.BytesIO(items),'text/csv')})
        self.assertIn('2 Duplikate',r.text)
        self.assertTrue(self.client.get('/import/sample/items.csv').content.startswith(b'\xef\xbb\xbf'))

    def test_stock_adjustment_and_tenant_protection(self):
        from app.db import db_connect
        self.client.post('/items/save',data={'_csrf':self.csrf(),
            'sku':'STOCK-1','name':'Testlager','cost':'4','price':'9',
            'stock':'5','track_stock':'1'})
        r=self.client.post('/items/1/stock',data={'_csrf':self.csrf(),
            'action':'add','quantity':'3.5','note':'Wareneingang November'})
        self.assertIn('Bestand erfolgreich',r.text)
        self.assertIn('8.5',r.text)
        self.client.post('/items/1/stock',data={'_csrf':self.csrf(),
            'action':'set','quantity':'7','note':'Inventur korrigiert'})
        r=self.client.post('/items/1/stock',data={'_csrf':self.csrf(),
            'action':'add','quantity':'-100','note':'Unmoeglicher Bestand'})
        self.assertIn('Resultierender Bestand',r.text)
        conn=db_connect(Path(self.tmp.name)/'rechnung.sqlite3')
        try:
            self.assertEqual(float(conn.execute('SELECT stock FROM items WHERE id=1').fetchone()[0]),7.0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM stock_movements').fetchone()[0],2)
        finally:conn.close()
        self.client.post('/companies/new',data={'_csrf':self.csrf(),'name':'Fremd AG'})
        self.assertEqual(self.client.get('/items/1/stock').status_code,404)
        self.assertEqual(self.client.post('/items/1/stock',data={'_csrf':self.csrf(),
            'action':'add','quantity':'1','note':'Fremd'}).status_code,404)

    def test_payment_reversal_reminder_pdf_and_receivables(self):
        from app.db import db_connect
        self.create_customer();self.make_invoice()
        self.client.post('/invoices/1/issue',data={'_csrf':self.csrf()})
        self.client.post('/invoices/1/payment',data={'_csrf':self.csrf(),
            'paid_at':'2026-11-08','amount':'100.00','method':'Bank'})
        self.assertIn('Zahlungshistorie',self.client.get('/invoices/1').text)
        r=self.client.post('/invoices/1/payments/1/reverse',data={'_csrf':self.csrf(),
            'reason':'Doppelt eingetragene Bankzahlung'})
        self.assertIn('Zahlungsstorno protokolliert',r.text)
        self.assertIn('STORNIERT',r.text)
        self.assertIn('Doppelt eingetragene',r.text)
        r=self.client.post('/invoices/1/payments/1/reverse',data={'_csrf':self.csrf(),
            'reason':'Nochmal wiederholen'})
        self.assertIn('bereits storniert',r.text)
        conn=db_connect(Path(self.tmp.name)/'rechnung.sqlite3')
        try:
            self.assertEqual(conn.execute('SELECT paid_total FROM invoices WHERE id=1').fetchone()[0],'0.00')
            self.assertTrue(conn.execute('SELECT reversed_at FROM payments WHERE id=1').fetchone()[0])
        finally:conn.close()
        r=self.client.get('/receivables?currency=CHF')
        self.assertEqual(r.status_code,200)
        self.assertIn('RE-2026-00001',r.text)
        self.assertIn('Kunde AG',r.text)
        self.assertIn('offene-posten-CHF.csv',self.client.get('/receivables.csv?currency=CHF').headers['content-disposition'])
        r=self.client.post('/invoices/1/reminder',data={'_csrf':self.csrf(),
            'note':'Bitte den offenen Betrag einzahlen'})
        self.assertIn('Mahn-PDF erstellt',r.text)
        r=self.client.get('/invoices/1/reminders/1/pdf')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.content[:4],b'%PDF')
        reader=PdfReader(io.BytesIO(r.content))
        self.assertGreaterEqual(len(reader.pages),2)
        self.assertIn('Zahlungserinnerung',reader.pages[0].extract_text())
        archived=Path(self.tmp.name)/'archive'/'1'/'reminders'/'00000001-00000001.pdf'
        self.assertTrue(archived.exists())
        original=archived.read_bytes()
        archived.write_bytes(original+b'modified')
        self.assertEqual(self.client.get('/invoices/1/reminders/1/pdf').status_code,409)
        archived.write_bytes(original)
        self.client.post('/companies/new',data={'_csrf':self.csrf(),'name':'Zweite Gesellschaft'})
        self.assertEqual(self.client.get('/invoices/1/reminders/1/pdf').status_code,404)
