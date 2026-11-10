import unittest
from decimal import Decimal
from app.billing import summarize,hash_password,check_password,cents,invoice_status

class BillingTests(unittest.TestCase):
    def test_mwst_mix(self):
        r=summarize([
            dict(description='Beratung',qty='2',price='100',tax_rate='8.1',discount='0'),
            dict(description='Buch',qty='3',price='10',tax_rate='2.6',discount='0')])
        self.assertEqual(r['subtotal'],'230.00')
        self.assertEqual(r['tax_total'],'16.98')
        self.assertEqual(r['total'],'246.98')

    def test_discount_and_round(self):
        r=summarize([dict(description='Arbeitsleistung',qty='3',price='11.15',tax_rate='8.1',discount='10')], '5')
        self.assertEqual(r['subtotal'],'28.60')
        self.assertEqual(r['tax_total'],'2.32')
        self.assertEqual(r['total'],'30.92')

    def test_bad_monetary_values(self):
        for bad in ('nan','Infinity','abrakadabra'):
            with self.assertRaises(ValueError):cents(bad)
        with self.assertRaises(ValueError):summarize([])
        with self.assertRaises(ValueError):summarize([dict(description='',qty=1,price=2,tax_rate=0)])

    def test_password_hash(self):
        digest=hash_password('Langes_geheimes_Passwort_123')
        self.assertTrue(check_password('Langes_geheimes_Passwort_123',digest))
        self.assertFalse(check_password('Falsch',digest))
        with self.assertRaises(ValueError):hash_password('kurz')
