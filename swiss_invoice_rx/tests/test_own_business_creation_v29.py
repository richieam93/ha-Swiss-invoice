"""Regression for the browser form and an isolated first-login company setup.

Earlier the 'own business' checkbox was *outside* the HTML form, so real
browser submissions silently created memberships in the inviter's company.
"""
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient
from app.db import db_connect
from app.main import create_app


class FormTree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.open_form = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'form':
            self.open_form = {'action': attrs.get('action'), 'controls': {}}
            self.forms.append(self.open_form)
        elif self.open_form is not None and tag in ('input', 'select', 'textarea'):
            name = attrs.get('name')
            if name:
                self.open_form['controls'][name] = attrs.get('value')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.open_form = None


class OwnBusinessBrowserFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app=create_app(self.tmp.name)
        self.db=Path(self.tmp.name)/'rechnung.sqlite3'
        self.owner=TestClient(self.app, follow_redirects=False)
        self.invitee=TestClient(self.app, follow_redirects=False)
        self.addCleanup(self.owner.close)
        self.addCleanup(self.invitee.close)
        r=self.owner.post('/setup',data={
            '_csrf':self.csrf(self.owner,'/setup'),
            'company_name':'Stammgeschäft Nord','email':'boss@test.ch',
            'full_name':'Hauptadmin','password':'StrongPassword12345!',
            'password2':'StrongPassword12345!'
        })
        self.assertEqual(r.headers['location'],'/settings')

    def csrf(self,client,path):
        r=client.get(path)
        self.assertEqual(r.status_code,200,(path,r.status_code))
        match=re.search(r'<input[^>]*name="_csrf"[^>]*value="([a-f0-9]+)"',r.text)
        self.assertIsNotNone(match)
        return match.group(1)

    def invite(self,email='second@test.ch', own=True):
        data={'_csrf':self.csrf(self.owner,'/team'),'email':email,
              'full_name':'Zweite Person','password':'DifferentVeryStrong12345!'}
        if own:
            data['create_own_company']='1'
        else:
            data['company_id']='1'
            data['role']='editor'
        r=self.owner.post('/team',data=data)
        self.assertEqual(r.status_code,303)
        return r

    def login_invited(self,email='second@test.ch'):
        return self.invitee.post('/login',data={
            '_csrf':self.csrf(self.invitee,'/login'),
            'email':email,'password':'DifferentVeryStrong12345!'
        })

    def setup_own_business(self):
        return self.invitee.post('/onboarding',data={
            '_csrf':self.csrf(self.invitee,'/onboarding'),
            'business_type':'sole','name':'Meine eigene Firma',
            'street':'Musterstrasse','building':'9','zip':'8000','city':'Zuerich',
            'country':'CH','email':'second@test.ch','iban':'',
            'currency':'CHF','default_due_days':'30',
            'tax_registered':'1','default_tax':'8.1','qr_reference_type':'AUTO',
            'uid':'CHE-123.456.789 MWST',
            'password_new':'BrandNewDifferent12345!',
            'password_confirm':'BrandNewDifferent12345!'
        })

    def test_checkbox_is_inside_the_actual_post_form(self):
        response=self.owner.get('/team')
        self.assertEqual(response.status_code,200)
        tree=FormTree()
        tree.feed(response.text)
        forms=[x for x in tree.forms if x['action']=='/team']
        self.assertEqual(len(forms),1)
        self.assertIn('create_own_company',forms[0]['controls'])
        self.assertIn('email',forms[0]['controls'])
        self.assertIn('password',forms[0]['controls'])
        self.assertIn('_csrf',forms[0]['controls'])

    def test_first_login_isolated_and_all_company_admin_tools_available(self):
        self.invite()
        with db_connect(self.db) as con:
            u=con.execute('SELECT * FROM users WHERE email=?',('second@test.ch',)).fetchone()
            self.assertEqual(u['can_create_company'],1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM memberships WHERE user_id=?',(u['id'],)).fetchone()[0],0)
        self.assertEqual(self.login_invited().headers['location'],'/onboarding')
        self.assertIn('Dein eigenes Geschäft einrichten', self.invitee.get('/onboarding').text)
        self.assertNotIn('Stammgeschäft Nord', self.invitee.get('/onboarding').text)
        for path in ('/dashboard','/customers','/invoices','/team','/templates','/systemcheck','/backup'):
            response=self.invitee.get(path)
            self.assertEqual(response.status_code,303,(path,response.status_code))
            self.assertEqual(response.headers['location'],'/onboarding',path)
        saved=self.setup_own_business()
        self.assertEqual(saved.status_code,303)
        self.assertEqual(saved.headers['location'],'/dashboard')
        with db_connect(self.db) as con:
            u=con.execute('SELECT * FROM users WHERE email=?',('second@test.ch',)).fetchone()
            companies=con.execute('SELECT id,name,tax_registered FROM companies ORDER BY id').fetchall()
            self.assertEqual([x['name'] for x in companies],['Stammgeschäft Nord','Meine eigene Firma'])
            self.assertEqual(companies[1]['tax_registered'],1)
            self.assertEqual(u['is_superadmin'],0)
            self.assertEqual(u['restricted_company_id'],2)
            roles=con.execute('SELECT company_id,role FROM memberships WHERE user_id=?',(u['id'],)).fetchall()
            self.assertEqual([(r['company_id'],r['role']) for r in roles],[(2,'admin')])
        # All of these are the same company-scoped admin functions as the inviter.
        for path in ('/dashboard','/settings','/team','/templates',
                     '/templates/designer','/qr-test','/customers','/items',
                     '/invoices','/reports','/bank','/backup','/systemcheck'):
            result=self.invitee.get(path)
            self.assertEqual(result.status_code,200,(path,result.status_code,result.text[:100]))
            self.assertNotIn('Stammgeschäft Nord',result.text)
        self.assertEqual(self.invitee.get('/companies/new').status_code,403)
        self.assertEqual(self.invitee.post('/company/switch',data={
            '_csrf':self.csrf(self.invitee,'/settings'),'company_id':'1'
        }).status_code,403)
        staff=self.invitee.post('/team',data={
            '_csrf':self.csrf(self.invitee,'/team'),
            'email':'newstaff@test.ch','full_name':'Team in der neuen Firma',
            'password':'ExtraSecurePassword12345!','role':'editor','company_id':'2'
        })
        self.assertEqual(staff.headers['location'],'/team')
        with db_connect(self.db) as con:
            member=con.execute('''SELECT m.company_id,m.role FROM memberships m
                JOIN users u ON u.id=m.user_id WHERE u.email='newstaff@test.ch' ''').fetchone()
            self.assertEqual((member['company_id'],member['role']),(2,'editor'))
        self.assertNotIn('newstaff@test.ch',self.owner.get('/team').text)
        self.assertEqual(self.owner.get('/onboarding').headers['location'],'/dashboard')
        self.assertNotIn('Meine eigene Firma',self.owner.get('/team').text)
        with db_connect(self.db) as con:
            # The original owner does not automatically become a tenant member.
            self.assertEqual(con.execute('SELECT COUNT(*) FROM memberships WHERE company_id=2 AND user_id=1').fetchone()[0],0)

    def test_convert_accidentally_assigned_member_to_own_business(self):
        self.invite(own=False)
        self.assertEqual(self.login_invited().headers['location'],'/dashboard')
        # Legacy business records remain with their original tenant during conversion.
        with db_connect(self.db) as con:
            con.execute("INSERT INTO customers(company_id,number,name) VALUES(1,'K-001','Bestehender Kunde')")
            con.commit()
        page=self.owner.get('/team').text
        self.assertIn('/team/2/own-business',page)
        response=self.owner.post('/team/2/own-business', data={
            '_csrf':self.csrf(self.owner,'/team')})
        self.assertEqual(response.headers['location'],'/team')
        with db_connect(self.db) as con:
            u=con.execute('SELECT * FROM users WHERE id=2').fetchone()
            self.assertEqual(u['can_create_company'],1)
            self.assertIsNone(u['restricted_company_id'])
            self.assertEqual(con.execute('SELECT COUNT(*) FROM memberships WHERE user_id=2').fetchone()[0],0)
        # Previously active login is immediately restricted, not only future logins.
        response=self.invitee.get('/dashboard')
        self.assertEqual(response.headers['location'],'/onboarding')
        self.assertEqual(self.setup_own_business().headers['location'],'/dashboard')
        self.assertNotIn('Stammgeschäft Nord', self.invitee.get('/dashboard').text)
        self.assertNotIn('Bestehender Kunde',self.invitee.get('/customers').text)
        self.assertIn('Bestehender Kunde',self.owner.get('/customers').text)
        with db_connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM customers WHERE company_id=1').fetchone()[0],1)

    def test_cannot_convert_installation_admin_or_one_with_many_companies(self):
        self.invite(own=False)
        response=self.owner.post('/team/1/own-business',data={
            '_csrf':self.csrf(self.owner,'/team')})
        self.assertEqual(response.status_code,403)
        with db_connect(self.db) as con:
            con.execute('INSERT INTO companies(name) VALUES(?)',('Extra business',))
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(2,2,'viewer')")
            con.commit()
        response=self.owner.post('/team/2/own-business',data={
            '_csrf':self.csrf(self.owner,'/team')})
        self.assertEqual(response.status_code,409)
        with db_connect(self.db) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM memberships WHERE user_id=2').fetchone()[0],2)

    def test_no_cross_business_conversion(self):
        self.invite(own=False)
        self.assertEqual(self.login_invited().headers['location'],'/dashboard')
        r=self.owner.post('/team/999/own-business',data={
            '_csrf':self.csrf(self.owner,'/team')})
        self.assertEqual(r.status_code,404)
        self.assertEqual(self.invitee.post('/team/1/own-business',data={
            '_csrf':self.csrf(self.invitee,'/dashboard')}).status_code,403)


if __name__ == '__main__':
    unittest.main()
