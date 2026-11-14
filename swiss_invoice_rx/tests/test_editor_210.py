"""2.10: Randlos-Logos, Artikel-Schnellerfassung und automatisches Entwurfsspeichern."""
import io
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

from app.db import db_connect
from app.designer import default_layout, dumps_layout, parse_layout
from app.main import create_app


class Editor210Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = TestClient(create_app(self.root), follow_redirects=True)
        self.client.post('/setup', data={
            '_csrf': self.csrf('/setup'), 'company_name': 'Swiss Demo GmbH',
            'email': 'admin@example.ch', 'full_name': 'Testadministrator',
            'password': 'PasswortSehrSicher2026!', 'password2': 'PasswortSehrSicher2026!',
        })
        with db_connect(self.root / 'rechnung.sqlite3') as con:
            con.execute("INSERT INTO customers(company_id,name,zip,city,country) VALUES(1,'Kunde Test AG','4000','Basel','CH')")
            con.commit()

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def csrf(self, path='/invoices/new'):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(r'name="_csrf"[^>]*value="([0-9a-f]+)"', response.text)
        self.assertIsNotNone(match, response.text[:550])
        return match.group(1)

    def invoice_data(self, **changes):
        payload = {
            '_csrf': self.csrf(), 'id': '', 'kind': 'invoice', 'customer_id': '1',
            'invoice_date': '2026-11-14', 'service_date': '2026-11-14',
            'due_date': '2026-12-14', 'currency': 'CHF', 'number': '',
            'subject': 'Montage', 'notes': 'Rechnungsentwurf', 'discount': '0',
            'description[]': 'Montageberatung', 'qty[]': '2', 'unit[]': 'Std.',
            'price[]': '75', 'tax_rate[]': '0', 'tax_mode[]': 'taxable',
            'discount[]': '0', 'item_id[]': '',
        }
        payload.update(changes)
        return payload

    def rows(self, sql, *args):
        with db_connect(self.root / 'rechnung.sqlite3') as con:
            return [tuple(r) for r in con.execute(sql, args)]

    def test_quick_item_create_and_invoice_selection(self):
        r = self.client.post('/api/items/quick-create', data={
            '_csrf': self.csrf(), 'name': 'Spezialwerkzeug', 'sku': 'SPEZ-08',
            'kind': 'product', 'price': '89.50', 'cost': '19', 'tax_rate': '0',
            'tax_mode': 'taxable', 'track_stock': '1', 'stock': '7', 'reorder_point': '2',
        })
        self.assertEqual(r.status_code, 200, r.text[:250])
        item = r.json()['item']
        self.assertEqual(item['sku'], 'SPEZ-08')
        self.assertEqual(item['stock'], '7')
        self.assertEqual(item['track_stock'], 1)
        self.assertIn('SPEZ-08', self.client.get('/invoices/new').text)
        result = self.client.post('/api/invoices/autosave', data=self.invoice_data(
            **{'item_id[]': str(item['id']), 'description[]': 'Spezialwerkzeug',
               'price[]': '89.50', 'qty[]': '1'}))
        self.assertEqual(result.status_code, 200, result.text[:250])
        iid = result.json()['id']
        self.assertEqual(self.rows('SELECT item_id FROM invoice_lines WHERE invoice_id=?', iid),
                         [(item['id'],)])

    def test_quick_item_image_and_validation(self):
        image = Image.new('RGB', (500, 300), '#14588a')
        memory = io.BytesIO(); image.save(memory, 'PNG')
        good = self.client.post('/api/items/quick-create',
            data={'_csrf': self.csrf(), 'name': 'Bilderartikel', 'price': '20',
                  'kind': 'product', 'tax_rate': '0'},
            files={'image': ('test.png', memory.getvalue(), 'image/png')})
        self.assertEqual(good.status_code, 200, good.text[:180])
        item = good.json()['item']
        self.assertTrue((self.root / item['image_path']).is_file())
        bad = self.client.post('/api/items/quick-create',
            data={'_csrf': self.csrf(), 'name': 'Fehler', 'sku': item['sku'], 'price': '20'})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM items'), [(1,)])

    def test_quick_item_is_business_scoped_and_requires_login(self):
        other = TestClient(create_app(self.root), follow_redirects=False)
        try:
            self.assertIn(other.post('/api/items/quick-create', data={'name': 'Hacker'}).status_code,
                          (302, 303, 401, 403))
        finally: other.close()
        self.client.post('/api/items/quick-create', data={
            '_csrf': self.csrf(), 'name': 'Normales Produkt', 'price': '25'})
        self.assertEqual(self.rows('SELECT DISTINCT company_id FROM items'), [(1,)])

    def test_autosave_creates_and_updates_only_draft(self):
        one = self.client.post('/api/invoices/autosave', data=self.invoice_data())
        self.assertEqual(one.status_code, 200, one.text[:300])
        response = one.json()
        self.assertEqual(response['status'], 'draft')
        iid = response['id']
        self.assertTrue(response['number'])
        two = self.client.post('/api/invoices/autosave', data=self.invoice_data(
            id=str(iid), number=response['number'], notes='Automatisch aktualisiert',
            **{'description[]': 'Neue Leistung', 'price[]': '120'}))
        self.assertEqual(two.status_code, 200, two.text[:250])
        self.assertEqual(two.json()['id'], iid)
        self.assertEqual(self.rows('SELECT status,notes,paid_total FROM invoices WHERE id=?', iid),
                         [('draft', 'Automatisch aktualisiert', '0.00')])
        self.assertEqual(self.rows('SELECT description,price FROM invoice_lines WHERE invoice_id=?', iid),
                         [('Neue Leistung', '120.00')])
        self.assertEqual(self.rows('SELECT COUNT(*) FROM activity WHERE action=?','Beleg gespeichert'), [(0,)])
        self.assertEqual(self.rows('SELECT COUNT(*) FROM stock_movements'), [(0,)])
        self.assertEqual(self.rows('SELECT COUNT(*) FROM invoices'), [(1,)])

    def test_autosave_never_creates_empty_draft_and_refuses_issued(self):
        empty = self.client.post('/api/invoices/autosave', data=self.invoice_data(**{'description[]': ''}))
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM invoices'), [(0,)])
        good = self.client.post('/api/invoices/autosave', data=self.invoice_data()).json()
        with db_connect(self.root / 'rechnung.sqlite3') as con:
            con.execute("UPDATE invoices SET status='sent' WHERE id=?", (good['id'],))
            con.commit()
        refused = self.client.post('/api/invoices/autosave', data=self.invoice_data(
            id=str(good['id']), number=good['number']))
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.rows('SELECT status FROM invoices WHERE id=?',good['id']), [('sent',)])

    def test_autosave_new_customer_created_once(self):
        data = self.invoice_data(customer_id='', new_customer_name='Neukunde AG',
                                 new_customer_zip='8000',new_customer_city='Zuerich',new_customer_country='CH')
        first = self.client.post('/api/invoices/autosave', data=data)
        self.assertEqual(first.status_code, 200, first.text[:300])
        created = first.json()
        next_data = self.invoice_data(id=str(created['id']),number=created['number'],
                                      customer_id=str(created['customer_id']))
        second = self.client.post('/api/invoices/autosave', data=next_data)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM customers'), [(2,)])

    def test_autosave_rejects_cross_business_invoice(self):
        with db_connect(self.root / 'rechnung.sqlite3') as con:
            con.execute("INSERT INTO companies(name) VALUES('Anderes Geschaeft')")
            con.execute("INSERT INTO invoices(company_id,kind,number,invoice_date,due_date) VALUES(2,'invoice','RE-B-99','2026-11-14','2026-12-14')")
            foreign_id=con.execute('SELECT last_insert_rowid()').fetchone()[0]
            con.commit()
        response = self.client.post('/api/invoices/autosave', data=self.invoice_data(
            id=str(foreign_id),number='RE-B-99'))
        self.assertEqual(response.status_code, 404)

    def test_designer_logo_bleed_validation_and_actual_pdf_image(self):
        logo_dir = self.root / 'uploads' / '1'; logo_dir.mkdir(parents=True, exist_ok=True)
        Image.new('RGB',(800,200),'#097ac8').save(logo_dir/'app-banner.png')
        with db_connect(self.root/'rechnung.sqlite3') as con:
            con.execute("UPDATE companies SET app_logo_path='uploads/1/app-banner.png' WHERE id=1")
            con.commit()
        layout = default_layout()
        layout['blocks'][0].update(x=-3,y=-3,w=216,h=80,fit='cover')
        self.assertEqual(parse_layout(layout)['blocks'][0]['fit'], 'cover')
        result = self.client.post('/templates/designer/preview.pdf', data={
            '_csrf': self.csrf('/templates/designer'), 'designer_layout':dumps_layout(layout),
            '_preview_kind':'invoice'})
        self.assertEqual(result.status_code, 200, result.text[:150] if result.status_code!=200 else '')
        self.assertGreater(len(PdfReader(io.BytesIO(result.content)).pages[0].images),0)
        layout['blocks'][0]['x']=-50
        with self.assertRaises(ValueError):parse_layout(layout)
        layout['blocks'][0].update(x=0,w=400)
        with self.assertRaises(ValueError):parse_layout(layout)

    def test_studio_logo_large_and_outside_page(self):
        logo_dir=self.root/'uploads'/'1';logo_dir.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(600,200),'#1245aa').save(logo_dir/'logo.png')
        with db_connect(self.root/'rechnung.sqlite3') as con:
            con.execute("UPDATE companies SET app_logo_path='uploads/1/logo.png' WHERE id=1")
            con.commit()
        response=self.client.post('/templates',data={
            '_csrf':self.csrf('/templates'), 'template_style':'modern',
            'template_accent':'#0f766e','template_title':'Rechnung','template_footer':'',
            'template_header_layout':'standard','template_title_size':'26',
            'template_density':'normal', 'template_table_style':'lines',
            'template_logo_size':'525','template_logo_x_mm':'-3',
            'template_logo_y_mm':'0','template_logo_height_mm':'90',
            'template_logo_fit':'cover','template_body_size':'9', 'template_show_logo':'1',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rows('SELECT template_logo_size,template_logo_x_mm,template_logo_y_mm,template_logo_fit FROM companies'),
                         [(525,'-3','0','cover')])
        pdf=self.client.get('/templates/preview.pdf')
        self.assertEqual(pdf.status_code,200)
        self.assertGreater(len(PdfReader(io.BytesIO(pdf.content)).pages[0].images),0)

    def test_editor_ui_has_quick_entry_and_autosave(self):
        html=self.client.get('/invoices/new').text
        for token in ('id="new-item-button"','id="new-item-dialog"','id="editor-autosave"',
                      'id="new-item-form"','data-user-id='):
            self.assertIn(token,html)
        self.assertIn('api/invoices/autosave',self.client.get('/static/editor.js').text)
        self.assertIn('d-full-page',self.client.get('/templates/designer').text)


if __name__=='__main__': unittest.main()
