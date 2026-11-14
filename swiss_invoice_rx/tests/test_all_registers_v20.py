"""HelveticInvoice 2.0: regression and cross-register workflow tests."""
import csv
import io
import re
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from fastapi.testclient import TestClient
from app.db import transaction
from app.main import create_app
from app.billing import hash_password


class AllRegisters20Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.client=TestClient(create_app(self.root))
        self.db=self.root/'rechnung.sqlite3'
        token=re.search(r'name="_csrf" value="([0-9a-f]+)"', self.client.get('/setup').text).group(1)
        r=self.client.post('/setup',data={'_csrf':token,'company_name':'Alpenland AG',
            'email':'admin@alpen.ch','full_name':'Admin','password':'SehrSicher!2026Test',
            'password2':'SehrSicher!2026Test'})
        self.assertEqual(r.status_code,200)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def csrf(self):
        page=self.client.get('/dashboard')
        self.assertEqual(page.status_code,200)
        return re.search(r'name="_csrf" value="([0-9a-f]+)"',page.text).group(1)

    def customer(self,name='Alpha AG',group='VIP',city='Bern',cid=1,active=1):
        with transaction(self.db,True) as con:
            cur=con.execute('INSERT INTO customers(company_id,number,name,group_name,city,active,payment_days) VALUES(?,?,?,?,?,?,?)',
                (cid,f'K{cid}-{con.execute("SELECT count(*) FROM customers").fetchone()[0]}',name,group,city,active,14))
            return cur.lastrowid

    def item(self,name='Kabel',category='Material',kind='product',active=1,cid=1):
        with transaction(self.db,True) as con:
            cur=con.execute('INSERT INTO items(company_id,sku,name,category,kind,active,price,track_stock,reorder_point,stock) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (cid,f'ART-{con.execute("SELECT count(*) FROM items").fetchone()[0]}',name,category,kind,active,'35.00',1,5,'3'))
            return cur.lastrowid

    def invoice(self,number='RE-X',when=None,due=None,cid=1,customer=None,kind='invoice',total='200',status='sent',currency='CHF'):
        when=when or date.today().isoformat()
        due=due or (date.today()+timedelta(days=14)).isoformat()
        with transaction(self.db,True) as con:
            cur=con.execute('''INSERT INTO invoices(company_id,number,kind,customer_id,invoice_date,due_date,total,currency,status,paid_total)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',(cid,number,kind,customer,when,due,total,currency,status,'0'))
            return cur.lastrowid

    def company2(self):
        with transaction(self.db,True) as con:
            con.execute("INSERT INTO companies(name) VALUES('Zweitfirma')")
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(2,1,'admin')")
        r=self.client.post('/company/switch',data={'_csrf':self.csrf(),'company_id':'2'})
        self.assertEqual(r.status_code,200)

    def test_customer_filter_archiving_restore_and_reinvoice(self):
        a=self.customer('Alpina AG','VIP')
        b=self.customer('Metall GmbH','B2B',active=0)
        self.assertIn('Alpina AG',self.client.get('/customers?group=VIP').text)
        self.assertNotIn('Metall GmbH',self.client.get('/customers?group=VIP').text)
        self.assertIn('Metall GmbH',self.client.get('/customers?archived=1').text)
        r=self.client.post(f'/customers/{b}/restore',data={'_csrf':self.csrf()})
        self.assertEqual(r.status_code,200)
        self.assertIn('Metall GmbH',self.client.get('/customers').text)
        self.assertIn(f'/invoices/new?customer_id={a}',self.client.get('/customers').text)
        editor=self.client.get(f'/invoices/new?customer_id={a}')
        self.assertEqual(editor.status_code,200)
        self.assertIn('value="'+str(a)+'" selected',editor.text)

    def test_customer_list_csv_and_literal_wildcard(self):
        self.customer('Name_100','VIP');self.customer('Normal GmbH','B2B')
        self.assertIn('Name_100',self.client.get('/customers',params={'q':'_100'}).text)
        self.assertIn('0 Treffer',self.client.get('/customers',params={'q':'%25'}).text)
        r=self.client.get('/customers/list.csv?group=VIP')
        self.assertEqual(r.status_code,200)
        data=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(len(data),2)
        self.assertEqual(data[1][1],'Name_100')

    def test_customer_50_row_pagination(self):
        for n in range(52):self.customer(f'Testkunde {n:02d}',group='')
        first=self.client.get('/customers?page=1').text
        second=self.client.get('/customers?page=2').text
        self.assertIn('Seite 1 von 2',first)
        self.assertIn('Seite 2 von 2',second)
        self.assertIn('Testkunde 50',second)
        self.assertNotIn('Testkunde 50',first)

    def test_customer_restore_foreign_company_not_allowed(self):
        a=self.customer(active=0)
        self.company2()
        self.assertEqual(self.client.post(f'/customers/{a}/restore',data={'_csrf':self.csrf()}).status_code,404)
        self.assertEqual(self.client.get('/customers?archived=1').status_code,200)
        self.assertNotIn('Alpha AG',self.client.get('/customers?archived=1').text)
        self.assertEqual(self.client.get('/invoices/new?customer_id='+str(a)).status_code,404)

    def test_items_filters_restore_and_export(self):
        self.item('Kupferkabel','Material')
        archived=self.item('Spezialbohrer','Werkzeug',active=0)
        self.item('Beratung','Services',kind='service')
        self.assertIn('Beratung',self.client.get('/items?kind=service').text)
        self.assertNotIn('Kupferkabel',self.client.get('/items?kind=service').text)
        self.assertIn('Spezialbohrer',self.client.get('/items?archived=1').text)
        self.assertEqual(self.client.post(f'/items/{archived}/restore',data={'_csrf':self.csrf()}).status_code,200)
        self.assertIn('Spezialbohrer',self.client.get('/items?category=Werkzeug').text)
        r=self.client.get('/items/list.csv?category=Werkzeug')
        self.assertIn('Spezialbohrer',r.text)
        self.assertNotIn('Kupferkabel',r.text)

    def test_items_invalid_filters_no_sql_injection(self):
        self.item(name='X%_ Kabel')
        self.assertEqual(self.client.get('/items?sort=DROP').status_code,400)
        self.assertEqual(self.client.get('/items?kind=hacked').status_code,400)
        self.assertIn('1 Treffer',self.client.get('/items',params={'q':'%_'}).text)

    def test_recurring_pause_resume_schedule_and_invalid(self):
        inv=self.invoice(status='sent')
        with transaction(self.db,True) as con:
            rid=con.execute('INSERT INTO recurrings(company_id,source_invoice_id,interval_months,next_date) VALUES(1,?,?,?)',
                (inv,1,date.today().isoformat())).lastrowid
        self.assertIn('RE-X',self.client.get('/recurring').text)
        data={'_csrf':self.csrf(),'interval_months':'6','next_date':'2027-04-02'}
        self.client.post(f'/recurring/{rid}/schedule',data=data)
        with transaction(self.db) as con:
            row=con.execute('SELECT interval_months,next_date FROM recurrings WHERE id=?',(rid,)).fetchone()
        self.assertEqual((row['interval_months'],row['next_date']),(6,'2027-04-02'))
        self.client.post(f'/recurring/{rid}/disable',data={'_csrf':self.csrf()})
        self.assertIn('RE-X',self.client.get('/recurring?status=paused').text)
        self.assertEqual(self.client.post(f'/recurring/{rid}/generate',data={'_csrf':self.csrf()}).status_code,409)
        self.client.post(f'/recurring/{rid}/schedule',data={'_csrf':self.csrf(),'interval_months':'100','next_date':'2030-01-01'})
        with transaction(self.db) as con:
            self.assertEqual(con.execute('SELECT interval_months FROM recurrings WHERE id=?',(rid,)).fetchone()[0],6)
        self.client.post(f'/recurring/{rid}/resume',data={'_csrf':self.csrf()})
        self.assertIn('RE-X',self.client.get('/recurring?status=active').text)

    def test_recurring_cross_company(self):
        inv=self.invoice()
        with transaction(self.db,True) as con:
            rid=con.execute('INSERT INTO recurrings(company_id,source_invoice_id,next_date) VALUES(1,?,?)',
                (inv,'2026-01-01')).lastrowid
        self.company2()
        self.assertEqual(self.client.post(f'/recurring/{rid}/resume',data={'_csrf':self.csrf()}).status_code,404)

    def test_receivables_filters_and_csv_agree(self):
        today=date.today()
        self.invoice('OVERDUE',due=(today-timedelta(days=10)).isoformat())
        self.invoice('SOON',due=(today+timedelta(days=3)).isoformat())
        self.invoice('LATER',due=(today+timedelta(days=20)).isoformat())
        page=self.client.get('/receivables?due=next7').text
        self.assertIn('SOON',page);self.assertNotIn('OVERDUE',page)
        self.assertNotIn('LATER',page)
        export=self.client.get('/receivables.csv?due=next7').text
        self.assertIn('SOON',export)
        self.assertNotIn('OVERDUE',export)
        self.assertIn('OVERDUE',self.client.get('/receivables?due=overdue').text)
        self.assertEqual(self.client.get('/receivables?due=other').status_code,400)

    def test_reports_date_and_payment_date_are_distinct(self):
        base=date.today()
        previous=(base-timedelta(days=30)).isoformat()
        today=base.isoformat()
        inv=self.invoice('HIST',when=previous,total='400')
        self.invoice('CURR',when=today,total='100')
        with transaction(self.db,True) as con:
            con.execute('INSERT INTO payments(company_id,invoice_id,paid_at,amount,method) VALUES(1,?,?,?,?)',(inv,today,'50.00','Bank'))
        page=self.client.get('/reports',params={'date_from':today,'date_to':today}).text
        self.assertIn('100.00',page)
        self.assertIn('50.00',page)
        export=self.client.get('/reports/summary.csv',params={'date_from':today,'date_to':today})
        self.assertEqual(export.status_code,200)
        self.assertIn('50.00',export.text)
        self.assertEqual(self.client.get('/reports?date_from=2026-12-31&date_to=2026-01-01').status_code,400)

    def test_archive_filters_count_and_invalid_dates(self):
        from hashlib import sha256
        a=self.invoice('ARCH-A',kind='invoice',currency='CHF')
        b=self.invoice('ARCH-B',kind='quote',currency='EUR')
        with transaction(self.db,True) as con:
            for i in (a,b):
                rel=f'archive/1/{i:08d}.pdf'
                (self.root/'archive'/'1').mkdir(parents=True,exist_ok=True)
                payload=b'%PDF-1.4 archive'
                (self.root/rel).write_bytes(payload)
                con.execute('UPDATE invoices SET pdf_file=?,pdf_sha256=? WHERE id=?',(rel,sha256(payload).hexdigest(),i))
        html=self.client.get('/archive?kind=quote&currency=EUR').text
        self.assertIn('ARCH-B',html);self.assertNotIn('ARCH-A',html)
        self.assertEqual(self.client.get('/archive?kind=bogus').status_code,400)
        self.assertEqual(self.client.get('/archive?date_from=bad').status_code,400)

    def test_bank_text_filter_and_currency(self):
        with transaction(self.db,True) as con:
            for i,(debtor,curr) in enumerate([('Alice AG','CHF'),('Bob GmbH','EUR')]):
                con.execute('''INSERT INTO bank_transactions(company_id,fingerprint,source,account_iban,value_date,amount,currency,debtor)
                    VALUES(1,?,'camt.053','CH9300762011623852957','2026-11-08','100',?,?)''',(str(i),curr,debtor))
        response=self.client.get('/bank?q=Alice&currency=CHF')
        self.assertIn('Alice AG',response.text)
        self.assertNotIn('Bob GmbH',response.text)
        self.assertEqual(self.client.get('/bank?currency=USD').status_code,400)

    def test_activity_search_dates_and_csv(self):
        with transaction(self.db,True) as con:
            con.execute("INSERT INTO activity(company_id,user_id,action,detail,at) VALUES(1,1,'Wartung','Pruefung 1','2026-11-08 08:00:00')")
            con.execute("INSERT INTO activity(company_id,user_id,action,detail,at) VALUES(1,1,'Test','Pruefung 2','2026-01-01 08:00:00')")
        page=self.client.get('/activity?q=Wartung&date_from=2026-11-01').text
        self.assertIn('Wartung',page)
        self.assertNotIn('Pruefung 2',page)
        csv_data=self.client.get('/activity.csv?q=Wartung&date_from=2026-11-01').text
        self.assertIn('Wartung',csv_data);self.assertNotIn('Pruefung 2',csv_data)

    def test_team_role_change_last_admin_guard_and_editor_access(self):
        with transaction(self.db,True) as con:
            uid=con.execute('INSERT INTO users(email,full_name,password_hash) VALUES(?,?,?)',
                ('team@alpen.ch','Team',hash_password('TeamPasswort!123'))).lastrowid
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(1,?,'viewer')",(uid,))
        t=self.csrf()
        self.assertEqual(self.client.post('/team/1/role',data={'_csrf':t,'role':'viewer'}).status_code,409)
        self.assertEqual(self.client.post('/team/1/remove',data={'_csrf':t}).status_code,400)
        self.client.post(f'/team/{uid}/role',data={'_csrf':t,'role':'editor'})
        self.assertIn('Bearbeiten',self.client.get('/team').text)
        self.assertEqual(self.client.post('/team/99999/role',data={'_csrf':t,'role':'viewer'}).status_code,404)
        self.assertEqual(self.client.post(f'/team/{uid}/role',data={'role':'admin'}).status_code,403)

    def test_navigation_dashboard_help_and_document_unchanged(self):
        for url in ('/dashboard','/invoices','/customers','/items','/bank','/receivables',
                    '/recurring','/archive','/reports','/settings','/templates','/templates/designer',
                    '/qr-test','/team','/activity','/backup','/systemcheck','/help'):
            res=self.client.get(url)
            self.assertEqual(res.status_code,200,f'{url}: {res.text[:100]}')
            self.assertIn('Swiss-invoice-RX 2.11.0',res.text)
        self.assertIn('einfach nutzen',self.client.get('/help').text)

if __name__=='__main__':
    unittest.main()
