"""2.11: visible discounts, toggleable VAT and invoice-unit dropdown."""
import io
import json
import re
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.billing import summarize, discount_details
from app.db import db_connect
from app.designer import default_layout
from app.main import create_app


class DiscountTaxUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.client=TestClient(create_app(self.root), follow_redirects=True)
        result=self.client.post('/setup',data={
            '_csrf':self.csrf('/setup'),'company_name':'Musterbetrieb GmbH',
            'email':'admin@example.ch','full_name':'Administrator',
            'password':'SehrSicher!2026XY','password2':'SehrSicher!2026XY',
        })
        self.assertEqual(result.status_code,200,result.text[:250])
        self.client.post('/customers/save',data={
            '_csrf':self.csrf('/customers'),'name':'Auftraggeber AG',
            'street':'Hauptstrasse','building':'1','zip':'4000','city':'Basel','country':'CH',
        })

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def csrf(self, path):
        result=self.client.get(path)
        self.assertEqual(result.status_code,200,result.text[:250])
        token=re.search(r'name="_csrf"[^>]*value="([a-f0-9]+)"',result.text)
        self.assertIsNotNone(token,result.text[:800])
        return token.group(1)

    def settings(self,vat):
        payload={'_csrf':self.csrf('/settings'),'name':'Musterbetrieb GmbH',
                 'business_type':'company','street':'Musterweg','building':'9','zip':'4051',
                 'city':'Basel','country':'CH','currency':'CHF','default_tax':'8.1',
                 'default_due_days':'30'}
        if vat:payload['tax_registered']='1'
        result=self.client.post('/settings',data=payload)
        self.assertEqual(result.status_code,200)
        self.assertIn('Firmendaten',result.text)

    def invoice_data(self, kind='invoice', global_discount='5'):
        return {'_csrf':self.csrf('/invoices/new'),'kind':kind,'customer_id':'1',
                'invoice_date':'2026-11-14','service_date':'2026-11-14',
                'due_date':'2026-12-14','currency':'CHF','discount':global_discount,
                'description[]':['Beratung','Material'], 'qty[]':['2','1'],
                'unit[]':['Std.','Stk.'], 'price[]':['100','50'],
                'tax_rate[]':['8.1','2.6'],'tax_mode[]':['taxable','taxable'],
                'discount[]':['10','0'],'item_id[]':['','']}

    def create_invoice(self, global_discount='5'):
        result=self.client.post('/invoices/save',data=self.invoice_data(global_discount=global_discount))
        self.assertEqual(result.status_code,200,result.text[:250])
        self.assertNotIn('Entwurf nicht gespeichert',result.text)
        with db_connect(self.root/'rechnung.sqlite3') as con:
            return con.execute('SELECT MAX(id) FROM invoices').fetchone()[0]

    def pdf_text(self, rid):
        result=self.client.get(f'/invoices/{rid}/pdf')
        self.assertEqual(result.status_code,200,result.text[:200] if result.status_code!=200 else '')
        return '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(result.content)).pages)

    def test_discount_details_and_decimal_rounding(self):
        rows=[{'description':'Beratung','qty':'2','price':'100','discount':'10','tax_rate':'8.1',
               'tax_mode':'taxable','unit':'Std.'},
              {'description':'Material','qty':'1','price':'50','discount':'0','tax_rate':'2.6',
               'tax_mode':'taxable','unit':'Stk.'}]
        summary=summarize(rows,'5')
        detail=discount_details(summary['lines'],'5')
        self.assertEqual(detail['gross'],'250.00')
        self.assertEqual(detail['line_discount'],'20.00')
        self.assertEqual(detail['after_positions'],'230.00')
        self.assertEqual(detail['global_discount'],'11.50')
        self.assertEqual(detail['final_net'],'218.50')
        self.assertEqual(summary['subtotal'],'218.50')
        self.assertEqual(summary['tax_total'],'15.09')
        self.assertEqual(summary['total'],'233.59')

    def test_discounts_in_normal_pdf_and_invoice_detail(self):
        self.settings(True)
        rid=self.create_invoice()
        detail=self.client.get(f'/invoices/{rid}').text
        self.assertIn('Positionsrabatt 10 %',detail)
        self.assertIn('Gesamtrabatt 5',detail)
        self.assertIn('218.50',detail)
        text=self.pdf_text(rid)
        self.assertIn('Positionsrabatt 10 %',text)
        self.assertIn('Gesamtrabatt 5 %',text)
        self.assertIn('Netto nach Rabatt',text)
        self.assertIn('233.59',text)
        self.assertIn('MWST 8.1 %',text)

    def test_no_global_discount_keeps_line_discount_visible(self):
        self.settings(True)
        rid=self.create_invoice(global_discount='0')
        text=self.pdf_text(rid)
        self.assertIn('Positionsrabatt 10 %',text)
        self.assertNotIn('Gesamtrabatt 0',text)
        self.assertIn('MWST',text)

    def test_discounts_in_free_designer_pdf(self):
        self.settings(True)
        rid=self.create_invoice()
        with db_connect(self.root/'rechnung.sqlite3') as con:
            con.execute('UPDATE companies SET designer_enabled=1,designer_layout=? WHERE id=1',
                        (json.dumps(default_layout()),))
            con.commit()
        text=self.pdf_text(rid)
        self.assertIn('Positionsrabatt 10 %',text)
        self.assertIn('Gesamtrabatt 5 %',text)
        self.assertIn('Netto nach Rabatt',text)
        self.assertIn('233.59',text)

    def test_vat_disabled_is_hidden_in_editor_detail_and_both_pdfs(self):
        self.settings(False)
        editor=self.client.get('/invoices/new').text
        self.assertIn('<select name="unit[]"',editor)
        self.assertIn('Std.',editor)
        self.assertNotIn('name="tax_rate[]" aria-label="MWST Satz"',editor)
        self.assertNotIn('<span>MWST-Satz</span>',editor)
        self.assertNotIn('MWST gesamt</span>',editor)
        rid=self.create_invoice()
        with db_connect(self.root/'rechnung.sqlite3') as con:
            saved=con.execute('SELECT subtotal,tax_total,total FROM invoices WHERE id=?',(rid,)).fetchone()
            line_rates=con.execute('SELECT tax_rate,tax_mode FROM invoice_lines WHERE invoice_id=?',(rid,)).fetchall()
        self.assertEqual(tuple(saved),('218.50','0.00','218.50'))
        self.assertTrue(all(tuple(row)==('0','taxable') for row in line_rates))
        detail=self.client.get(f'/invoices/{rid}').text
        self.assertNotIn('<th>MWST</th>',detail)
        self.assertNotIn('<span>MWST</span>',detail)
        text=self.pdf_text(rid)
        self.assertNotIn('MWST',text)
        self.assertIn('Gesamtrabatt 5 %',text)
        with db_connect(self.root/'rechnung.sqlite3') as con:
            con.execute('UPDATE companies SET designer_enabled=1,designer_layout=? WHERE id=1',
                        (json.dumps(default_layout()),));con.commit()
        designer_text=self.pdf_text(rid)
        self.assertNotIn('MWST',designer_text)
        self.assertIn('Gesamtrabatt 5 %',designer_text)
        item_form=self.client.get('/items/new').text
        self.assertNotIn('MWST-Satz %',item_form)

    def test_vat_switch_recalculates_only_drafts(self):
        self.settings(True)
        first=self.create_invoice()
        second=self.create_invoice()
        with db_connect(self.root/'rechnung.sqlite3') as con:
            prev=con.execute('SELECT tax_total,total FROM invoices WHERE id=?',(first,)).fetchone()
            self.assertEqual(tuple(prev),('15.09','233.59'))
        issued=self.client.post(f'/invoices/{first}/issue',data={'_csrf':self.csrf(f'/invoices/{first}')})
        self.assertEqual(issued.status_code,200)
        with db_connect(self.root/'rechnung.sqlite3') as con:
            stored=con.execute('SELECT status,subtotal,tax_total,total FROM invoices WHERE id=?',(first,)).fetchone()
            self.assertEqual(stored['status'],'sent')
        self.settings(False)
        with db_connect(self.root/'rechnung.sqlite3') as con:
            unchanged=con.execute('SELECT subtotal,tax_total,total FROM invoices WHERE id=?',(first,)).fetchone()
            modified=con.execute('SELECT subtotal,tax_total,total FROM invoices WHERE id=?',(second,)).fetchone()
        self.assertEqual(tuple(unchanged),('218.50','15.09','233.59'))
        self.assertEqual(tuple(modified),('218.50','0.00','218.50'))
        self.assertIn('MWST',self.pdf_text(first))
        self.assertNotIn('MWST',self.pdf_text(second))

    def test_custom_unit_preserved_in_edit_dropdown_and_pdf(self):
        self.settings(False)
        data=self.invoice_data(global_discount='0')
        data['unit[]']=['km','m²']
        result=self.client.post('/invoices/save',data=data)
        self.assertEqual(result.status_code,200)
        edit=self.client.get('/invoices/1/edit').text
        self.assertIn('<option value="km" selected',edit)
        self.assertIn('<option value="m²" selected',edit)
        self.assertIn('km',self.pdf_text(1))

    def test_designer_preview_omits_vat_when_not_registered(self):
        self.settings(False)
        document=self.client.get('/templates/designer').text
        self.assertIn('data-tax-registered="0"', document)
        self.assertIn('data-add="uid">＋ UID</button>', document)
        self.settings(True)
        document=self.client.get('/templates/designer').text
        self.assertIn('data-tax-registered="1"', document)
        self.assertIn('data-add="uid">＋ UID / MWST</button>', document)

    def test_credit_discount_adjustments_keep_correct_sign(self):
        lines=[{'description':'Rückerstattung Stunden','qty':'-2','price':'50',
                'discount':'10','tax_rate':'0','tax_mode':'taxable','unit':'Std.'}]
        summary=summarize(lines,'5')
        detail=discount_details(summary['lines'],'5')
        self.assertEqual(detail['gross'],'-100.00')
        self.assertEqual(detail['line_discount'],'-10.00')
        self.assertEqual(detail['line_adjustment'],'+ 10.00')
        self.assertEqual(detail['global_adjustment'],'+ 4.50')
        self.assertEqual(detail['final_net'],'-85.50')



if __name__=='__main__':unittest.main()
