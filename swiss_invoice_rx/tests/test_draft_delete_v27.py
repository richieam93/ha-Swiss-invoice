"""Swiss-invoice-RX 2.7: Drafts can be deleted, issued documents remain protected."""
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from app.db import db_connect
from app.main import create_app


class DraftDeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'rechnung.sqlite3'
        self.app = create_app(self.temp.name)
        self.client = TestClient(self.app, follow_redirects=True)
        self.client.get('/setup')
        result = self.client.post('/setup', data={
            '_csrf': self.csrf('/setup'), 'company_name': 'Erste Firma AG',
            'email': 'owner@example.ch', 'full_name': 'Owner',
            'password': 'MeinPasswortSicher!1234', 'password2': 'MeinPasswortSicher!1234'})
        self.assertEqual(result.status_code, 200)
        self.customer()

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def csrf(self, location='/dashboard'):
        response = self.client.get(location)
        match = re.search(r'name="_csrf" value="([a-f0-9]+)"', response.text)
        self.assertIsNotNone(match)
        return match.group(1)

    def customer(self):
        result = self.client.post('/customers/save', data={
            '_csrf': self.csrf(), 'name': 'Kunde GmbH', 'street': 'Musterstrasse',
            'building': '2', 'zip': '4000', 'city': 'Basel', 'country': 'CH'})
        self.assertEqual(result.status_code, 200)

    def draft(self, kind='invoice', number=None):
        data = {'_csrf': self.csrf(), 'kind': kind,
                'customer_id': '1', 'invoice_date': '2026-11-14',
                'service_date': '2026-11-14', 'due_date': '2026-12-14',
                'currency': 'CHF', 'description[]': ['Beratung', 'Material'],
                'qty[]': ['-1', '-2'] if kind=='credit' else ['1', '2'], 'unit[]': ['Std.', 'Stk.'],
                'price[]': ['90', '15'], 'tax_rate[]': ['0', '0'],
                'tax_mode[]': ['taxable', 'taxable'], 'discount[]': ['0', '0'],
                'item_id[]': ['', '']}
        if number:
            data['number'] = number
        response = self.client.post('/invoices/save', data=data)
        self.assertEqual(response.status_code, 200, response.text[:350])
        with db_connect(self.db) as con:
            return con.execute('SELECT MAX(id) FROM invoices').fetchone()[0]

    def test_delete_draft_from_list_cascades_only_lines(self):
        rid = self.draft()
        list_page = self.client.get('/invoices?kind=invoice&status=draft&q=RE-')
        self.assertIn(f'/invoices/{rid}/delete', list_page.text)
        self.assertIn('data-confirm="Entwurf', list_page.text)
        self.assertIn('Löschen', list_page.text)
        result = self.client.post(f'/invoices/{rid}/delete', data={
            '_csrf': self.csrf(),
            'return_query': 'kind=invoice&status=draft&q=RE-&page=1'},
            follow_redirects=False)
        self.assertEqual(result.status_code, 303)
        self.assertIn('kind=invoice', result.headers['location'])
        self.assertIn('status=draft', result.headers['location'])
        self.assertIn('q=RE-', result.headers['location'])
        with db_connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM invoices').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM invoice_lines').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM customers').fetchone()[0], 1)
            action = con.execute('SELECT action,detail FROM activity WHERE action=?', ('Entwurf geloescht',)).fetchone()
            self.assertIsNotNone(action)
            self.assertIn('RE-', action['detail'])
        self.assertNotIn(f'/invoices/{rid}/delete', self.client.get('/invoices?status=draft').text)

    def test_detail_action_and_delete_quote_and_credit(self):
        for kind in ('quote', 'credit'):
            rid = self.draft(kind=kind)
            detail = self.client.get(f'/invoices/{rid}')
            self.assertIn('Entwurf löschen', detail.text)
            self.assertIn(f'/invoices/{rid}/delete', detail.text)
            self.assertNotIn('>Stornieren</button>', detail.text)
            response = self.client.post(f'/invoices/{rid}/delete', data={'_csrf': self.csrf()}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers['location'], f'/invoices?kind={kind}')
            self.assertEqual(self.client.get(f'/invoices/{rid}').status_code, 404)

    def test_freigegebene_rechnung_will_not_delete(self):
        rid = self.draft()
        result = self.client.post(f'/invoices/{rid}/issue', data={'_csrf': self.csrf()})
        self.assertIn('Beleg freigegeben', result.text)
        self.assertNotIn(f'/invoices/{rid}/delete', self.client.get('/invoices?kind=invoice').text)
        self.assertNotIn('Entwurf löschen', self.client.get(f'/invoices/{rid}').text)
        refused = self.client.post(f'/invoices/{rid}/delete', data={'_csrf': self.csrf()})
        self.assertEqual(refused.status_code, 409)
        with db_connect(self.db) as con:
            self.assertEqual(con.execute('SELECT status FROM invoices WHERE id=?', (rid,)).fetchone()['status'], 'sent')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?', (rid,)).fetchone()[0], 2)

    def test_access_no_csrf_and_wrong_company(self):
        rid = self.draft()
        self.assertEqual(self.client.post(f'/invoices/{rid}/delete').status_code, 403)
        self.assertEqual(self.client.get(f'/invoices/{rid}/delete').status_code, 405)
        created = self.client.post('/companies/new', data={'_csrf': self.csrf(), 'name': 'Andere Firma'})
        self.assertEqual(created.status_code, 200)
        self.assertEqual(self.client.post(f'/invoices/{rid}/delete',data={'_csrf': self.csrf()}).status_code, 404)
        with db_connect(self.db) as con:
            self.assertIsNotNone(con.execute('SELECT id FROM invoices WHERE id=?', (rid,)).fetchone())

    def test_viewer_cannot_delete_or_see_action_but_editor_can(self):
        rid = self.draft()
        invited = self.client.post('/team', data={
            '_csrf': self.csrf(), 'company_id': '1',
            'email': 'viewer@example.ch', 'full_name': 'Betrachter',
            'role': 'viewer', 'password': 'SicheresPasswort1234!'})
        self.assertEqual(invited.status_code, 200)
        self.client.post('/logout', data={'_csrf': self.csrf()})
        self.client.post('/login', data={'_csrf': self.csrf('/login'),
                                        'email': 'viewer@example.ch', 'password': 'SicheresPasswort1234!'})
        self.assertNotIn(f'/invoices/{rid}/delete', self.client.get('/invoices').text)
        self.assertNotIn(f'/invoices/{rid}/delete', self.client.get(f'/invoices/{rid}').text)
        self.assertEqual(self.client.post(f'/invoices/{rid}/delete',data={'_csrf': self.csrf()}).status_code, 403)
        with db_connect(self.db) as con:
            self.assertIsNotNone(con.execute('SELECT id FROM invoices WHERE id=?', (rid,)).fetchone())
        self.client.post('/logout', data={'_csrf': self.csrf()})
        self.client.post('/login', data={'_csrf': self.csrf('/login'),
                                        'email': 'owner@example.ch', 'password': 'MeinPasswortSicher!1234'})
        self.client.post('/team', data={
            '_csrf': self.csrf(), 'company_id': '1',
            'email': 'editor@example.ch', 'full_name': 'Editor',
            'role': 'editor', 'password': 'SicheresPasswort1234!'})
        self.client.post('/logout', data={'_csrf': self.csrf()})
        self.client.post('/login', data={'_csrf': self.csrf('/login'),
                                        'email': 'editor@example.ch', 'password': 'SicheresPasswort1234!'})
        self.assertIn(f'/invoices/{rid}/delete', self.client.get('/invoices').text)
        self.assertEqual(self.client.post(f'/invoices/{rid}/delete',data={'_csrf': self.csrf()},follow_redirects=False).status_code,303)

    def test_recurring_schedule_protected(self):
        rid = self.draft()
        setup = self.client.post(f'/invoices/{rid}/recurring', data={
            '_csrf': self.csrf(), 'interval_months': '1', 'next_date': '2026-12-01'})
        self.assertEqual(setup.status_code, 200)
        response = self.client.post(f'/invoices/{rid}/delete',data={'_csrf':self.csrf()})
        self.assertEqual(response.status_code,409)
        with db_connect(self.db) as con:
            self.assertIsNotNone(con.execute('SELECT id FROM invoices WHERE id=?',(rid,)).fetchone())
            self.assertEqual(con.execute('SELECT COUNT(*) FROM recurrings WHERE source_invoice_id=?',(rid,)).fetchone()[0], 1)

    def test_duplicate_draft_kept_without_dangling_parent(self):
        original = self.draft()
        result=self.client.post(f'/invoices/{original}/copy',data={'_csrf':self.csrf()})
        self.assertEqual(result.status_code,200)
        with db_connect(self.db) as con:
            duplicate=con.execute('SELECT id,parent_id FROM invoices WHERE id!=?',(original,)).fetchone()
            self.assertIsNotNone(duplicate)
            self.assertEqual(duplicate['parent_id'], original)
        result=self.client.post(f'/invoices/{original}/delete',data={'_csrf':self.csrf()})
        self.assertEqual(result.status_code,200)
        with db_connect(self.db) as con:
            duplicate=con.execute('SELECT id,parent_id FROM invoices').fetchone()
            self.assertIsNotNone(duplicate)
            self.assertIsNone(duplicate['parent_id'])

    def test_not_redirect_to_external_site(self):
        rid=self.draft()
        response=self.client.post(f'/invoices/{rid}/delete',data={
            '_csrf':self.csrf(), 'return_query':'https://evil.example/?kind=invoice&status=draft&next=https://evil.example'},
            follow_redirects=False)
        self.assertEqual(response.status_code,303)
        self.assertTrue(response.headers['location'].startswith('/invoices?kind=invoice'))
        self.assertNotIn('next=',response.headers['location'])


if __name__=='__main__':
    unittest.main()
