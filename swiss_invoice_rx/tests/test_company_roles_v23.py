"""HelveticInvoice 2.3: exklusive Geschaeftszuweisung und Mandantenrechte."""
import re
import sqlite3
import tempfile
from contextlib import closing
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.db import db_connect, initialize


class CompanyRoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'rechnung.sqlite3'
        self.client = TestClient(create_app(self.tmp.name), follow_redirects=True)
        self.client.get('/setup')
        response = self.client.post('/setup', data={
            '_csrf': self.csrf(), 'company_name': 'Firma Eins AG',
            'email': 'owner@example.ch', 'full_name': 'Inhaber',
            'password': 'SicheresPasswort!2026', 'password2': 'SicheresPasswort!2026'
        })
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def csrf(self):
        response = self.client.get('/dashboard' if self.client.cookies.get('helvetic_session') else '/setup')
        if response.status_code == 403:
            response = self.client.get('/login')
        match = re.search(r'name="_csrf"\s+value="([^"]+)"', response.text)
        self.assertIsNotNone(match, response.text[:500])
        return match.group(1)

    def owner_adds_second_company(self):
        response = self.client.post('/companies/new', data={
            '_csrf': self.csrf(), 'name': 'Firma Zwei GmbH'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Firma Zwei', response.text)
        return 2

    def switch(self, company_id):
        return self.client.post('/company/switch', data={
            '_csrf': self.csrf(), 'company_id': str(company_id)})

    def create_limited_admin(self, cid=2, email='leitung@example.ch'):
        return self.client.post('/team', data={
            '_csrf': self.csrf(), 'company_id': str(cid),
            'email': email, 'full_name': 'Geschaeftsleitung', 'role': 'admin',
            'password': 'EinSehrSicheresPasswort2026'})

    def login_as(self, email='leitung@example.ch', pwd='EinSehrSicheresPasswort2026'):
        self.client.post('/logout', data={'_csrf': self.csrf()})
        response = self.client.post('/login', data={
            '_csrf': self.csrf(), 'email': email, 'password': pwd})
        self.assertEqual(response.status_code, 200, response.text[:500])
        self.assertIn('Dashboard', response.text)

    def test_owner_assigns_business_admin_to_chosen_business(self):
        self.owner_adds_second_company()
        self.switch(1)
        page = self.client.get('/team').text
        self.assertIn('Aktives Geschäft zuweisen', page)
        self.assertIn('Firma Eins AG', page)
        self.assertIn('Firma Zwei GmbH', page)
        response = self.create_limited_admin(2)
        self.assertIn('Geschaeftsleitung', response.text)
        with closing(db_connect(self.db)) as con:
            u = con.execute('SELECT * FROM users WHERE email=?', ('leitung@example.ch',)).fetchone()
            self.assertEqual(u['restricted_company_id'], 2)
            self.assertEqual(u['is_superadmin'], 0)
            memberships = con.execute('SELECT company_id,role FROM memberships WHERE user_id=?', (u['id'],)).fetchall()
            self.assertEqual([(x['company_id'], x['role']) for x in memberships], [(2, 'admin')])

        self.login_as()
        dashboard = self.client.get('/dashboard').text
        self.assertIn('Firma Zwei GmbH', dashboard)
        self.assertNotIn('Firma Eins AG', dashboard)
        self.assertIn('Nur dieses Geschäft', dashboard)
        self.assertNotIn('Weiteres Geschäft', dashboard)
        for path in ('/settings', '/team', '/templates', '/templates/designer',
                     '/qr-test', '/reports', '/bank', '/archive', '/systemcheck',
                     '/backup', '/activity'):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertNotIn('action="/backup/download"', self.client.get('/backup').text)
        self.assertEqual(self.client.get('/companies/new').status_code, 403)
        self.assertEqual(self.client.post('/backup/download', data={
            '_csrf': self.csrf()}).status_code, 403)
        self.assertEqual(self.switch(1).status_code, 403)
        self.assertEqual(self.client.get('/customers').status_code, 200)
        self.assertEqual(self.client.post('/customers/save', data={
            '_csrf': self.csrf(), 'name': 'Kunde Nur Zwei', 'city': 'Liestal'}).status_code, 200)
        with closing(db_connect(self.db)) as con:
            c = con.execute('SELECT company_id FROM customers WHERE name=?', ('Kunde Nur Zwei',)).fetchone()
            self.assertEqual(c['company_id'], 2)

    def test_scoped_admin_can_manage_only_its_team(self):
        self.owner_adds_second_company()
        self.create_limited_admin(2)
        self.login_as()
        team_html = self.client.get('/team').text
        self.assertIn('Firma Zwei', team_html)
        self.assertNotIn('Firma Eins', team_html)
        self.assertEqual(self.client.post('/team', data={
            '_csrf': self.csrf(), 'company_id': '1',
            'email': 'forbidden@example.ch', 'role': 'admin', 'password': 'Sicheres!12345678'
        }).status_code, 403)
        self.assertEqual(self.client.post('/team/1/role', data={
            '_csrf': self.csrf(), 'role': 'viewer'}).status_code, 403)
        self.assertEqual(self.client.post('/team/1/remove', data={
            '_csrf': self.csrf()}).status_code, 403)
        response = self.client.post('/team', data={
            '_csrf': self.csrf(), 'company_id': '2',
            'email': 'helper@example.ch', 'full_name': 'Assistent',
            'role': 'editor', 'password': 'Sicheres!12345678'})
        self.assertIn('Zugang gespeichert', response.text)
        with closing(db_connect(self.db)) as con:
            self.assertIsNone(con.execute('SELECT id FROM users WHERE email=?', ('forbidden@example.ch',)).fetchone())
            helper = con.execute('SELECT id,restricted_company_id FROM users WHERE email=?', ('helper@example.ch',)).fetchone()
            self.assertEqual(helper['restricted_company_id'], 2)
            self.assertEqual(con.execute('SELECT role FROM memberships WHERE user_id=?',
                                         (helper['id'],)).fetchone()['role'], 'editor')

    def test_extra_membership_cannot_bypass_fixed_scope(self):
        self.owner_adds_second_company()
        self.create_limited_admin(2)
        with closing(db_connect(self.db)) as con:
            uid = con.execute('SELECT id FROM users WHERE email=?', ('leitung@example.ch',)).fetchone()['id']
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(1,?,'admin')", (uid,))
            con.commit()
        self.login_as()
        self.assertEqual(self.switch(1).status_code, 403)
        self.assertNotIn('Firma Eins', self.client.get('/team').text)
        self.assertEqual(self.client.post('/team', data={
            '_csrf': self.csrf(), 'company_id': '1',
            'role': 'admin', 'email': 'hijack@example.ch',
            'password': 'Sicheres!12345678'}).status_code, 403)
        with closing(db_connect(self.db)) as con:
            self.assertIsNone(con.execute('SELECT id FROM users WHERE email=?', ('hijack@example.ch',)).fetchone())

    def test_existing_multi_business_account_not_silently_restricted(self):
        self.owner_adds_second_company()
        with closing(db_connect(self.db)) as con:
            from app.billing import hash_password
            uid=con.execute('INSERT INTO users(email,full_name,password_hash) VALUES(?,?,?)',
                            ('old@example.ch', 'Alt', hash_password('AltSicheresPasswort!'))).lastrowid
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(1,?,'viewer')", (uid,))
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(2,?,'viewer')", (uid,))
            con.commit()
        response=self.client.post('/team', data={
            '_csrf': self.csrf(), 'company_id': '2', 'email': 'old@example.ch',
            'role': 'admin'})
        self.assertIn('bereits ein anderes Geschaeft', response.text)
        with closing(db_connect(self.db)) as con:
            self.assertIsNone(con.execute('SELECT restricted_company_id FROM users WHERE id=?', (uid,)).fetchone()[0])
            self.assertEqual(con.execute('SELECT role FROM memberships WHERE user_id=? AND company_id=2', (uid,)).fetchone()[0], 'viewer')
        # Only the owner may explicitly permit several company memberships.
        response=self.client.post('/team', data={
            '_csrf': self.csrf(), 'company_id': '2', 'email': 'old@example.ch',
            'role': 'admin', 'multi_company': '1'})
        self.assertIn('Zugang gespeichert', response.text)
        with closing(db_connect(self.db)) as con:
            self.assertEqual(con.execute('SELECT role FROM memberships WHERE user_id=? AND company_id=2',
                                         (uid,)).fetchone()[0], 'admin')

    def test_owner_can_move_exclusive_user_to_another_company(self):
        self.owner_adds_second_company()
        self.create_limited_admin(2)
        with closing(db_connect(self.db)) as con:
            uid = con.execute('SELECT id FROM users WHERE email=?', ('leitung@example.ch',)).fetchone()['id']
        response=self.client.post(f'/team/{uid}/move', data={
            '_csrf': self.csrf(), 'company_id': '1'})
        self.assertIn('sicher in das ausgewaehlte Geschaeft verschoben',response.text)
        with closing(db_connect(self.db)) as con:
            self.assertEqual(con.execute('SELECT restricted_company_id FROM users WHERE id=?',
                                         (uid,)).fetchone()[0],1)
            membership=con.execute('SELECT company_id,role FROM memberships WHERE user_id=?', (uid,)).fetchall()
            self.assertEqual([(x['company_id'],x['role']) for x in membership], [(1,'admin')])
        self.login_as()
        self.assertIn('Firma Eins AG',self.client.get('/dashboard').text)
        self.assertNotIn('Firma Zwei GmbH',self.client.get('/team').text)
        self.assertEqual(self.switch(2).status_code,403)

    def test_company_admin_cannot_move_users_or_change_owner(self):
        self.owner_adds_second_company()
        self.create_limited_admin(2)
        self.login_as()
        self.assertEqual(self.client.post('/team/1/move',data={
            '_csrf': self.csrf(), 'company_id':'1'}).status_code,403)
        self.assertEqual(self.client.post('/team',data={
            '_csrf': self.csrf(), 'company_id':'2',
            'email':'owner@example.ch','role':'viewer'}).status_code,403)
        self.assertNotIn('Mehrere Geschäftszugriffe ausdrücklich erlauben',self.client.get('/team').text)

    def test_migration_of_old_users_table_is_additive(self):
        with tempfile.TemporaryDirectory() as old_dir:
            path=Path(old_dir)/'rechnung.sqlite3'
            with sqlite3.connect(path) as con:
                con.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,email TEXT NOT NULL,full_name TEXT NOT NULL,password_hash TEXT NOT NULL,is_superadmin INTEGER DEFAULT 0,active INTEGER DEFAULT 1)')
                con.execute("INSERT INTO users(email,full_name,password_hash) VALUES('old@example.ch','Alt','hash')")
                con.execute('PRAGMA user_version=10')
            initialize(path)
            with closing(db_connect(path)) as con:
                self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 15)
                row = con.execute('SELECT full_name,restricted_company_id FROM users').fetchone()
                self.assertEqual(row['full_name'], 'Alt')
                self.assertIsNone(row['restricted_company_id'])


if __name__ == '__main__':
    unittest.main()
