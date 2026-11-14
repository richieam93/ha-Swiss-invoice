"""Swiss-invoice-RX 2.5: automatic invoice logo and configurable draft mark."""
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

from app.db import db_connect, initialize
from app.designer import default_layout, dumps_layout
from app.main import create_app
from app.branding import document_logo_path


def logo_bytes(rgb):
    buf=io.BytesIO()
    Image.new('RGB',(240,92),rgb).save(buf,'PNG')
    return buf.getvalue()


class PdfBrandingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.client=TestClient(create_app(self.root),follow_redirects=False)
        response=self.client.post('/setup',data={
            '_csrf':self.csrf('/setup'),'company_name':'Nord AG',
            'full_name':'Hauptadministrator','email':'admin@example.ch',
            'password':'EinSicheresPasswort123!','password2':'EinSicheresPasswort123!'})
        self.assertEqual(response.status_code,303)
        self.upload_brand((200,20,30))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def csrf(self,url):
        r=self.client.get(url)
        self.assertEqual(r.status_code,200)
        match=re.search(r'name="_csrf"[^>]*value="([a-f0-9]+)"',r.text)
        self.assertIsNotNone(match)
        return match.group(1)

    def upload_brand(self,rgb):
        r=self.client.post('/settings/branding',data={'_csrf':self.csrf('/settings')},
                           files={'app_logo':('logo.png',logo_bytes(rgb),'image/png')})
        self.assertEqual(r.status_code,303)

    def create_invoice(self):
        with db_connect(self.root/'rechnung.sqlite3') as con:
            con.execute("INSERT INTO customers(company_id,number,name,street,building,zip,city) VALUES(1,'K100','Kunde AG','Weg','1','8000','Zuerich')")
            cid=con.execute('SELECT last_insert_rowid()').fetchone()[0]
            con.execute("""INSERT INTO invoices(company_id,kind,number,customer_id,invoice_date,due_date,
                          currency,status,subtotal,tax_total,total,tax_breakdown)
                          VALUES(1,'invoice','RE-2026-04200',?,'2026-11-12','2026-12-12','CHF','draft','50.00','0.00','50.00','{}')""",(cid,))
            inv_id=con.execute('SELECT last_insert_rowid()').fetchone()[0]
            con.execute("""INSERT INTO invoice_lines(company_id,invoice_id,position,description,qty,unit,price,tax_rate,tax_mode,discount,line_net)
                          VALUES(1,?,1,'Testprodukt','1','Stk.','50.00','0','taxable','0','50.00')""",(inv_id,))
            con.commit()
        return inv_id

    def test_studio_and_designer_see_business_logo(self):
        studio=self.client.get('/templates')
        self.assertEqual(studio.status_code,200)
        self.assertIn('id="studio-logo"',studio.text)
        self.assertIn('/media/logo',studio.text)
        designer=self.client.get('/templates/designer')
        self.assertEqual(designer.status_code,200)
        self.assertIn('data-logo="1"',designer.text)
        media=self.client.get('/media/logo')
        self.assertEqual(media.status_code,200)
        self.assertEqual(media.headers['content-type'],'image/png')
        self.assertIn('no-store',media.headers['cache-control'])

    def test_preview_pdf_and_designer_embed_logo(self):
        preview=self.client.get('/templates/preview.pdf')
        self.assertEqual(preview.status_code,200)
        doc=PdfReader(io.BytesIO(preview.content))
        self.assertGreaterEqual(len(doc.pages[0].images),1)
        self.assertIn('ENTWURF - NICHT VERSENDEN',doc.pages[0].extract_text())
        resp=self.client.post('/templates/designer/preview.pdf',data={
            '_csrf':self.csrf('/templates/designer'),
            'designer_layout':dumps_layout(default_layout()),
            'designer_enabled':'1','_preview_kind':'invoice'})
        self.assertEqual(resp.status_code,200,resp.text[:200] if resp.status_code!=200 else '')
        d=PdfReader(io.BytesIO(resp.content))
        self.assertGreaterEqual(len(d.pages[0].images),1)

    def test_draft_mark_can_be_disabled_and_enabled_without_changing_status(self):
        iid=self.create_invoice()
        before=PdfReader(io.BytesIO(self.client.get(f'/invoices/{iid}/pdf').content))
        self.assertIn('ENTWURF - NICHT VERSENDEN',before.pages[0].extract_text())
        self.assertGreaterEqual(len(before.pages[0].images),1)
        with db_connect(self.root/'rechnung.sqlite3') as con:
            company=dict(con.execute('SELECT * FROM companies WHERE id=1').fetchone())
        data={key:str(company[key]) for key in (
            'name','street','building','zip','city','country','email','phone','uid','iban','currency',
            'default_tax','color','footer_text','payment_terms','default_due_days','number_prefix',
            'quote_prefix','credit_prefix','number_padding','next_invoice','next_quote','next_credit',
            'qr_reference_type','qr_message')}
        data['_csrf']=self.csrf('/settings')
        data['_pdf_draft_mark_present']='1'
        r=self.client.post('/settings',data=data)
        self.assertEqual(r.status_code,303)
        with db_connect(self.root/'rechnung.sqlite3') as con:
            row=con.execute('SELECT pdf_show_draft_mark FROM companies WHERE id=1').fetchone()
            self.assertEqual(row[0],0)
        after=PdfReader(io.BytesIO(self.client.get(f'/invoices/{iid}/pdf').content))
        self.assertNotIn('ENTWURF - NICHT VERSENDEN',after.pages[0].extract_text())
        self.assertGreaterEqual(len(after.pages[0].images),1)
        with db_connect(self.root/'rechnung.sqlite3') as con:
            self.assertEqual(con.execute('SELECT status FROM invoices WHERE id=?',(iid,)).fetchone()[0],'draft')
        # Printable design samples always carry the safety label.
        sample=PdfReader(io.BytesIO(self.client.get('/templates/preview.pdf').content))
        self.assertIn('ENTWURF - NICHT VERSENDEN',sample.pages[0].extract_text())
        data['pdf_show_draft_mark']='1'
        data['_csrf']=self.csrf('/settings')
        self.assertEqual(self.client.post('/settings',data=data).status_code,303)
        self.assertIn('ENTWURF - NICHT VERSENDEN',
                      PdfReader(io.BytesIO(self.client.get(f'/invoices/{iid}/pdf').content)).pages[0].extract_text())

    def test_document_logo_does_not_cross_tenants(self):
        with db_connect(self.root/'rechnung.sqlite3') as con:
            con.execute("INSERT INTO companies(name) VALUES('Sued GmbH')")
            con.commit()
            first=dict(con.execute('SELECT * FROM companies WHERE id=1').fetchone())
            second=dict(con.execute('SELECT * FROM companies WHERE id=2').fetchone())
            self.assertIsNotNone(document_logo_path(self.root,first))
            self.assertIsNone(document_logo_path(self.root,second))
            con.execute('UPDATE companies SET app_logo_path=? WHERE id=2',(first['app_logo_path'],))
            con.commit()
            second=dict(con.execute('SELECT * FROM companies WHERE id=2').fetchone())
            self.assertIsNone(document_logo_path(self.root,second))

    def test_explicit_invoice_logo_has_precedence_and_hidden_logo_is_respected(self):
        with db_connect(self.root/'rechnung.sqlite3') as con:
            row=dict(con.execute('SELECT * FROM companies WHERE id=1').fetchone())
            custom=self.root/'uploads'/'1'/'explicit-invoice-logo.png'
            custom.write_bytes(logo_bytes((10,90,200)))
            con.execute('UPDATE companies SET logo_path=? WHERE id=1', ('uploads/1/explicit-invoice-logo.png',))
            con.commit()
        media=self.client.get('/media/logo')
        self.assertEqual(media.content,custom.read_bytes())
        self.assertNotEqual(media.content,self.client.get('/media/app-logo').content)
        with db_connect(self.root/'rechnung.sqlite3') as con:
            con.execute('UPDATE companies SET template_show_logo=0 WHERE id=1')
            con.commit()
        self.assertEqual(len(PdfReader(io.BytesIO(self.client.get('/templates/preview.pdf').content)).pages[0].images),0)
        self.assertIn('data-logo="0"',self.client.get('/templates/designer').text)

    def test_qr_payment_page_honors_draft_switch(self):
        with db_connect(self.root/'rechnung.sqlite3') as con:
            con.execute("UPDATE companies SET iban='CH9300762011623852957', street='Hauptweg', building='1', zip='3011', city='Bern', pdf_show_draft_mark=0 WHERE id=1")
            con.commit()
        iid=self.create_invoice()
        pdf=PdfReader(io.BytesIO(self.client.get(f'/invoices/{iid}/pdf').content))
        self.assertEqual(len(pdf.pages),2)
        self.assertIn('Zahlteil und Empfangsschein',pdf.pages[-1].extract_text())
        self.assertNotIn('ENTWURF - NICHT VERSENDEN','\n'.join(p.extract_text() for p in pdf.pages))

    def test_migration_defaults_to_marked_draft(self):
        with db_connect(self.root/'rechnung.sqlite3') as con:
            con.execute('ALTER TABLE companies DROP COLUMN pdf_show_draft_mark')
            con.execute('PRAGMA user_version=12')
            con.commit()
        initialize(self.root/'rechnung.sqlite3')
        with db_connect(self.root/'rechnung.sqlite3') as con:
            self.assertEqual(con.execute('SELECT pdf_show_draft_mark FROM companies WHERE id=1').fetchone()[0],1)
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],14)


if __name__=='__main__':unittest.main()
