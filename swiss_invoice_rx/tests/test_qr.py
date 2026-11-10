import unittest
from app.qr import valid_iban,is_qr_iban,qrr_reference,valid_qrr,scor_reference,valid_scor,build_payload,qr_image

COMPANY = dict(id=1,name='Alpen GmbH',street='Bergstrasse',building='5',zip='3000',city='Bern',country='CH',iban='CH9300762011623852957')
CUSTOMER = dict(name='Kunde AG',street='Bahnstrasse',building='14',zip='8000',city='Zuerich',country='CH')

class QrTests(unittest.TestCase):
    def qr_iban(self):
        bban='30000'+'000000000001'
        base=bban+'CH00'
        num=''.join(str(int(c,36)) if c.isalpha() else c for c in base)
        check=98-int(num)%97
        return f'CH{check:02d}{bban}'

    def test_iban(self):
        self.assertTrue(valid_iban(COMPANY['iban']))
        self.assertFalse(valid_iban('CH9300762011623852958'))
        self.assertFalse(is_qr_iban(COMPANY['iban']))
        self.assertTrue(is_qr_iban(self.qr_iban()))

    def test_references(self):
        # Bekannter Gueltig-Test aus dem Schweizer Zahlungsverkehr.
        self.assertTrue(valid_qrr('210000000003139471430009017'))
        self.assertEqual(qrr_reference('21000000000313947143000901'),'210000000003139471430009017')
        self.assertTrue(valid_scor('RF18539007547034'))
        qrr=qrr_reference(123)
        self.assertEqual(len(qrr),27)
        self.assertTrue(valid_qrr(qrr))
        self.assertFalse(valid_qrr(qrr[:-1] + str((int(qrr[-1])+1)%10)))
        scor=scor_reference('RE-2026-00420')
        self.assertTrue(valid_scor(scor))

    def test_payload(self):
        obj=build_payload(COMPANY,CUSTOMER,'121.85','CHF','12345','Rechnung RE-12345')
        fields=obj['payload'].split('\r\n')
        self.assertEqual(fields[0:4],['SPC','0200','1',COMPANY['iban']])
        self.assertEqual(fields[4],'S')
        self.assertEqual(fields[11:18],['']*7)
        self.assertEqual(fields[18:21],['121.85','CHF','S'])
        self.assertEqual(fields[27],'SCOR')
        self.assertEqual(fields[30],'EPD')
        self.assertTrue(valid_scor(fields[28]))
        another=build_payload(COMPANY,CUSTOMER,'121.85','CHF','0000100000000000001','Rechnung 1')
        newer=build_payload(COMPANY,CUSTOMER,'121.85','CHF','0000100000000000002','Rechnung 2')
        self.assertNotEqual(another['reference'],newer['reference'])
        self.assertGreater(qr_image(obj['payload']).width,500)

    def test_iban_reference_restrictions(self):
        qrcompany={**COMPANY,'iban':self.qr_iban()}
        data=build_payload(qrcompany,CUSTOMER,'1.00','CHF','12345')
        self.assertEqual(data['reference_type'],'QRR')
        self.assertTrue(valid_qrr(data['reference']))
        with self.assertRaises(ValueError):build_payload(qrcompany,CUSTOMER,'5','EUR','12345')
        with self.assertRaises(ValueError):build_payload(COMPANY,{**CUSTOMER,'city':''},'5','CHF','12345')
        with self.assertRaises(ValueError):build_payload(COMPANY,CUSTOMER,'-1','CHF','12345')
