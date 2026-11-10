import io
import re
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from fastapi.testclient import TestClient
from pypdf import PdfReader
from app.bank import parse_camt
from app.main import create_app
from app.db import db_connect
from app.qr import qrr_reference, scor_reference

IBAN = 'CH9300762011623852957'


def camt_xml(value='100.00', date='2026-11-08', account=IBAN, memo='RE-2026-00001',
             currency='CHF', ref='', message='camt.053', status='BOOK', direction='CRDT',
             bankref='STATEMENT-999'):
    root, group = ('BkToCstmrStmt', 'Stmt') if message == 'camt.053' else ('BkToCstmrDbtCdtNtfctn', 'Ntfctn')
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:{message}.001.08"><{root}><{group}>
<Acct><Id><IBAN>{account}</IBAN></Id></Acct><Ntry>
<Amt Ccy="{currency}">{value}</Amt><CdtDbtInd>{direction}</CdtDbtInd><Sts><Cd>{status}</Cd></Sts>
<BookgDt><Dt>{date}</Dt></BookgDt><AcctSvcrRef>{bankref}</AcctSvcrRef>
<NtryDtls><TxDtls><AmtDtls><TxAmt><Amt Ccy="{currency}">{value}</Amt></TxAmt></AmtDtls>
<RltdPties><Dbtr><Pty><Nm>Musterzahler AG</Nm></Pty></Dbtr></RltdPties>
<RmtInf><Strd><CdtrRefInf><Ref>{ref}</Ref></CdtrRefInf></Strd><Ustrd>{memo}</Ustrd></RmtInf>
</TxDtls></NtryDtls></Ntry></{group}></{root}></Document>'''.encode('utf-8')


class CamtParserTests(unittest.TestCase):
    def test_053_reference_and_amount(self):
        result = parse_camt(camt_xml(ref='RF123', value='12.40'))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['amount'], '12.40')
        self.assertEqual(result[0]['payment_reference'], 'RF123')
        self.assertEqual(result[0]['debtor'], 'Musterzahler AG')
        self.assertEqual(result[0]['value_date'], '2026-11-08')
        self.assertEqual(result[0]['account_iban'], IBAN)

    def test_054_supported_and_deterministic(self):
        data = camt_xml(message='camt.054')
        a, b = parse_camt(data), parse_camt(data)
        self.assertEqual(a[0]['fingerprint'], b[0]['fingerprint'])
        self.assertEqual(a[0]['source'], 'camt.054')

    def test_credit_only_and_pending_not_booked(self):
        with self.assertRaisesRegex(ValueError, 'Keine gebuchten'):
            parse_camt(camt_xml(direction='DBIT'))
        with self.assertRaisesRegex(ValueError, 'Keine gebuchten'):
            parse_camt(camt_xml(status='PDNG'))

    def test_forbid_entities_large_files_and_wrong_format(self):
        with self.assertRaisesRegex(ValueError, 'XML-Entities'):
            parse_camt(b'<!DOCTYPE lol [<!ENTITY x "attack">]>' + camt_xml())
        with self.assertRaises(ValueError):
            parse_camt(b'x' * (3*1024*1024+1))
        with self.assertRaises(ValueError):
            parse_camt(b'<Document/>')

    def test_group_entry_with_unknown_split_amount_rejected(self):
        raw = camt_xml()
        raw = raw.replace(b'<AmtDtls><TxAmt><Amt Ccy="CHF">100.00</Amt></TxAmt></AmtDtls>', b'')
        raw = raw.replace(b'</TxDtls>',b'</TxDtls><TxDtls><RmtInf><Ustrd>Second</Ustrd></RmtInf></TxDtls>')
        with self.assertRaisesRegex(ValueError,'Sammelbuchung'):
            parse_camt(raw)

    def test_refs_match_ch_qr(self):
        self.assertEqual(len(qrr_reference('00001000000000001')),27)
        self.assertTrue(scor_reference('INV00001000000000001').startswith('RF'))


class BankWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(self.tmp.name), follow_redirects=True)
        self.client.get('/setup')
        self.client.post('/setup', data={'_csrf':self.token('/setup'), 'company_name':'Muster GmbH',
             'email':'alice@example.ch', 'full_name':'Alice','password':'EinSicheresPasswort_1337',
             'password2':'EinSicheresPasswort_1337'})
        self.client.post('/settings', data={'_csrf':self.token('/settings'), 'name':'Muster GmbH',
             'street':'Bundesgasse','building':'1','zip':'3011','city':'Bern','country':'CH',
             'iban':IBAN, 'currency':'CHF', 'tax_registered':'1', 'default_tax':'8.1',
             'color':'#2563eb', 'number_prefix':'RE', 'default_due_days':'30'})
        self.client.post('/customers/save',data={'_csrf':self.token('/customers/new'), 'name':'Kunde AG',
             'street':'Weg','building':'22','zip':'8000','city':'Zurich','country':'CH'})
        self.client.post('/invoices/save', data={
             '_csrf':self.token('/invoices/new'), 'kind':'invoice','customer_id':'1',
             'invoice_date':'2026-11-08','due_date':'2026-12-08','currency':'CHF','discount':'0',
             'description[]':['Dienstleistung'], 'qty[]':['1'],'unit[]':['Stk.'],
             'price[]':['100.00'],'tax_rate[]':['0'], 'tax_mode[]':['taxable'],
             'discount[]':['0'], 'item_id[]':['']})
        self.client.post('/invoices/1/issue',data={'_csrf':self.token('/invoices/1')})

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def token(self, url):
        html = self.client.get(url).text
        found = re.search(r'name="_csrf" value="([0-9a-f]{48})"',html)
        self.assertIsNotNone(found,html[:500])
        return found.group(1)

    def upload(self, payload, filename='bank.xml'):
        return self.client.post('/bank/import',data={'_csrf':self.token('/bank')},
            files={'statement':(filename,payload,'application/xml')})

    def raw(self):
        return closing(db_connect(Path(self.tmp.name)/'rechnung.sqlite3'))

    def test_import_duplicate_manual_assignment_and_reversal(self):
        xml = camt_xml(ref=scor_reference('INV00001000000000001'))
        self.assertIn('1 neue Bankgutschriften',self.upload(xml).text)
        self.assertIn('0 neue Bankgutschriften',self.upload(xml).text)
        with self.raw() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM bank_transactions').fetchone()[0],1)
        r=self.client.get('/bank')
        self.assertIn('Vorschlag verfügbar',r.text)
        self.assertIn('Musterzahler AG',r.text)
        t=self.token('/bank')
        r=self.client.post('/bank/1/assign',data={'_csrf':t,'invoice_id':'1'})
        self.assertIn('Bankzahlung wurde der Rechnung',r.text)
        with self.raw() as con:
            self.assertEqual(con.execute('SELECT paid_total FROM invoices WHERE id=1').fetchone()[0],'100.00')
            self.assertEqual(con.execute('SELECT status FROM bank_transactions WHERE id=1').fetchone()[0],'matched')
            payment_id=con.execute('SELECT payment_id FROM bank_transactions').fetchone()[0]
        r=self.client.post('/bank/1/assign',data={'_csrf':self.token('/bank'),'invoice_id':'1'})
        self.assertIn('bereits zugeordnet',r.text)
        r=self.client.post(f'/invoices/1/payments/{payment_id}/reverse',data={
            '_csrf':self.token('/invoices/1'), 'reason':'Zahlung irrtuemlich zugeordnet'})
        self.assertIn('Zahlungsstorno',r.text)
        with self.raw() as con:
            row=con.execute('SELECT status,payment_id FROM bank_transactions WHERE id=1').fetchone()
            self.assertEqual(row['status'],'open')
            self.assertIsNone(row['payment_id'])
            self.assertEqual(con.execute('SELECT paid_total FROM invoices WHERE id=1').fetchone()[0],'0.00')

    def test_wrong_account_and_tamper_protected(self):
        self.assertIn('andere IBAN', self.upload(camt_xml(account='CH5604835012345678009')).text)
        self.assertEqual(self.client.post('/bank/import',data={},files={'statement':('bank.xml',camt_xml())}).status_code,403)
        self.assertIn('1 neue Bankgutschriften',self.upload(camt_xml()).text)
        self.client.post('/companies/new',data={'_csrf':self.token('/companies/new'),'name':'Andere AG'})
        self.assertNotIn('Musterzahler AG', self.client.get('/bank').text)
        self.assertEqual(self.client.post('/bank/1/assign',data={
            '_csrf':self.token('/bank'),'invoice_id':'1'}).status_code,404)
        self.assertEqual(self.client.get('/customers/1/statement.pdf').status_code,404)

    def test_overpayment_and_currency_validation(self):
        self.upload(camt_xml(value='150.00'))
        r=self.client.post('/bank/1/assign',data={'_csrf':self.token('/bank'),'invoice_id':'1'})
        self.assertIn('uebersteigt',r.text)
        with self.raw() as con:
            self.assertEqual(con.execute('SELECT paid_total FROM invoices WHERE id=1').fetchone()[0],'0.00')
            self.assertEqual(con.execute('SELECT status FROM bank_transactions WHERE id=1').fetchone()[0],'open')

    def test_ignore_then_reopen(self):
        self.upload(camt_xml())
        r=self.client.post('/bank/1/ignore',data={'_csrf':self.token('/bank'),'reason':'Nicht fuer Kundenrechnung'})
        self.assertIn('nicht zuordenbar markiert',r.text)
        self.assertIn('Nicht fuer Kundenrechnung',self.client.get('/bank?status=ignored').text)
        r=self.client.post('/bank/1/reopen',data={'_csrf':self.token('/bank'),'reason':''})
        self.assertIn('wieder zur Zuordnung',r.text)
        with self.raw() as con:self.assertEqual(con.execute('SELECT status FROM bank_transactions').fetchone()[0],'open')

    def test_customer_account_statement_pdf_and_date_validation(self):
        r=self.client.get('/customers/1/statement.pdf?currency=CHF&start=2026-01-01&end=2026-12-31')
        self.assertEqual(r.status_code,200)
        text=' '.join(page.extract_text() for page in PdfReader(io.BytesIO(r.content)).pages)
        self.assertIn('Kundenkontoauszug',text)
        self.assertIn('RE-2026-00001',text)
        self.assertIn('100.00',text)
        self.assertEqual(self.client.get('/customers/1/statement.pdf?start=2026-12-31&end=2026-01-01').status_code,400)
        self.assertEqual(self.client.get('/customers/1/statement.pdf?currency=USD').status_code,400)
        self.assertIn('value="CHF"',self.client.get('/customers/1').text)

    def test_import_rejects_invalid_xml_without_partial_entries(self):
        self.assertIn('Keine gueltige XML-Bankdatei',self.upload(b'<broken>').text)
        with self.raw() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM bank_transactions').fetchone()[0],0)

if __name__=='__main__':
    unittest.main()
