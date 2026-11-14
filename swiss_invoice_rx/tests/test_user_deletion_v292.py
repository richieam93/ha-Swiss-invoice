"""Recycling deleted email addresses without cross-company or session leaks."""
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import db_connect
from app.main import create_app


class UserDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'rechnung.sqlite3'
        self.app = create_app(self.temp.name)
        self.owner = TestClient(self.app, follow_redirects=False)
        self.employee = TestClient(self.app, follow_redirects=False)
        self.addCleanup(self.owner.close)
        self.addCleanup(self.employee.close)
        result = self.owner.post('/setup', data={
            '_csrf': self.csrf(self.owner, '/setup'),
            'company_name': 'Firma A', 'email': 'owner@example.ch',
            'full_name': 'Hauptadministrator',
            'password': 'StrongPassword01234!',
            'password2': 'StrongPassword01234!',
        })
        self.assertEqual(result.headers['location'], '/settings')

    def csrf(self, client, path):
        response = client.get(path)
        self.assertEqual(response.status_code, 200, path)
        token = re.search(r'name="_csrf"\s+value="([a-f0-9]+)"', response.text)
        self.assertIsNotNone(token, response.text[:400])
        return token.group(1)

    def add_user(self, email='helfer@example.ch', password='OldPassword01234!', own=False, multi=False, company_id=1):
        data = {
            '_csrf': self.csrf(self.owner, '/team'),
            'email': email, 'full_name': 'Helfer', 'password': password,
            'company_id': str(company_id), 'role': 'editor',
        }
        if own:
            data['create_own_company'] = '1'
        if multi:
            data['multi_company'] = '1'
        res = self.owner.post('/team', data=data)
        self.assertEqual(res.status_code, 303)
        return res

    def member_login(self, email='helfer@example.ch', password='OldPassword01234!'):
        res = self.employee.post('/login', data={
            '_csrf': self.csrf(self.employee, '/login'),
            'email': email, 'password': password,
        })
        self.assertEqual(res.status_code, 303)
        return res

    def delete_user(self, uid=2):
        return self.owner.post(f'/team/{uid}/remove', data={'_csrf': self.csrf(self.owner, '/team')})

    def test_last_membership_deletes_account_and_email_reusable_for_private_onboarding(self):
        self.add_user()
        self.assertEqual(self.member_login().headers['location'], '/dashboard')
        with db_connect(self.db) as con:
            uid = con.execute("SELECT id FROM users WHERE email='helfer@example.ch'").fetchone()[0]
            con.execute("INSERT INTO customers(company_id,number,name) VALUES(1,'K-1','Bestehender Kunde')")
            con.execute("INSERT INTO activity(company_id,user_id,action,detail) VALUES(1,?,'Dokument geprüft','Ausführung')", (uid,))
            con.commit()
        listing = self.owner.get('/team').text
        self.assertIn('Benutzer löschen', listing)
        deleted = self.delete_user(uid)
        self.assertEqual(deleted.status_code, 303)
        with db_connect(self.db) as con:
            self.assertIsNone(con.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())
            self.assertIsNone(con.execute('SELECT * FROM memberships WHERE user_id=?', (uid,)).fetchone())
            self.assertEqual(con.execute('SELECT COUNT(*) FROM customers').fetchone()[0], 1)
            audit = con.execute("SELECT user_id,detail FROM activity WHERE action='Dokument geprüft'").fetchone()
            self.assertIsNotNone(audit)
            self.assertIsNone(audit['user_id'])
            self.assertEqual(audit['detail'], 'Ausführung')
        # After deletion, an old session must no longer grant access.
        self.assertEqual(self.employee.get('/dashboard').headers['location'], '/login')
        # The same email address can now be used for a separate, isolated business.
        self.add_user(password='NewPassword98765!', own=True)
        with db_connect(self.db) as con:
            new = con.execute("SELECT id,can_create_company FROM users WHERE email='helfer@example.ch'").fetchone()
            self.assertEqual(new['can_create_company'], 1)
            self.assertGreater(new['id'],uid)  # Never reuse a deleted user's numeric ID.
            self.assertEqual(con.execute('SELECT COUNT(*) FROM memberships WHERE user_id=?',(new['id'],)).fetchone()[0],0)
        # Even with a recycled SQLite user ID, the previous account's session is unusable.
        self.assertEqual(self.employee.get('/dashboard').headers['location'], '/login')
        failed = self.member_login(password='OldPassword01234!')
        self.assertEqual(failed.headers['location'], '/login')
        succeed = self.member_login(password='NewPassword98765!')
        self.assertEqual(succeed.headers['location'], '/onboarding')
        self.assertNotIn('Firma A', self.employee.get('/onboarding').text)

    def test_legacy_orphan_is_purged_when_email_reused(self):
        self.add_user()
        self.assertEqual(self.member_login().headers['location'], '/dashboard')
        with db_connect(self.db) as con:
            old = con.execute("SELECT id,session_nonce FROM users WHERE email='helfer@example.ch'").fetchone()
            con.execute('DELETE FROM memberships WHERE user_id=?', (old['id'],))
            con.commit()
        self.add_user(password='Replacement98765!', own=True)
        with db_connect(self.db) as con:
            new = con.execute("SELECT id,session_nonce,can_create_company FROM users WHERE email='helfer@example.ch'").fetchone()
            self.assertEqual(new['can_create_company'], 1)
            self.assertNotEqual(new['session_nonce'], old['session_nonce'])
        self.assertEqual(self.employee.get('/dashboard').headers['location'], '/login')
        self.assertEqual(self.member_login(password='Replacement98765!').headers['location'], '/onboarding')

    def test_legacy_orphan_can_be_recreated_as_assigned_employee(self):
        self.add_user()
        with db_connect(self.db) as con:
            old_id=con.execute("SELECT id FROM users WHERE email='helfer@example.ch'").fetchone()[0]
            con.execute('DELETE FROM memberships WHERE user_id=?', (old_id,))
            con.commit()
        self.add_user(password='AnotherPassword9876!')
        with db_connect(self.db) as con:
            user=con.execute("SELECT id FROM users WHERE email='helfer@example.ch'").fetchone()
            self.assertIsNotNone(user)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM memberships WHERE user_id=?', (user['id'],)).fetchone()[0],1)
        self.assertEqual(self.member_login(password='AnotherPassword9876!').headers['location'], '/dashboard')

    def test_multi_business_removes_membership_only_and_preserves_identity(self):
        self.owner.post('/companies/new', data={'_csrf':self.csrf(self.owner,'/team'), 'name':'Firma B'})
        self.owner.post('/company/switch',data={'_csrf':self.csrf(self.owner,'/settings'),'company_id':'1'})
        self.add_user(multi=True)
        self.owner.post('/company/switch',data={'_csrf':self.csrf(self.owner,'/settings'),'company_id':'2'})
        self.add_user(multi=True, company_id=2)
        with db_connect(self.db) as con:
            uid=con.execute("SELECT id FROM users WHERE email='helfer@example.ch'").fetchone()['id']
            self.assertEqual(con.execute('SELECT COUNT(*) FROM memberships WHERE user_id=?',(uid,)).fetchone()[0],2)
        self.owner.post('/company/switch',data={'_csrf':self.csrf(self.owner,'/settings'),'company_id':'1'})
        listing = self.owner.get('/team').text
        self.assertIn('Zugriff entfernen', listing)
        self.assertEqual(self.delete_user(uid).status_code, 303)
        with db_connect(self.db) as con:
            self.assertIsNotNone(con.execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone())
            remaining=con.execute('SELECT company_id FROM memberships WHERE user_id=?',(uid,)).fetchall()
            self.assertEqual([r['company_id'] for r in remaining], [2])
        self.add_user(password='NewPassword98765!',own=True)
        with db_connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM users WHERE email=?',('helfer@example.ch',)).fetchone()[0],1)
        self.assertEqual(self.member_login().headers['location'], '/dashboard')
        self.assertNotIn('Firma A', self.employee.get('/dashboard').text)

    def test_repeated_removal_and_self_removal_are_protected(self):
        self.assertEqual(self.delete_user(uid=1).status_code, 400)
        self.add_user()
        self.assertEqual(self.delete_user(uid=2).status_code, 303)
        self.assertEqual(self.delete_user(uid=2).status_code, 404)
        with db_connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM users WHERE is_superadmin=1').fetchone()[0],1)

    def test_pending_invitation_is_never_silently_purged(self):
        self.add_user(own=True)
        self.add_user(own=True)
        with db_connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM users WHERE email=?',('helfer@example.ch',)).fetchone()[0],1)
        self.assertIn('Ausstehende eigene Geschäftseinrichtungen',self.owner.get('/team').text)
        self.owner.post('/team/pending/2/cancel',data={'_csrf':self.csrf(self.owner,'/team')})
        with db_connect(self.db) as con:
            self.assertIsNone(con.execute('SELECT id FROM users WHERE id=2').fetchone())
        self.add_user(own=True)
        with db_connect(self.db) as con:
            self.assertIsNotNone(con.execute("SELECT id FROM users WHERE email='helfer@example.ch'").fetchone())


if __name__ == '__main__':
    unittest.main()
