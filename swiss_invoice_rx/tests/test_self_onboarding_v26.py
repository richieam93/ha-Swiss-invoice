"""Self-serve tenant onboarding: no existing tenant access before or after creation."""
import io
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient

from app.db import db_connect, initialize
from app.main import create_app


def png_bytes():
    mem=io.BytesIO()
    Image.new('RGB',(210,100),'#416bee').save(mem,'PNG')
    return mem.getvalue()


class NewBusinessWizardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app=create_app(self.temp.name)
        self.owner=TestClient(self.app, follow_redirects=False)
        self.invited=TestClient(self.app, follow_redirects=False)
        self.addCleanup(self.owner.close)
        self.addCleanup(self.invited.close)
        self.db=Path(self.temp.name)/'rechnung.sqlite3'
        r=self.owner.get('/setup')
        self.assertEqual(r.status_code,200)
        self.owner.post('/setup', data={'_csrf':self.csrf(self.owner,'/setup'),
                          'company_name':'Firma Alpha AG','full_name':'Eigentuemer',
                          'email':'owner@example.ch','password':'LongVerySecurePass1!',
                          'password2':'LongVerySecurePass1!'})

    @staticmethod
    def csrf(client, path):
        page=client.get(path)
        assert page.status_code == 200, (path, page.status_code)
        m=re.search(r'name="_csrf"[^>]*value="([a-f0-9]+)"',page.text)
        assert m, (path,page.text[:300])
        return m.group(1)

    def invite(self,email='tenant@example.ch'):
        result=self.owner.post('/team',data={'_csrf':self.csrf(self.owner,'/team'),
                       'create_own_company':'1','email':email,'full_name':'Neuer Benutzer',
                       'password':'AReallySecurePassword123!'})
        self.assertEqual(result.status_code,303)
        with db_connect(self.db) as con:
            u=con.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
            self.assertIsNotNone(u)
            self.assertEqual(u['can_create_company'],1)
            self.assertIsNone(u['restricted_company_id'])
            self.assertEqual(con.execute('SELECT COUNT(*) FROM memberships WHERE user_id=?',(u['id'],)).fetchone()[0],0)
            self.assertEqual(u['invited_from_company_id'],1)
        return u['id']

    def login_invited(self,email='tenant@example.ch'):
        result=self.invited.post('/login',data={'_csrf':self.csrf(self.invited,'/login'),
                  'email':email,'password':'AReallySecurePassword123!'})
        self.assertEqual(result.status_code,303)
        self.assertEqual(result.headers.get('location'),'/onboarding')
        return self.csrf(self.invited,'/onboarding')

    def fields(self, **update):
        data={'_csrf':self.csrf(self.invited,'/onboarding'),'business_type':'private',
              'name':'Meine Privatrechnungen','street':'Seestrasse','building':'22',
              'zip':'4001','city':'Basel','country':'CH','email':'tenant@example.ch',
              'currency':'CHF','qr_reference_type':'AUTO','iban':'',
              'default_due_days':'14','password_new':'TheNewPrivatePassword123!',
              'password_confirm':'TheNewPrivatePassword123!'}
        data.update(update)
        return data

    def onboard(self,**update):
        return self.invited.post('/onboarding',data=self.fields(**update))

    def test_unassigned_account_sees_only_wizard(self):
        self.invite();self.login_invited()
        page=self.invited.get('/onboarding')
        self.assertIn('Privatperson',page.text)
        self.assertIn('Einzelunternehmen',page.text)
        self.assertIn('Logo hochladen',page.text)
        self.assertNotIn('Firma Alpha AG',page.text)
        for url in ('/dashboard','/customers','/settings','/invoices','/team','/backup','/companies/new'):
            resp=self.invited.get(url)
            self.assertIn(resp.status_code,(303,403),url)
            if resp.status_code==303:self.assertEqual(resp.headers['location'],'/onboarding',url)
        resp=self.invited.post('/company/switch',data={'_csrf':self.csrf(self.invited,'/onboarding'),'company_id':'1'})
        self.assertEqual(resp.status_code,403)
        self.assertEqual(self.invited.get('/media/app-logo').headers['location'],'/onboarding')

    def test_new_secret_password_is_required(self):
        self.invite();self.login_invited()
        for values in ({'password_new':'a','password_confirm':'a'},
                       {'password_new':'AReallySecurePassword123!','password_confirm':'AReallySecurePassword123!'},
                       {'password_new':'AnotherNewPassword123!','password_confirm':'NotTheSamePassword123!'}):
            resp=self.onboard(**values)
            self.assertEqual(resp.headers['location'],'/onboarding')
        with db_connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM companies').fetchone()[0],1)

    def test_private_onboarding_creates_one_isolated_tenant_and_admin(self):
        self.invite();self.login_invited()
        result=self.onboard()
        self.assertEqual(result.status_code,303)
        self.assertEqual(result.headers['location'],'/dashboard')
        with db_connect(self.db) as con:
            rows=con.execute('SELECT id,name,business_type,tax_registered,default_tax,default_due_days FROM companies ORDER BY id').fetchall()
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[1]['business_type'],'private')
            self.assertEqual(rows[1]['tax_registered'],0)
            self.assertEqual(rows[1]['default_tax'],'0')
            self.assertEqual(rows[1]['default_due_days'],14)
            user=con.execute("SELECT * FROM users WHERE email='tenant@example.ch'").fetchone()
            self.assertEqual(user['can_create_company'],0)
            self.assertEqual(user['restricted_company_id'],2)
            memberships=con.execute('SELECT company_id,role FROM memberships WHERE user_id=?',(user['id'],)).fetchall()
            self.assertEqual([(r['company_id'],r['role']) for r in memberships],[(2,'admin')])
        self.assertEqual(self.invited.get('/settings').status_code,200)
        self.assertEqual(self.invited.get('/team').status_code,200)
        self.assertNotIn('Firma Alpha AG',self.invited.get('/team').text)
        self.assertEqual(self.invited.get('/companies/new').status_code,403)
        self.assertEqual(self.invited.post('/company/switch',data={'_csrf':self.csrf(self.invited,'/settings'),'company_id':'1'}).status_code,403)
        self.assertEqual(self.invited.get('/onboarding').headers['location'],'/dashboard')
        payload={'_csrf':self.csrf(self.invited,'/settings'),'business_type':'sole',
                 'name':'Weiteres Unternehmen','street':'Strasse','zip':'3000','city':'Bern'}
        self.assertEqual(self.invited.post('/onboarding',data=payload).status_code,403)

    def test_start_password_rejected_after_own_company_creation(self):
        self.invite();self.login_invited()
        self.onboard()
        self.invited.post('/logout',data={'_csrf':self.csrf(self.invited,'/dashboard')})
        rejected=self.invited.post('/login',data={'_csrf':self.csrf(self.invited,'/login'),
                     'email':'tenant@example.ch','password':'AReallySecurePassword123!'})
        self.assertEqual(rejected.headers['location'],'/login')
        accepted=self.invited.post('/login',data={'_csrf':self.csrf(self.invited,'/login'),
                     'email':'tenant@example.ch','password':'TheNewPrivatePassword123!'})
        self.assertEqual(accepted.headers['location'],'/dashboard')

    def test_legal_form_and_tax_registration_are_separate(self):
        self.invite();self.login_invited()
        result=self.onboard(business_type='sole',tax_registered='1',default_tax='8.1',
                            uid='CHE-123.456.789 MWST')
        self.assertEqual(result.status_code,303)
        with db_connect(self.db) as con:
            business=con.execute('SELECT business_type,tax_registered,default_tax,uid FROM companies WHERE id=2').fetchone()
            self.assertEqual((business['business_type'],business['tax_registered'],business['default_tax']),('sole',1,'8.1'))
            self.assertEqual(business['uid'],'CHE-123.456.789 MWST')
        # Later allow changing the type and tax status independently.
        payload={'_csrf':self.csrf(self.invited,'/settings'),'name':'Meine Firma GmbH','business_type':'company',
                 'street':'Seestrasse','building':'22','zip':'4001','city':'Basel','country':'CH',
                 'currency':'CHF','iban':'','default_tax':'2.6','default_due_days':'30',
                 'number_prefix':'RE','quote_prefix':'OF','credit_prefix':'GS',
                 'number_padding':'5','next_invoice':'1','next_quote':'1','next_credit':'1'}
        result=self.invited.post('/settings',data=payload)
        self.assertEqual(result.status_code,303)
        with db_connect(self.db) as con:
            b=con.execute('SELECT business_type,tax_registered,default_tax FROM companies WHERE id=2').fetchone()
            self.assertEqual((b['business_type'],b['tax_registered'],b['default_tax']),('company',0,'0'))
        payload.update({'_csrf':self.csrf(self.invited,'/settings'),'business_type':'sole','tax_registered':'1','default_tax':'2.6'})
        self.invited.post('/settings',data=payload)
        with db_connect(self.db) as con:
            b=con.execute('SELECT business_type,tax_registered,default_tax FROM companies WHERE id=2').fetchone()
            self.assertEqual((b['business_type'],b['tax_registered'],b['default_tax']),('sole',1,'2.6'))

    def test_private_cannot_set_vat_and_invalid_fields_do_not_create_tenant(self):
        self.invite();self.login_invited()
        result=self.onboard(tax_registered='1')
        self.assertEqual(result.status_code,303)
        self.assertEqual(result.headers['location'],'/onboarding')
        result=self.onboard(zip='',tax_registered='')
        self.assertEqual(result.status_code,303)
        self.assertEqual(result.headers['location'],'/onboarding')
        result=self.onboard(iban='CH0000000000000000000')
        self.assertEqual(result.status_code,303)
        result=self.onboard(iban='CH9300762011623852957',qr_reference_type='QRR')
        self.assertEqual(result.status_code,303)
        with db_connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM companies').fetchone()[0],1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM memberships').fetchone()[0],1)

    def test_logo_and_qr_configuration_in_wizard(self):
        self.invite();self.login_invited()
        values=self.fields(business_type='company',name='Beta GmbH',iban='CH9300762011623852957',
                           qr_reference_type='AUTO',currency='CHF')
        result=self.invited.post('/onboarding',data=values,files={'app_logo':('branding.png',png_bytes(),'image/png')})
        self.assertEqual(result.status_code,303)
        with db_connect(self.db) as con:
            business=con.execute('SELECT * FROM companies WHERE id=2').fetchone()
            self.assertEqual(business['iban'],'CH9300762011623852957')
            self.assertTrue(business['app_logo_path'])
            self.assertTrue((Path(self.temp.name)/business['app_logo_path']).is_file())
        logo=self.invited.get('/media/app-logo')
        self.assertEqual(logo.status_code,200)
        self.assertEqual(logo.content[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(self.invited.get('/qr-test').status_code,200)

    def test_inviter_cannot_see_new_tenant_or_logo(self):
        self.invite();self.login_invited()
        self.onboard(business_type='company',name='Geheime Beta AG')
        owner_dashboard=self.owner.get('/dashboard').text
        self.assertNotIn('Geheime Beta AG',owner_dashboard)
        self.assertNotIn('Geheime Beta AG',self.owner.get('/team').text)
        self.assertEqual(self.owner.post('/company/switch',data={'_csrf':self.csrf(self.owner,'/team'),'company_id':'2'}).status_code,403)
        # Core company separation is enforced even for the original inviter.
        self.assertEqual(self.invited.post('/company/switch',data={'_csrf':self.csrf(self.invited,'/settings'),'company_id':'1'}).status_code,403)

    def test_existing_email_cannot_be_invited_to_new_tenant(self):
        r=self.owner.post('/team',data={'_csrf':self.csrf(self.owner,'/team'),
                 'create_own_company':'1','email':'owner@example.ch','password':'AnotherStrongPassword123!'})
        self.assertEqual(r.status_code,303)
        with db_connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)

    def test_cancel_pending_is_scoped_and_blocks_login(self):
        member_id=self.invite()
        r=self.owner.post(f'/team/pending/{member_id}/cancel',data={'_csrf':self.csrf(self.owner,'/team')})
        self.assertEqual(r.status_code,303)
        with db_connect(self.db) as con:
            self.assertIsNone(con.execute('SELECT id FROM users WHERE id=?',(member_id,)).fetchone())
        result=self.invited.post('/login',data={'_csrf':self.csrf(self.invited,'/login'),
                           'email':'tenant@example.ch','password':'AReallySecurePassword123!'})
        self.assertEqual(result.headers['location'],'/login')

    def test_invitation_cannot_be_managed_by_other_business(self):
        member_id=self.invite()
        self.owner.post('/companies/new',data={'_csrf':self.csrf(self.owner,'/team'),'name':'Andere Firma'})
        result=self.owner.post(f'/team/pending/{member_id}/cancel',
                               data={'_csrf':self.csrf(self.owner,'/team')})
        self.assertEqual(result.status_code,404)
        with db_connect(self.db) as con:
            self.assertIsNotNone(con.execute('SELECT id FROM users WHERE id=?',(member_id,)).fetchone())

    def test_private_registration_change_needs_correct_company_type(self):
        self.invite();self.login_invited();self.onboard()
        fields={'_csrf':self.csrf(self.invited,'/settings'),'name':'Meine Privatrechnungen',
                'business_type':'private','tax_registered':'1','default_tax':'8.1',
                'street':'Seestrasse','building':'22','zip':'4001','city':'Basel','country':'CH',
                'currency':'CHF','default_due_days':'14'}
        result=self.invited.post('/settings',data=fields)
        self.assertEqual(result.status_code,303)
        with db_connect(self.db) as con:
            r=con.execute('SELECT business_type,tax_registered FROM companies WHERE id=2').fetchone()
            self.assertEqual(r['business_type'],'private')
            self.assertEqual(r['tax_registered'],0)

    def test_non_admin_cannot_invite_separate_business_users(self):
        # Viewer role cannot invoke the invitation endpoint.
        from app.billing import hash_password
        with db_connect(self.db) as con:
            con.execute('INSERT INTO users(email,full_name,password_hash,restricted_company_id) VALUES(?,?,?,?)',
                        ('viewer@example.ch','Viewer',hash_password('ViewerPassword12345!'),1))
            vid=con.execute('SELECT last_insert_rowid()').fetchone()[0]
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(1,?,'viewer')",(vid,))
            con.commit()
        viewer=TestClient(self.app,follow_redirects=False)
        try:
            csrf=self.csrf(viewer,'/login')
            r=viewer.post('/login',data={'_csrf':csrf,'email':'viewer@example.ch','password':'ViewerPassword12345!'})
            self.assertEqual(r.status_code,303)
            csrf=self.csrf(viewer,'/dashboard')
            r=viewer.post('/team',data={'_csrf':csrf,'create_own_company':'1',
                'email':'bad_invite@example.ch','password':'AnotherLongPassword12345!'})
            self.assertEqual(r.status_code,403)
            with db_connect(self.db) as con:
                self.assertIsNone(con.execute('SELECT id FROM users WHERE email=?',('bad_invite@example.ch',)).fetchone())
        finally:
            viewer.close()

    def test_pending_not_in_existing_business_member_list(self):
        self.invite()
        result=self.owner.get('/team').text
        self.assertIn('Ausstehende eigene Geschäftseinrichtungen',result)
        self.assertIn('tenant@example.ch',result)
        self.assertNotIn('tenant@example.ch</strong></td>',result)


class PreviousDBMigrationTest(unittest.TestCase):
    def test_existing_company_users_and_data_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=create_app(tmp)
            path=Path(tmp)/'rechnung.sqlite3'
            with db_connect(path) as con:
                con.execute("INSERT INTO users(email,full_name,password_hash) VALUES('preserved@example.ch','A','hash')")
                con.execute("INSERT INTO companies(name) VALUES('Unveraendert GmbH')")
                con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(1,1,'viewer')")
                con.commit()
                con.execute('PRAGMA user_version=13')
            initialize(path)
            with db_connect(path) as con:
                self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0],14)
                user=con.execute('SELECT * FROM users WHERE id=1').fetchone()
                self.assertEqual(user['can_create_company'],0)
                self.assertIsNone(user['restricted_company_id'])
                company=con.execute('SELECT * FROM companies WHERE id=1').fetchone()
                self.assertEqual(company['business_type'],'company')
                self.assertEqual(company['name'],'Unveraendert GmbH')
                self.assertEqual(con.execute('SELECT role FROM memberships WHERE user_id=1').fetchone()[0],'viewer')


if __name__ == '__main__': unittest.main()
