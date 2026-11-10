"""Regressionstests fuer die vereinfachten Rechnungspositionskarten ab 2.2."""
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from app.db import db_connect
from app.main import create_app


class PositionEditor22Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = TestClient(create_app(self.root), follow_redirects=True)
        self.client.post('/setup', data={
            '_csrf':self.token('/setup'),'company_name':'Testfirma AG',
            'email':'admin@example.ch','full_name':'Administrator',
            'password':'Sicher!Passwort2026','password2':'Sicher!Passwort2026'})
        self.client.post('/settings',data={
            '_csrf':self.token('/settings'),'name':'Testfirma AG',
            'street':'Weg','building':'12','zip':'3000','city':'Bern','country':'CH',
            'currency':'CHF','tax_registered':'1','default_tax':'8.1','default_due_days':'30'})
        self.client.post('/customers/save',data={
            '_csrf':self.token('/customers/new'),'name':'Kunde AG',
            'street':'Ringweg','building':'1','zip':'8000','city':'Zuerich','country':'CH'})

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def token(self,path):
        res=self.client.get(path)
        m=re.search(r'name="_csrf" value="([0-9a-f]+)"',res.text)
        self.assertIsNotNone(m,res.text[:800])
        return m.group(1)

    def test_position_list_has_simplified_cards_and_advanced_fields(self):
        res=self.client.get('/invoices/new')
        self.assertEqual(res.status_code,200)
        html=res.text
        self.assertEqual(html.count('class="editor-line hi-line-card"'),1)
        self.assertIn('id="invoice-rows"',html)
        self.assertIn('class="hi-line-advanced"',html)
        self.assertIn('Rabatt &amp; MWST',html)
        self.assertIn('Leere Positionen entfernen',html)
        self.assertNotIn('class="table invoice-lines"',html)
        for name in ('description','qty','unit','price','discount','tax_rate','tax_mode','item_id'):
            self.assertIn(f'name="{name}[]"',html)
        for button in ('row-copy','row-up','row-down','remove-row','undo-row','add-row','bulk-import-panel'):
            self.assertIn(button,html)

    def test_line_values_are_saved_and_editable(self):
        data={
            '_csrf':self.token('/invoices/new'),'kind':'invoice','customer_id':'1',
            'invoice_date':'2026-11-08','service_date':'2026-11-08','due_date':'2026-12-08',
            'currency':'CHF','discount':'0','number':'RE-2026-KARTEN',
            'description[]':['Montage'],'qty[]':['2'],'unit[]':['Std.'],
            'price[]':['85.00'],'tax_rate[]':['8.1'], 'tax_mode[]':['taxable'],
            'discount[]':['10'],'item_id[]':['']}
        res=self.client.post('/invoices/save',data=data)
        self.assertEqual(res.status_code,200)
        con=db_connect(self.root/'rechnung.sqlite3')
        try:
            row=con.execute('SELECT qty,unit,price,discount,tax_rate,line_net FROM invoice_lines WHERE invoice_id=1').fetchone()
            self.assertEqual(row['qty'],'2')
            self.assertEqual(row['unit'],'Std.')
            self.assertEqual(row['price'],'85.00')
            self.assertEqual(row['discount'],'10')
            self.assertEqual(row['tax_rate'],'8.1')
            self.assertEqual(row['line_net'],'153.00')
            total=con.execute('SELECT total FROM invoices WHERE id=1').fetchone()[0]
            self.assertEqual(total,'165.39')
        finally:
            con.close()
        edit=self.client.get('/invoices/1/edit')
        self.assertIn('RE-2026-KARTEN',edit.text)
        self.assertIn('class="editor-line hi-line-card"',edit.text)
        self.assertIn('value="85.00"',edit.text)
        pdf=self.client.get('/invoices/1/pdf')
        self.assertEqual(pdf.status_code,200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))

    def test_credit_note_starts_with_negative_quantity(self):
        res=self.client.get('/invoices/new?kind=credit')
        self.assertEqual(res.status_code,200)
        self.assertRegex(res.text,r'name="qty\[\]"[^>]*value="-1"')
        self.assertIn('class="editor-line hi-line-card"',res.text)

    def test_preview_does_not_save_customer_or_document(self):
        data={
            '_csrf':self.token('/invoices/new'),'kind':'invoice','number':'PREVIEW-ONLY',
            'new_customer_name':'Nur Vorschau Kunde','new_customer_city':'Bern',
            'new_customer_zip':'3000','new_customer_country':'CH',
            'invoice_date':'2026-11-08','service_date':'2026-11-08','due_date':'2026-12-08',
            'currency':'CHF','discount':'0','description[]':['Beratung'],'qty[]':['1'],
            'unit[]':['Std.'],'price[]':['85.00'],'tax_rate[]':['8.1'],
            'tax_mode[]':['taxable'],'discount[]':['0'],'item_id[]':['']}
        response=self.client.post('/invoices/preview.pdf',data=data)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b'%PDF'))
        con=db_connect(self.root/'rechnung.sqlite3')
        try:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM customers').fetchone()[0],1)
        finally:con.close()

    def test_static_editor_supports_blank_reuse_and_live_totals(self):
        script=self.client.get('/static/editor.js')
        self.assertEqual(script.status_code,200)
        for fragment in ('function isBlankRow','clean-empty-rows','line-tax-summary',
                         "querySelectorAll('.editor-line')",'bulkUndo','row-copy'):
            self.assertIn(fragment,script.text)
        css=self.client.get('/static/app.css')
        self.assertIn('.hi-line-card',css.text)
        self.assertIn('.hi-line-advanced-fields',css.text)
        self.assertIn('max-width:650px',css.text)


if __name__=='__main__':
    unittest.main()
