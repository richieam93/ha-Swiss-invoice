"""Branding for Home Assistant: separate app logos per business and neutral login."""
import io
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.billing import hash_password
from app.db import db_connect, initialize
from app.main import create_app


def png(color):
    output = io.BytesIO()
    Image.new('RGBA', (100, 45), color=color).save(output, 'PNG')
    return output.getvalue()


class BrandingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name)
        self.client = TestClient(self.app, follow_redirects=False)
        self.csrf_from('/setup')
        self.client.post('/setup', data={
            '_csrf': self.csrf_from('/setup'), 'company_name': 'Geschäft A',
            'full_name': 'Besitzer', 'email': 'owner@example.ch',
            'password': 'SuperSicheresPasswort123!', 'password2': 'SuperSicheresPasswort123!'
        })

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def csrf_from(self, path='/dashboard', client=None):
        client = client or self.client
        page = client.get(path)
        self.assertEqual(page.status_code, 200)
        match = re.search(r'name="_csrf"\s+(?:type="hidden"\s+)?value="([^"]+)"', page.text)
        self.assertIsNotNone(match, page.text[:500])
        return match.group(1)

    def upload(self, logo_name, color, *, client=None):
        client = client or self.client
        r = client.post('/settings/branding',
                        data={'_csrf': self.csrf_from('/settings', client=client)},
                        files={logo_name: ('logo.png', png(color), 'image/png')})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers['location'], '/settings#hi-branding')

    def create_second_business(self):
        r = self.client.post('/companies/new', data={
            '_csrf': self.csrf_from(), 'name': 'Geschäft B'})
        self.assertEqual(r.status_code, 303)
        with db_connect(Path(self.temp.name) / 'rechnung.sqlite3') as con:
            row = con.execute('SELECT id FROM companies WHERE name=?', ('Geschäft B',)).fetchone()
            return row['id']

    def switch(self, cid):
        response = self.client.post('/company/switch', data={
            '_csrf': self.csrf_from(), 'company_id': cid})
        self.assertEqual(response.status_code, 303)

    def restricted_user(self, cid, email):
        with db_connect(Path(self.temp.name) / 'rechnung.sqlite3') as con:
            uid=con.execute('INSERT INTO users(email, full_name, password_hash, restricted_company_id) '
                            'VALUES(?,?,?,?)',
                            (email, 'Mitarbeiter', hash_password('SicheresTestPasswort123!'), cid)).lastrowid
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(?,?,'viewer')", (cid, uid))
            con.commit()

    def login_as(self, email):
        client = TestClient(self.app, follow_redirects=False)
        self.assertEqual(client.get('/login').status_code, 200)
        response=client.post('/login', data={
            '_csrf':self.csrf_from('/login',client=client), 'email':email,
            'password':'SicheresTestPasswort123!'})
        self.assertEqual(response.status_code,303)
        return client

    def test_company_logos_are_isolated_by_membership(self):
        # Original company A, then business B with distinct upload.
        self.upload('app_logo', (255, 25, 30, 255))
        logo_a = self.client.get('/media/app-logo')
        self.assertEqual(logo_a.status_code, 200)
        self.assertEqual(logo_a.headers['content-type'], 'image/png')
        b = self.create_second_business()
        self.switch(b)
        self.upload('app_logo', (10, 160, 230, 255))
        logo_b = self.client.get('/media/app-logo')
        self.assertEqual(logo_b.status_code, 200)
        self.assertNotEqual(logo_a.content, logo_b.content)
        self.restricted_user(1, 'a@example.ch')
        self.restricted_user(b, 'b@example.ch')
        with self.login_as('a@example.ch') as a_client, self.login_as('b@example.ch') as b_client:
            a_page = a_client.get('/dashboard').text
            b_page = b_client.get('/dashboard').text
            self.assertIn('Geschäft A', a_page)
            self.assertNotIn('Geschäft B', a_page)
            self.assertIn('Geschäft B', b_page)
            self.assertNotIn('Geschäft A', b_page)
            self.assertIn('/media/app-logo', a_page)
            self.assertIn('/media/app-logo', b_page)
            self.assertEqual(a_client.get('/media/app-logo').content, logo_a.content)
            self.assertEqual(b_client.get('/media/app-logo').content, logo_b.content)
            fail = b_client.post('/company/switch',data={
                '_csrf': self.csrf_from('/dashboard', client=b_client), 'company_id':'1'})
            self.assertEqual(fail.status_code, 403)
            self.assertEqual(b_client.get('/media/app-logo').content, logo_b.content)
        self.switch(1)
        self.assertEqual(self.client.get('/media/app-logo').content, logo_a.content)

    def test_general_login_logo_only_main_admin_and_before_login(self):
        # Before upload: generic logo; no organization-specific image.
        with TestClient(self.app, follow_redirects=False) as anonymous:
            login_page = anonymous.get('/login')
            self.assertEqual(login_page.status_code, 200)
            self.assertNotIn('media/app-logo', login_page.text)
            self.assertEqual(anonymous.get('/media/login-logo').status_code, 404)
        with TestClient(self.app, follow_redirects=False) as anonymous:
            self.assertEqual(anonymous.get('/media/app-logo').status_code, 303)
        self.upload('login_logo', (80, 210, 40, 255))
        with TestClient(self.app, follow_redirects=False) as anonymous:
            page = anonymous.get('/login')
            self.assertIn('/media/login-logo', page.text)
            logo = anonymous.get('/media/login-logo')
            self.assertEqual(logo.status_code, 200)
            self.assertEqual(logo.headers['content-type'], 'image/png')

        self.restricted_user(1, 'employee@example.ch')
        with self.login_as('employee@example.ch') as user:
            self.assertEqual(user.get('/settings').status_code, 403)
            attack = user.post('/settings/branding',data={'_csrf':self.csrf_from('/dashboard',client=user)},
                               files={'login_logo':('evil.png',png('red'),'image/png')})
            self.assertEqual(attack.status_code,403)
        self.assertEqual(self.client.get('/media/login-logo').content, logo.content)

    def test_scoped_admin_cannot_change_public_logo(self):
        from app.db import db_connect
        with db_connect(Path(self.temp.name) / 'rechnung.sqlite3') as con:
            uid=con.execute('INSERT INTO users(email,full_name,password_hash,restricted_company_id) VALUES(?,?,?,?)',
                            ('admin2@example.ch','Leitung',hash_password('SicheresTestPasswort123!'),1)).lastrowid
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(?,?,'admin')",(1,uid))
            con.commit()
        with self.login_as('admin2@example.ch') as scoped:
            page = scoped.get('/settings').text
            self.assertIn('Logo dieses Geschäfts', page)
            self.assertNotIn('Allgemeines Anmeldelogo', page)
            r = scoped.post('/settings/branding', data={'_csrf':self.csrf_from('/settings',client=scoped)},
                            files={'login_logo':('some.png',png('purple'),'image/png')})
            self.assertEqual(r.status_code,403)
            r = scoped.post('/settings/branding', data={'_csrf':self.csrf_from('/settings',client=scoped)},
                            files={'app_logo':('own.png',png('purple'),'image/png')})
            self.assertEqual(r.status_code,303)
            self.assertEqual(scoped.get('/media/app-logo').status_code,200)
            self.assertEqual(scoped.get('/media/login-logo').status_code,404)

    def test_invalid_and_oversize_images_leave_previous_logo(self):
        self.upload('app_logo', 'blue')
        before = self.client.get('/media/app-logo').content
        for file in (('hack.svg',b'<svg><script/></svg>','image/svg+xml'),
                     ('huge.png',b'x'*(5*1024*1024+1),'image/png')):
            r = self.client.post('/settings/branding',
                     data={'_csrf': self.csrf_from('/settings')},
                     files={'app_logo':file})
            self.assertEqual(r.status_code,303)
            self.assertEqual(self.client.get('/media/app-logo').content,before)
            self.assertIn('notice error',self.client.get('/settings').text)

    def test_remove_custom_logo_returns_to_invoice_logo(self):
        self.upload('app_logo', 'red')
        r = self.client.post('/settings/branding', data={
            '_csrf':self.csrf_from('/settings'), 'remove_app_logo':'1'})
        self.assertEqual(r.status_code,303)
        self.assertEqual(self.client.get('/media/app-logo').status_code,404)
        # Existing invoice logo is never deleted or replaced by branding upload.
        settings=self.client.get('/settings')
        self.assertIn('Firmenlogo',settings.text)

    def test_invoice_logo_fallback_and_other_company_path_block(self):
        # Pre-existing PDF logo remains valid and can act as the app fallback.
        a_path = Path(self.temp.name) / 'uploads' / '1'
        a_path.mkdir(parents=True, exist_ok=True)
        logo = a_path / 'invoice-logo.jpg'
        from PIL import Image
        Image.new('RGB', (90, 35), color='yellow').save(logo, 'JPEG')
        with db_connect(Path(self.temp.name) / 'rechnung.sqlite3') as con:
            con.execute('UPDATE companies SET logo_path=?,app_logo_path=? WHERE id=1',
                        ('uploads/1/invoice-logo.jpg', ''))
            con.commit()
        result = self.client.get('/media/app-logo')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content, logo.read_bytes())
        # Even a bad DB reference cannot serve another company's private logo.
        b = self.create_second_business()
        self.switch(b)
        with db_connect(Path(self.temp.name) / 'rechnung.sqlite3') as con:
            con.execute('UPDATE companies SET logo_path=?,app_logo_path=? WHERE id=?',
                        ('', 'uploads/1/invoice-logo.jpg', b))
            con.commit()
        self.assertEqual(self.client.get('/media/app-logo').status_code, 404)

    def test_general_login_logo_removable(self):
        self.upload('login_logo', 'green')
        self.assertEqual(self.client.get('/media/login-logo').status_code, 200)
        r = self.client.post('/settings/branding', data={
            '_csrf': self.csrf_from('/settings'), 'remove_login_logo':'1'})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.client.get('/media/login-logo').status_code, 404)

    def test_home_assistant_ingress_paths_for_branding(self):
        import asyncio
        import os
        import httpx
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {'SWISS_INVOICE_INGRESS':'1'}):
                app=create_app(temp)
                prefix='/api/hassio_ingress/TestBrand_ABC.99'
                async def check():
                    transport=httpx.ASGITransport(app=app, client=('172.30.32.2',5000))
                    async with httpx.AsyncClient(transport=transport, base_url='http://local',
                            headers={'X-Ingress-Path':prefix}, follow_redirects=False) as c:
                        page=await c.get('/setup')
                        self.assertEqual(page.status_code,200)
                        csrf=re.search(r'name="_csrf"\s+value="([^"]+)"',page.text).group(1)
                        r=await c.post('/setup',data={
                            '_csrf':csrf, 'company_name':'Ingress AG', 'full_name':'Owner',
                            'email':'owner@ingress.ch', 'password':'SecurePassWord111!',
                            'password2':'SecurePassWord111!'})
                        self.assertEqual(r.status_code,303)
                        settings=await c.get('/settings')
                        self.assertEqual(settings.status_code,200)
                        token=re.search(r'name="_csrf"\s+value="([^"]+)"',settings.text).group(1)
                        uploaded=await c.post('/settings/branding',data={'_csrf':token},
                            files={'app_logo':('company.png',png('blue'),'image/png')})
                        self.assertEqual(uploaded.headers['location'],prefix+'/settings#hi-branding')
                        dash=await c.get('/dashboard')
                        self.assertIn(f'src="{prefix}/media/app-logo"',dash.text)
                        image=await c.get('/media/app-logo')
                        self.assertEqual(image.status_code,200)
                        self.assertEqual(image.headers['content-type'],'image/png')
                asyncio.run(check())

    def test_migration_adds_branding_to_existing_install(self):
        path=Path(self.temp.name) / 'rechnung.sqlite3'
        with db_connect(path) as con:
            con.execute('ALTER TABLE companies DROP COLUMN app_logo_path')
            con.execute('PRAGMA user_version=11')
            con.commit()
        initialize(path)
        with db_connect(path) as con:
            self.assertIn('app_logo_path',{x['name'] for x in con.execute('PRAGMA table_info(companies)')})
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],16)
            self.assertEqual(con.execute('SELECT name FROM companies WHERE id=1').fetchone()['name'],'Geschäft A')

if __name__ == '__main__':
    unittest.main()
