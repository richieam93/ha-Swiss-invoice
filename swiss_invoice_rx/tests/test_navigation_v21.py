"""Version 2.1: groups, routes, roles and non-JavaScript fallback."""
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from app.billing import hash_password
from app.db import transaction
from app.main import create_app


class SidebarNavigation21Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = TestClient(create_app(self.root), follow_redirects=True)
        setup = self.client.get('/setup').text
        token = self.token(setup)
        response = self.client.post('/setup', data={
            '_csrf': token, 'company_name': 'Muster AG', 'full_name': 'Super Admin',
            'email': 'admin@beispiel.ch', 'password': 'SicheresPasswort!123',
            'password2': 'SicheresPasswort!123'
        })
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    @staticmethod
    def token(html):
        return re.search(r'name="_csrf" value="([0-9a-f]+)"', html).group(1)

    def link_keys(self, html):
        return re.findall(r'<a href="[^"]+" class="nav-link[^"]*" data-nav-key="([^"]+)"', html)

    def test_all_original_sidebar_destinations_remain(self):
        html = self.client.get('/dashboard').text
        keys = self.link_keys(html)
        expected = ('dashboard search invoices quotes credits recurring customers items '
                    'receivables bank archive reports templates designer qr-test settings '
                    'team activity backup systemcheck help').split()
        self.assertEqual(set(keys), set(expected))
        self.assertEqual(len(keys), len(expected))
        self.assertIn('href="/companies/new"', html)
        self.assertIn('href="/account"', html)
        self.assertIn('action="/logout"', html)
        self.assertIn('action="/company/switch"', html)
        self.assertIn('data-open-global-search', html)

    def test_six_groups_have_native_details_and_correct_totals(self):
        html = self.client.get('/dashboard').text
        groups = re.findall(r'<details class="nav-group" data-nav-group="([^"]+)"', html)
        self.assertEqual(groups, ['sales', 'contacts', 'finance', 'documents', 'design', 'admin'])
        self.assertEqual(html.count('class="nav-group-summary"'), 6)
        self.assertEqual(html.count('class="nav-group-links"'), 6)
        self.assertIn('<nav class="sidebar-nav" aria-label="Arbeitsbereiche">', html)
        self.assertIn('class="nav-link nav-pinned" data-nav-key="dashboard"', html)

    def test_current_section_open_even_without_javascript(self):
        for route, group in [('/invoices?kind=credit', 'sales'),
                             ('/invoices/new?kind=quote', 'sales'),
                             ('/customers/new', 'contacts'),
                             ('/items/new', 'contacts'),
                             ('/receivables', 'finance'),
                             ('/reports', 'documents'),
                             ('/templates/designer', 'design'),
                             ('/qr-test', 'design'),
                             ('/systemcheck', 'admin')]:
            with self.subTest(route=route):
                page = self.client.get(route)
                self.assertEqual(page.status_code, 200, route)
                self.assertRegex(page.text,
                    rf'<details class="nav-group" data-nav-group="{group}"\s+open>')

    def test_invoice_kind_is_forwarded_to_navigation_for_edit_and_preview(self):
        html = self.client.get('/invoices/new?kind=quote').text
        self.assertIn('data-document-kind="quote"', html)
        html = self.client.get('/invoices/new?kind=credit').text
        self.assertIn('data-document-kind="credit"', html)

    def test_viewer_does_not_see_admin_groups_or_links(self):
        with transaction(self.root/'rechnung.sqlite3', True) as con:
            user_id = con.execute('INSERT INTO users(email,full_name,password_hash) VALUES(?,?,?)',
                        ('viewer@beispiel.ch', 'Leserin', hash_password('ViewerPasswort!2026'))).lastrowid
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(1,?,'viewer')", (user_id,))
        html = self.client.get('/dashboard').text
        self.client.post('/logout', data={'_csrf':self.token(html)})
        token = self.token(self.client.get('/login').text)
        self.client.post('/login', data={'_csrf':token, 'email':'viewer@beispiel.ch',
                                         'password':'ViewerPasswort!2026'})
        page = self.client.get('/dashboard')
        self.assertEqual(page.status_code, 200)
        keys = set(self.link_keys(page.text))
        self.assertNotIn('admin', page.text.split('data-nav-group='))
        for key in ('templates', 'designer', 'qr-test', 'settings', 'team',
                    'activity', 'backup', 'systemcheck'):
            self.assertNotIn(key, keys)
        for key in ('dashboard', 'search', 'invoices', 'quotes', 'credits', 'recurring',
                    'customers', 'items', 'receivables', 'bank', 'archive', 'reports', 'help'):
            self.assertIn(key, keys)
        self.assertNotIn('href="/companies/new"', page.text)
        self.assertIn('action="/company/switch"', page.text)
        self.assertIn('action="/logout"', page.text)
        self.assertEqual(self.client.get('/settings').status_code, 403)

    def test_links_accessible_on_mobile_and_focusable_native_summary(self):
        html = self.client.get('/dashboard').text
        self.assertIn('id="mobile-menu-toggle"', html)
        self.assertIn('id="sidebar-overlay"', html)
        self.assertIn('aria-controls="main-sidebar"', html)
        self.assertIn('class="nav-group-summary"', html)
        self.assertEqual(self.client.get('/static/app.js').status_code, 200)
        self.assertEqual(self.client.get('/static/app.css').status_code, 200)


if __name__ == '__main__':
    unittest.main()
