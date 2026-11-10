import io
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader
from app.main import create_app
from app.db import db_connect
from app.qr import build_payload, is_qr_iban, valid_qrr
from app.numbering import valid_number, valid_prefix, valid_padding


class EditorQrTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(self.tmp.name),follow_redirects=True)
        token = self._token('/setup')
        response = self.client.post('/setup',data={
            '_csrf':token,'company_name':'Alpen GmbH','email':'admin@example.ch',
            'full_name':'Test Admin','password':'SicheresPasswort123',
            'password2':'SicheresPasswort123'})
        self.assertEqual(response.status_code,200)
        self.settings({'iban':'CH9300762011623852957'})
        self.client.post('/customers/save', data={
            '_csrf':self._token(),'name':'Alpha AG','street':'Testweg','building':'8',
            'zip':'8000','city':'Zuerich','country':'CH'})

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def _token(self, path='/settings'):
        html = self.client.get(path).text
        match = re.search(r'name="_csrf"[^>]*value="([a-f0-9]+)"',html)
        self.assertIsNotNone(match,html[:250])
        return match.group(1)

    def settings(self,changes=None):
        values = dict(_csrf=self._token(),name='Alpen GmbH',street='Alpenstrasse',building='6',
                      zip='3000',city='Bern',country='CH',color='#2563eb',
                      iban='CH9300762011623852957',currency='CHF',default_tax='0',
                      default_due_days='30',number_prefix='RE',payment_terms='Zahlbar innert {days} Tagen.',
                      qr_reference_type='AUTO',qr_message='{number}')
        values.update(changes or {})
        return self.client.post('/settings',data=values)

    def document(self,number='',kind='invoice',rid=None,description='Beratung',currency='CHF',customer_id='1'):
        values = {'_csrf':self._token(), 'kind':kind,'customer_id':customer_id,'invoice_date':'2026-11-08',
                  'service_date':'2026-11-08','due_date':'2026-12-08','currency':currency,
                  'notes':'Vielen Dank','discount':'0',
                  'description[]':[description], 'qty[]':['1'],'unit[]':['Std.'],
                  'price[]':['120'],'tax_rate[]':['0'],'tax_mode[]':['taxable'],
                  'item_id[]':[''],'discount[]':['0']}
        if number is not None: values['number']=number
        if rid:values['id']=str(rid)
        return self.client.post('/invoices/save',data=values)

    def database(self,sql,args=()):
        con=db_connect(Path(self.tmp.name)/'rechnung.sqlite3')
        try:return [tuple(row) for row in con.execute(sql,args).fetchall()]
        finally:con.close()

    def test_editor_form_contains_number_preview_and_tools(self):
        r=self.client.get('/invoices/new')
        self.assertEqual(r.status_code,200)
        for text in ('id="invoice-number"','Vorschlag: RE-', 'id="add-service"',
                     'id="add-text"','id="live-preview-rows"','row-copy',
                     'row-up','row-down','editor.js'):
            self.assertIn(text,r.text)
        script=self.client.get('/static/editor.js')
        self.assertEqual(script.status_code,200)
        self.assertIn('beforeunload',script.text)

    def test_manual_number_edit_audit_pdf_and_issue_lock(self):
        r=self.document('SPEZIAL-2026-003')
        self.assertIn('SPEZIAL-2026-003',r.text)
        r=self.document('SPEZIAL-2026-004',rid=1)
        self.assertIn('SPEZIAL-2026-004',r.text)
        self.assertEqual(self.database('SELECT number FROM invoices WHERE id=1'),[('SPEZIAL-2026-004',)])
        self.assertTrue(self.database("SELECT id FROM activity WHERE action='Belegnummer geaendert'"))
        pdf=self.client.get('/invoices/1/pdf').content
        self.assertIn('SPEZIAL-2026-004',PdfReader(io.BytesIO(pdf)).pages[0].extract_text())
        self.client.post('/invoices/1/issue',data={'_csrf':self._token()})
        r=self.document('NOCHMAL-999',rid=1)
        self.assertIn('unveraenderbar',r.text)
        self.assertEqual(self.database('SELECT number FROM invoices WHERE id=1'),[('SPEZIAL-2026-004',)])
        archived=self.client.get('/invoices/1/pdf').content
        self.assertIn('SPEZIAL-2026-004',PdfReader(io.BytesIO(archived)).pages[0].extract_text())
        self.assertEqual(self.client.get('/invoices/1/pdf').content,archived)

    def test_duplicate_number_does_not_erase_editor_inputs(self):
        self.document('TEST-01')
        r=self.document('test-01',description='WICHTIGE POSITION NICHT VERLIEREN')
        self.assertIn('bereits vergeben',r.text)
        self.assertIn('WICHTIGE POSITION NICHT VERLIEREN',r.text)
        self.assertIn('value="test-01"',r.text)
        self.assertEqual(self.database('SELECT count(*) FROM invoices'),[(1,)])
        r=self.document('RE/2026/0002')
        self.assertIn('keine Schraegstriche',r.text)
        self.assertEqual(self.database('SELECT count(*) FROM invoices'),[(1,)])

    def test_auto_numbers_skip_manually_occupied_and_counter_restart(self):
        self.document('RE-2026-00001')
        r=self.document(number='')
        self.assertIn('RE-2026-00002',r.text)
        r=self.settings({'next_invoice':'1'})
        self.assertIn('gespeichert',r.text)
        r=self.document(number='')
        self.assertIn('RE-2026-00003',r.text)
        self.assertEqual(self.database('SELECT next_invoice FROM companies WHERE id=1'),[(4,)])

    def test_custom_prefix_number_start_padding_per_kind(self):
        r=self.settings({'number_prefix':'RG','quote_prefix':'ANG','credit_prefix':'KOR',
                         'number_padding':'7','next_invoice':'61','next_quote':'12','next_credit':'99'})
        self.assertIn('gespeichert',r.text)
        self.assertIn('RG-2026-0000061',self.client.get('/settings').text)
        self.assertIn('ANG-2026-0000012',self.client.get('/settings').text)
        self.assertIn('KOR-2026-0000099',self.client.get('/settings').text)
        self.assertIn('RG-2026-0000061',self.document(number='').text)
        self.assertIn('ANG-2026-0000012',self.document(number='',kind='quote').text)

    def test_number_isolation_between_businesses(self):
        self.document('FIRMA-01')
        self.client.post('/companies/new',data={'_csrf':self._token(),'name':'Andere AG'})
        self.client.post('/customers/save',data={
            '_csrf':self._token(),'name':'Kunde B','zip':'3011','city':'Bern','country':'CH'})
        second=self.document('FIRMA-01',customer_id='2')
        self.assertIn('FIRMA-01',second.text)
        self.assertEqual(self.database('SELECT count(*) FROM invoices WHERE number=?',('FIRMA-01',)),[(2,)])

    def test_settings_invalid_reference_combination_kept_unchanged(self):
        r=self.settings({'qr_reference_type':'QRR'})
        self.assertIn('passt nicht zur IBAN',r.text)
        self.assertEqual(self.database('SELECT qr_reference_type FROM companies WHERE id=1'),[('AUTO',)])
        r=self.settings({'number_prefix':'INVALID PREFIX'})
        self.assertIn('Praefix',r.text)
        self.assertEqual(self.database('SELECT number_prefix FROM companies WHERE id=1'),[('RE',)])

    def qr_test(self,changes=None,output='preview'):
        values=dict(_csrf=self._token('/qr-test'), iban='CH9300762011623852957',
                   qr_reference_type='AUTO',qr_message='Rechnung {number}',
                   amount='12.50',currency='CHF',invoice_number='TEST-001',
                   name='Testkunde AG',street='Weg',building='1',zip='3000',city='Bern',country='CH',format=output)
        values.update(changes or {})
        return self.client.post('/qr-test',data=values)

    def test_qr_preview_png_payload_and_pdf(self):
        r=self.qr_test()
        self.assertIn('Test erfolgreich',r.text)
        self.assertIn('data:image/png;base64,',r.text)
        self.assertIn('SCOR',r.text)
        self.assertIn('Rechnung TEST-001',r.text)
        pdf=self.qr_test(output='pdf')
        self.assertEqual(pdf.status_code,200)
        self.assertEqual(pdf.headers['content-type'],'application/pdf')
        self.assertEqual(len(PdfReader(io.BytesIO(pdf.content)).pages),1)
        text=PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text()
        self.assertIn('NICHT VERSENDEN',text)

    def test_qr_reference_modes_non_scor_and_invalid_iban(self):
        r=self.qr_test({'qr_reference_type':'NON','qr_message':''})
        self.assertIn('Test erfolgreich',r.text)
        self.assertIn('NON',r.text)
        r=self.qr_test({'qr_reference_type':'QRR'})
        self.assertIn('QR-Referenz (QRR) benoetigt eine QR-IBAN',r.text)
        r=self.qr_test({'iban':'CH9300762011623852958'})
        self.assertIn('QR-Test nicht bestanden',r.text)
        r=self.qr_test({'zip':''})
        self.assertIn('QR-Test nicht bestanden',r.text)

    def test_qr_iban_only_qrr_chf(self):
        bban='30000'+'000000000001'
        converted=''.join(str(int(c,36)) if c.isalpha() else c for c in bban+'CH00')
        iban=f'CH{98-int(converted)%97:02d}{bban}'
        self.assertTrue(is_qr_iban(iban))
        r=self.qr_test({'iban':iban})
        self.assertIn('QRR',r.text)
        r=self.qr_test({'iban':iban,'currency':'EUR'})
        self.assertIn('nur in CHF',r.text)
        company=dict(id=1,iban=iban,name='Alpen GmbH',street='Weg',building='1',zip='3000',city='Bern',country='CH',qr_reference_type='AUTO',qr_message='{number}')
        customer=dict(name='Kunde AG',street='Weg',building='1',zip='8000',city='Zuerich',country='CH')
        qr=build_payload(company,customer,'12.50','CHF','111','TEST')
        self.assertEqual(qr['reference_type'],'QRR')
        self.assertTrue(valid_qrr(qr['reference']))

    def test_qr_without_csrf_and_nonadmin_denied(self):
        self.assertEqual(self.client.post('/qr-test',data={'amount':'10'}).status_code,403)
        # A member with viewer access must not see bank configuration.
        self.client.post('/team',data={'_csrf':self._token(),
                                       'email':'viewer@example.ch','full_name':'Viewer User',
                                       'password':'ViewerPasswort123','role':'viewer'})
        second=TestClient(create_app(self.tmp.name),follow_redirects=False)
        try:
            second.get('/login')
            token=re.search(r'name="_csrf"[^>]*value="([a-f0-9]+)"',second.get('/login').text).group(1)
            second.post('/login',data={'_csrf':token,'email':'viewer@example.ch','password':'ViewerPasswort123'})
            self.assertEqual(second.get('/qr-test').status_code,403)
        finally:second.close()

    def test_pdf_template_preview_is_nonpayable_and_does_not_create_invoice(self):
        preview=self.client.get('/templates/preview.pdf')
        self.assertEqual(preview.status_code,200)
        reader=PdfReader(io.BytesIO(preview.content))
        self.assertEqual(len(reader.pages),1)
        text=reader.pages[0].extract_text()
        self.assertIn('MUSTER-RECHNUNG',text)
        self.assertIn('Nicht versenden',text)
        self.assertEqual(self.database('SELECT COUNT(*) FROM invoices'),[(0,)])

    def test_saved_non_reference_and_custom_qr_message_in_real_invoice(self):
        response=self.settings({'qr_reference_type':'NON','qr_message':'Zahlung zu {number}'})
        self.assertIn('gespeichert',response.text)
        self.document('FREI-2026-007')
        pdf=self.client.get('/invoices/1/pdf')
        self.assertEqual(pdf.status_code,200)
        text=' '.join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
        self.assertIn('Zahlung zu FREI-2026-007',text)
        self.assertNotIn('SCOR',text)
        self.assertEqual(self.database('SELECT qr_reference_type FROM companies WHERE id=1'),[('NON',)])

    def test_number_validators(self):
        self.assertEqual(valid_number('INV 2026-00001'),'INV 2026-00001')
        for x in ('', '../etc/passwd', 'RE\n0', 'RE/001', 'R'*42):
            with self.assertRaises(ValueError):valid_number(x)
        with self.assertRaises(ValueError):valid_prefix('bad prefix')
        with self.assertRaises(ValueError):valid_padding('2')

if __name__=='__main__':unittest.main()
