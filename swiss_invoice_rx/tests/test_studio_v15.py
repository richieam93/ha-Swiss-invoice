"""Version 1.5: template-studio PDF parity, safe previews, tenant isolation."""
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.db import db_connect, initialize
from app.main import create_app
from app.pdf import make_pdf, title_parts
from reportlab.pdfbase.pdfmetrics import stringWidth


class StudioVersion15Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.client=TestClient(create_app(self.tmp.name),follow_redirects=True)
        self.client.post('/setup',data={'_csrf':self.csrf('/setup'),
             'company_name':'Beispiel AG','email':'tester@example.ch',
             'full_name':'Test Benutzer','password':'SuperGeheim2026!',
             'password2':'SuperGeheim2026!'})
        self.client.post('/settings',data={
            '_csrf':self.csrf('/settings'),'name':'Beispiel AG',
            'street':'Hauptplatz','building':'5','zip':'3011',
            'city':'Bern','country':'CH','iban':'CH9300762011623852957',
            'currency':'CHF','tax_registered':'1','default_tax':'8.1',
            'payment_terms':'Zahlbar innert {days} Tagen.',
            'default_due_days':'30','number_prefix':'RE'})
        self.client.post('/customers/save',data={'_csrf':self.csrf('/customers/new'),
            'name':'Kunde AG','email':'mail@kunde.example','street':'Seeweg',
            'building':'2','zip':'8000','city':'Zuerich','country':'CH'})

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def csrf(self,route='/templates'):
        html=self.client.get(route).text
        match=re.search(r'name="_csrf"[^>]*value="([a-f0-9]+)"',html)
        self.assertIsNotNone(match,html[:600])
        return match.group(1)

    def options(self,**overrides):
        data={'_csrf':self.csrf(),
              'template_style':'modern','template_accent':'#0f766e',
              'template_title':'Service-Rechnung','template_footer':'Beispiel Fusszeile',
              'template_show_logo':'1','template_header_layout':'mirrored',
              'template_title_size':'30','template_density':'spacious',
              'template_show_customer_email':'1',
              'default_invoice_notes':'Danke fuer den Auftrag!'}
        data.update(overrides)
        return data

    def db(self,sql,args=()):
        con=db_connect(Path(self.tmp.name)/'rechnung.sqlite3')
        try:return [tuple(row) for row in con.execute(sql,args)]
        finally:con.close()

    def invoice(self,**overrides):
        data={'_csrf':self.csrf('/invoices/new'),'kind':'invoice',
              'customer_id':'1','invoice_date':'2026-11-08',
              'service_date':'2026-11-08','due_date':'2026-12-08',
              'currency':'CHF','discount':'0','description[]':['Beratung'],
              'qty[]':['2'],'unit[]':['Std.'],'price[]':['100.00'],
              'tax_rate[]':['8.1'],'tax_mode[]':['taxable'],
              'discount[]':['0'],'item_id[]':['']}
        data.update(overrides)
        return self.client.post('/invoices/save',data=data)

    def pdftext(self,response):
        self.assertEqual(response.headers.get('content-type'),'application/pdf')
        return '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(response.content)).pages)

    def test_ux_has_studio_controls_and_customer_search(self):
        html=self.client.get('/templates').text
        for control in ('id="template-studio"','id="tpl-density"','id="tpl-header"',
                        'id="tpl-size"','id="tpl-default-notes"','id="studio-undo"',
                        'formaction="/templates/preview.pdf"'):
            self.assertIn(control,html)
        r=self.client.get('/invoices/new')
        self.assertIn('id="customer-filter"',r.text)
        self.assertIn('id="customer-summary"',r.text)
        self.assertIn('Kunde AG',r.text)
        self.assertEqual(self.client.get('/static/template_studio.js').status_code,200)

    def test_studio_save_affects_real_pdf_and_default_text(self):
        r=self.client.post('/templates',data=self.options())
        self.assertIn('Rechnungsvorlage gespeichert',r.text)
        self.assertEqual(self.db('SELECT template_header_layout,template_title_size,template_density,default_invoice_notes FROM companies'),
                         [('mirrored',30,'spacious','Danke fuer den Auftrag!')])
        r=self.client.get('/invoices/new')
        self.assertIn('Danke fuer den Auftrag!',r.text)
        self.invoice(notes='Hallo auf dem PDF')
        pdf=self.pdftext(self.client.get('/invoices/1/pdf'))
        self.assertIn('Service-Rechnung',pdf)
        self.assertIn('mail@kunde.example',pdf)
        self.assertNotIn('Leistungsdatum:',pdf)
        self.assertNotIn('Zahlbar innert',pdf)
        self.assertIn('Hallo auf dem PDF',pdf)
        self.assertIn('Beispiel Fusszeile',pdf)

    def test_unsaved_pdf_preview_is_marked_and_does_not_save(self):
        before=self.db('SELECT template_style, template_title, template_density FROM companies')
        activity_before=self.db('SELECT COUNT(*) FROM activity')
        response=self.client.post('/templates/preview.pdf',data=self.options(template_title='Nur Vorschau'))
        text=self.pdftext(response)
        self.assertIn('Nur Vorschau',text)
        self.assertIn('ENTWURF - NICHT VERSENDEN',text)
        self.assertNotIn('Zahlteil und Empfangsschein',text)
        self.assertEqual(self.db('SELECT template_style, template_title, template_density FROM companies'),before)
        self.assertEqual(self.db('SELECT COUNT(*) FROM activity'),activity_before)
        self.assertEqual(self.db('SELECT COUNT(*) FROM invoices'),[(0,)])

    def test_saved_template_pdf_does_not_create_invoice_or_qr(self):
        text=self.pdftext(self.client.get('/templates/preview.pdf'))
        self.assertIn('MUSTER-RECHNUNG',text)
        self.assertIn('ENTWURF - NICHT VERSENDEN',text)
        self.assertNotIn('Zahlteil und Empfangsschein',text)
        self.assertEqual(self.db('SELECT COUNT(*) FROM invoices'),[(0,)])

    def test_invalid_template_input_rejected_without_persisting(self):
        before=self.db('SELECT template_title, template_density FROM companies')
        for bad in ({'template_header_layout':'invalid'},
                    {'template_density':'super-mini'},
                    {'template_title_size':'1000'},
                    {'template_style':'custom'},
                    {'template_title':'A'*61}):
            response=self.client.post('/templates/preview.pdf',data=self.options(**bad))
            self.assertEqual(response.status_code,422,response.text[:200])
            result=self.client.post('/templates',data=self.options(**bad))
            self.assertIn('error',result.text)
            self.assertEqual(self.db('SELECT template_title, template_density FROM companies'),before)

    def test_preview_protected_by_csrf_and_login(self):
        response=self.client.post('/templates/preview.pdf',data={'template_style':'modern'})
        self.assertEqual(response.status_code,403)
        second=TestClient(create_app(self.tmp.name),follow_redirects=False)
        try:
            response=second.post('/templates/preview.pdf',data=self.options())
            self.assertEqual(response.status_code,303)
        finally:second.close()

    def test_default_note_only_for_invoices(self):
        self.client.post('/templates',data=self.options(default_invoice_notes='NEUER STANDARDTEXT'))
        self.assertIn('NEUER STANDARDTEXT',self.client.get('/invoices/new').text)
        self.assertNotIn('NEUER STANDARDTEXT',self.client.get('/invoices/new?kind=quote').text)
        self.assertNotIn('NEUER STANDARDTEXT',self.client.get('/invoices/new?kind=credit').text)

    def test_tenant_specific_templates(self):
        self.client.post('/templates',data=self.options(template_title='Firma A Design'))
        self.client.post('/companies/new',data={'_csrf':self.csrf('/companies/new'),'name':'Firma B'})
        self.assertNotIn('Firma A Design',self.client.get('/templates').text)
        self.client.post('/templates',data=self.options(template_title='Firma B Design',template_density='compact'))
        rows=self.db('SELECT name, template_title, template_density FROM companies ORDER BY id')
        self.assertEqual(rows[0][1:3],('Firma A Design','spacious'))
        self.assertEqual(rows[1][1:3],('Firma B Design','compact'))

    def test_archived_pdf_unchanged_after_template_update(self):
        self.client.post('/templates',data=self.options(template_title='Design ALT'))
        self.invoice(notes='Archivausgabe')
        self.client.post('/invoices/1/issue',data={'_csrf':self.csrf('/invoices/1')})
        original=self.client.get('/invoices/1/pdf').content
        self.assertIn('Design ALT',self.pdftext(self.client.get('/invoices/1/pdf')))
        self.client.post('/templates',data=self.options(template_title='Design NEU'))
        self.assertEqual(self.client.get('/invoices/1/pdf').content,original)
        self.assertNotIn('Design NEU',self.pdftext(self.client.get('/invoices/1/pdf')))

    def test_multi_tax_is_still_itemized_when_option_off(self):
        self.client.post('/templates',data=self.options())
        self.invoice(**{'description[]':['Leistung','Buch'], 'qty[]':['1','1'],
                        'price[]':['100','100'],'tax_rate[]':['8.1','2.6'],
                        'tax_mode[]':['taxable','taxable'], 'unit[]':['Stk.','Stk.'],
                        'discount[]':['0','0'], 'item_id[]':['','']})
        content=self.pdftext(self.client.get('/invoices/1/pdf'))
        self.assertIn('MWST 8.1 %',content)
        self.assertIn('MWST 2.6 %',content)

    def test_long_heading_stays_inside_pdf_column(self):
        title='Dienstleistungsrechnung fuer umfangreiche Arbeiten'
        lines,size=title_parts(title,34)
        self.assertLessEqual(len(lines),2)
        self.assertEqual(' '.join(lines),title)
        self.assertTrue(all(stringWidth(part,'Helvetica-Bold',size)<=350 for part in lines))
        short,size=title_parts('Ihre Dienstleistungsrechnung',26)
        self.assertEqual(short,['Ihre Dienstleistungsrechnung'])

    def test_simplified_vat_line_still_contains_rate(self):
        self.client.post('/templates',data=self.options(template_show_service_date='1'))
        self.invoice()
        pdf=self.pdftext(self.client.get('/invoices/1/pdf'))
        self.assertIn('MWST gesamt (8.1 %)',pdf)

    def test_density_changes_page_pagination(self):
        company={'id':1,'name':'Beispiel AG','street':'Testweg','building':'1',
                 'zip':'3011','city':'Bern','country':'CH','iban':'',
                 'template_style':'modern','template_title':'Rechnung',
                 'template_accent':'#2563eb'}
        customer={'name':'Kunde AG','street':'Weg','building':'4',
                  'zip':'3000','city':'Bern','country':'CH'}
        inv={'kind':'invoice','number':'TEST-1','invoice_date':'2026-11-08',
             'service_date':'2026-11-08','due_date':'2026-12-08','currency':'CHF',
             'subtotal':'600.00','tax_total':'0.00','total':'600.00',
             'tax_breakdown':json.dumps({'0':{'tax':'0.00','net':'600.00'}})}
        lines=[{'description':'Beratung '+str(i),'qty':'1','unit':'Stk.',
                'price':'10','line_net':'10','discount':'0','tax_rate':'0'} for i in range(60)]
        compact,_=make_pdf(inv,dict(company,template_density='compact'),customer,lines)
        spacious,_=make_pdf(inv,dict(company,template_density='spacious'),customer,lines)
        self.assertLess(len(PdfReader(io.BytesIO(compact)).pages),
                        len(PdfReader(io.BytesIO(spacious)).pages))


class MigrationVersion15Tests(unittest.TestCase):
    def test_migration_does_not_change_existing_draft_or_customer(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'rechnung.sqlite3'
            initialize(path)
            con=db_connect(path)
            try:
                con.execute("INSERT INTO companies(name) VALUES('Alt GmbH')")
                con.execute("INSERT INTO customers(company_id,name) VALUES(1,'Alt Kunde')")
                con.execute("INSERT INTO invoices(company_id,kind,number,customer_id,invoice_date,due_date) VALUES(1,'invoice','ALT-1',1,'2026-11-01','2026-11-30')")
                con.commit()
                for name in ('template_header_layout','template_title_size','template_density',
                             'template_show_service_date','template_show_tax_breakdown',
                             'template_show_payment_terms','template_show_customer_email',
                             'default_invoice_notes'):
                    con.execute('ALTER TABLE companies DROP COLUMN '+name)
                con.execute('PRAGMA user_version=5')
                con.commit()
            finally:con.close()
            initialize(path)
            initialize(path)
            con=db_connect(path)
            try:
                self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],15)
                self.assertEqual([tuple(x) for x in con.execute('SELECT number FROM invoices')],[('ALT-1',)])
                self.assertEqual([tuple(x) for x in con.execute('SELECT name FROM customers')],[('Alt Kunde',)])
                self.assertEqual(con.execute('SELECT template_density FROM companies').fetchone()[0],'normal')
            finally:con.close()


if __name__=='__main__':
    unittest.main()
