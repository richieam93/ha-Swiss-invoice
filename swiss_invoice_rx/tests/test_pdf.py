import io
import json
import unittest
from pypdf import PdfReader
from app.pdf import make_pdf

class PdfTests(unittest.TestCase):
    def test_layout(self):
        company=dict(id=1,name='Alpen GmbH',street='Bergstrasse',building='4',zip='3000',city='Bern',
                     country='CH',iban='CH9300762011623852957',template_accent='#2563eb',
                     default_due_days=30,template_style='modern',template_title='Rechnung')
        customer=dict(name='Muster Kunde',street='Bahnhofstrasse',building='1',zip='8000',city='Zuerich',country='CH')
        inv=dict(id=1,kind='invoice',number='RE-2026-00001',invoice_date='2026-11-08',
                 service_date='2026-11-08',due_date='2026-12-08',currency='CHF',notes='Danke',
                 subtotal='100.00',tax_total='8.10',total='108.10',
                 tax_breakdown=json.dumps({'8.1':{'net':'100.00','tax':'8.10'}}))
        lines=[dict(description='Dienstleistung',qty='1',unit='Std.',price='100',tax_rate='8.1',discount='0',line_net='100')]
        buf,qr=make_pdf(inv,company,customer,lines)
        self.assertTrue(buf.startswith(b'%PDF'))
        self.assertEqual(len(PdfReader(io.BytesIO(buf)).pages),2)
        self.assertEqual(qr['reference_type'],'SCOR')

    def test_multipage_invoice_with_final_qr(self):
        company=dict(id=1,name='Beispiel AG',street='Strasse',building='1',zip='3011',city='Bern',
                     country='CH',iban='CH9300762011623852957',template_style='modern')
        customer=dict(name='Kunde AG',street='Hauptstrasse',building='9',zip='8000',city='Zuerich',country='CH')
        inv=dict(id=1,kind='invoice',number='RE-2026-00120',invoice_date='2026-11-08',
                 service_date='2026-11-08',due_date='2026-11-30',currency='CHF',
                 subtotal='550.00',tax_total='44.55',total='594.55',
                 tax_breakdown=json.dumps({'8.1':{'net':'550.00','tax':'44.55'}}))
        rows=[dict(description=f'Position {n:03d} - Dienstleistung mit Material und Beratung',
                   qty='1',unit='Std.',price='10.00',line_net='10.00',
                   tax_rate='8.1',discount='0',tax_mode='taxable') for n in range(1,56)]
        result,qr=make_pdf(inv,company,customer,rows)
        pages=PdfReader(io.BytesIO(result)).pages
        self.assertGreater(len(pages),2)
        content='\n'.join(p.extract_text() for p in pages)
        self.assertIn('Position 001',content)
        self.assertIn('Position 055',content)
        self.assertIn('Zahlteil und Empfangsschein',pages[-1].extract_text())
        self.assertIsNotNone(qr)
