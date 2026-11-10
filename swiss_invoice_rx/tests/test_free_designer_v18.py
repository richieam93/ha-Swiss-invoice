"""Drag-and-drop data contract, PDF parity, security and safe migrations in 1.8."""
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader
from app.designer import parse_layout, default_layout, dumps_layout
from app.db import db_connect, initialize
from app.main import create_app
from app.pdf import make_pdf


class LayoutValidationTests(unittest.TestCase):
    def test_default_layout_valid(self):
        layout=parse_layout(default_layout())
        self.assertEqual(len(layout['blocks']),13)
        self.assertIn('table',{b['kind'] for b in layout['blocks']})

    def test_invalid_structure_and_missing_required(self):
        for value in ('{','[]','{}','{"version":2,"blocks":[]}',{'version':1,'blocks':[]}):
            with self.assertRaises(ValueError):parse_layout(value)
        val=default_layout();val['blocks']=[b for b in val['blocks'] if b['kind']!='number']
        with self.assertRaisesRegex(ValueError,'Pflichtfelder'):parse_layout(val)

    def test_geometry_nan_clipping_duplicate_fields_and_color(self):
        for key,value in [('x',-3),('x',999),('w',3),('y',float('nan')),('h',300),('color','red'),('size',88)]:
            val=default_layout();val['blocks'][2][key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):parse_layout(val)
        val=default_layout();val['blocks'].append(dict(val['blocks'][0],id='other'))
        with self.assertRaises(ValueError):parse_layout(val)
        val=default_layout();val['blocks'][0]['id']='../../secret'
        with self.assertRaises(ValueError):parse_layout(val)

    def test_custom_text_safe_and_image_id_strict(self):
        val=default_layout();val['blocks'].append({'id':'custom','kind':'text','x':10,'y':50,'w':40,'h':10,'text':'{nummer}: danke!','size':11,'color':'#ffbbaa'})
        norm=parse_layout(val);self.assertEqual(norm['blocks'][-1]['text'],'{nummer}: danke!')
        self.assertEqual(json.loads(dumps_layout(val))['blocks'][-1]['size'],11)
        norm['blocks'][-1]['kind']='image';norm['blocks'][-1]['asset']='../../etc/passwd'
        with self.assertRaises(ValueError):parse_layout(norm)

    def test_default_pdf_flow_and_qr_still_separate(self):
        from app.billing import summarize
        company={'name':'Demo AG','id':1,'street':'Hauptgasse','building':'5','zip':'3000','city':'Bern','country':'CH','iban':'','designer_enabled':1,'designer_layout':dumps_layout(default_layout()), 'template_style':'modern'}
        customer={'name':'Kunde AG','street':'Testweg','building':'1','zip':'8000','city':'Zuerich','country':'CH'}
        lines=[{'description':'Beratung','qty':'2','unit':'Std.','price':'125','tax_rate':'8.1','tax_mode':'taxable','discount':'0'}]
        calc=summarize(lines)
        inv={'kind':'invoice','number':'RE-TEST-01','invoice_date':'2026-11-08','due_date':'2026-12-08','service_date':'2026-11-08','currency':'CHF','subtotal':calc['subtotal'],'total':calc['total'],'tax_total':calc['tax_total'],'tax_breakdown':json.dumps(calc['tax_breakdown']),'notes':'Vielen Dank fuer alles'}
        pdf,_=make_pdf(inv,company,customer,calc['lines'],preview=True)
        doc=PdfReader(io.BytesIO(pdf))
        self.assertEqual(len(doc.pages),1,'Eine kleine Musterrechnung darf keine Leer-Folgeseite erhalten')
        text=doc.pages[0].extract_text()
        for token in ['Beratung','RE-TEST-01','Kunde AG','TOTAL','ENTWURF - NICHT VERSENDEN']:
            self.assertIn(token,text)
        more=summarize([dict(lines[0],description=f'Position {i}') for i in range(65)])
        inv.update(subtotal=more['subtotal'],total=more['total'],tax_total=more['tax_total'],tax_breakdown=json.dumps(more['tax_breakdown']))
        pdf,_=make_pdf(inv,company,customer,more['lines'],preview=True)
        pages=PdfReader(io.BytesIO(pdf)).pages
        self.assertGreaterEqual(len(pages),3)
        self.assertIn('Position 64','\n'.join(p.extract_text() for p in pages))
        self.assertIn('TOTAL',pages[-1].extract_text())


class WebDesignerV18Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)
        self.client=TestClient(create_app(self.path),follow_redirects=True)
        self.client.post('/setup',data={
            '_csrf':self.csrf('/setup'),'company_name':'Designer AG',
            'email':'admin@example.ch','full_name':'Admin',
            'password':'SuperGeheim2026!','password2':'SuperGeheim2026!'})

    def tearDown(self):
        self.client.close();self.tmp.cleanup()

    def csrf(self,path='/templates/designer'):
        r=self.client.get(path)
        match=re.search(r'name="_csrf"[^>]*value="([0-9a-f]+)"',r.text)
        self.assertIsNotNone(match,r.text[:500]);return match.group(1)

    def rows(self,sql,*params):
        con=db_connect(self.path/'rechnung.sqlite3')
        try:return [tuple(row) for row in con.execute(sql,params)]
        finally:con.close()

    def savedata(self,layout=None,**kwargs):
        data={'_csrf':self.csrf(),'designer_enabled':'1',
              'designer_layout':dumps_layout(layout or default_layout())}
        data.update(kwargs);return data

    def pdftext(self,resp):
        self.assertEqual(resp.status_code,200,resp.text[:160] if resp.status_code!=200 else '')
        self.assertTrue(resp.content.startswith(b'%PDF'))
        return '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(resp.content)).pages)

    def test_ui_assets_visible_after_setup(self):
        response=self.client.get('/templates/designer');self.assertEqual(response.status_code,200)
        for text in ('id="designer-paper"','id="designer-layout-json"','id="designer-block-list"','id="designer-save-form"','id="designer-pdf-preview"'):
            self.assertIn(text,response.text)
        self.assertIn('Freier Drag-and-Drop-Designer',self.client.get('/templates').text)
        self.assertEqual(self.client.get('/static/designer.js').status_code,200)
        self.assertEqual(self.client.get('/static/designer.css').status_code,200)

    def test_unsaved_pdf_preview_does_not_write_data(self):
        l=default_layout();l['blocks'].append({'id':'label','kind':'text','x':22,'y':88,'w':86,'h':10,'text':'TEST-LAYOUT {nummer}','size':10,'color':'#14233c'})
        pdf=self.client.post('/templates/designer/preview.pdf',data=self.savedata(l))
        text=self.pdftext(pdf)
        self.assertIn('TEST-LAYOUT MUSTER-RECHNUNG',text)
        self.assertIn('ENTWURF - NICHT VERSENDEN',text)
        self.assertNotIn('Zahlteil und Empfangsschein',text)
        self.assertEqual(self.rows('SELECT designer_enabled,designer_layout FROM companies'),[(0,'')])
        self.assertEqual(self.rows('SELECT COUNT(*) FROM invoices'),[(0,)])

    def test_save_layout_affects_pdf_and_toggle_off(self):
        layout=default_layout();layout['blocks'][3]['y']=90
        layout['blocks'].append({'id':'offer','kind':'text','x':16,'y':81,'w':80,'h':10,'text':'Erstellt fuer {kunde}','size':9,'color':'#123456'})
        response=self.client.post('/templates/designer/save',data=self.savedata(layout))
        self.assertIn('Layout gespeichert',response.text)
        self.assertEqual(self.rows('SELECT designer_enabled FROM companies'),[(1,)])
        content=self.pdftext(self.client.get('/templates/preview.pdf'))
        self.assertIn('Erstellt fuer Musterkunde AG',content)
        self.client.post('/templates/designer/save',data=self.savedata(layout,designer_enabled='0'))
        self.assertEqual(self.rows('SELECT designer_enabled FROM companies'),[(0,)])
        self.assertNotIn('Erstellt fuer Musterkunde AG',self.pdftext(self.client.get('/templates/preview.pdf')))

    def test_save_as_and_restore_template_modes(self):
        layout=default_layout()
        self.client.post('/templates/designer/save',data=self.savedata(layout,template_name='Freies A4',save_as='1'))
        self.assertEqual(self.rows('SELECT name,active FROM invoice_templates ORDER BY id'),[('Standard',0),('Freies A4',1)])
        self.assertEqual(self.rows('SELECT designer_enabled FROM companies'),[(1,)])
        self.client.post('/templates/activate',data={'_csrf':self.csrf('/templates'),'template_id':'1'})
        self.assertEqual(self.rows('SELECT designer_enabled FROM companies'),[(0,)])
        self.client.post('/templates/activate',data={'_csrf':self.csrf('/templates'),'template_id':'2'})
        self.assertEqual(self.rows('SELECT designer_enabled FROM companies'),[(1,)])
        # Classic studio saving does not discard the layout.
        self.client.post('/templates',data={
            '_csrf':self.csrf('/templates'),'template_style':'modern','template_accent':'#2563eb',
            'template_header_layout':'standard','template_density':'normal','template_title_size':'26',
            'template_table_style':'lines','template_logo_size':'110','template_body_size':'9',
            'designer_enabled':'1','designer_layout':dumps_layout(layout)})
        self.assertEqual(self.rows('SELECT designer_enabled FROM companies'),[(1,)])

    def test_invalid_layout_does_not_overwrite_company_or_templates(self):
        before=self.rows('SELECT designer_enabled,designer_layout FROM companies')
        for wrong in ('invalid', '{"version":1,"blocks":[]}', '{}'):
            response=self.client.post('/templates/designer/save',data=self.savedata(designer_layout=wrong))
            self.assertIn('notice error',response.text)
            self.assertEqual(before,self.rows('SELECT designer_enabled,designer_layout FROM companies'))
        resp=self.client.post('/templates/designer/preview.pdf',data=self.savedata(designer_layout='{}'))
        self.assertEqual(resp.status_code,422)

    def test_access_and_csrf_enforced(self):
        for path in ('/templates/designer/save','/templates/designer/preview.pdf','/templates/designer/image'):
            self.assertEqual(self.client.post(path,data={'designer_layout':'{}'}).status_code,403)
        unauth=TestClient(create_app(self.path),follow_redirects=False)
        try:
            self.assertEqual(unauth.get('/templates/designer').status_code,303)
        finally:unauth.close()

    def test_tenant_isolation_layout_and_asset(self):
        layout=default_layout();layout['blocks'][3]['text']='A-NUR'
        self.client.post('/templates/designer/save',data=self.savedata(layout))
        self.client.post('/companies/new',data={'_csrf':self.csrf('/companies/new'),'name':'Firma B'})
        self.assertEqual(self.rows('SELECT designer_enabled FROM companies ORDER BY id'),[(1,),(0,)])
        self.assertNotIn('A-NUR',self.client.get('/templates/designer').text)

    def test_jpeg_upload_and_tenant_scoped_get(self):
        img=Image.new('RGB',(80,44),'blue');out=io.BytesIO();img.save(out,format='PNG')
        response=self.client.post('/templates/designer/image',data={'_csrf':self.csrf()},files={'image':('logo.png',out.getvalue(),'image/png')})
        self.assertEqual(response.status_code,200,response.text[:200]);name=response.json()['asset']
        self.assertRegex(name,r'^[a-f0-9]{32}\.jpg$')
        self.assertEqual(self.client.get('/templates/designer/image/'+name).status_code,200)
        self.assertEqual(self.client.get('/templates/designer/image/../../x').status_code,404)
        layout=default_layout()
        layout['blocks'].append({'id':'photo','kind':'image','x':68,'y':40,'w':40,'h':20,'asset':name})
        self.assertEqual(self.client.post('/templates/designer/preview.pdf',data=self.savedata(layout)).status_code,200)
        self.client.post('/companies/new',data={'_csrf':self.csrf('/companies/new'),'name':'Firma B'})
        self.assertEqual(self.client.get('/templates/designer/image/'+name).status_code,404)

    def test_issued_invoice_pdf_is_stable_after_redesign(self):
        self.client.post('/customers/save',data={
            '_csrf':self.csrf('/customers/new'),'name':'Kundin AG','street':'Weg',
            'building':'3','zip':'3011','city':'Bern','country':'CH'})
        self.client.post('/invoices/save',data={
            '_csrf':self.csrf('/invoices/new'),'customer_id':'1','kind':'invoice',
            'invoice_date':'2026-11-08','due_date':'2026-12-08','service_date':'2026-11-08',
            'currency':'CHF','description[]':['Dienstleistung'],'qty[]':['1'],
            'unit[]':['Stk.'],'price[]':['50'],'tax_rate[]':['0'],
            'tax_mode[]':['taxable'],'item_id[]':[''],'discount[]':['0']})
        self.client.post('/invoices/1/issue',data={'_csrf':self.csrf('/invoices/1')})
        baseline=self.client.get('/invoices/1/pdf').content
        layout=default_layout()
        self.client.post('/templates/designer/save',data=self.savedata(layout))
        self.assertEqual(self.client.get('/invoices/1/pdf').content,baseline)


if __name__=='__main__':unittest.main()
