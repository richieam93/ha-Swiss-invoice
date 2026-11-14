"""V1.7: saved designs, tenant permissions and PDF changes actually rendered."""
import io
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

from app.db import db_connect, initialize
from app.main import create_app
from app.pdf import make_pdf


class LibraryV17Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)
        self.client=TestClient(create_app(self.path),follow_redirects=True)
        self.client.get('/setup')
        self.client.post('/setup',data={
            '_csrf':self.token('/setup'),'company_name':'Design Test AG',
            'email':'studio@example.ch','full_name':'Administrator',
            'password':'TestPasswort2026!','password2':'TestPasswort2026!'})

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def token(self,path='/templates'):
        match=re.search(r'name="_csrf"[^>]*value="([0-9a-f]+)"', self.client.get(path).text)
        self.assertIsNotNone(match)
        return match.group(1)

    def data(self,**kw):
        values={
            '_csrf':self.token(), 'template_style':'modern','template_accent':'#0f766e',
            'template_title':'Service-Rechnung','template_footer':'Erstellt in Bern',
            'template_header_layout':'mirrored','template_title_size':'30',
            'template_density':'normal','template_show_logo':'1',
            'template_show_service_date':'1','template_show_tax_breakdown':'1',
            'template_show_payment_terms':'1','template_show_page_numbers':'1',
            'template_table_style':'zebra','template_logo_size':'140',
            'template_body_size':'10','default_invoice_notes':'Vielen Dank!',
        }
        values.update(kw)
        return values

    def rows(self,sql,*params):
        con=db_connect(self.path/'rechnung.sqlite3')
        try:return [tuple(row) for row in con.execute(sql,params)]
        finally:con.close()

    def pdftext(self,resp):
        self.assertEqual(resp.status_code,200)
        self.assertTrue(resp.content.startswith(b'%PDF'))
        return '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(resp.content)).pages)

    def test_initial_library_preserves_existing_live_design(self):
        con=db_connect(self.path/'rechnung.sqlite3')
        try:
            con.execute("UPDATE companies SET template_title='Historischer Titel' WHERE id=1")
            con.commit()
        finally:con.close()
        html=self.client.get('/templates').text
        self.assertIn('Standard',html)
        self.assertIn('Historischer Titel',html)
        self.assertEqual(self.rows('SELECT name,active FROM invoice_templates'), [('Standard',1)])
        self.assertEqual(self.rows('SELECT template_title FROM companies'),[('Historischer Titel',)])

    def test_save_as_activate_switch_and_active_save(self):
        self.client.post('/templates/save-as',data=self.data(template_name='Petrol Design'))
        self.assertEqual(self.rows('SELECT name,active FROM invoice_templates ORDER BY id'),
                         [('Standard',0),('Petrol Design',1)])
        self.assertEqual(self.rows('SELECT template_body_size,template_logo_size,template_table_style FROM companies'),
                         [(10,140,'zebra')])
        self.client.post('/templates',data=self.data(template_title='Neuer Titel'))
        self.assertIn('Neuer Titel',self.pdftext(self.client.get('/templates/preview.pdf')))
        self.client.post('/templates/activate',data={'_csrf':self.token(),'template_id':'1'})
        self.assertEqual(self.rows('SELECT template_title FROM companies'), [('Rechnung',)])
        self.assertIn('Rechnung',self.pdftext(self.client.get('/templates/preview.pdf')))
        self.client.post('/templates/activate',data={'_csrf':self.token(),'template_id':'2'})
        self.assertEqual(self.rows('SELECT template_title FROM companies'), [('Neuer Titel',)])
        self.assertEqual(self.rows('SELECT active FROM invoice_templates ORDER BY id'),[(0,),(1,)])

    def test_delete_inactive_not_active(self):
        self.client.post('/templates/save-as',data=self.data(template_name='Alternativ'))
        r=self.client.post('/templates/delete',data={'_csrf':self.token(),'template_id':'2'})
        self.assertIn('aktive Vorlage',r.text)
        self.assertEqual(len(self.rows('SELECT id FROM invoice_templates')),2)
        self.client.post('/templates/delete',data={'_csrf':self.token(),'template_id':'1'})
        self.assertEqual(self.rows('SELECT name FROM invoice_templates'),[('Alternativ',)])

    def test_duplicate_name_and_invalid_design_never_change_live(self):
        self.client.post('/templates/save-as',data=self.data(template_name='Gold'))
        before=self.rows('SELECT template_title,template_accent FROM companies')
        bad=self.client.post('/templates/save-as',data=self.data(template_name='gold',template_title='Nicht speichern'))
        self.assertIn('bereits vergeben',bad.text)
        for kw in ({'template_table_style':'unknown'}, {'template_logo_size':'1000'},
                   {'template_body_size':'99'}, {'template_title':'x'*61}):
            response=self.client.post('/templates/save-as',data=self.data(template_name='Invalid',**kw))
            self.assertIn('notice error',response.text)
        self.assertEqual(self.rows('SELECT template_title,template_accent FROM companies'),before)
        self.assertEqual(len(self.rows('SELECT id FROM invoice_templates')),2)

    def test_rename_active_and_inactive_preserves_design(self):
        self.client.post('/templates/save-as',data=self.data(template_name='Alt'))
        self.client.post('/templates/rename',data={'_csrf':self.token(),'template_id':'2','template_name':'Neu'})
        self.assertEqual(self.rows('SELECT name FROM invoice_templates WHERE active=1'), [('Neu',)])
        before=self.rows('SELECT template_title FROM companies')
        response=self.client.post('/templates/rename',data={'_csrf':self.token(),'template_id':'1','template_name':'Neu'})
        self.assertIn('bereits',response.text)
        self.assertEqual(self.rows('SELECT template_title FROM companies'),before)
        self.assertEqual(self.rows('SELECT name FROM invoice_templates ORDER BY id'), [('Standard',),('Neu',)])

    def test_preview_types_never_save(self):
        initial=self.rows('SELECT COUNT(*) FROM invoices')
        for kind,title in [('invoice','Test Betreff'),('quote','Offerte'),('credit','Gutschrift')]:
            response=self.client.post('/templates/preview.pdf',data=self.data(_preview_kind=kind,template_title='Test Betreff'))
            text=self.pdftext(response)
            self.assertIn(title,text)
            self.assertIn('ENTWURF - NICHT VERSENDEN',text)
            self.assertNotIn('Zahlteil und Empfangsschein',text)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM invoices'),initial)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM invoice_templates'),[(1,)])
        self.assertEqual(self.client.get('/templates/preview.pdf?kind=invalid').status_code,422)

    def test_library_access_requires_login_and_csrf(self):
        for path in ('/templates/save-as','/templates/activate','/templates/delete'):
            self.assertEqual(self.client.post(path,data={'template_id':1}).status_code,403)
        anonymous=TestClient(create_app(self.path),follow_redirects=False)
        try:
            self.assertEqual(anonymous.post('/templates/activate',data={'_csrf':'1','template_id':'1'}).status_code,303)
        finally:anonymous.close()

    def test_business_isolation_and_no_cross_tenant_switch(self):
        self.client.post('/templates/save-as',data=self.data(template_name='Nur A'))
        self.client.post('/companies/new',data={'_csrf':self.token('/companies/new'),'name':'Firma B'})
        html=self.client.get('/templates').text
        self.assertNotIn('Nur A',html)
        self.assertEqual(self.rows('SELECT company_id,name FROM invoice_templates ORDER BY id'),
                         [(1,'Standard'),(1,'Nur A'),(2,'Standard')])
        for path in ('/templates/activate','/templates/delete'):
            r=self.client.post(path,data={'_csrf':self.token(),'template_id':'2'},follow_redirects=False)
            self.assertEqual(r.status_code,404)
        self.assertEqual(self.rows('SELECT active FROM invoice_templates WHERE company_id=1 ORDER BY id'),
                         [(0,),(1,)])
        self.assertIn('Standard',self.client.get('/templates').text)

    def test_named_templates_do_not_modify_existing_issued_pdf(self):
        self.client.post('/customers/save',data={
            '_csrf':self.token('/customers/new'),'name':'Kundin AG',
            'street':'Alpenweg','building':'2','zip':'3011','city':'Bern','country':'CH'})
        self.client.post('/invoices/save',data={
            '_csrf':self.token('/invoices/new'),'customer_id':'1','kind':'invoice',
            'invoice_date':'2026-11-08','due_date':'2026-12-08','service_date':'2026-11-08',
            'currency':'CHF','discount':'0','description[]':['Arbeit'],
            'qty[]':['1'],'unit[]':['Stk.'],'price[]':['50'],
            'tax_rate[]':['0'],'tax_mode[]':['taxable'],
            'item_id[]':[''],'discount[]':['0']})
        self.client.post('/invoices/1/issue',data={'_csrf':self.token('/invoices/1')})
        pdf_before=self.client.get('/invoices/1/pdf').content
        self.client.post('/templates/save-as',data=self.data(template_name='Anders',template_title='NEUES DESIGN'))
        self.assertEqual(pdf_before,self.client.get('/invoices/1/pdf').content)

    def test_printed_table_optics_and_font_size_change_pdf(self):
        company={'id':1,'name':'Test AG','street':'Weg','building':'1','zip':'3000',
                 'city':'Bern','country':'CH','iban':'','template_style':'modern'}
        customer={'name':'Kunde','street':'Testweg','building':'2','zip':'3000','city':'Bern'}
        inv={'kind':'quote','number':'TEST-1','invoice_date':'2026-11-08',
             'service_date':'2026-11-08','due_date':'2026-12-01','currency':'CHF',
             'subtotal':'200.00','tax_total':'0.00','total':'200.00','tax_breakdown':'{}'}
        lines=[{'description':f'Position {i}','qty':'1','unit':'Stk.',
                'price':'100','line_net':'100','discount':'0','tax_rate':'0'} for i in range(2)]
        plain,_=make_pdf(inv,dict(company,template_table_style='clean',template_body_size=8),customer,lines)
        shaded,_=make_pdf(inv,dict(company,template_table_style='zebra',template_body_size=10),customer,lines)
        self.assertNotEqual(plain,shaded)
        stream_plain=PdfReader(io.BytesIO(plain)).pages[0].get_contents().get_data()
        stream_shaded=PdfReader(io.BytesIO(shaded)).pages[0].get_contents().get_data()
        # Zebra rows are extra filled PDF rectangles; clean has none.
        self.assertGreater(len(re.findall(rb'\bre\b',stream_shaded)),
                           len(re.findall(rb'\bre\b',stream_plain)))

    def test_logo_size_changes_image_dimensions_and_long_footer_wraps(self):
        logo=self.path/'logo.png'
        Image.new('RGB',(200,80),'white').save(logo)
        company={'id':1,'name':'Test AG','street':'Weg','building':'1','zip':'3000',
                 'city':'Bern','country':'CH','iban':'','template_style':'modern',
                 'logo_path':str(logo),'template_show_logo':1,
                 'template_footer':'Ein wirklich sehr langer Fusszeilentext mit wichtigen '
                         'Informationen zur Adresse und zu unseren Bedingungen. '*3}
        customer={'name':'Kunde','street':'Testweg','building':'2','zip':'3000','city':'Bern'}
        inv={'kind':'quote','number':'TEST-1','invoice_date':'2026-11-08',
             'service_date':'2026-11-08','due_date':'2026-12-01','currency':'CHF',
             'subtotal':'100.00','tax_total':'0.00','total':'100.00','tax_breakdown':'{}'}
        lines=[{'description':'Leistung','qty':'1','unit':'Stk.','price':'100',
                'line_net':'100','discount':'0','tax_rate':'0'}]
        results=[]
        for width in (80,140):
            pdf,_=make_pdf(inv,dict(company,template_logo_size=width),customer,lines)
            page=PdfReader(io.BytesIO(pdf)).pages[0]
            raw=page.get_contents().get_data()
            logo_match=re.search(rb'(?m)^([0-9.]+) 0 0 [0-9.]+ [0-9.]+ [0-9.]+ cm\s*/FormX',raw)
            self.assertIsNotNone(logo_match)
            results.append(float(logo_match.group(1)))
            self.assertIn('...',page.extract_text())
        self.assertLess(results[0],results[1])

    def test_existing_company_migration_is_additive(self):
        # Drop fields from a second fresh database to imitate v1.6.
        with tempfile.TemporaryDirectory() as t:
            db=Path(t)/'rechnung.sqlite3'
            initialize(db)
            con=db_connect(db)
            try:
                con.execute("INSERT INTO companies(name) VALUES('Alt AG')")
                con.execute("INSERT INTO customers(company_id,name) VALUES(1,'Alt Kunde')")
                con.execute("INSERT INTO invoices(company_id,kind,number,invoice_date,due_date) VALUES(1,'quote','ALT-42','2026-11-01','2026-12-01')")
                for column in ('template_table_style','template_logo_size','template_body_size','template_show_page_numbers'):
                    con.execute('ALTER TABLE companies DROP COLUMN '+column)
                con.execute('DROP TABLE invoice_templates')
                con.execute('PRAGMA user_version=7')
                con.commit()
            finally:con.close()
            initialize(db)
            initialize(db)
            con=db_connect(db)
            try:
                self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],15)
                self.assertEqual(con.execute('SELECT number FROM invoices').fetchone()[0],'ALT-42')
                self.assertEqual(con.execute('SELECT name FROM customers').fetchone()[0],'Alt Kunde')
                self.assertEqual(con.execute('SELECT template_logo_size FROM companies').fetchone()[0],110)
                self.assertEqual(con.execute('SELECT COUNT(*) FROM invoice_templates').fetchone()[0],0)
            finally:con.close()


if __name__=='__main__': unittest.main()
