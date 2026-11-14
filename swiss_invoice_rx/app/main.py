"""Swiss-invoice-RX: lokale FastAPI-Webanwendung (nur 127.0.0.1)."""
import csv
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import uuid
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError
from starlette.datastructures import UploadFile
from starlette.middleware.sessions import SessionMiddleware

from .db import initialize, transaction, one, allrows, audit, db_connect
from .business_profile import BUSINESS_TYPES, parse_profile
from .billing import (dec, cents, money, num, percent, hash_password, check_password,
                      future, valid_date, safe_color, invoice_status)
from .billing import summarize
from .pdf import make_pdf, make_reminder_pdf, make_qr_test_pdf
from .imports import read_csv, safe_csv, CUSTOMER_FIELDS, ITEM_FIELDS
from .qr import normalize_iban, valid_iban, build_payload, qrr_reference, scor_reference
from .customer_statement import create_customer_statement
from .diagnostics import company_checks, invoice_checks
from .numbering import (assign_number, peek_number, ensure_available, valid_prefix,
                        valid_counter, valid_padding)
from .template_library import (TEMPLATE_FIELDS, snapshot, as_json, create_initial,
                               set_live_company, ensure_named)
from .designer import parse_layout, dumps_layout, default_layout
from .search import search_all
from .system_check import check_installation
from .branding import (uploaded_logo, save_company_logo, save_site_logo,
                       site_logo_path, company_logo_path, document_logo_path)

HERE = Path(__file__).resolve().parent
DEFAULT_DIR = HERE.parent / 'storage'
TEMPLATES = Jinja2Templates(directory=str(HERE / 'templates'))
TEMPLATES.env.filters['money'] = money
TEMPLATES.env.filters['status_label'] = lambda v: {
    'draft':'Entwurf','sent':'Offen / Versendet','partial':'Teilbezahlt',
    'paid':'Bezahlt','overdue':'Ueberfaellig','cancelled':'Storniert'}.get(v,v)
TEMPLATES.env.filters['kind_label'] = lambda v: {
    'invoice':'Rechnung','quote':'Offerte','credit':'Gutschrift'}.get(v,v)


def redirect(url):
    return RedirectResponse(url=url, status_code=303)


def to_dict(row):
    return dict(row) if row is not None else None


def create_app(data_dir=None):
    root = Path(data_dir or (os.environ.get('SWISS_INVOICE_DATA_DIR') or os.environ.get('HELVETIC_DATA_DIR') or DEFAULT_DIR)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for folder in ('uploads','archive','backups'):
        (root/folder).mkdir(exist_ok=True)
    db_path = root / 'rechnung.sqlite3'
    initialize(db_path)
    secret_file = root / '.session_key'
    if not secret_file.exists():
        fd = os.open(str(secret_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_hex(32))
    secret_key = secret_file.read_text().strip()
    app = FastAPI(title='Swiss-invoice-RX', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.root = root
    app.state.db = db_path
    app.add_middleware(SessionMiddleware, secret_key=secret_key,
                       same_site='lax', https_only=False, max_age=28800, session_cookie='helvetic_session')
    app.mount('/static', StaticFiles(directory=str(HERE/'static')), name='static')

    @app.middleware('http')
    async def safety_headers(request, call_next):
        """Home-Assistant-Ingress: nur Supervisor-IP, Pfade und Weiterleitungen.

        Der Supervisor setzt X-Ingress-Path; wir uebernehmen keinen anderen
        Host-/Pfad-Header als Grundlage fuer Links oder Berechtigungen.
        """
        ingress_mode = os.environ.get('SWISS_INVOICE_INGRESS') == '1'
        ingress_prefix = ''
        if ingress_mode:
            client_ip = request.client.host if request.client else ''
            # /health ist nur vom Container selbst fuer den Docker Healthcheck zugaenglich.
            if client_ip not in ('172.30.32.2', '127.0.0.1', '::1'):
                return Response('Zugriff nur ueber Home Assistant erlaubt.', status_code=403)
            forwarded = request.headers.get('x-ingress-path', '').rstrip('/')
            if forwarded and re.fullmatch(r'/api/hassio_ingress/[a-zA-Z0-9._~-]+', forwarded):
                ingress_prefix = forwarded
            elif forwarded:
                return Response('Ungueltiger Home-Assistant-Ingress-Pfad.', status_code=400)
        request.state.ingress_prefix = ingress_prefix
        response = await call_next(request)
        if ingress_prefix:
            location = response.headers.get('location','')
            if location.startswith('/') and not location.startswith('//') and not location.startswith(ingress_prefix+'/'):
                response.headers['Location'] = ingress_prefix + location
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN' if ingress_mode else 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors " + ("'self'" if ingress_mode else "'none'") + "; base-uri 'self'; form-action 'self'")
        response.headers['Cache-Control'] = 'no-store'
        return response

    def notify(request, message, category='success'):
        request.session['flash'] = (category, str(message)[:350])

    def active_user(request):
        uid = request.session.get('uid')
        if not uid:
            return None
        with transaction(db_path) as con:
            u = one(con, 'SELECT * FROM users WHERE id=? AND active=1', (uid,))
            return to_dict(u)

    def permitted_companies(con, user):
        """Mitgliedschaften und eine feste Einzelgeschaefts-Zuweisung durchsetzen."""
        return [dict(x) for x in allrows(con, '''SELECT c.*,m.role FROM memberships m
            JOIN companies c ON c.id=m.company_id
            WHERE m.user_id=? AND (? IS NULL OR c.id=?) ORDER BY c.name''',
            (user['id'],user['restricted_company_id'],user['restricted_company_id']))]

    def current(request, role='viewer'):
        user = active_user(request)
        if not user:
            raise HTTPException(303, headers={'Location': '/login'})
        cid = request.session.get('cid')
        with transaction(db_path) as con:
            memberships = permitted_companies(con,user)
            if not memberships:
                if user.get('can_create_company'):
                    raise HTTPException(303, headers={'Location': '/onboarding'})
                raise HTTPException(403, 'Kein Unternehmen zugeordnet')
            company = next((x for x in memberships if x['id'] == cid), memberships[0])
            if cid != company['id']:
                request.session['cid'] = company['id']
        if {'viewer':0,'editor':1,'admin':2}[company['role']] < {'viewer':0,'editor':1,'admin':2}[role]:
            raise HTTPException(403, 'Keine Berechtigung fuer diese Aktion')
        return user, company

    def view(request, name, **context):
        request.session.setdefault('csrf', secrets.token_hex(24))
        user = active_user(request)
        memberships = []
        selected_company = None
        if user:
            with transaction(db_path) as con:
                memberships = permitted_companies(con,user)
            selected_company = next((x for x in memberships if x['id']==request.session.get('cid')), None)
            if not selected_company and memberships:
                selected_company = memberships[0]
                request.session['cid'] = selected_company['id']
        return TEMPLATES.TemplateResponse(request, name, {
            'user':user, 'company_menu':memberships, 'active_company':selected_company,
            'csrf':request.session['csrf'], 'flash':request.session.pop('flash', None),
            'company_app_logo':bool(company_logo_path(root, selected_company)),
            'document_logo_available':bool(document_logo_path(root, selected_company)),
            'site_login_logo':bool(site_logo_path(root)),
            'ingress_prefix':getattr(request.state, 'ingress_prefix', ''),
            'today':date.today().isoformat(), 'year':date.today().year, **context
        })

    async def form(request):
        data = await request.form()
        token = str(data.get('_csrf',''))
        expected = str(request.session.get('csrf',''))
        if not expected or not hmac.compare_digest(token, expected):
            await data.close()
            raise HTTPException(403, 'Ungueltiges Sicherheits-Token. Seite neu laden.')
        return data

    def fetch(con, tab, cid, rid):
        if tab not in ('customers','items','invoices','recurrings'):
            raise ValueError('Ungueltige Tabelle')
        obj = one(con, f'SELECT * FROM {tab} WHERE id=? AND company_id=?', (rid, cid))
        if obj is None:
            raise HTTPException(404, 'Eintrag nicht gefunden')
        return to_dict(obj)

    def list_query(text, length=80):
        # LIKE special characters are literal user input, not wildcards.
        return '%' + str(text or '').strip()[:length].replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'

    def period_bounds(date_from='', date_to=''):
        try:
            first = valid_date(date_from) if date_from else ''
            last = valid_date(date_to) if date_to else ''
        except ValueError as exc:
            raise HTTPException(400, 'Ungueltiger Datumsfilter') from exc
        if first and last and first > last:
            raise HTTPException(400, 'Startdatum liegt nach dem Enddatum')
        return first, last

    def checked_page(page, count, size=50):
        pages = max(1, (count + size - 1)//size)
        return min(max(page,1),pages),pages

    def csv_download(filename, headers, rows, numeric=()):
        stream = io.StringIO()
        stream.write('\ufeff')
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(headers)
        for row in rows:
            writer.writerow([safe_csv(value, ix in numeric) for ix,value in enumerate(row)])
        return Response(stream.getvalue().encode('utf-8'),media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':f'attachment; filename="{filename}"'})

    def payment_days(data):
        raw = str(data.get('payment_days', '0') or '0').strip()
        if not re.fullmatch(r'[0-9]{1,3}', raw):
            raise ValueError('Zahlungsziel: Bitte 0 bis 365 Tage eingeben.')
        value = int(raw)
        if value > 365:
            raise ValueError('Zahlungsziel darf maximal 365 Tage betragen.')
        return value

    def insert_customer(con, cid, data):
        name = str(data.get('name','')).strip()
        if not name:
            raise ValueError('Kundenname fehlt')
        fields = ('name','contact','email','phone','street','building','zip','city','country','group_name','notes')
        values = [str(data.get(f,'CH' if f=='country' else '')).strip()[:500] for f in fields]
        number = 'K' + str((one(con, "SELECT COALESCE(MAX(CAST(SUBSTR(number,2) AS INTEGER)),0)+1 AS n FROM customers WHERE company_id=?", (cid,))['n'])).zfill(5)
        con.execute('''INSERT INTO customers(company_id,number,name,contact,email,phone,street,building,zip,city,country,group_name,notes,payment_days)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (cid,number,*values,payment_days(data)))
        return con.execute('SELECT last_insert_rowid()').fetchone()[0]

    def item_image(con, cid, upload, previous=''):
        if not upload or not getattr(upload, 'filename', ''):
            return previous
        if not isinstance(upload, UploadFile):
            raise ValueError('Ungueltiger Bild-Upload')
        file = upload.file
        file.seek(0, 2)
        size = file.tell()
        file.seek(0)
        if size > 5*1024*1024:
            raise ValueError('Bild zu gross (maximal 5 MB)')
        try:
            image = Image.open(file)
            image.verify()
            file.seek(0)
            image = Image.open(file)
            image.thumbnail((1600,1600))
            if image.mode not in ('RGB','L'):
                image = image.convert('RGB')
            sub = root/'uploads'/str(cid)
            sub.mkdir(exist_ok=True)
            target = sub / f'{uuid.uuid4().hex}.jpg'
            image.save(target, format='JPEG', quality=88, optimize=True)
            return str(target.relative_to(root))
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError('Nur gueltige JPG-/PNG-/WEBP-Bilder erlaubt') from exc

    def next_number(con, cid, kind, company, invoice_year=None):
        return assign_number(con, cid, kind, company, invoice_year or date.today().year)

    def parse_lines(data, kind, tax_registered=True):
        fields = ['description','qty','unit','price','tax_rate','tax_mode','discount','item_id']
        arrays = {k:data.getlist(k+'[]') for k in fields}
        n = len(arrays['description'])
        if n > 150:
            raise ValueError('Maximal 150 Positionen pro Beleg')
        lines=[]
        for i in range(n):
            if not str(arrays['description'][i]).strip():
                continue
            row = {k: arrays[k][i] if i < len(arrays[k]) else '' for k in fields}
            if kind != 'credit' and dec(row['qty']) < 0:
                raise ValueError('Negative Mengen sind nur auf Gutschriften erlaubt')
            if not tax_registered and (row['tax_mode'] or 'taxable') == 'taxable' and dec(row['tax_rate'] or 0) != 0:
                raise ValueError('Firma ist nicht MWST-pflichtig: MWST-Satz 0 % waehlen')
            lines.append(row)
        return lines

    def customer_snapshot(con, cid, customer_id):
        if not customer_id:
            raise ValueError('Bitte einen Kunden waehlen')
        return fetch(con, 'customers', cid, int(customer_id))

    def write_invoice(con, cid, data, kind, company, existing=None, author=None):
        cust_id = data.get('customer_id')
        if data.get('new_customer_name'):
            cd = {x.replace('new_customer_',''):str(data.get(x,'')) for x in (
                'new_customer_name','new_customer_email','new_customer_street','new_customer_building',
                'new_customer_zip','new_customer_city','new_customer_country','new_customer_payment_days')}
            cust_id = insert_customer(con, cid, cd)
        customer = customer_snapshot(con, cid, cust_id)
        items = parse_lines(data, kind, bool(company['tax_registered']))
        result = summarize(items, data.get('discount','0'))
        if kind == 'credit' and cents(result['total']) >= 0:
            raise ValueError('Eine Gutschrift muss einen negativen Gesamtbetrag aufweisen')
        if kind != 'credit' and cents(result['total']) < 0:
            raise ValueError('Rechnungsbetrag muss positiv sein')
        invoice_date = valid_date(data.get('invoice_date'))
        due = valid_date(data.get('due_date'))
        service_date = valid_date(data['service_date']) if data.get('service_date') else ''
        currency = str(data.get('currency','CHF')).upper()
        if currency not in ('CHF','EUR'):
            raise ValueError('Nur CHF/EUR in dieser Version')
        vals = (int(customer['id']), invoice_date, service_date, due, currency,
                str(data.get('subject','')).strip()[:140], str(data.get('notes',''))[:3000], str(percent(data.get('discount','0'))),
                result['subtotal'],result['tax_total'],result['total'], json.dumps(result['tax_breakdown']))
        requested_number = data.get('number')
        if existing:
            iid=existing['id']
            number = ensure_available(con, cid, requested_number if requested_number is not None else existing['number'], iid)
            if number != existing['number']:
                audit(con,cid,author,'Belegnummer geaendert',f"{existing['number']} -> {number}")
            con.execute('''UPDATE invoices SET number=?,customer_id=?,invoice_date=?,service_date=?,due_date=?,currency=?,subject=?,
                notes=?,discount=?,subtotal=?,tax_total=?,total=?,tax_breakdown=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND company_id=? AND status='draft' ''', (number,*vals, iid,cid))
            con.execute('DELETE FROM invoice_lines WHERE invoice_id=? AND company_id=?',(iid,cid))
        else:
            number = (ensure_available(con, cid, requested_number) if str(requested_number or '').strip()
                      else next_number(con,cid,kind,company,int(invoice_date[:4])))
            con.execute('''INSERT INTO invoices(company_id,kind,number,customer_id,invoice_date,service_date,due_date,
                currency,subject,notes,discount,subtotal,tax_total,total,tax_breakdown) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (cid,kind,number,*vals))
            iid=con.execute('SELECT last_insert_rowid()').fetchone()[0]
        for pos,ln in enumerate(result['lines'],1):
            item_id = ln['item_id']
            if item_id:
                fetch(con,'items',cid,int(item_id))
            con.execute('''INSERT INTO invoice_lines(company_id,invoice_id,item_id,position,description,qty,unit,price,tax_rate,tax_mode,discount,line_net)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (cid,iid,item_id,pos,ln['description'],ln['qty'],ln['unit'],ln['price'],ln['tax_rate'],ln['tax_mode'],ln['discount'],ln['line_net']))
        audit(con,cid,author,'Beleg gespeichert',f"{kind} #{iid}")
        return iid

    def duplicate(con, cid, src, kind, company, uid, credit=False):
        number=next_number(con,cid,kind,company)
        date_value=date.today().isoformat()
        due=future(int(company['default_due_days']))
        con.execute('''INSERT INTO invoices(company_id,kind,number,customer_id,invoice_date,service_date,due_date,
            currency,status,subject,notes,discount,subtotal,tax_total,total,tax_breakdown,parent_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid,kind,number,src['customer_id'],date_value,date_value,due,src['currency'],
             'draft',src.get('subject',''),src['notes'],src['discount'],src['subtotal'],src['tax_total'],src['total'],src['tax_breakdown'],src['id']))
        iid=con.execute('SELECT last_insert_rowid()').fetchone()[0]
        origin=allrows(con,'SELECT * FROM invoice_lines WHERE invoice_id=? AND company_id=? ORDER BY position',(src['id'],cid))
        if credit:
            rows=[]
            for ln in origin:
                d=dict(ln)
                d['qty']=str(-dec(d['qty']))
                rows.append(d)
            result=summarize(rows,src['discount'])
            con.execute('UPDATE invoices SET subtotal=?,tax_total=?,total=?,tax_breakdown=? WHERE id=?',
                        (result['subtotal'],result['tax_total'],result['total'],json.dumps(result['tax_breakdown']),iid))
            lines=result['lines']
        else:
            lines=[dict(ln) for ln in origin]
        for pos,ln in enumerate(lines,1):
            con.execute('''INSERT INTO invoice_lines(company_id,invoice_id,item_id,position,description,qty,unit,price,tax_rate,tax_mode,discount,line_net)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (cid,iid,ln['item_id'],pos,ln['description'],ln['qty'],ln['unit'],ln['price'],ln['tax_rate'],ln['tax_mode'],ln['discount'],ln['line_net']))
        audit(con,cid,uid,'Beleg dupliziert',f"{src['number']} -> {number}")
        return iid

    def pdf_for(con, inv, company, cid, preview=False):
        inv=dict(inv)
        c = dict(company)
        if inv.get('company_snapshot') and inv['company_snapshot'] != '{}':
            c=json.loads(inv['company_snapshot'])
        logo = document_logo_path(root, c)
        c['logo_path'] = str(logo) if logo else ''
        c['designer_asset_root'] = str(root/'uploads'/'designs'/str(cid))
        if inv.get('customer_snapshot') and inv['customer_snapshot'] != '{}':
            cust=json.loads(inv['customer_snapshot'])
        else:
            cust=customer_snapshot(con,cid,inv['customer_id'])
        lines=[dict(x) for x in allrows(con,'SELECT * FROM invoice_lines WHERE invoice_id=? AND company_id=? ORDER BY position',(inv['id'],cid))]
        return make_pdf(inv,c,cust,lines,preview=preview)

    def issue_invoice(con, cid, inv, company, uid):
        if inv['status'] != 'draft':
            raise ValueError('Nur Entwuerfe koennen freigegeben werden')
        customer=customer_snapshot(con,cid,inv['customer_id'])
        if inv['kind']=='invoice' and company['iban']:
            if not valid_iban(company['iban']):
                raise ValueError('Firmendaten: IBAN ist ungueltig')
            build_payload(company,customer,inv['total'],inv['currency'],
                          f"{cid:05d}{inv['id']:012d}",inv['number'])
        if inv['kind']=='invoice':
            lines=allrows(con,'SELECT * FROM invoice_lines WHERE invoice_id=? AND company_id=?',(inv['id'],cid))
            required={}
            for ln in lines:
                if ln['item_id']:
                    item=fetch(con,'items',cid,ln['item_id'])
                    if item['track_stock']:
                        required[item['id']]=required.get(item['id'], Decimal('0'))+dec(ln['qty'])
            for item_id,qty in required.items():
                item=fetch(con,'items',cid,item_id)
                if dec(item['stock'])<qty:
                    raise ValueError(f"Nicht genug Lagerbestand: {item['name']} ({item['stock']} verfuegbar)")
                con.execute('UPDATE items SET stock=? WHERE id=? AND company_id=?',
                            (str(dec(item['stock'])-qty),item_id,cid))
                con.execute('INSERT INTO stock_movements(company_id,item_id,invoice_id,quantity,note) VALUES(?,?,?,?,?)',
                            (cid,item_id,inv['id'],str(-qty),'Rechnung '+inv['number']))
        cs=dict(company)
        cs.pop('role',None)
        con.execute('''UPDATE invoices SET status='sent',customer_snapshot=?,company_snapshot=?,issued_at=?,
                       updated_at=CURRENT_TIMESTAMP WHERE id=? AND company_id=?''',
                    (json.dumps(customer,ensure_ascii=False),json.dumps(cs,ensure_ascii=False),datetime.now().isoformat(),inv['id'],cid))
        stamped=fetch(con,'invoices',cid,inv['id'])
        pdf_bytes,qr=pdf_for(con,stamped,company,cid)
        dest_dir=root/'archive'/str(cid)
        dest_dir.mkdir(exist_ok=True)
        dest=dest_dir/f"{inv['id']:08d}.pdf"
        temp=dest.with_suffix('.tmp')
        temp.write_bytes(pdf_bytes)
        os.replace(temp,dest)
        rel=str(dest.relative_to(root))
        con.execute('UPDATE invoices SET pdf_file=?,pdf_sha256=? WHERE id=? AND company_id=?',
                    (rel,hashlib.sha256(pdf_bytes).hexdigest(),inv['id'],cid))
        audit(con,cid,uid,'Beleg freigegeben',inv['number'])
        return bool(qr)

    @app.get('/', response_class=HTMLResponse)
    async def index(request:Request):
        with transaction(db_path) as con:
            exists=one(con,'SELECT id FROM users LIMIT 1')
        if not exists:
            return redirect('/setup')
        user = active_user(request)
        if not user:
            return redirect('/login')
        if user['can_create_company']:
            with transaction(db_path) as con:
                if not permitted_companies(con, user):
                    return redirect('/onboarding')
        return redirect('/dashboard')

    @app.get('/setup')
    async def setup_page(request:Request):
        with transaction(db_path) as con:
            if one(con,'SELECT id FROM users LIMIT 1'):
                return redirect('/login')
        return view(request,'setup.html')

    @app.post('/setup')
    async def setup_save(request:Request):
        data=await form(request)
        try:
            with transaction(db_path,True) as con:
                if one(con,'SELECT id FROM users LIMIT 1'):
                    raise ValueError('Einrichtung bereits abgeschlossen')
                name=str(data.get('company_name','')).strip()
                email=str(data.get('email','')).strip().lower()
                if not name or '@' not in email:
                    raise ValueError('Firmenname und gueltige E-Mail erforderlich')
                pwd=str(data.get('password',''))
                if pwd != data.get('password2'):
                    raise ValueError('Passwoerter stimmen nicht ueberein')
                con.execute('INSERT INTO users(email,full_name,password_hash,is_superadmin) VALUES(?,?,?,1)',
                            (email,str(data.get('full_name','Admin')).strip() or 'Admin', hash_password(pwd)))
                uid=con.execute('SELECT last_insert_rowid()').fetchone()[0]
                con.execute('INSERT INTO companies(name) VALUES(?)',(name,))
                cid=con.execute('SELECT last_insert_rowid()').fetchone()[0]
                con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(?,?,'admin')",(cid,uid))
            request.session.clear()
            request.session.update({'uid':uid,'cid':cid,'csrf':secrets.token_hex(24)})
            notify(request,'Einrichtung abgeschlossen. Bitte Firmendaten und IBAN vervollstaendigen.')
            return redirect('/settings')
        except (ValueError, sqlite3.IntegrityError) as exc:
            notify(request,str(exc),'error')
            return redirect('/setup')

    @app.get('/login')
    async def login_page(request:Request):
        user=active_user(request)
        if user:
            with transaction(db_path) as con:
                if user['can_create_company'] and not permitted_companies(con,user):
                    return redirect('/onboarding')
            return redirect('/dashboard')
        return view(request,'login.html')

    @app.post('/login')
    async def login(request:Request):
        data=await form(request)
        email=str(data.get('email','')).strip().lower()
        pwd=str(data.get('password',''))
        with transaction(db_path,True) as con:
            u=one(con,'SELECT * FROM users WHERE email=? AND active=1',(email,))
            locked=bool(u and u['locked_until'] and u['locked_until']>datetime.now().isoformat())
            if not u or locked or not check_password(pwd,u['password_hash']):
                if u and not locked:
                    fails=u['failed_logins']+1
                    lock=(datetime.now()+timedelta(minutes=15)).isoformat() if fails>=8 else ''
                    con.execute('UPDATE users SET failed_logins=?,locked_until=? WHERE id=?',(fails,lock,u['id']))
                notify(request,'Anmeldung fehlgeschlagen oder Konto voruebergehend gesperrt.','error')
                return redirect('/login')
            con.execute("UPDATE users SET failed_logins=0,locked_until='' WHERE id=?",(u['id'],))
            m=one(con,'''SELECT company_id FROM memberships WHERE user_id=?
                AND (? IS NULL OR company_id=?) ORDER BY company_id LIMIT 1''',
                (u['id'],u['restricted_company_id'],u['restricted_company_id']))
            if not m and not u['can_create_company']:
                notify(request,'Keinem Unternehmen zugeordnet.','error')
                return redirect('/login')
        request.session.clear()
        request.session.update({'uid':u['id'],'csrf':secrets.token_hex(24)})
        if not m:
            return redirect('/onboarding')
        request.session['cid']=m['company_id']
        return redirect('/dashboard')

    @app.get('/onboarding')
    async def onboarding(request:Request):
        """Private company creation only for an authenticated, unassigned invitee."""
        user=active_user(request)
        if not user:
            return redirect('/login')
        with transaction(db_path) as con:
            if permitted_companies(con,user):
                return redirect('/dashboard')
        if not user['can_create_company']:
            raise HTTPException(403,'Kein Einrichtungsrecht. Bitte den Administrator kontaktieren.')
        return view(request,'onboarding.html',business_types=BUSINESS_TYPES,
                    new_business_email=user['email'])

    @app.post('/onboarding')
    async def onboarding_save(request:Request):
        user=active_user(request)
        if not user:
            return redirect('/login')
        data=await form(request)
        with transaction(db_path) as con:
            if not user['can_create_company'] or one(con,'SELECT 1 FROM memberships WHERE user_id=?',(user['id'],)):
                raise HTTPException(403,'Du hast bereits ein Geschäft oder keine Freigabe zur Einrichtung.')
        image_path=None
        try:
            profile=parse_profile(data)
            password_new=str(data.get('password_new',''))
            if password_new != str(data.get('password_confirm','')):
                raise ValueError('Die neuen Passwörter stimmen nicht überein.')
            password_hash=hash_password(password_new)
            logo_bytes=uploaded_logo(data.get('app_logo'))
            due=int(data.get('default_due_days',30))
            if due<0 or due>365:
                raise ValueError('Zahlungsziel muss zwischen 0 und 365 Tagen liegen.')
            # No existing tenant membership is inherited from the invitation.
            with transaction(db_path,True) as con:
                fresh=one(con,'SELECT * FROM users WHERE id=? AND active=1',(user['id'],))
                if not fresh or not fresh['can_create_company']:
                    raise HTTPException(403,'Einrichtung nicht freigegeben')
                if one(con,'SELECT 1 FROM memberships WHERE user_id=?',(user['id'],)):
                    raise HTTPException(409,'Benutzer hat bereits ein Geschäft')
                if check_password(password_new,fresh['password_hash']):
                    raise ValueError('Bitte ein eigenes, neues Passwort statt des Startpassworts wählen.')
                cols=tuple(profile)+('default_due_days',)
                values=list(profile.values())+[due]
                placeholders=','.join('?' for _ in cols)
                con.execute('INSERT INTO companies('+','.join(cols)+') VALUES('+placeholders+')',values)
                cid=con.execute('SELECT last_insert_rowid()').fetchone()[0]
                if logo_bytes is not None:
                    image_path=save_company_logo(root,cid,logo_bytes)
                    con.execute('UPDATE companies SET app_logo_path=? WHERE id=?',(image_path,cid))
                con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(?,?,'admin')",(cid,user['id']))
                con.execute('UPDATE users SET can_create_company=0, restricted_company_id=?, password_hash=? WHERE id=?',(cid,password_hash,user['id']))
                audit(con,cid,user['id'],'Eigenes Geschäft eingerichtet',profile['name']+' / '+profile['business_type'])
            request.session['cid']=cid
            notify(request,'Dein eigenes Geschäft ist eingerichtet. Einstellungen und QR-Code kannst du jederzeit ändern.')
            return redirect('/dashboard')
        except HTTPException:
            raise
        except (ValueError,sqlite3.IntegrityError) as exc:
            if image_path:
                (root/image_path).unlink(missing_ok=True)
            notify(request,str(exc),'error')
            return redirect('/onboarding')

    @app.post('/logout')
    async def logout(request:Request):
        await form(request)
        request.session.clear()
        return redirect('/login')

    @app.post('/company/switch')
    async def switch_company(request:Request):
        await form(request)
        user=active_user(request)
        if not user:
            return redirect('/login')
        data=await request.form()
        try:
            cid=int(data.get('company_id',0))
        except (ValueError,TypeError):
            raise HTTPException(400,'Ungueltige Geschaeftsauswahl')
        with transaction(db_path) as con:
            if not one(con,'''SELECT 1 FROM memberships WHERE company_id=? AND user_id=?
                AND (? IS NULL OR company_id=?)''',
                (cid,user['id'],user['restricted_company_id'],user['restricted_company_id'])):
                raise HTTPException(403,'Kein Zugang zu diesem Geschaeft')
        request.session['cid']=cid
        return redirect('/dashboard')


    @app.get('/search')
    async def search_page(request:Request,q:str=''):
        user,co=current(request)
        q=q.strip()[:80]
        with transaction(db_path) as con:
            found=search_all(con,co['id'],q,limit=30,can_edit=co['role']!='viewer')
        return view(request,'search.html',q=q,found=found,
                    total_hits=sum(len(items) for items in found.values()))

    @app.get('/api/search')
    async def search_suggest(request:Request,q:str=''):
        user,co=current(request)
        q=q.strip()[:80]
        with transaction(db_path) as con:
            found=search_all(con,co['id'],q,limit=6,can_edit=co['role']!='viewer')
        return {'q':q,'groups':found}

    @app.get('/dashboard')
    async def dashboard(request:Request, currency:str=''):
        user,co=current(request)
        currency=currency if currency in ('CHF','EUR') else co['currency']
        cid=co['id']
        with transaction(db_path) as con:
            invoices=[dict(x) for x in allrows(con,"SELECT * FROM invoices WHERE company_id=? AND currency=? AND kind='invoice' ORDER BY id DESC",(cid,currency))]
            recent=[dict(x) for x in allrows(con,'SELECT * FROM activity WHERE company_id=? ORDER BY id DESC LIMIT 7',(cid,))]
            drafts=[dict(x) for x in allrows(con,"""SELECT i.id,i.number,i.kind,i.updated_at,i.subject,c.name AS customer_name
                FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id AND c.company_id=i.company_id
                WHERE i.company_id=? AND i.status='draft' ORDER BY i.updated_at DESC,i.id DESC LIMIT 5""",(cid,))]
            last=[dict(x) for x in allrows(con,'SELECT * FROM invoices WHERE company_id=? ORDER BY id DESC LIMIT 8',(cid,))]
            low=[dict(x) for x in allrows(con,"""SELECT * FROM items WHERE company_id=? AND track_stock=1
                  AND CAST(stock AS REAL)<=CAST(reorder_point AS REAL) AND active=1
                  ORDER BY CAST(stock AS REAL) LIMIT 5""",(cid,))]
            count_cust=one(con,'SELECT COUNT(*) AS n FROM customers WHERE company_id=? AND active=1',(cid,))['n']
            count_items=one(con,'SELECT COUNT(*) AS n FROM items WHERE company_id=? AND active=1',(cid,))['n']
            count_pending=one(con,'SELECT COUNT(*) AS n FROM invoices WHERE company_id=? AND status=\'draft\'',(cid,))['n']
            bank_unassigned=one(con,"SELECT COUNT(*) AS n FROM bank_transactions WHERE company_id=? AND status='open'",(cid,))['n']
            recurring_due=one(con,'SELECT COUNT(*) AS n FROM recurrings WHERE company_id=? AND active=1 AND next_date<=?',
                              (cid,date.today().isoformat()))['n']
        open_sum=sum((cents(i['total'])-cents(i['paid_total']) for i in invoices if i['status'] not in ('draft','cancelled') and cents(i['total'])>cents(i['paid_total'])),Decimal('0'))
        paid_sum=sum((cents(i['paid_total']) for i in invoices),Decimal('0'))
        overdue=sum(1 for i in invoices if invoice_status(i)=='overdue')
        for i in last:
            i['display_status']=invoice_status(i)
        setup_warnings = ([c for c in company_checks(co) if c['level'] in ('error','warn')]
                          if co['role']=='admin' else [])
        return view(request,'dashboard.html',latest=last,activities=recent,low_stock=low,
                    total_open=open_sum,total_paid=paid_sum,overdue=overdue,customer_count=count_cust,
                    selected_currency=currency,bank_unassigned=bank_unassigned,recurring_due=recurring_due,
                    drafts=drafts,setup_warnings=setup_warnings,
                    item_count=count_items,draft_count=count_pending,
                    monthly_totals=[{'month':m,'total':sum((cents(i['total']) for i in invoices
                      if i['invoice_date'][:7]==m and i['status'] not in ('draft','cancelled')),Decimal('0'))}
                      for m in [(date.today().replace(day=1)-timedelta(days=1)).strftime('%Y-%m'),date.today().strftime('%Y-%m')]])

    @app.get('/companies/new')
    async def new_company(request:Request):
        user,co=current(request)
        if not user['is_superadmin']:
            raise HTTPException(403)
        return view(request,'company_new.html')

    @app.post('/companies/new')
    async def save_company(request:Request):
        user,co=current(request,'admin')
        if not user['is_superadmin']:
            raise HTTPException(403)
        data=await form(request)
        name=str(data.get('name','')).strip()
        if not name:
            notify(request,'Firmenname fehlt','error');return redirect('/companies/new')
        with transaction(db_path,True) as con:
            con.execute('INSERT INTO companies(name) VALUES(?)',(name,))
            cid=con.execute('SELECT last_insert_rowid()').fetchone()[0]
            con.execute("INSERT INTO memberships(company_id,user_id,role) VALUES(?,?,'admin')",(cid,user['id']))
            audit(con,cid,user['id'],'Firma erstellt',name)
        request.session['cid']=cid
        return redirect('/settings')

    def admin_companies(con, user):
        """Nur die vom aktuellen Benutzer verwaltbaren Geschaefte anbieten."""
        return [dict(x) for x in allrows(con, '''SELECT c.id,c.name FROM companies c
            JOIN memberships m ON m.company_id=c.id
            WHERE m.user_id=? AND m.role='admin'
              AND (? IS NULL OR c.id=?) ORDER BY c.name''',
            (user['id'],user['restricted_company_id'],user['restricted_company_id']))]

    @app.get('/team')
    async def team(request:Request):
        user,co=current(request,'admin')
        with transaction(db_path) as con:
            members=[dict(x) for x in allrows(con,'''SELECT u.id,u.email,u.full_name,u.active,
                u.restricted_company_id,u.is_superadmin,m.role
                FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.company_id=? ORDER BY u.full_name''',(co['id'],))]
            businesses=admin_companies(con,user)
            pending=[dict(x) for x in allrows(con,'''SELECT id,email,full_name,created_at FROM users
                WHERE can_create_company=1 AND active=1 AND invited_from_company_id=? ORDER BY id DESC''',(co['id'],))]
        return view(request,'team.html',members=members,businesses=businesses,pending=pending)

    @app.post('/team')
    async def save_member(request:Request):
        user,co=current(request,'admin')
        data=await form(request)
        email=str(data.get('email','')).strip().lower()
        name=str(data.get('full_name','')).strip()
        role=str(data.get('role','viewer'))
        if data.get('create_own_company')=='1':
            if '@' not in email or len(email)>254:
                raise HTTPException(400,'Bitte eine gültige E-Mail-Adresse angeben')
            try:
                password=str(data.get('password',''))
                hashed=hash_password(password)
                with transaction(db_path,True) as con:
                    if one(con,'SELECT id FROM users WHERE email=?',(email,)):
                        raise ValueError('Diese E-Mail-Adresse ist bereits vergeben. Für eine eigene Einrichtung einen neuen Benutzer anlegen.')
                    con.execute('''INSERT INTO users(email,full_name,password_hash,can_create_company,invited_from_company_id)
                        VALUES(?,?,?,1,?)''',(email,name or email,hashed,co['id']))
                    audit(con,co['id'],user['id'],'Eigene Einrichtung eingeladen',email)
                notify(request,'Benutzer erstellt. Er hat keinen Zugriff auf dein Geschäft und richtet beim ersten Login sein eigenes ein.')
            except (ValueError,sqlite3.IntegrityError) as exc:
                notify(request,str(exc),'error')
            return redirect('/team')
        try:
            cid=int(data.get('company_id') or co['id'])
        except (ValueError,TypeError):
            raise HTTPException(400,'Ungueltige Geschaeftsauswahl')
        if role not in ('admin','editor','viewer') or '@' not in email:
            raise HTTPException(400,'Ungueltige E-Mail-Adresse oder Rolle')
        # Absichtliche Mehrfachzuordnung ist nur dem Installationsadmin erlaubt.
        multi=bool(user['is_superadmin'] and data.get('multi_company')=='1')
        try:
            with transaction(db_path,True) as con:
                if cid not in {c['id'] for c in admin_companies(con,user)}:
                    raise HTTPException(403,'Dieses Geschaeft darfst du nicht verwalten')
                existing=one(con,'SELECT * FROM users WHERE email=?',(email,))
                if existing:
                    uid=existing['id']
                    if existing['can_create_company']:
                        raise ValueError('Dieser Benutzer wartet auf seine eigene Geschäftseinrichtung.')
                    if existing['is_superadmin'] and uid!=user['id']:
                        raise HTTPException(403,'Der Hauptadministrator kann hier nicht geaendert werden')
                    if existing['restricted_company_id'] not in (None,cid) and not multi:
                        raise ValueError('Dieses Konto ist fest einem anderen Geschaeft zugeordnet. Nur der Hauptadministrator kann Mehrfachzugriff erlauben.')
                    others=one(con,'SELECT COUNT(*) AS n FROM memberships WHERE user_id=? AND company_id<>?',
                               (uid,cid))['n']
                    if others and not multi:
                        raise ValueError('Dieser Benutzer hat bereits ein anderes Geschaeft. Fuer exklusiven Zugang bitte eine eigene E-Mail verwenden.')
                    if not existing['is_superadmin']:
                        con.execute('UPDATE users SET restricted_company_id=? WHERE id=?',
                                    (None if multi else cid,uid))
                else:
                    password=str(data.get('password',''))
                    con.execute('''INSERT INTO users(email,full_name,password_hash,restricted_company_id)
                        VALUES(?,?,?,?)''',
                        (email,name or email,hash_password(password),None if multi else cid))
                    uid=con.execute('SELECT last_insert_rowid()').fetchone()[0]
                existing_role=one(con,'SELECT role FROM memberships WHERE company_id=? AND user_id=?',(cid,uid))
                if existing_role and existing_role['role']=='admin' and role!='admin':
                    admin_count=one(con,"SELECT COUNT(*) AS n FROM memberships WHERE company_id=? AND role='admin'",(cid,))['n']
                    if uid==user['id'] or admin_count<=1:
                        raise ValueError('Der eigene oder letzte Administratorzugang darf hier nicht entfernt werden.')
                con.execute('INSERT INTO memberships(company_id,user_id,role) VALUES(?,?,?) ON CONFLICT(company_id,user_id) DO UPDATE SET role=excluded.role',
                            (cid,uid,role))
                audit(con,cid,user['id'],'Teammitglied zugeordnet',
                      email+' / '+role+(' / Mehrfachzugriff' if multi else ' / nur dieses Geschaeft'))
            request.session['cid']=cid
            notify(request,'Zugang gespeichert: '+ ('Geschaeftsleitung fuer dieses Geschaeft' if role=='admin' else 'Zugriff auf dieses Geschaeft'))
        except (ValueError, sqlite3.IntegrityError) as exc:
            notify(request,str(exc),'error')
        return redirect('/team')

    @app.post('/team/pending/{member_id}/cancel')
    async def team_cancel_pending(request:Request,member_id:int):
        user,co=current(request,'admin')
        await form(request)
        with transaction(db_path,True) as con:
            pending=one(con,"SELECT id,email FROM users WHERE id=? AND can_create_company=1 AND invited_from_company_id=? AND active=1",(member_id,co['id']))
            if not pending:
                raise HTTPException(404,'Einladung nicht vorhanden')
            if one(con,'SELECT 1 FROM memberships WHERE user_id=?',(member_id,)):
                raise HTTPException(409,'Benutzer hat bereits ein Geschäft')
            con.execute('DELETE FROM users WHERE id=?',(member_id,))
            audit(con,co['id'],user['id'],'Einrichtungseinladung widerrufen',pending['email'])
        notify(request,'Einladung widerrufen.')
        return redirect('/team')

    @app.post('/team/{member_id}/role')
    async def team_change_role(request:Request,member_id:int):
        user,co=current(request,'admin');data=await form(request)
        role=str(data.get('role',''))
        if role not in ('admin','editor','viewer'):
            raise HTTPException(400,'Ungueltige Rolle')
        with transaction(db_path,True) as con:
            membership=one(con,'SELECT role FROM memberships WHERE company_id=? AND user_id=?',(co['id'],member_id))
            if membership is None:raise HTTPException(404)
            target=one(con,'SELECT is_superadmin FROM users WHERE id=?',(member_id,))
            if target['is_superadmin'] and not user['is_superadmin']:
                raise HTTPException(403,'Nur der Hauptadministrator darf diesen Zugang aendern')
            if membership['role']=='admin' and role!='admin':
                admin_count=one(con,"SELECT COUNT(*) AS n FROM memberships WHERE company_id=? AND role='admin'",(co['id'],))['n']
                if member_id==user['id'] or admin_count<=1:
                    raise HTTPException(409,'Eigenen oder letzten Administrator nicht herabstufen')
            con.execute('UPDATE memberships SET role=? WHERE company_id=? AND user_id=?',(role,co['id'],member_id))
            audit(con,co['id'],user['id'],'Benutzerrolle geaendert',f'{member_id}: {role}')
        notify(request,'Benutzerrolle aktualisiert')
        return redirect('/team')

    @app.post('/team/{member_id}/remove')
    async def team_remove(request:Request,member_id:int):
        user,co=current(request,'admin');await form(request)
        if member_id==user['id']:
            raise HTTPException(400,'Den eigenen Firmenzugang nicht entfernen')
        with transaction(db_path,True) as con:
            membership=one(con,'SELECT role FROM memberships WHERE company_id=? AND user_id=?',
                           (co['id'],member_id))
            if membership is None:raise HTTPException(404)
            target=one(con,'SELECT is_superadmin FROM users WHERE id=?',(member_id,))
            if target['is_superadmin'] and not user['is_superadmin']:
                raise HTTPException(403,'Nur der Hauptadministrator darf diesen Zugang entfernen')
            if membership['role']=='admin':
                count=one(con,"SELECT COUNT(*) AS n FROM memberships WHERE company_id=? AND role='admin'",(co['id'],))['n']
                if count<=1:raise HTTPException(409,'Letzten Administrator nicht entfernen')
            con.execute('DELETE FROM memberships WHERE company_id=? AND user_id=?',(co['id'],member_id))
            audit(con,co['id'],user['id'],'Teammitglied entfernt',str(member_id))
        notify(request,'Benutzerzugriff fuer dieses Geschaeft entfernt')
        return redirect('/team')

    @app.post('/team/{member_id}/move')
    async def team_move(request:Request,member_id:int):
        """Ein exklusives Konto atomar in ein anderes Geschaeft verschieben.

        Nur der Installationsadmin kann Zugriffe zwischen Mandanten umhaengen.
        """
        user,co=current(request,'admin')
        if not user['is_superadmin']:
            raise HTTPException(403,'Nur der Hauptadministrator kann Geschaefte zuweisen')
        data=await form(request)
        try:
            dest=int(data.get('company_id',0))
        except (ValueError,TypeError):
            raise HTTPException(400,'Ungueltige Geschaeftsauswahl')
        if dest==co['id']:
            raise HTTPException(400,'Bitte ein anderes Geschaeft waehlen')
        with transaction(db_path,True) as con:
            if dest not in {c['id'] for c in admin_companies(con,user)}:
                raise HTTPException(403,'Keine Administratorrechte im Zielgeschaeft')
            membership=one(con,'''SELECT m.role,u.restricted_company_id,u.is_superadmin
                FROM memberships m JOIN users u ON u.id=m.user_id
                WHERE m.company_id=? AND m.user_id=?''',(co['id'],member_id))
            if membership is None:
                raise HTTPException(404,'Benutzer gehoert nicht zu diesem Geschaeft')
            if membership['is_superadmin'] or member_id==user['id']:
                raise HTTPException(403,'Der Hauptadministrator darf nicht verschoben werden')
            if membership['restricted_company_id']!=co['id']:
                raise HTTPException(409,'Nur exklusiv zugeordnete Benutzer koennen verschoben werden')
            memberships=one(con,'SELECT COUNT(*) AS n FROM memberships WHERE user_id=?',(member_id,))['n']
            if memberships!=1:
                raise HTTPException(409,'Der Benutzer hat mehrere Zuordnungen. Bitte zuerst die Rechte pruefen')
            if membership['role']=='admin':
                admins=one(con,"SELECT COUNT(*) AS n FROM memberships WHERE company_id=? AND role='admin'",(co['id'],))['n']
                if admins<=1:
                    raise HTTPException(409,'Letzten Administrator des Geschaefts nicht verschieben')
            con.execute('DELETE FROM memberships WHERE company_id=? AND user_id=?',(co['id'],member_id))
            con.execute('INSERT INTO memberships(company_id,user_id,role) VALUES(?,?,?)',
                        (dest,member_id,membership['role']))
            con.execute('UPDATE users SET restricted_company_id=? WHERE id=?',(dest,member_id))
            audit(con,co['id'],user['id'],'Benutzer verschoben',f'{member_id} -> Geschaeft {dest}')
            audit(con,dest,user['id'],'Benutzer zugeordnet',f'Benutzer {member_id} aus Geschaeft {co["id"]}')
        request.session['cid']=dest
        notify(request,'Benutzer wurde sicher in das ausgewaehlte Geschaeft verschoben.')
        return redirect('/team')

    @app.get('/account')
    async def account_page(request:Request):
        current(request)
        return view(request,'account.html')

    @app.post('/account/password')
    async def account_password(request:Request):
        user,co=current(request);data=await form(request)
        old=str(data.get('password_old',''))
        new=str(data.get('password_new',''))
        confirm=str(data.get('password_confirm',''))
        try:
            if new!=confirm:raise ValueError('Neue Passwoerter stimmen nicht ueberein')
            with transaction(db_path,True) as con:
                fresh=one(con,'SELECT password_hash FROM users WHERE id=?',(user['id'],))
                if not check_password(old,fresh['password_hash']):
                    raise ValueError('Bisheriges Passwort ist nicht korrekt')
                con.execute('UPDATE users SET password_hash=? WHERE id=?',
                            (hash_password(new),user['id']))
                audit(con,co['id'],user['id'],'Passwort geaendert','')
            notify(request,'Passwort wurde geaendert')
        except ValueError as exc:
            notify(request,str(exc),'error')
        return redirect('/account')

    @app.get('/import/sample/{kind}.csv')
    async def csv_sample(request:Request,kind:str):
        current(request)
        fields = CUSTOMER_FIELDS if kind=='customers' else ITEM_FIELDS if kind=='items' else None
        if fields is None:raise HTTPException(404)
        stream = io.StringIO()
        stream.write('\ufeff')
        csv.writer(stream, delimiter=';').writerow(fields)
        return Response(stream.getvalue().encode('utf-8'), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':f'attachment; filename="vorlage-{kind}.csv"'})

    @app.get('/import/{kind}')
    async def import_page(request:Request, kind:str):
        current(request,'editor')
        if kind not in ('customers','items'):raise HTTPException(404)
        return view(request,'import_csv.html',kind=kind,
                    columns=(CUSTOMER_FIELDS if kind=='customers' else ITEM_FIELDS))

    @app.post('/import/{kind}')
    async def import_save(request:Request, kind:str):
        user,co=current(request,'editor')
        if kind not in ('customers','items'):raise HTTPException(404)
        data=await form(request)
        try:
            records=read_csv(data.get('file'))
            created=skipped=0
            # Entweder alle Zeilen einer CSV werden importiert oder keine.
            with transaction(db_path, True) as con:
                for index, values in records:
                    name=values.get('name','').strip()
                    if not name or len(name)>200:
                        raise ValueError(f'CSV Zeile {index}: Artikel-/Kundenname fehlt oder ist zu lang')
                    if kind=='customers':
                        values['country']=(values.get('country') or 'CH').upper()
                        if len(values['country'])!=2:
                            raise ValueError(f'CSV Zeile {index}: Land muss ISO-2-Code sein')
                        duplicate_cust=one(con, '''SELECT id FROM customers WHERE company_id=?
                            AND name=? COLLATE NOCASE AND zip=? AND city=? COLLATE NOCASE''',
                            (co['id'],name,values.get('zip',''),values.get('city','')))
                        if duplicate_cust:
                            skipped+=1;continue
                        insert_customer(con,co['id'],values)
                    else:
                        kind_value=(values.get('kind') or 'product').lower()
                        if kind_value not in ('product','service'):
                            raise ValueError(f'CSV Zeile {index}: kind muss product oder service sein')
                        mode=(values.get('tax_mode') or 'taxable').lower()
                        if mode not in ('taxable','exempt','excluded'):
                            raise ValueError(f'CSV Zeile {index}: tax_mode ungueltig')
                        sku=(values.get('sku') or 'ART-'+uuid.uuid4().hex[:8].upper()).strip()[:100]
                        if one(con,'SELECT 1 FROM items WHERE company_id=? AND sku=? COLLATE NOCASE',(co['id'],sku)):
                            skipped+=1;continue
                        cost=num(values.get('cost') or '0')
                        price=num(values.get('price') or '0')
                        tax=dec(values.get('tax_rate') or '0')
                        stock=dec(values.get('stock') or '0')
                        if cents(cost)<0 or cents(price)<0 or tax<0 or tax>100 or stock<0 or stock>1000000:
                            raise ValueError(f'CSV Zeile {index}: Preis, Steuer oder Lagerwert ungueltig')
                        if not co['tax_registered'] and tax and mode=='taxable':
                            raise ValueError(f'CSV Zeile {index}: Firma nicht MWST-pflichtig')
                        track=1 if values.get('track_stock','').lower() in ('1','ja','yes','true','x') else 0
                        con.execute('''INSERT INTO items(company_id,sku,name,kind,category,description,cost,
                            price,tax_rate,tax_mode,stock,track_stock) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (co['id'],sku,name,kind_value,values.get('category','')[:100],
                             values.get('description','')[:2000],cost,price,str(tax),mode,str(stock),track))
                    created+=1
                audit(con,co['id'],user['id'],'CSV importiert',f'{kind}: {created} neu, {skipped} uebersprungen')
            notify(request,f'CSV-Import abgeschlossen: {created} neu, {skipped} Duplikate uebersprungen')
            return redirect('/customers' if kind=='customers' else '/items')
        except (ValueError,sqlite3.IntegrityError,UnicodeError,csv.Error) as exc:
            notify(request,str(exc),'error')
            return redirect('/import/'+kind)
        finally:
            await data.close()

    def filtered_customers(con, cid, q='', group='', archived=False, sort='name'):
        if sort not in ('name','newest','city'):
            raise HTTPException(400, 'Ungueltige Sortierung')
        clauses = ['company_id=?','active=?',
            "(name LIKE ? ESCAPE '!' OR email LIKE ? ESCAPE '!' OR number LIKE ? ESCAPE '!' OR city LIKE ? ESCAPE '!')"]
        args = [cid,0 if archived else 1,*([list_query(q)]*4)]
        if group:
            clauses.append('group_name=?');args.append(group[:100])
        order={'name':'name COLLATE NOCASE,id','newest':'id DESC','city':'city COLLATE NOCASE,name COLLATE NOCASE'}[sort]
        return ' WHERE '+' AND '.join(clauses),args,order

    @app.get('/customers')
    async def customers(request:Request,q:str='',group:str='',archived:int=0,sort:str='name',page:int=1):
        user,co=current(request)
        with transaction(db_path) as con:
            where,args,order=filtered_customers(con,co['id'],q,group,archived==1,sort)
            count=one(con,'SELECT COUNT(*) AS n FROM customers'+where,args)['n']
            page,pages=checked_page(page,count)
            rows=[dict(r) for r in allrows(con,'SELECT * FROM customers'+where+' ORDER BY '+order+' LIMIT 50 OFFSET ?',(*args,(page-1)*50))]
            groups=[r['group_name'] for r in allrows(con,"SELECT DISTINCT group_name FROM customers WHERE company_id=? AND active=1 AND group_name!='' ORDER BY group_name",(co['id'],))]
        query=urlencode({'q':q,'group':group,'archived':int(archived==1),'sort':sort})
        return view(request,'customers.html',customers=rows,q=q,group=group,groups=groups,
                    archived=(archived==1),sort=sort,count=count,page=page,pages=pages,filter_query=query)

    @app.get('/customers/list.csv')
    async def customers_filtered_csv(request:Request,q:str='',group:str='',archived:int=0,sort:str='name'):
        user,co=current(request)
        with transaction(db_path) as con:
            where,args,order=filtered_customers(con,co['id'],q,group,archived==1,sort)
            rows=allrows(con,'SELECT number,name,contact,email,phone,street,building,zip,city,country,group_name,payment_days FROM customers'+where+' ORDER BY '+order,args)
        headers=['Nummer','Name','Kontakt','E-Mail','Telefon','Strasse','Hausnummer','PLZ','Ort','Land','Gruppe','Zahlungsziel Tage']
        return csv_download('kunden-auswahl.csv',headers,[[r[k] for k in r.keys()] for r in rows],numeric=(11,))

    @app.post('/customers/{rid}/restore')
    async def customer_restore(request:Request,rid:int):
        user,co=current(request,'editor');await form(request)
        with transaction(db_path,True) as con:
            row=fetch(con,'customers',co['id'],rid)
            if row['active']==0:
                con.execute('UPDATE customers SET active=1 WHERE company_id=? AND id=?',(co['id'],rid))
                audit(con,co['id'],user['id'],'Kunde reaktiviert',str(rid))
        notify(request,'Kunde wieder aktiviert')
        return redirect('/customers?archived=1')

    @app.get('/customers/new')
    async def customer_new(request:Request):
        user,co=current(request,'editor')
        return view(request,'customer_form.html',customer={},editing=False)

    @app.get('/customers/{rid}/edit')
    async def customer_edit(request:Request,rid:int):
        user,co=current(request,'editor')
        with transaction(db_path) as con:
            row=fetch(con,'customers',co['id'],rid)
        return view(request,'customer_form.html',customer=row,editing=True)

    @app.get('/customers/{rid}')
    async def customer_detail(request:Request,rid:int):
        user,co=current(request)
        with transaction(db_path) as con:
            customer=fetch(con,'customers',co['id'],rid)
            invoices=[dict(x) for x in allrows(con, '''SELECT * FROM invoices
                WHERE company_id=? AND customer_id=? ORDER BY id DESC LIMIT 200''',(co['id'],rid))]
            payments=[dict(x) for x in allrows(con, '''SELECT p.*,i.number,i.currency
                FROM payments p JOIN invoices i ON i.id=p.invoice_id AND i.company_id=p.company_id
                WHERE p.company_id=? AND i.customer_id=? ORDER BY p.id DESC LIMIT 100''',(co['id'],rid))]
        for inv in invoices:
            inv['display_status']=invoice_status(inv)
        outstanding={currency:sum((cents(i['total'])-cents(i['paid_total']) for i in invoices
                     if i['kind']=='invoice' and i['currency']==currency
                     and i['status'] not in ('draft','cancelled')) ,Decimal('0')) for currency in ('CHF','EUR')}
        return view(request,'customer_detail.html',customer=customer,invoices=invoices,
                    payments=payments,outstanding=outstanding)


    @app.get('/customers/{rid}/statement.pdf')
    async def customer_statement(request: Request, rid: int, currency: str = 'CHF',
                                 start: str = '', end: str = ''):
        user, co = current(request)
        if currency not in ('CHF','EUR'):
            raise HTTPException(400, 'Nur CHF/EUR')
        try:
            start = valid_date(start or '2000-01-01')
            end = valid_date(end or date.today().isoformat())
            if start > end:
                raise ValueError('Startdatum liegt nach Enddatum.')
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        with transaction(db_path) as con:
            customer = fetch(con, 'customers', co['id'], rid)
            invs = allrows(con, '''SELECT id,number,invoice_date,total,kind FROM invoices
                WHERE company_id=? AND customer_id=? AND currency=?
                AND kind IN ('invoice','credit') AND status NOT IN ('draft','cancelled') ''',
                (co['id'],rid,currency))
            pays = allrows(con, '''SELECT p.paid_at,p.amount,i.number FROM payments p
                JOIN invoices i ON i.id=p.invoice_id AND i.company_id=p.company_id
                WHERE p.company_id=? AND i.customer_id=? AND i.currency=?
                AND i.kind='invoice' AND i.status NOT IN ('draft','cancelled')
                AND p.reversed_at='' ''',(co['id'],rid,currency))
        events = ([{'date':i['invoice_date'],'type':'Gutschrift' if i['kind']=='credit' else 'Rechnung',
                    'number':i['number'],'delta':i['total']} for i in invs]
                  + [{'date':p['paid_at'],'type':'Zahlung','number':p['number'],
                      'delta':num(-cents(p['amount']))} for p in pays])
        try:
            content = create_customer_statement(co, customer, events, currency, start, end)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc
        return Response(content,media_type='application/pdf',headers={
            'Content-Disposition': f'inline; filename="kundenkonto-{rid}-{currency}.pdf"'})

    @app.post('/customers/save')
    async def customer_save(request:Request):
        user,co=current(request,'editor')
        data=await form(request)
        rid=int(data.get('id') or 0)
        try:
            with transaction(db_path,True) as con:
                if rid:
                    fetch(con,'customers',co['id'],rid)
                    fields=('name','contact','email','phone','street','building','zip','city','country','group_name','notes')
                    name=str(data.get('name','')).strip()
                    if not name:raise ValueError('Name fehlt')
                    vals=[str(data.get(f,'CH' if f=='country' else '')).strip()[:500] for f in fields]
                    con.execute(f"UPDATE customers SET {','.join(x+'=?' for x in fields)},payment_days=? WHERE id=? AND company_id=?",(*vals,payment_days(data),rid,co['id']))
                else:
                    rid=insert_customer(con,co['id'],data)
                audit(con,co['id'],user['id'],'Kunde gespeichert',str(rid))
            notify(request,'Kunde gespeichert')
            return redirect('/customers')
        except (ValueError,sqlite3.IntegrityError) as exc:
            notify(request,str(exc),'error')
            return redirect(f'/customers/{rid}/edit' if rid else '/customers/new')

    @app.post('/customers/{rid}/archive')
    async def customer_archive(request:Request,rid:int):
        user,co=current(request,'editor');await form(request)
        with transaction(db_path,True) as con:
            fetch(con,'customers',co['id'],rid)
            con.execute('UPDATE customers SET active=0 WHERE id=? AND company_id=?',(rid,co['id']))
            audit(con,co['id'],user['id'],'Kunde archiviert',str(rid))
        return redirect('/customers')

    def filtered_items(con, cid, q='', low=False, kind='', category='', archived=False, sort='name'):
        if kind not in ('','product','service') or sort not in ('name','newest','price','stock'):
            raise HTTPException(400, 'Ungueltiger Artikel-Filter')
        clauses=['company_id=?','active=?',"(name LIKE ? ESCAPE '!' OR sku LIKE ? ESCAPE '!' OR category LIKE ? ESCAPE '!')"]
        args=[cid,0 if archived else 1,*([list_query(q)]*3)]
        if low:
            clauses.append('track_stock=1 AND CAST(stock AS REAL)<=CAST(reorder_point AS REAL)')
        if kind:
            clauses.append('kind=?');args.append(kind)
        if category:
            clauses.append('category=?');args.append(category[:120])
        order={'name':'name COLLATE NOCASE,id','newest':'id DESC','price':'CAST(price AS REAL) DESC,id',
               'stock':'CAST(stock AS REAL) ASC,id'}[sort]
        return ' WHERE '+' AND '.join(clauses),args,order

    @app.get('/items')
    async def items(request:Request,q:str='',low:int=0,kind:str='',category:str='',archived:int=0,sort:str='name',page:int=1):
        user,co=current(request)
        with transaction(db_path) as con:
            where,args,order=filtered_items(con,co['id'],q,low==1,kind,category,archived==1,sort)
            count=one(con,'SELECT COUNT(*) AS n FROM items'+where,args)['n']
            page,pages=checked_page(page,count)
            rows=[dict(x) for x in allrows(con,'SELECT * FROM items'+where+' ORDER BY '+order+' LIMIT 50 OFFSET ?',(*args,(page-1)*50))]
            categories=[r['category'] for r in allrows(con,"SELECT DISTINCT category FROM items WHERE company_id=? AND active=1 AND category!='' ORDER BY category",(co['id'],))]
        query=urlencode({'q':q,'low':int(low==1),'kind':kind,'category':category,
                         'archived':int(archived==1),'sort':sort})
        return view(request,'items.html',items=rows,q=q,low=(low==1),kind=kind,category=category,
                    categories=categories,archived=(archived==1),sort=sort,count=count,page=page,pages=pages,filter_query=query)

    @app.get('/items/list.csv')
    async def items_filtered_csv(request:Request,q:str='',low:int=0,kind:str='',category:str='',archived:int=0,sort:str='name'):
        user,co=current(request)
        with transaction(db_path) as con:
            where,args,order=filtered_items(con,co['id'],q,low==1,kind,category,archived==1,sort)
            rows=allrows(con,'SELECT sku,name,kind,category,cost,price,tax_rate,stock,track_stock,reorder_point FROM items'+where+' ORDER BY '+order,args)
        headers=['Artikelnummer','Name','Typ','Kategorie','Einkauf','Verkauf','MWST','Lagerbestand','Lager aktiv','Mindestbestand']
        return csv_download('artikel-auswahl.csv',headers,[[r[k] for k in r.keys()] for r in rows],numeric=tuple(range(4,10)))

    @app.post('/items/{rid}/restore')
    async def item_restore(request:Request,rid:int):
        user,co=current(request,'editor');await form(request)
        with transaction(db_path,True) as con:
            row=fetch(con,'items',co['id'],rid)
            if row['active']==0:
                con.execute('UPDATE items SET active=1 WHERE company_id=? AND id=?',(co['id'],rid))
                audit(con,co['id'],user['id'],'Artikel reaktiviert',str(rid))
        notify(request,'Artikel wieder aktiviert')
        return redirect('/items?archived=1')

    @app.get('/items/low-stock.csv')
    async def stock_low_csv(request:Request):
        user,co=current(request)
        with transaction(db_path) as con:
            rows=allrows(con,"""SELECT sku,name,category,stock,reorder_point,cost,price FROM items
                WHERE company_id=? AND active=1 AND track_stock=1
                AND CAST(stock AS REAL)<=CAST(reorder_point AS REAL) ORDER BY name""",(co['id'],))
        stream=io.StringIO()
        stream.write('\ufeff')
        writer=csv.writer(stream,delimiter=';')
        writer.writerow(['Artikelnummer','Artikel','Kategorie','Lagerbestand','Mindestbestand','Einkaufspreis','Verkaufspreis'])
        for it in rows:
            writer.writerow([safe_csv(v) for v in it])
        return Response(stream.getvalue().encode('utf-8'),media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':f'attachment; filename="nachbestellliste-{co["id"]}.csv"'})

    @app.get('/items/new')
    async def item_new(request:Request):
        current(request,'editor')
        return view(request,'item_form.html',item={},editing=False)

    @app.get('/items/{rid}/stock')
    async def stock_history(request:Request, rid:int):
        user,co=current(request)
        with transaction(db_path) as con:
            item=fetch(con,'items',co['id'],rid)
            moves=[dict(x) for x in allrows(con, '''SELECT m.*,i.number AS invoice_number
                FROM stock_movements m LEFT JOIN invoices i ON i.id=m.invoice_id
                AND i.company_id=m.company_id WHERE m.company_id=? AND m.item_id=?
                ORDER BY m.id DESC LIMIT 300''',(co['id'],rid))]
        return view(request,'stock.html',item=item,movements=moves)

    @app.post('/items/{rid}/stock')
    async def stock_adjust(request:Request, rid:int):
        user,co=current(request,'editor')
        data=await form(request)
        try:
            action=str(data.get('action','add'))
            if action not in ('add','set'):
                raise ValueError('Unbekannte Lageraktion')
            quantity=dec(data.get('quantity','0'))
            if abs(quantity)>1000000:
                raise ValueError('Lagerkorrektur zu gross')
            note=str(data.get('note','')).strip()[:200]
            if len(note)<3:
                raise ValueError('Bitte Grund der Lagerkorrektur angeben (mindestens 3 Zeichen)')
            with transaction(db_path, True) as con:
                item=fetch(con,'items',co['id'],rid)
                if not item['track_stock']:
                    raise ValueError('Bestandsfuehrung fuer diesen Artikel aktivieren')
                previous=dec(item['stock'])
                changed=(quantity-previous if action=='set' else quantity)
                new=previous+changed
                if new<0 or new>1000000 or not changed:
                    raise ValueError('Resultierender Bestand muss zwischen 0 und 1 Mio. liegen und sich aendern')
                con.execute('UPDATE items SET stock=? WHERE id=? AND company_id=?',
                            (str(new),rid,co['id']))
                con.execute('INSERT INTO stock_movements(company_id,item_id,quantity,note) VALUES(?,?,?,?)',
                            (co['id'],rid,str(changed),'Manuell: '+note))
                audit(con,co['id'],user['id'],'Bestand korrigiert',f'{item["sku"]}: {previous} -> {new}')
            notify(request,'Bestand erfolgreich angepasst und protokolliert')
        except ValueError as exc:
            notify(request,str(exc),'error')
        return redirect(f'/items/{rid}/stock')

    @app.get('/items/{rid}/edit')
    async def item_edit(request:Request,rid:int):
        user,co=current(request,'editor')
        with transaction(db_path) as con:
            it=fetch(con,'items',co['id'],rid)
        return view(request,'item_form.html',item=it,editing=True)

    @app.post('/items/save')
    async def item_save(request:Request):
        user,co=current(request,'editor')
        data=await form(request)
        rid=int(data.get('id') or 0)
        try:
            name=str(data.get('name','')).strip()
            if not name:raise ValueError('Artikelname fehlt')
            price=num(data.get('price','0'));cost=num(data.get('cost','0'))
            stock=str(dec(data.get('stock','0')))
            reorder_point=dec(data.get('reorder_point','5') or '5')
            if reorder_point<0 or reorder_point>1000000:
                raise ValueError('Mindestbestand muss zwischen 0 und 1 Million liegen')
            reorder_point=str(reorder_point)
            tax=str(dec(data.get('tax_rate','0')))
            if data.get('tax_mode','taxable') not in ('taxable','exempt','excluded'):
                raise ValueError('MWST-Behandlung ungueltig')
            if dec(price)<0 or dec(cost)<0 or dec(stock)<0:
                raise ValueError('Preis, Kosten und Bestand duerfen nicht negativ sein')
            fields=('sku','name','kind','category','description','cost','price','tax_rate','tax_mode','stock','track_stock','reorder_point','image_path')
            with transaction(db_path,True) as con:
                existing=fetch(con,'items',co['id'],rid) if rid else None
                img=item_image(con,co['id'],data.get('image'),existing['image_path'] if existing else '')
                values=[str(data.get('sku','')).strip() or 'ART-'+uuid.uuid4().hex[:8].upper(),name,
                        str(data.get('kind','product')),str(data.get('category',''))[:100],
                        str(data.get('description',''))[:2000],cost,price,tax,str(data.get('tax_mode','taxable')),stock,
                        1 if data.get('track_stock') else 0,reorder_point,img]
                if rid:
                    con.execute('UPDATE items SET '+','.join(f+'=?' for f in fields)+' WHERE id=? AND company_id=?',(*values,rid,co['id']))
                    if dec(stock) != dec(existing['stock']):
                        con.execute('INSERT INTO stock_movements(company_id,item_id,quantity,note) VALUES(?,?,?,?)',
                                    (co['id'],rid,str(dec(stock)-dec(existing['stock'])),'Manuelle Bestandskorrektur'))
                else:
                    con.execute('INSERT INTO items(company_id,'+','.join(fields)+') VALUES(?,'+','.join('?' for _ in fields)+')',(co['id'],*values))
                    rid=con.execute('SELECT last_insert_rowid()').fetchone()[0]
                audit(con,co['id'],user['id'],'Artikel gespeichert',str(rid))
            notify(request,'Artikel gespeichert')
            return redirect('/items')
        except (ValueError,sqlite3.IntegrityError) as exc:
            notify(request,str(exc),'error')
            return redirect(f'/items/{rid}/edit' if rid else '/items/new')

    @app.post('/items/{rid}/archive')
    async def item_archive(request:Request,rid:int):
        user,co=current(request,'editor');await form(request)
        with transaction(db_path,True) as con:
            fetch(con,'items',co['id'],rid)
            con.execute('UPDATE items SET active=0 WHERE id=? AND company_id=?',(rid,co['id']))
        return redirect('/items')

    @app.get('/media/item/{rid}')
    async def item_media(request:Request,rid:int):
        user,co=current(request)
        with transaction(db_path) as con:
            obj=fetch(con,'items',co['id'],rid)
        if not obj['image_path']:raise HTTPException(404)
        path=(root / obj['image_path']).resolve()
        if not path.is_relative_to((root/'uploads').resolve()) or not path.exists():
            raise HTTPException(404)
        return FileResponse(path,media_type='image/jpeg')

    @app.get('/media/app-logo')
    async def app_brand_logo(request:Request):
        user, company = current(request)
        path = company_logo_path(root, company)
        if not path:
            raise HTTPException(404, 'Kein Logo fuer dieses Geschaeft')
        return FileResponse(path, media_type='image/png' if path.suffix.lower()=='.png' else 'image/jpeg',
                            headers={'Cache-Control':'no-store, private'})

    @app.get('/media/login-logo')
    async def public_login_logo(request:Request):
        # Das einzige vor dem Login sichtbare Logo ist installationsweit und
        # nur vom Hauptadministrator bearbeitbar. Keine Konten/Filialen verraten.
        path = site_logo_path(root)
        if not path:
            raise HTTPException(404)
        return FileResponse(path, media_type='image/png', headers={'Cache-Control':'no-store'})

    @app.get('/media/logo')
    async def logo_media(request:Request):
        user,co=current(request)
        path=document_logo_path(root, co)
        if not path:
            raise HTTPException(404)
        return FileResponse(path,media_type='image/png' if path.suffix.lower()=='.png' else 'image/jpeg',
                            headers={'Cache-Control':'no-store, private'})

    def filtered_invoices(con, cid, kind, q='', status='', currency='', date_from='', date_to='', sort='newest'):
        """Build one parameterized filter for the on-screen list and its CSV export."""
        if kind not in ('invoice','quote','credit'):
            raise HTTPException(400, 'Ungueltige Belegart')
        if status not in ('','draft','sent','partial','paid','overdue','cancelled'):
            raise HTTPException(400, 'Ungueltiger Statusfilter')
        if currency not in ('','CHF','EUR'):
            raise HTTPException(400, 'Ungueltige Waehrung')
        if sort not in ('newest','oldest','due','amount'):
            raise HTTPException(400, 'Ungueltige Sortierung')
        try:
            date_from = valid_date(date_from) if date_from else ''
            date_to = valid_date(date_to) if date_to else ''
        except ValueError as exc:
            raise HTTPException(400, 'Ungueltiger Datumsfilter') from exc
        if date_from and date_to and date_from > date_to:
            raise HTTPException(400, 'Startdatum liegt nach dem Enddatum')
        # Escape % and _ so search means literal text, not SQL wildcards.
        search = '%' + str(q or '').strip()[:80].replace('!', '!!').replace('%','!%').replace('_','!_') + '%'
        conditions = ['i.company_id=?','i.kind=?',
            "(i.number LIKE ? ESCAPE '!' OR c.name LIKE ? ESCAPE '!' OR i.subject LIKE ? ESCAPE '!')"]
        params = [cid, kind, search, search, search]
        if currency:
            conditions.append('i.currency=?'); params.append(currency)
        if date_from:
            conditions.append('i.invoice_date>=?'); params.append(date_from)
        if date_to:
            conditions.append('i.invoice_date<=?'); params.append(date_to)
        # Status mirrors billing.invoice_status, with the filter applied BEFORE pagination.
        expr = ("CASE WHEN i.status IN ('draft','cancelled') THEN i.status "
                "WHEN i.kind='quote' THEN 'sent' "
                "WHEN CAST(i.total AS REAL)>0 AND CAST(i.paid_total AS REAL)>=CAST(i.total AS REAL) THEN 'paid' "
                "WHEN i.kind='invoice' AND i.due_date<? THEN 'overdue' "
                "WHEN CAST(i.paid_total AS REAL)>0 THEN 'partial' ELSE 'sent' END")
        if status:
            conditions.append('('+expr+')=?')
            params.extend([date.today().isoformat(),status])
        where=' AND '.join(conditions)
        base=' FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id AND c.company_id=i.company_id WHERE '+where
        order={'newest':'i.invoice_date DESC,i.id DESC','oldest':'i.invoice_date ASC,i.id ASC',
               'due':'i.due_date ASC,i.id DESC',
               'amount':'CAST(i.total AS REAL) DESC,i.id DESC'}[sort]
        return base,params,order

    @app.get('/invoices')
    async def invoice_list(request:Request,kind:str='invoice',q:str='',status:str='',
                           currency:str='',date_from:str='',date_to:str='',sort:str='newest',page:int=1):
        user,co=current(request)
        with transaction(db_path) as con:
            base,params,order=filtered_invoices(con,co['id'],kind,q,status,currency,date_from,date_to,sort)
            count=con.execute('SELECT COUNT(*) '+base,params).fetchone()[0]
            pages=max(1,(count+24)//25)
            page=min(max(page,1),pages)
            records=[dict(x) for x in allrows(con,
                'SELECT i.*,c.name AS customer_name '+base+' ORDER BY '+order+' LIMIT 25 OFFSET ?',
                (*params,25*(page-1)))]
        for inv in records:
            inv['display_status']=invoice_status(inv)
        sums={}
        for inv in records:
            curr=inv['currency']
            if curr not in sums:sums[curr]={'total':Decimal('0'),'open':Decimal('0')}
            sums[curr]['total']+=cents(inv['total'])
            if inv['kind']=='invoice' and inv['status'] not in ('draft','cancelled'):
                sums[curr]['open']+=cents(inv['total'])-cents(inv['paid_total'])
        return view(request,'invoices.html',invoices=records,kind=kind,q=q,status=status,
                    currency=currency,date_from=date_from,date_to=date_to,sort=sort,
                    page=page,pages=pages,count=count,page_sums=sums,
                    filter_query=urlencode({'kind':kind,'q':q,'status':status,'currency':currency,
                        'date_from':date_from,'date_to':date_to,'sort':sort}))

    @app.get('/invoices/list.csv')
    async def invoice_list_csv(request:Request,kind:str='invoice',q:str='',status:str='',
                               currency:str='',date_from:str='',date_to:str='',sort:str='newest'):
        user,co=current(request)
        with transaction(db_path) as con:
            base,params,order=filtered_invoices(con,co['id'],kind,q,status,currency,date_from,date_to,sort)
            rows=allrows(con,'SELECT i.*,c.name AS customer_name '+base+' ORDER BY '+order,params)
        cols=['number','customer_name','subject','invoice_date','due_date','display_status',
              'currency','subtotal','tax_total','total','paid_total','open']
        stream=io.StringIO()
        stream.write('\ufeff')
        writer=csv.writer(stream,delimiter=';')
        writer.writerow(['Belegnummer','Kunde','Betreff','Datum','Faellig','Status','Waehrung',
                         'Netto','MWST','Total','Bezahlt','Offen'])
        for r in rows:
            inv=dict(r)
            inv['display_status']=invoice_status(inv)
            inv['open']=num(cents(inv['total'])-cents(inv['paid_total'])) if inv['kind']=='invoice' and inv['status'] not in ('draft','cancelled') else '0.00'
            writer.writerow([safe_csv(inv[c],c in ('subtotal','tax_total','total','paid_total','open')) for c in cols])
        return Response(stream.getvalue().encode('utf-8'),media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':f'attachment; filename="belege-{kind}-{co["id"]}.csv"'})

    @app.get('/invoices/new')
    async def invoice_new(request:Request,kind:str='invoice',customer_id:int=0):
        user,co=current(request,'editor')
        if kind not in ('invoice','quote','credit'):raise HTTPException(400)
        with transaction(db_path) as con:
            cust=[dict(r) for r in allrows(con,'SELECT * FROM customers WHERE company_id=? AND active=1 ORDER BY name',(co['id'],))]
            article=[dict(r) for r in allrows(con,'SELECT * FROM items WHERE company_id=? AND active=1 ORDER BY name',(co['id'],))]
            suggestion,_=peek_number(con,co['id'],kind,co,date.today().year)
            selected_customer=next((x for x in cust if x['id']==customer_id),None)
            if customer_id and selected_customer is None:
                raise HTTPException(404,'Kunde nicht in diesem Geschaeft gefunden')
            default_days=(selected_customer['payment_days'] or co['default_due_days']) if selected_customer else co['default_due_days']
        return view(request,'invoice_form.html',number_hint=suggestion,invoice={'kind':kind,'invoice_date':date.today().isoformat(),
                     'service_date':date.today().isoformat(),'due_date':future(default_days),
                     'currency':co['currency'],'discount':'0','customer_id':customer_id or None,
                     'notes':co['default_invoice_notes'] if kind=='invoice' else ''},
                     lines=[{'description':'','qty':'-1' if kind=='credit' else '1','unit':'Stk.','price':'0.00',
                             'tax_rate':co['default_tax'] if co['tax_registered'] else '0',
                             'discount':'0','item_id':''}],
                     customers=cust,items=article,editing=False)

    @app.get('/invoices/{rid}/edit')
    async def invoice_edit(request:Request,rid:int):
        user,co=current(request,'editor')
        with transaction(db_path) as con:
            inv=fetch(con,'invoices',co['id'],rid)
            if inv['status']!='draft':
                notify(request,'Freigegebene Belege koennen nicht veraendert werden; bitte kopieren.','error')
                return redirect(f'/invoices/{rid}')
            lines=[dict(r) for r in allrows(con,'SELECT * FROM invoice_lines WHERE company_id=? AND invoice_id=? ORDER BY position',(co['id'],rid))]
            cust=[dict(r) for r in allrows(con,'SELECT * FROM customers WHERE company_id=? AND active=1 ORDER BY name',(co['id'],))]
            article=[dict(r) for r in allrows(con,'SELECT * FROM items WHERE company_id=? AND active=1 ORDER BY name',(co['id'],))]
        return view(request,'invoice_form.html',invoice=inv,number_hint=inv['number'],lines=lines,customers=cust,items=article,editing=True)

    @app.get('/api/invoices/check-number')
    async def check_invoice_number(request:Request,number:str='',exclude_id:int=0):
        user,co=current(request,'editor')
        from .numbering import valid_number, is_taken
        try:
            number=valid_number(number)
        except ValueError as exc:
            return {'available':False,'message':str(exc)}
        with transaction(db_path) as con:
            if exclude_id:
                inv=fetch(con,'invoices',co['id'],exclude_id)
                if inv['status']!='draft':
                    return {'available':False,'message':'Nur im Entwurf aenderbar.'}
            taken=is_taken(con,co['id'],number,exclude_id or None)
        return {'available':not taken,'message': 'Nummer ist frei.' if not taken else 'Diese Belegnummer wird bereits verwendet.'}

    @app.post('/invoices/preview.pdf')
    async def invoice_unsaved_preview(request:Request):
        user,co=current(request,'editor')
        data=await form(request)
        kind=str(data.get('kind','invoice'))
        if kind not in ('invoice','quote','credit'):
            raise HTTPException(400,'Ungueltige Belegart')
        rid=int(data.get('id') or 0)
        try:
            with transaction(db_path) as con:
                if rid:
                    old=fetch(con,'invoices',co['id'],rid)
                    if old['status']!='draft' or old['kind']!=kind:
                        raise ValueError('Nur bearbeitbare Entwuerfe duerfen angezeigt werden.')
                if str(data.get('new_customer_name') or '').strip():
                    cust={field:str(data.get('new_customer_'+field,'')).strip() for field in
                          ('name','email','street','building','zip','city','country')}
                else:
                    cust=customer_snapshot(con,co['id'],data.get('customer_id'))
                lines=parse_lines(data,kind,bool(co['tax_registered']))
                result=summarize(lines,data.get('discount','0'))
                if not result['lines']:
                    raise ValueError('Bitte mindestens eine Rechnungsposition erfassen.')
                if kind=='credit' and cents(result['total'])>=0:
                    raise ValueError('Eine Gutschrift benoetigt einen negativen Betrag.')
                number=str(data.get('number','')).strip()
                from .numbering import valid_number
                if number:
                    number=valid_number(number)
                else:
                    number=peek_number(con,co['id'],kind,co,int(valid_date(data.get('invoice_date'))[:4]))[0]
            currency=str(data.get('currency','CHF')).upper()
            if currency not in ('CHF','EUR'):
                raise ValueError('Nur CHF oder EUR erlaubt.')
            invoice={'kind':kind,'number':number,'invoice_date':valid_date(data.get('invoice_date')),
                     'service_date':valid_date(data.get('service_date')) if data.get('service_date') else '',
                     'due_date':valid_date(data.get('due_date')),'currency':currency,
                     'subject':str(data.get('subject','')).strip()[:140],
                     'notes':str(data.get('notes',''))[:3000],
                     'subtotal':result['subtotal'],'tax_total':result['tax_total'],
                     'total':result['total'],'tax_breakdown':json.dumps(result['tax_breakdown'])}
            company=dict(co)
            # Nicht versandfaehig: bewusst kein bezahlbarer QR-Zahlteil vor Freigabe.
            company['iban']=''
            doc_logo = document_logo_path(root, company)
            company['logo_path'] = str(doc_logo) if doc_logo else ''
            company['designer_asset_root']=str(root/'uploads'/'designs'/str(co['id']))
            pdf,_=make_pdf(invoice,company,cust,result['lines'],preview=True)
            return Response(pdf,media_type='application/pdf',headers={
                'Content-Disposition':'inline; filename="RECHNUNG_VORSCHAU.pdf"'})
        except (ValueError,OverflowError,TypeError) as exc:
            raise HTTPException(422,'PDF-Vorschau: '+str(exc))

    @app.post('/invoices/save')
    async def invoice_save(request:Request):
        user,co=current(request,'editor')
        data=await form(request)
        rid=int(data.get('id') or 0)
        kind=str(data.get('kind','invoice'))
        if kind not in ('invoice','quote','credit'):raise HTTPException(400)
        try:
            with transaction(db_path,True) as con:
                existing=fetch(con,'invoices',co['id'],rid) if rid else None
                if existing and (existing['status']!='draft' or existing['kind'] != kind):
                    raise ValueError('Beleg ist nicht mehr bearbeitbar')
                iid=write_invoice(con,co['id'],data,kind,co,existing,user['id'])
            notify(request,'Entwurf gespeichert')
            return redirect(f'/invoices/{iid}')
        except (ValueError,sqlite3.IntegrityError) as exc:
            if rid:
                with transaction(db_path) as con:
                    state=fetch(con,'invoices',co['id'],rid)
                if state['status']!='draft':
                    notify(request,'Freigegebener Beleg bleibt unveraenderbar. Bitte kopieren.','error')
                    return redirect(f'/invoices/{rid}')
            # Eingaben bei einem Fehler nicht wegwerfen: ein wichtiger Editor-Workflow.
            with transaction(db_path) as con:
                cust=[dict(r) for r in allrows(con,'SELECT * FROM customers WHERE company_id=? AND active=1 ORDER BY name',(co['id'],))]
                article=[dict(r) for r in allrows(con,'SELECT * FROM items WHERE company_id=? AND active=1 ORDER BY name',(co['id'],))]
                suggestion,_=peek_number(con,co['id'],kind,co,date.today().year)
            invoice={k:str(data.get(k,'')).strip() for k in (
                'number','invoice_date','service_date','due_date','currency','subject','notes','discount',
                'new_customer_name','new_customer_email','new_customer_street',
                'new_customer_building','new_customer_zip','new_customer_city','new_customer_country','new_customer_payment_days')}
            invoice.update(id=rid or None,kind=kind,customer_id=str(data.get('customer_id','')))
            columns=('description','qty','unit','price','tax_rate','tax_mode','discount','item_id')
            groups={k:data.getlist(k+'[]') for k in columns}
            line_count=min(150,max((len(a) for a in groups.values()),default=0))
            lines=[{k:(groups[k][i] if i<len(groups[k]) else '') for k in columns}
                   for i in range(line_count)]
            if not lines:
                lines=[{'description':'','qty':'1','unit':'Stk.','price':'0','tax_rate':co['default_tax'],
                        'tax_mode':'taxable','discount':'0','item_id':''}]
            return view(request,'invoice_form.html',invoice=invoice,
                        number_hint=invoice['number'] or suggestion,lines=lines,customers=cust,
                        items=article,editing=bool(rid),error_inline=str(exc))

    @app.get('/invoices/{rid}')
    async def invoice_detail(request:Request,rid:int):
        user,co=current(request)
        with transaction(db_path) as con:
            inv=fetch(con,'invoices',co['id'],rid)
            cust=to_dict(one(con,'SELECT * FROM customers WHERE id=? AND company_id=?',(inv['customer_id'],co['id'])))
            if inv['customer_snapshot']!='{}':cust=json.loads(inv['customer_snapshot'])
            lines=[dict(r) for r in allrows(con,'SELECT * FROM invoice_lines WHERE invoice_id=? AND company_id=? ORDER BY position',(rid,co['id']))]
            payments=[dict(r) for r in allrows(con,'SELECT * FROM payments WHERE invoice_id=? AND company_id=? ORDER BY paid_at DESC',(rid,co['id']))]
            reminders=[dict(r) for r in allrows(con,'SELECT * FROM reminders WHERE invoice_id=? AND company_id=? ORDER BY id DESC',(rid,co['id']))]
            recurring=to_dict(one(con,'SELECT * FROM recurrings WHERE source_invoice_id=? AND company_id=?',(rid,co['id'])))
            used_ids={r['item_id'] for r in lines if r['item_id']}
            items_by_id={i:fetch(con,'items',co['id'],i) for i in used_ids}
            preflight=invoice_checks(inv,co,cust,lines,items_by_id) if inv['status']=='draft' else []
        inv['display_status']=invoice_status(inv)
        return view(request,'invoice_detail.html',invoice=inv,customer=cust,lines=lines,payments=payments,
                    reminders=reminders,recurring=recurring,preflight=preflight,balance=cents(inv['total'])-cents(inv['paid_total']))

    @app.post('/invoices/{rid}/issue')
    async def issue(request:Request,rid:int):
        user,co=current(request,'editor');await form(request)
        try:
            with transaction(db_path,True) as con:
                inv=fetch(con,'invoices',co['id'],rid)
                has_qr=issue_invoice(con,co['id'],inv,co,user['id'])
            notify(request,'Beleg freigegeben und als PDF archiviert.' + ('' if has_qr or inv['kind']!='invoice' else ' Ohne hinterlegte IBAN kein QR-Zahlteil!'))
        except (ValueError,OSError,sqlite3.IntegrityError) as exc:
            notify(request,str(exc),'error')
        return redirect(f'/invoices/{rid}')

    @app.post('/invoices/{rid}/copy')
    async def copy_invoice(request:Request,rid:int):
        user,co=current(request,'editor')
        data=await form(request)
        action=str(data.get('action','copy'))
        kind={'copy':None,'convert':'invoice','credit':'credit'}.get(action)
        if action not in ('copy','convert','credit'):raise HTTPException(400)
        with transaction(db_path,True) as con:
            src=fetch(con,'invoices',co['id'],rid)
            if action=='credit' and (src['status']=='draft' or src['kind']!='invoice'):
                raise HTTPException(400)
            if action=='convert' and src['kind']!='quote':
                raise HTTPException(400)
            iid=duplicate(con,co['id'],src,kind or src['kind'],co,user['id'],credit=action=='credit')
        notify(request,'Neuer bearbeitbarer Entwurf erstellt')
        return redirect(f'/invoices/{iid}/edit')

    @app.post('/invoices/{rid}/cancel')
    async def cancel_invoice(request:Request,rid:int):
        user,co=current(request,'admin');await form(request)
        with transaction(db_path,True) as con:
            inv=fetch(con,'invoices',co['id'],rid)
            if dec(inv['paid_total'])>0:raise HTTPException(400,'Bezahlte Rechnungen duerfen nicht storniert werden; Gutschrift erstellen')
            if inv['status']=='cancelled':raise HTTPException(400)
            if inv['kind']=='invoice' and inv['status']!='draft':
                moves=allrows(con,'SELECT item_id,quantity FROM stock_movements WHERE invoice_id=? AND company_id=?',(rid,co['id']))
                for mv in moves:
                    itm=fetch(con,'items',co['id'],mv['item_id'])
                    delta=-dec(mv['quantity'])
                    con.execute('UPDATE items SET stock=? WHERE id=? AND company_id=?',(str(dec(itm['stock'])+delta),mv['item_id'],co['id']))
                    con.execute('INSERT INTO stock_movements(company_id,item_id,invoice_id,quantity,note) VALUES(?,?,?,?,?)',
                                (co['id'],mv['item_id'],None,str(delta),'Storno '+inv['number']))
                # Originalbewegungen bleiben fuer eine lueckenlose Lagerhistorie erhalten.
            con.execute("UPDATE invoices SET status='cancelled' WHERE id=? AND company_id=?",(rid,co['id']))
            audit(con,co['id'],user['id'],'Beleg storniert',inv['number'])
        return redirect(f'/invoices/{rid}')

    @app.get('/invoices/{rid}/pdf')
    async def invoice_pdf(request:Request,rid:int):
        user,co=current(request)
        with transaction(db_path) as con:
            inv=fetch(con,'invoices',co['id'],rid)
            if inv['pdf_file']:
                path=(root / inv['pdf_file']).resolve()
                if not path.is_relative_to((root/'archive').resolve()) or not path.exists():
                    raise HTTPException(404,'Archivdatei fehlt')
                if hashlib.sha256(path.read_bytes()).hexdigest()!=inv['pdf_sha256']:
                    raise HTTPException(409,'Archiv-PDF wurde geaendert! Bitte Backup pruefen.')
                return FileResponse(path, media_type='application/pdf',filename=inv['number']+'.pdf')
            try:
                pdf,qr=pdf_for(con,inv,co,co['id'],preview=inv['status']=='draft')
            except ValueError as exc:
                notify(request,str(exc),'error')
                return redirect(f'/invoices/{rid}')
        return Response(content=pdf,media_type='application/pdf',headers={
            'Content-Disposition': 'inline; filename="'+inv['number']+'.pdf"'})

    @app.post('/invoices/{rid}/payment')
    async def payment(request:Request,rid:int):
        user,co=current(request,'editor');data=await form(request)
        try:
            amount=cents(data.get('amount','0'))
            if amount<=0:raise ValueError('Zahlung muss positiv sein')
            when=valid_date(data.get('paid_at',date.today().isoformat()))
            with transaction(db_path,True) as con:
                inv=fetch(con,'invoices',co['id'],rid)
                if inv['kind']!='invoice' or inv['status'] in ('draft','cancelled'):
                    raise ValueError('Zahlungen nur fuer freigegebene Rechnungen')
                outstanding=cents(inv['total'])-cents(inv['paid_total'])
                if amount>outstanding:
                    raise ValueError('Zahlung uebersteigt offenen Betrag')
                con.execute('INSERT INTO payments(company_id,invoice_id,paid_at,amount,method,note) VALUES(?,?,?,?,?,?)',
                            (co['id'],rid,when,num(amount),str(data.get('method','Bank'))[:30],str(data.get('note',''))[:300]))
                con.execute('UPDATE invoices SET paid_total=? WHERE id=? AND company_id=?',
                            (num(cents(inv['paid_total'])+amount),rid,co['id']))
                audit(con,co['id'],user['id'],'Zahlung gebucht',inv['number']+' '+num(amount))
            notify(request,'Zahlung erfasst')
        except ValueError as exc:
            notify(request,str(exc),'error')
        return redirect(f'/invoices/{rid}')

    @app.post('/invoices/{rid}/payments/{payment_id}/reverse')
    async def reverse_payment(request:Request, rid:int, payment_id:int):
        user,co=current(request,'admin')
        data=await form(request)
        reason=str(data.get('reason','')).strip()[:300]
        try:
            if len(reason)<5:
                raise ValueError('Bitte einen Stornogrund mit mindestens 5 Zeichen angeben')
            with transaction(db_path, True) as con:
                inv=fetch(con,'invoices',co['id'],rid)
                if inv['kind']!='invoice' or inv['status'] in ('draft','cancelled'):
                    raise ValueError('Kein gueltiger Zahlungsvorgang')
                payment=one(con,'''SELECT * FROM payments
                    WHERE id=? AND invoice_id=? AND company_id=?''',(payment_id,rid,co['id']))
                if not payment or payment['reversed_at']:
                    raise ValueError('Zahlung nicht gefunden oder bereits storniert')
                con.execute('''UPDATE payments SET reversed_at=?,reversed_by=?,reversal_note=?
                    WHERE id=? AND invoice_id=? AND company_id=? AND reversed_at='' ''',
                    (datetime.now().isoformat(),user['id'],reason,payment_id,rid,co['id']))
                active=allrows(con,'''SELECT amount FROM payments
                    WHERE invoice_id=? AND company_id=? AND reversed_at='' ''',(rid,co['id']))
                new_paid=sum((cents(p['amount']) for p in active),Decimal('0'))
                con.execute('UPDATE invoices SET paid_total=? WHERE id=? AND company_id=?',
                            (num(new_paid),rid,co['id']))
                con.execute('''UPDATE bank_transactions
                    SET status='open',payment_id=NULL
                    WHERE company_id=? AND payment_id=? AND status='matched' ''',
                    (co['id'],payment_id))
                audit(con,co['id'],user['id'],'Zahlung storniert',
                      f'{inv["number"]}: {payment["amount"]} {inv["currency"]}; {reason}')
            notify(request,'Zahlungsstorno protokolliert; offener Saldo neu berechnet')
        except ValueError as exc:
            notify(request,str(exc),'error')
        return redirect(f'/invoices/{rid}')

    @app.post('/invoices/{rid}/reminder')
    async def reminder(request:Request,rid:int):
        user,co=current(request,'editor')
        data=await form(request)
        try:
            with transaction(db_path,True) as con:
                inv=fetch(con,'invoices',co['id'],rid)
                balance=cents(inv['total'])-cents(inv['paid_total'])
                if inv['kind']!='invoice' or inv['status'] in ('draft','cancelled') or balance<=0:
                    raise ValueError('Keine mahnfaehige Rechnung')
                level=one(con,'''SELECT COUNT(*) AS n FROM reminders
                    WHERE company_id=? AND invoice_id=?''',(co['id'],rid))['n']+1
                reminder_row={'level':level,'sent_at':date.today().isoformat(),
                              'note':str(data.get('note','')).strip()[:300]}
                if inv['customer_snapshot']!='{}':
                    customer=json.loads(inv['customer_snapshot'])
                else:
                    customer=customer_snapshot(con,co['id'],inv['customer_id'])
                comp=dict(co)
                doc_logo = document_logo_path(root, comp)
                comp['logo_path'] = str(doc_logo) if doc_logo else ''
                pdf_bytes,qr=make_reminder_pdf(inv,comp,customer,reminder_row,balance)
                con.execute('''INSERT INTO reminders(company_id,invoice_id,level,sent_at,note,balance_at)
                    VALUES(?,?,?,?,?,?)''',(co['id'],rid,level,reminder_row['sent_at'],
                                           reminder_row['note'],num(balance)))
                mid=con.execute('SELECT last_insert_rowid()').fetchone()[0]
                dest_dir=root/'archive'/str(co['id'])/'reminders'
                dest_dir.mkdir(parents=True,exist_ok=True)
                dest=dest_dir/f'{rid:08d}-{mid:08d}.pdf'
                tmp=dest.with_suffix('.tmp')
                tmp.write_bytes(pdf_bytes)
                os.replace(tmp,dest)
                con.execute('''UPDATE reminders SET pdf_file=?,pdf_sha256=? WHERE id=? AND company_id=?''',
                            (str(dest.relative_to(root)),hashlib.sha256(pdf_bytes).hexdigest(),mid,co['id']))
                audit(con,co['id'],user['id'],'Mahn-PDF erstellt',inv['number']+' #'+str(level))
            notify(request,'Mahn-PDF erstellt und archiviert (kein automatischer Versand)')
        except (ValueError,OSError,sqlite3.IntegrityError) as exc:
            notify(request,str(exc),'error')
        return redirect(f'/invoices/{rid}')

    @app.get('/invoices/{rid}/reminders/{reminder_id}/pdf')
    async def reminder_pdf_download(request:Request, rid:int, reminder_id:int):
        user,co=current(request)
        with transaction(db_path) as con:
            fetch(con,'invoices',co['id'],rid)
            reminder_row=one(con,'''SELECT * FROM reminders
                WHERE id=? AND invoice_id=? AND company_id=?''',(reminder_id,rid,co['id']))
        if not reminder_row or not reminder_row['pdf_file']:
            raise HTTPException(404,'Mahn-PDF nicht gefunden')
        path=(root/reminder_row['pdf_file']).resolve()
        expected=(root/'archive'/str(co['id'])/'reminders').resolve()
        if not path.is_relative_to(expected) or not path.is_file():
            raise HTTPException(404,'Archivierte Mahnung fehlt')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=reminder_row['pdf_sha256']:
            raise HTTPException(409,'Mahn-PDF wurde veraendert. Bitte Backup pruefen.')
        return FileResponse(path,media_type='application/pdf',
                            filename=f'mahnung-{rid}-{reminder_id}.pdf')

    @app.post('/invoices/{rid}/recurring')
    async def recurring_save(request:Request,rid:int):
        user,co=current(request,'editor');data=await form(request)
        months=int(data.get('interval_months',1))
        if not (1<=months<=36):raise HTTPException(400)
        next_date=valid_date(data.get('next_date'))
        with transaction(db_path,True) as con:
            inv=fetch(con,'invoices',co['id'],rid)
            if inv['kind']!='invoice':raise HTTPException(400)
            con.execute('''INSERT INTO recurrings(company_id,source_invoice_id,interval_months,next_date,active)
                VALUES(?,?,?,?,1) ON CONFLICT DO NOTHING''',(co['id'],rid,months,next_date))
            con.execute('UPDATE recurrings SET interval_months=?,next_date=?,active=1 WHERE company_id=? AND source_invoice_id=?',
                        (months,next_date,co['id'],rid))
        return redirect('/recurring')

    @app.get('/recurring')
    async def recurring_index(request:Request,status:str='active',q:str=''):
        user,co=current(request)
        if status not in ('active','paused','all'):
            raise HTTPException(400,'Ungueltiger Status')
        conditions=['r.company_id=?',"(i.number LIKE ? ESCAPE '!' OR c.name LIKE ? ESCAPE '!')"]
        args=[co['id'],list_query(q),list_query(q)]
        if status!='all':
            conditions.append('r.active=?');args.append(int(status=='active'))
        with transaction(db_path) as con:
            rows=[dict(x) for x in allrows(con,'''SELECT r.*,i.number,i.total,i.currency,c.name AS customer_name
                FROM recurrings r JOIN invoices i ON i.id=r.source_invoice_id AND i.company_id=r.company_id
                LEFT JOIN customers c ON c.id=i.customer_id AND c.company_id=r.company_id
                WHERE '''+' AND '.join(conditions)+' ORDER BY r.active DESC,r.next_date ASC LIMIT 300',args)]
            active_count=one(con,'SELECT COUNT(*) AS n FROM recurrings WHERE company_id=? AND active=1',(co['id'],))['n']
            paused_count=one(con,'SELECT COUNT(*) AS n FROM recurrings WHERE company_id=? AND active=0',(co['id'],))['n']
        for row in rows:
            row['due']=bool(row['active'] and row['next_date']<=date.today().isoformat())
        return view(request,'recurring.html',recurrings=rows,selected_status=status,q=q,
                    active_count=active_count,paused_count=paused_count)

    @app.post('/recurring/{rid}/schedule')
    async def recurring_schedule(request:Request,rid:int):
        user,co=current(request,'editor')
        data=await form(request)
        try:
            months=int(str(data.get('interval_months','')))
            if months not in (1,2,3,6,12):
                raise ValueError('Erlaubte Intervalle: 1, 2, 3, 6 oder 12 Monate')
            next_date=valid_date(str(data.get('next_date','')))
            if not 2000<=int(next_date[:4])<=2100:
                raise ValueError('Datum ausserhalb des erlaubten Bereichs')
        except (ValueError, TypeError) as exc:
            notify(request,str(exc),'error');return redirect('/recurring?status=all')
        with transaction(db_path,True) as con:
            fetch(con,'recurrings',co['id'],rid)
            con.execute('UPDATE recurrings SET interval_months=?,next_date=? WHERE company_id=? AND id=?',
                        (months,next_date,co['id'],rid))
            audit(con,co['id'],user['id'],'Wiederholung angepasst',str(rid))
        notify(request,'Wiederholung aktualisiert')
        return redirect('/recurring?status=all')

    @app.post('/recurring/{rid}/resume')
    async def recurring_resume(request:Request,rid:int):
        user,co=current(request,'editor');await form(request)
        with transaction(db_path,True) as con:
            fetch(con,'recurrings',co['id'],rid)
            con.execute('UPDATE recurrings SET active=1 WHERE company_id=? AND id=?',(co['id'],rid))
            audit(con,co['id'],user['id'],'Wiederholung fortgesetzt',str(rid))
        notify(request,'Wiederholung aktiviert')
        return redirect('/recurring?status=all')

    @app.post('/recurring/{rid}/generate')
    async def recurring_generate(request:Request,rid:int):
        user,co=current(request,'editor');await form(request)
        with transaction(db_path,True) as con:
            rec=fetch(con,'recurrings',co['id'],rid)
            if not rec['active']:
                raise HTTPException(409,'Pausierte Wiederholung zuerst aktivieren')
            src=fetch(con,'invoices',co['id'],rec['source_invoice_id'])
            iid=duplicate(con,co['id'],src,'invoice',co,user['id'])
            # monatlich ohne Zusatzpaket: Kalendermonat sicher auf letzten Tag begrenzen
            d=date.fromisoformat(rec['next_date'])
            m=d.month-1+rec['interval_months']
            yr=d.year+m//12;mo=m%12+1
            import calendar
            day=min(d.day,calendar.monthrange(yr,mo)[1])
            next_date=date(yr,mo,day).isoformat()
            con.execute('UPDATE recurrings SET next_date=? WHERE id=? AND company_id=?',(next_date,rid,co['id']))
        notify(request,'Wiederkehrenden Entwurf erstellt. Bitte vor dem Freigeben kontrollieren.')
        return redirect(f'/invoices/{iid}/edit')

    @app.post('/recurring/{rid}/disable')
    async def recurring_disable(request:Request,rid:int):
        user,co=current(request,'editor');await form(request)
        with transaction(db_path,True) as con:
            fetch(con,'recurrings',co['id'],rid)
            con.execute('UPDATE recurrings SET active=0 WHERE id=? AND company_id=?',(rid,co['id']))
            audit(con,co['id'],user['id'],'Wiederholung pausiert',str(rid))
        notify(request,'Wiederholung pausiert (nicht geloescht)')
        return redirect('/recurring?status=all')

    @app.get('/archive')
    async def archive(request:Request,q:str='',kind:str='',currency:str='',date_from:str='',date_to:str='',page:int=1):
        user,co=current(request)
        if kind not in ('','invoice','quote','credit') or currency not in ('','CHF','EUR'):
            raise HTTPException(400,'Ungueltiger Archivfilter')
        date_from,date_to=period_bounds(date_from,date_to)
        clauses=['i.company_id=?',"i.pdf_file!=''",
                 "(i.number LIKE ? ESCAPE '!' OR c.name LIKE ? ESCAPE '!')"]
        args=[co['id'],list_query(q),list_query(q)]
        if kind:clauses.append('i.kind=?');args.append(kind)
        if currency:clauses.append('i.currency=?');args.append(currency)
        if date_from:clauses.append('i.invoice_date>=?');args.append(date_from)
        if date_to:clauses.append('i.invoice_date<=?');args.append(date_to)
        base=' FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id AND c.company_id=i.company_id WHERE '+' AND '.join(clauses)
        with transaction(db_path) as con:
            count=con.execute('SELECT COUNT(*) '+base,args).fetchone()[0]
            page,pages=checked_page(page,count)
            records=[dict(x) for x in allrows(con,'SELECT i.*,c.name AS customer_name '+base+' ORDER BY i.id DESC LIMIT 50 OFFSET ?',(*args,50*(page-1)))]
        query=urlencode({'q':q,'kind':kind,'currency':currency,'date_from':date_from,'date_to':date_to})
        return view(request,'archive.html',invoices=records,q=q,kind=kind,currency=currency,
                    date_from=date_from,date_to=date_to,count=count,page=page,pages=pages,filter_query=query)

    @app.post('/archive/export.zip')
    async def archive_export_zip(request:Request):
        """Nur explizit ausgewaehlte, unveraenderte Archiv-PDFs dieses Mandanten."""
        user,co=current(request)
        data=await form(request)
        supplied=[str(v).strip() for v in data.getlist('invoice_ids')]
        if not supplied or len(supplied)>25 or any(not re.fullmatch(r'[1-9][0-9]{0,10}',v) for v in supplied):
            raise HTTPException(400,'Bitte 1 bis 25 gueltige Archivbelege auswaehlen.')
        ids=list(dict.fromkeys(int(v) for v in supplied))
        if len(ids)!=len(supplied):
            raise HTTPException(400,'Doppelte Auswahl ist nicht erlaubt.')
        archive_base=(root/'archive'/str(co['id'])).resolve()
        total_bytes=0
        documents=[]
        with transaction(db_path) as con:
            for rid in ids:
                inv=fetch(con,'invoices',co['id'],rid)
                if not inv['pdf_file'] or not inv['pdf_sha256']:
                    raise HTTPException(400,'Nur freigegebene Archiv-PDFs duerfen exportiert werden.')
                path=(root/inv['pdf_file']).resolve()
                if not path.is_relative_to(archive_base) or not path.is_file():
                    raise HTTPException(404,'Ein ausgewaehltes Archiv-PDF fehlt.')
                total_bytes+=path.stat().st_size
                if total_bytes>60*1024*1024:
                    raise HTTPException(413,'PDF-Auswahl ist groesser als 60 MB. Bitte weniger Belege auswaehlen.')
                content=path.read_bytes()
                digest=hashlib.sha256(content).hexdigest()
                if not hmac.compare_digest(digest,inv['pdf_sha256']):
                    raise HTTPException(409,'Ein Archiv-PDF ist veraendert. Keine ZIP-Datei erstellt.')
                # Benutzerangaben niemals als Dateipfad uebernehmen.
                safe_no=re.sub(r'[^a-zA-Z0-9_-]','_',str(inv['number']))[:60]
                name=f'{rid:08d}-{safe_no}.pdf'
                documents.append((name,content,digest,inv))
        target=io.BytesIO()
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            index=io.StringIO()
            index.write('\ufeff')
            writer=csv.writer(index,delimiter=';')
            writer.writerow(['Datei','Belegnummer','Typ','Datum','Waehrung','Betrag','SHA256'])
            for name,content,digest,inv in documents:
                archive.writestr('PDF/'+name,content)
                writer.writerow([safe_csv(v) for v in (name,inv['number'],inv['kind'],inv['invoice_date'],
                                                         inv['currency'],inv['total'],digest)])
            archive.writestr('Belegliste.csv',index.getvalue().encode('utf-8'))
            archive.writestr('HINWEIS.txt','Swiss-invoice-RX PDF-Export. Nur fuer die eigene Ablage.\n'
                             'SHA256-Pruefsummen stehen in Belegliste.csv.\n'
                             'Dies ist kein verschluesseltes Backup und ersetzt keine Datensicherung.\n')
        return Response(target.getvalue(),media_type='application/zip',headers={
            'Content-Disposition':'attachment; filename="Swiss-invoice-RX-Archiv-Auswahl.zip"'})

    @app.get('/bank')
    async def bank_list(request: Request, status: str = 'open', q: str = '', currency: str = ''):
        user, co = current(request)
        if status not in ('open', 'matched', 'ignored', 'all'):
            status = 'open'
        if currency not in ('','CHF','EUR'):
            raise HTTPException(400,'Ungueltige Waehrung')
        bank_criteria=["bt.company_id=?", "(bt.debtor LIKE ? ESCAPE '!' OR bt.payment_reference LIKE ? ESCAPE '!' OR bt.message LIKE ? ESCAPE '!' OR bt.bank_reference LIKE ? ESCAPE '!')"]
        bank_args=[co['id'],*([list_query(q)]*4)]
        if currency:
            bank_criteria.append('bt.currency=?');bank_args.append(currency)
        if status!='all':
            bank_criteria.append('bt.status=?');bank_args.append(status)
        with transaction(db_path) as con:
            entries=[dict(r) for r in allrows(con, '''SELECT bt.*,i.number AS matched_number
                FROM bank_transactions bt LEFT JOIN payments p ON p.id=bt.payment_id AND p.company_id=bt.company_id
                LEFT JOIN invoices i ON i.id=p.invoice_id AND i.company_id=bt.company_id
                WHERE '''+' AND '.join(bank_criteria)+' ORDER BY bt.id DESC LIMIT 250',bank_args)]
            counts = {r['status']: r['n'] for r in allrows(con,
                'SELECT status, COUNT(*) AS n FROM bank_transactions WHERE company_id=? GROUP BY status',
                (co['id'],))}
            open_invoices = [dict(r) for r in allrows(con, '''SELECT i.id,i.number,i.total,i.paid_total,i.currency,
                c.name AS customer_name FROM invoices i LEFT JOIN customers c
                ON c.id=i.customer_id AND c.company_id=i.company_id
                WHERE i.company_id=? AND i.kind='invoice' AND i.status NOT IN ('draft','cancelled')
                ORDER BY i.due_date ASC LIMIT 1000''', (co['id'],))]
        open_invoices = [i for i in open_invoices if cents(i['total']) > cents(i['paid_total'])]
        for e in entries:
            # Vorschlaege sind nur Hinweise und buchen NIE selbststaendig.
            choices = []
            label = (e['payment_reference'] + ' ' + e['message'] + ' ' + e['bank_reference']).upper()
            norm_ref = re.sub(r'\s+', '', e['payment_reference']).upper()
            for inv in open_invoices:
                if inv['currency'] != e['currency']:
                    continue
                due = cents(inv['total']) - cents(inv['paid_total'])
                if due < cents(e['amount']):
                    continue
                seed = f"{co['id']:05d}{inv['id']:012d}"
                expected = None
                if norm_ref:
                    expected = norm_ref in (qrr_reference(seed), scor_reference('INV' + seed))
                matches_number = inv['number'].upper() in label
                amount_matches = due == cents(e['amount'])
                priority = 0 if expected else 1 if matches_number else 2 if amount_matches else 3
                choices.append((priority, inv))
            choices.sort(key=lambda pair: (pair[0], pair[1]['number']))
            e['suggestions'] = [dict(inv, is_suggestion=priority < 2,
                                      remaining=cents(inv['total'])-cents(inv['paid_total']))
                                for priority, inv in choices[:50]]
            e['has_more_choices'] = len(choices) > 50
        return view(request, 'bank.html', entries=entries, selected_status=status,
                    counts=counts, bank_iban=co.get('iban') or '',q=q,currency=currency)

    @app.post('/bank/import')
    async def bank_import(request: Request):
        user, co = current(request, 'editor')
        data = await form(request)
        file = data.get('statement')
        if not isinstance(file, UploadFile) or not file.filename:
            notify(request, 'Bitte eine camt.053- oder camt.054-XML-Datei auswaehlen.', 'error')
            return redirect('/bank')
        try:
            from .bank import parse_camt, MAX_CAMT_BYTES
            raw = await file.read(MAX_CAMT_BYTES + 1)
            entries = parse_camt(raw)
            company_account = normalize_iban(co.get('iban'))
            if not company_account:
                raise ValueError('Bitte zuerst die Bank-IBAN unter Firmendaten eintragen.')
            # Strict tenant/account match prevents importing money belonging to another business.
            if any(e['account_iban'] != company_account for e in entries):
                raise ValueError('Bankdatei enthaelt eine andere IBAN als die hinterlegte Firmen-IBAN. '
                                 'Bitte Bankkonto und aktives Geschaeft pruefen.')
            import_name = Path(str(file.filename).replace('\\', '/')).name[:100]
            inserted = 0
            with transaction(db_path, True) as con:
                for e in entries:
                    cur = con.execute('''INSERT OR IGNORE INTO bank_transactions
                        (company_id,fingerprint,source,account_iban,value_date,amount,currency,
                         bank_reference,payment_reference,debtor,message,import_name)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (co['id'],e['fingerprint'],e['source'],e['account_iban'],e['value_date'],
                         e['amount'],e['currency'],e['bank_reference'],e['payment_reference'],
                         e['debtor'],e['message'],import_name))
                    inserted += cur.rowcount
                audit(con,co['id'],user['id'],'Bankdatei importiert',
                      f'{import_name}: {inserted} neue, {len(entries)-inserted} doppelte')
            notify(request, f'{inserted} neue Bankgutschriften importiert, '
                            f'{len(entries)-inserted} bereits vorhanden. Bitte Rechnungen manuell zuordnen.')
        except ValueError as exc:
            notify(request, str(exc), 'error')
        finally:
            await file.close()
        return redirect('/bank')

    @app.post('/bank/{bank_id}/assign')
    async def bank_assign(request: Request, bank_id: int):
        user, co = current(request, 'editor')
        data = await form(request)
        try:
            invoice_id = int(data.get('invoice_id') or 0)
            with transaction(db_path, True) as con:
                entry = one(con, 'SELECT * FROM bank_transactions WHERE id=? AND company_id=?',
                            (bank_id, co['id']))
                if entry is None:
                    raise HTTPException(404)
                if entry['status'] != 'open':
                    raise ValueError('Bankzahlung ist bereits zugeordnet oder ignoriert.')
                inv = fetch(con, 'invoices', co['id'], invoice_id)
                if inv['kind'] != 'invoice' or inv['status'] in ('draft', 'cancelled'):
                    raise ValueError('Nur freigegebene Rechnungen koennen Zahlungen erhalten.')
                if inv['currency'] != entry['currency']:
                    raise ValueError('Waehrung der Bankzahlung und Rechnung unterscheiden sich.')
                amount = cents(entry['amount'])
                if amount <= 0 or amount > cents(inv['total']) - cents(inv['paid_total']):
                    raise ValueError('Bankzahlung uebersteigt den offenen Rechnungsbetrag. '
                                     'Bitte manuell klaeren; Sammelzahlungen werden nicht automatisch verteilt.')
                note = ('camt ' + entry['source'] + ' / ' + entry['bank_reference'] + ' / '
                        + entry['payment_reference'])[:300]
                con.execute('''INSERT INTO payments(company_id,invoice_id,paid_at,amount,method,note)
                    VALUES(?,?,?,?,?,?)''',
                    (co['id'], inv['id'], entry['value_date'], entry['amount'], 'Bankimport', note))
                payment_id = con.execute('SELECT last_insert_rowid()').fetchone()[0]
                con.execute('UPDATE invoices SET paid_total=? WHERE company_id=? AND id=?',
                            (num(cents(inv['paid_total'])+amount),co['id'],inv['id']))
                con.execute("""UPDATE bank_transactions SET status='matched',payment_id=?
                    WHERE company_id=? AND id=? AND status='open'""", (payment_id,co['id'],bank_id))
                audit(con,co['id'],user['id'],'Bankgutschrift zugeordnet',
                      f'{inv["number"]}: {entry["amount"]} {entry["currency"]}')
            notify(request,'Bankzahlung wurde der Rechnung zugeordnet und als Zahlung gebucht.')
        except (ValueError, sqlite3.IntegrityError) as exc:
            notify(request, str(exc), 'error')
        return redirect('/bank')

    @app.post('/bank/{bank_id}/ignore')
    async def bank_ignore(request: Request, bank_id: int):
        user,co=current(request,'editor')
        data=await form(request)
        reason=str(data.get('reason','')).strip()[:250]
        try:
            if len(reason)<5:
                raise ValueError('Bitte einen Grund mit mindestens 5 Zeichen angeben.')
            with transaction(db_path,True) as con:
                entry=one(con,'SELECT * FROM bank_transactions WHERE id=? AND company_id=?',(bank_id,co['id']))
                if not entry:raise HTTPException(404)
                if entry['status']!='open':raise ValueError('Nur offene Bankgutschriften ignorierbar.')
                con.execute("""UPDATE bank_transactions SET status='ignored',ignore_reason=?
                    WHERE id=? AND company_id=?""", (reason, bank_id, co['id']))
                audit(con,co['id'],user['id'],'Bankgutschrift ignoriert',f'#{bank_id}: {reason}')
            notify(request,'Bankeintrag als nicht zuordenbar markiert.')
        except ValueError as exc:
            notify(request,str(exc),'error')
        return redirect('/bank')

    @app.post('/bank/{bank_id}/reopen')
    async def bank_reopen(request: Request, bank_id: int):
        user,co=current(request,'admin')
        await form(request)
        with transaction(db_path,True) as con:
            entry=one(con,'SELECT * FROM bank_transactions WHERE id=? AND company_id=?',(bank_id,co['id']))
            if not entry:raise HTTPException(404)
            if entry['status']!='ignored':raise HTTPException(400)
            con.execute("""UPDATE bank_transactions SET status='open',ignore_reason=''
                WHERE id=? AND company_id=?""",(bank_id,co['id']))
            audit(con,co['id'],user['id'],'Bankeintrag wieder geoeffnet',str(bank_id))
        notify(request,'Bankeintrag steht wieder zur Zuordnung bereit.')
        return redirect('/bank?status=ignored')

    def outstanding_rows(con, cid, currency, q='', due='all'):
        if currency not in ('CHF','EUR') or due not in ('all','overdue','next7','later'):
            raise HTTPException(400,'Ungueltiger Filter')
        records=[dict(x) for x in allrows(con,'''SELECT i.*,c.name AS customer_name
            FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id AND c.company_id=i.company_id
            WHERE i.company_id=? AND i.kind='invoice' AND i.currency=?
            AND i.status NOT IN ('draft','cancelled') ORDER BY i.due_date ASC,i.id ASC''',(cid,currency))]
        now=date.today()
        needle=str(q or '').strip().casefold()[:80]
        selected=[]
        for inv in records:
            remaining=cents(inv['total'])-cents(inv['paid_total'])
            if remaining<=0:continue
            if needle not in (inv['number']+' '+str(inv['customer_name'] or '')).casefold():continue
            diff=(date.fromisoformat(inv['due_date'])-now).days
            if due=='overdue' and diff>=0:continue
            if due=='next7' and not 0<=diff<=7:continue
            if due=='later' and diff<=7:continue
            inv['remaining']=remaining
            inv['days_overdue']=-diff
            selected.append(inv)
        return selected

    @app.get('/receivables')
    async def receivables(request:Request,currency:str='',q:str='',due:str='all'):
        user,co=current(request)
        currency=currency if currency in ('CHF','EUR') else co['currency']
        with transaction(db_path) as con:
            rows=outstanding_rows(con,co['id'],currency,q,due)
        groups={'future':Decimal('0'),'1_30':Decimal('0'),'31_60':Decimal('0'),'61_plus':Decimal('0')}
        for inv in rows:
            group=('future' if inv['days_overdue']<=0 else '1_30' if inv['days_overdue']<=30
                   else '31_60' if inv['days_overdue']<=60 else '61_plus')
            groups[group]+=inv['remaining']
        return view(request,'receivables.html',invoices=rows,groups=groups,
                    selected_currency=currency,q=q,due=due,total=sum(groups.values(),Decimal('0')))

    @app.get('/receivables.csv')
    async def receivables_export(request:Request,currency:str='CHF',q:str='',due:str='all'):
        user,co=current(request)
        with transaction(db_path) as con:
            rows=outstanding_rows(con,co['id'],currency,q,due)
        return csv_download('offene-posten-'+currency+'.csv',
            ['Nummer','Kunde','Rechnungsdatum','Faellig am','Waehrung','Total','Bezahlt','Offen'],
            [[i['number'],i['customer_name'],i['invoice_date'],i['due_date'],currency,
              i['total'],i['paid_total'],num(i['remaining'])] for i in rows],numeric=(5,6,7))

    def report_dataset(con, cid, currency, date_from='', date_to=''):
        if currency not in ('CHF','EUR'):
            raise HTTPException(400,'Nur CHF und EUR')
        date_from,date_to=period_bounds(date_from,date_to)
        where="company_id=? AND currency=? AND status NOT IN ('draft','cancelled')"
        args=[cid,currency]
        if date_from:where+=' AND invoice_date>=?';args.append(date_from)
        if date_to:where+=' AND invoice_date<=?';args.append(date_to)
        invoices=[dict(r) for r in allrows(con,'SELECT * FROM invoices WHERE '+where+" AND kind='invoice' ORDER BY invoice_date",args)]
        credits=[dict(r) for r in allrows(con,'SELECT * FROM invoices WHERE '+where+" AND kind='credit' ORDER BY invoice_date",args)]
        pays_sql='''SELECT p.paid_at,p.amount FROM payments p JOIN invoices i
            ON i.id=p.invoice_id AND i.company_id=p.company_id
            WHERE p.company_id=? AND i.currency=? AND i.kind='invoice'
            AND i.status NOT IN ('draft','cancelled') AND p.reversed_at='' '''
        pay_args=[cid,currency]
        if date_from:pays_sql+=' AND p.paid_at>=?';pay_args.append(date_from)
        if date_to:pays_sql+=' AND p.paid_at<=?';pay_args.append(date_to)
        payments=[dict(r) for r in allrows(con,pays_sql,pay_args)]
        customers={r['id']:r['name'] for r in allrows(con,'SELECT id,name FROM customers WHERE company_id=?',(cid,))}
        per_month={}
        tax_totals={}
        customer_totals={k:{'name':v,'total':Decimal('0')} for k,v in customers.items()}
        for inv in invoices:
            month=inv['invoice_date'][:7]
            per_month.setdefault(month,{'billed':Decimal('0'),'paid':Decimal('0'),'credit':Decimal('0')})['billed']+=cents(inv['total'])
            if inv['customer_id'] in customer_totals:
                customer_totals[inv['customer_id']]['total']+=cents(inv['total'])
            for rate,values in json.loads(inv['tax_breakdown']).items():
                tax_totals[rate]=tax_totals.get(rate,Decimal('0'))+cents(values['tax'])
        for inv in credits:
            per_month.setdefault(inv['invoice_date'][:7],{'billed':Decimal('0'),'paid':Decimal('0'),'credit':Decimal('0')})['credit']+=cents(inv['total'])
        for pay in payments:
            per_month.setdefault(pay['paid_at'][:7],{'billed':Decimal('0'),'paid':Decimal('0'),'credit':Decimal('0')})['paid']+=cents(pay['amount'])
        monthly=[{'month':month,**v} for month,v in sorted(per_month.items())]
        monthly_total=max((row['billed'] for row in monthly),default=Decimal('0')) or Decimal('1')
        for row in monthly:row['width']=float(row['billed']/monthly_total*100)
        return {'months':monthly[-24:],'all_months':monthly,'taxes':sorted(tax_totals.items()),
                'biggest':sorted(customer_totals.values(),key=lambda x:x['total'],reverse=True)[:8],
                'billed':sum((cents(i['total']) for i in invoices),Decimal('0')),
                'credits':sum((cents(i['total']) for i in credits),Decimal('0')),
                'paid':sum((cents(p['amount']) for p in payments),Decimal('0')),
                'invoice_count':len(invoices),'payment_count':len(payments)}

    @app.get('/reports')
    async def reports(request:Request,currency:str='',date_from:str='',date_to:str=''):
        user,co=current(request)
        currency=currency if currency in ('CHF','EUR') else co['currency']
        with transaction(db_path) as con:
            values=report_dataset(con,co['id'],currency,date_from,date_to)
        values.pop('all_months',None)
        return view(request,'reports.html',selected_currency=currency,
                    date_from=date_from,date_to=date_to,**values)

    @app.get('/reports/summary.csv')
    async def reports_summary_csv(request:Request,currency:str='CHF',date_from:str='',date_to:str=''):
        user,co=current(request)
        with transaction(db_path) as con:
            values=report_dataset(con,co['id'],currency,date_from,date_to)
        return csv_download('auswertung-'+currency+'.csv',
            ['Monat','Rechnungen brutto','Gutschriften','Zahlungseingaenge','Waehrung'],
            [[m['month'],num(m['billed']),num(m['credit']),num(m['paid']),currency]
             for m in values['all_months']],numeric=(1,2,3))

    @app.get('/export/{kind}.csv')
    async def csv_export(request:Request,kind:str):
        user,co=current(request)
        tables={
            'customers':('customers',['number','name','contact','email','phone','street','building','zip','city','country','group_name']),
            'items':('items',['sku','name','kind','category','cost','price','tax_rate','stock','track_stock']),
            'invoices':('invoices',['number','kind','invoice_date','due_date','status','currency','subtotal','tax_total','total','paid_total']),
            'payments':('payments',['invoice_id','paid_at','amount','method','note','reversed_at','reversal_note']),
            'bank':('bank_transactions',['value_date','source','account_iban','amount','currency','bank_reference','payment_reference','debtor','message','status','ignore_reason'])}
        if kind not in tables:raise HTTPException(404)
        table,cols=tables[kind]
        with transaction(db_path) as con:
            rows=allrows(con,'SELECT '+','.join(cols)+f' FROM {table} WHERE company_id=? ORDER BY id',(co['id'],))
        stream=io.StringIO()
        stream.write('\ufeff')
        writer=csv.writer(stream,delimiter=';')
        writer.writerow(cols)
        for r in rows:writer.writerow([safe_csv(r[c],c in ('cost','price','tax_rate','stock','track_stock','invoice_id','subtotal','tax_total','total','paid_total','amount')) for c in cols])
        return Response(stream.getvalue().encode('utf-8'),media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition':f'attachment; filename="{kind}-{co["id"]}.csv"'})

    @app.get('/settings')
    async def settings(request:Request):
        user,co=current(request,'admin')
        with transaction(db_path) as con:
            suggestions={kind:peek_number(con,co['id'],kind,co,date.today().year)[0]
                         for kind in ('invoice','quote','credit')}
        return view(request,'settings.html',settings=co,number_examples=suggestions,qr_checks=company_checks(co))

    @app.post('/settings')
    async def settings_save(request:Request):
        user,co=current(request,'admin')
        data=await form(request)
        try:
            draft_mark = (1 if data.get('pdf_show_draft_mark') else 0) if data.get('_pdf_draft_mark_present') else int(co.get('pdf_show_draft_mark', 1))
            iban=normalize_iban(data.get('iban'))
            if iban and not valid_iban(iban):
                raise ValueError('Die IBAN-Pruefziffer ist ungueltig. Nur CH-/LI-IBAN erlaubt.')
            days=int(data.get('default_due_days','30'))
            if days<0 or days>365:raise ValueError('Zahlungsfrist 0-365 Tage')
            color=safe_color(data.get('color','#2563eb'))
            business_type=str(data.get('business_type',co.get('business_type','company')))
            if business_type not in BUSINESS_TYPES:
                raise ValueError('Bitte eine gültige Geschäftsart auswählen')
            if business_type=='private' and data.get('tax_registered'):
                raise ValueError('Private Gelegenheitsrechnungen nicht mit MWST ausstellen. Bitte die Geschäftsart oder den MWST-Status ändern.')
            tax=str(dec(data.get('default_tax','0'))) if data.get('tax_registered') else '0'
            if dec(tax)<0 or dec(tax)>100:raise ValueError('MWST-Satz ungueltig')
            number_prefix=valid_prefix(data.get('number_prefix',co['number_prefix']))
            quote_prefix=valid_prefix(data.get('quote_prefix',co['quote_prefix']),'OF')
            credit_prefix=valid_prefix(data.get('credit_prefix',co['credit_prefix']),'GS')
            padding=valid_padding(data.get('number_padding',co['number_padding']))
            next_invoice=valid_counter(data.get('next_invoice',co['next_invoice']))
            next_quote=valid_counter(data.get('next_quote',co['next_quote']))
            next_credit=valid_counter(data.get('next_credit',co['next_credit']))
            qr_type=str(data.get('qr_reference_type',co['qr_reference_type']) or 'AUTO').upper()
            if qr_type not in ('AUTO','SCOR','QRR','NON'):
                raise ValueError('Ungueltige QR-Referenzart')
            qr_message=str(data.get('qr_message',co['qr_message'])).strip()
            if len(qr_message)>140 or any(ord(ch)<32 for ch in qr_message):
                raise ValueError('QR-Mitteilung: maximal 140 Zeichen, ohne Zeilenumbrueche')
            from .qr import is_qr_iban
            if iban and ((is_qr_iban(iban) and qr_type in ('SCOR','NON')) or
                         (not is_qr_iban(iban) and qr_type=='QRR')):
                raise ValueError('QR-Referenzart passt nicht zur IBAN. AUTO waehlen oder im QR-Test pruefen.')
            fields=('name','business_type','street','building','zip','city','country','email','phone','uid','iban','currency','tax_registered',
                    'default_tax','color','footer_text','payment_terms','default_due_days','number_prefix',
                    'quote_prefix','credit_prefix','number_padding','next_invoice','next_quote','next_credit',
                    'qr_reference_type','qr_message','logo_path','pdf_show_draft_mark')
            with transaction(db_path,True) as con:
                logo=item_image(con,co['id'],data.get('logo'),co['logo_path'])
                values=[str(data.get('name','')).strip(),business_type,str(data.get('street','')).strip(),str(data.get('building','')).strip(),
                        str(data.get('zip','')).strip(),str(data.get('city','')).strip(),
                        str(data.get('country','CH')).upper().strip(),str(data.get('email','')).strip(),
                        str(data.get('phone','')).strip(),str(data.get('uid','')).strip(),iban,
                        str(data.get('currency','CHF')).upper(),1 if data.get('tax_registered') else 0,
                        tax,color,str(data.get('footer_text',''))[:300],str(data.get('payment_terms',''))[:300],
                        days,number_prefix,quote_prefix,credit_prefix,padding,next_invoice,next_quote,next_credit,
                        qr_type,qr_message,logo,draft_mark]
                if not values[0]:raise ValueError('Firmenname fehlt')
                if values[11] not in ('CHF','EUR'):raise ValueError('Waehrung CHF oder EUR')
                con.execute('UPDATE companies SET '+','.join(f+'=?' for f in fields)+' WHERE id=?',(*values,co['id']))
                audit(con,co['id'],user['id'],'Firmeneinstellungen','inkl. Nummernkreis und QR-Einstellungen aktualisiert')
            notify(request,'Firmendaten, Nummernkreise und QR-Einstellungen gespeichert')
        except (ValueError,sqlite3.IntegrityError) as exc:
            notify(request,str(exc),'error')
        return redirect('/settings')

    @app.post('/settings/branding')
    async def settings_branding(request:Request):
        user, co = current(request, 'admin')
        data = await form(request)
        company_upload = data.get('app_logo')
        login_upload = data.get('login_logo')
        remove_company = str(data.get('remove_app_logo', '')) == '1'
        remove_login = str(data.get('remove_login_logo', '')) == '1'
        if not user['is_superadmin'] and (remove_login or getattr(login_upload, 'filename', '')):
            raise HTTPException(403, 'Nur der Hauptadministrator darf das Anmeldelogo aendern.')
        try:
            # Beide Dateien vor einer Datenbank- oder Dateioperation pruefen.
            company_image = uploaded_logo(company_upload)
            login_image = uploaded_logo(login_upload) if user['is_superadmin'] else None
            with transaction(db_path, True) as con:
                changed = False
                if company_image is not None or remove_company:
                    new_path = save_company_logo(root, co['id'], company_image) if company_image is not None else ''
                    con.execute('UPDATE companies SET app_logo_path=? WHERE id=?', (new_path, co['id']))
                    changed = True
                if user['is_superadmin'] and (login_image is not None or remove_login):
                    if login_image is not None:
                        save_site_logo(root, login_image)
                    else:
                        path = site_logo_path(root)
                        if path:
                            path.unlink()
                    changed = True
                if changed:
                    audit(con, co['id'], user['id'], 'Logos aktualisiert',
                          'Oberflaechenlogo und/oder Anmeldelogo angepasst')
            notify(request, 'Logos gespeichert. Das Geschaeftslogo erscheint bei allen zugewiesenen Benutzern.'
                   if changed else 'Kein neues Logo ausgewaehlt.')
        except ValueError as exc:
            notify(request, str(exc), 'error')
        return redirect('/settings#hi-branding')

    def qr_test_fields(co):
        return {
            'iban':co['iban'], 'qr_reference_type':co['qr_reference_type'],
            'qr_message':co['qr_message'], 'amount':'12.50','currency':co['currency'],
            'invoice_number':'TEST-2026-0001','name':'Musterkunde AG',
            'street':'Musterstrasse','building':'10','zip':'3000','city':'Bern','country':'CH'
        }

    @app.get('/qr-test')
    async def qr_test_page(request:Request):
        user,co=current(request,'admin')
        return view(request,'qr_test.html',fields=qr_test_fields(co),result=None,test_error=None)

    @app.post('/qr-test')
    async def qr_test_run(request:Request):
        user,co=current(request,'admin')
        data=await form(request)
        fields={k:str(data.get(k, '')) for k in qr_test_fields(co)}
        try:
            settings=dict(co)
            settings['iban']=normalize_iban(fields['iban'])
            settings['qr_reference_type']=fields['qr_reference_type']
            settings['qr_message']=fields['qr_message']
            customer={k:fields[k] for k in ('name','street','building','zip','city','country')}
            amount=num(dec(fields['amount']))
            currency=fields['currency'].upper()
            number=fields['invoice_number'].strip()
            if not number or len(number)>40:
                raise ValueError('Bitte eine Test-Rechnungsnummer mit maximal 40 Zeichen eingeben.')
            from .qr import qr_image
            qr=build_payload(settings,customer,amount,currency,
                             f"{co['id']:05d}0000000000001",number)
            if data.get('format')=='pdf':
                pdf=make_qr_test_pdf(settings,customer,qr,amount,currency,number)
                return Response(pdf,media_type='application/pdf',headers={
                    'Content-Disposition':'attachment; filename="QR_TEST_NICHT_VERSENDEN.pdf"'})
            image=qr_image(qr['payload'],pixel_size=736)
            output=io.BytesIO()
            image.save(output,format='PNG')
            qr['png']='data:image/png;base64,'+base64.b64encode(output.getvalue()).decode('ascii')
            return view(request,'qr_test.html',fields=fields,result=qr,test_error=None)
        except (ValueError,OverflowError) as exc:
            return view(request,'qr_test.html',fields=fields,result=None,test_error=str(exc))

    def parse_template_options(data):
        style=str(data.get('template_style','modern'))
        if style not in ('modern','classic','minimal'):
            raise ValueError('Bitte einen gueltigen Designstil auswaehlen.')
        layout=str(data.get('template_header_layout','standard'))
        if layout not in ('standard','mirrored'):
            raise ValueError('Bitte einen gueltigen Kopfbereich auswaehlen.')
        density=str(data.get('template_density','normal'))
        if density not in ('compact','normal','spacious'):
            raise ValueError('Bitte einen gueltigen Zeilenabstand auswaehlen.')
        try:
            title_size=int(data.get('template_title_size',26))
        except (ValueError,TypeError) as exc:
            raise ValueError('Ungueltige Schriftgroesse.') from exc
        if title_size not in (22,26,30,34):
            raise ValueError('Bitte eine gueltige Schriftgroesse waehlen.')
        table_style=str(data.get('template_table_style','lines'))
        if table_style not in ('lines','zebra','clean'):
            raise ValueError('Bitte eine gueltige Tabellenoptik waehlen.')
        try:
            logo_size=int(data.get('template_logo_size',110))
            body_size=int(data.get('template_body_size',9))
        except (ValueError,TypeError) as exc:
            raise ValueError('Ungueltige Schrift- oder Logogroesse.') from exc
        if logo_size not in (80,110,140) or body_size not in (8,9,10):
            raise ValueError('Bitte eine erlaubte Schrift- und Logogroesse waehlen.')
        options={
            'template_table_style':table_style,
            'template_logo_size':logo_size,
            'template_body_size':body_size,
            'template_style':style,
            'template_accent':safe_color(data.get('template_accent','#2563eb')),
            'template_header_layout':layout,
            'template_title_size':title_size,
            'template_density':density,
        }
        for name,max_length in (('template_title',60),('template_footer',200),
                                ('default_invoice_notes',1200)):
            val=str(data.get(name,''))
            if len(val)>max_length:
                raise ValueError(name+' ist zu lang (maximal '+str(max_length)+' Zeichen).')
            if any(ord(ch)<32 and ch not in '\n\r\t' for ch in val):
                raise ValueError('Ungueltige Steuerzeichen in '+name)
            options[name]=val.strip()
        options['designer_enabled']=1 if str(data.get('designer_enabled','0'))=='1' else 0
        options['designer_layout']=dumps_layout(data.get('designer_layout','')) if data.get('designer_layout') else ''
        for name in ('template_show_logo','template_show_service_date',
                     'template_show_tax_breakdown','template_show_payment_terms',
                     'template_show_customer_email','template_show_page_numbers'):
            options[name]=1 if data.get(name) else 0
        return options

    def named_templates(con, co):
        create_initial(con, co)
        return [dict(x) for x in allrows(con,
            'SELECT id,name,active,updated_at FROM invoice_templates WHERE company_id=? ORDER BY active DESC, name COLLATE NOCASE',
            (co['id'],))]

    @app.get('/templates')
    async def template_editor(request:Request):
        user,co=current(request,'admin')
        with transaction(db_path,True) as con:
            library=named_templates(con,co)
        return view(request,'template_editor.html',settings=co,library=library)

    @app.post('/templates')
    async def template_save(request:Request):
        user,co=current(request,'admin')
        data=await form(request)
        try:
            options=parse_template_options(data)
        except ValueError as exc:
            notify(request,str(exc),'error')
            return redirect('/templates')
        with transaction(db_path,True) as con:
            named_templates(con,co)
            set_live_company(con,co['id'],options)
            con.execute('UPDATE invoice_templates SET payload=?,updated_at=CURRENT_TIMESTAMP WHERE company_id=? AND active=1',
                        (as_json(options),co['id']))
            audit(con,co['id'],user['id'],'Vorlage angepasst',
                  'Aktive Gestaltung mit Schrift, Tabelle und Standardtext gespeichert')
        notify(request,'Rechnungsvorlage gespeichert. Neue Dokumente verwenden das aktuelle Design.')
        return redirect('/templates')

    @app.post('/templates/save-as')
    async def template_save_as(request:Request):
        user,co=current(request,'admin')
        data=await form(request)
        try:
            options=parse_template_options(data)
            name=ensure_named(data.get('template_name'))
            with transaction(db_path,True) as con:
                named_templates(con,co)
                if one(con,'SELECT id FROM invoice_templates WHERE company_id=? AND name=? COLLATE NOCASE',
                       (co['id'],name)):
                    raise ValueError('Dieser Vorlagenname ist bereits vergeben.')
                if one(con,'SELECT COUNT(*) n FROM invoice_templates WHERE company_id=?',
                       (co['id'],))['n'] >= 20:
                    raise ValueError('Maximal 20 Vorlagen pro Geschaeft. Bitte eine ungenutzte entfernen.')
                con.execute('UPDATE invoice_templates SET active=0 WHERE company_id=?',(co['id'],))
                con.execute('INSERT INTO invoice_templates(company_id,name,payload,active) VALUES(?,?,?,1)',
                            (co['id'],name,as_json(options)))
                set_live_company(con,co['id'],options)
                audit(con,co['id'],user['id'],'Vorlage angelegt','Design gespeichert: '+name)
        except ValueError as exc:
            notify(request,str(exc),'error')
            return redirect('/templates')
        notify(request,'Neue Vorlage "'+name+'" gespeichert und aktiviert.')
        return redirect('/templates')

    @app.post('/templates/activate')
    async def template_activate(request:Request):
        user,co=current(request,'admin')
        data=await form(request)
        try:
            template_id=int(data.get('template_id',''))
        except (ValueError,TypeError) as exc:
            raise HTTPException(422,'Ungueltige Vorlagen-ID') from exc
        with transaction(db_path,True) as con:
            named_templates(con,co)
            found=one(con,'SELECT * FROM invoice_templates WHERE id=? AND company_id=?',
                      (template_id,co['id']))
            if found is None:
                raise HTTPException(404,'Vorlage nicht vorhanden')
            try:
                options=parse_template_options(json.loads(found['payload']))
            except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
                raise HTTPException(422,'Vorlage ist beschaedigt') from exc
            con.execute('UPDATE invoice_templates SET active=0 WHERE company_id=?',(co['id'],))
            con.execute('UPDATE invoice_templates SET active=1 WHERE id=? AND company_id=?',
                        (template_id,co['id']))
            set_live_company(con,co['id'],options)
            audit(con,co['id'],user['id'],'Vorlage aktiviert',found['name'])
        notify(request,'Vorlage "'+found['name']+'" aktiviert.')
        return redirect('/templates')

    @app.post('/templates/rename')
    async def template_rename(request:Request):
        user,co=current(request,'admin')
        data=await form(request)
        try:
            template_id=int(data.get('template_id',''))
            name=ensure_named(data.get('template_name'))
        except (ValueError,TypeError) as exc:
            notify(request,'Bitte einen gueltigen Vorlagennamen angeben.','error')
            return redirect('/templates')
        try:
            with transaction(db_path,True) as con:
                named_templates(con,co)
                found=one(con,'SELECT * FROM invoice_templates WHERE id=? AND company_id=?',
                          (template_id,co['id']))
                if not found:
                    raise HTTPException(404,'Vorlage nicht vorhanden')
                duplicate=one(con,'SELECT id FROM invoice_templates WHERE company_id=? AND name=? COLLATE NOCASE AND id!=?',
                              (co['id'],name,template_id))
                if duplicate:
                    raise ValueError('Eine Vorlage mit diesem Namen gibt es bereits.')
                con.execute('UPDATE invoice_templates SET name=?,updated_at=CURRENT_TIMESTAMP WHERE company_id=? AND id=?',
                            (name,co['id'],template_id))
                audit(con,co['id'],user['id'],'Vorlage umbenannt',found['name']+' -> '+name)
        except ValueError as exc:
            notify(request,str(exc),'error')
            return redirect('/templates')
        notify(request,'Vorlage erfolgreich umbenannt.')
        return redirect('/templates')

    @app.post('/templates/delete')
    async def template_delete(request:Request):
        user,co=current(request,'admin')
        data=await form(request)
        try:
            template_id=int(data.get('template_id',''))
        except (ValueError,TypeError) as exc:
            raise HTTPException(422,'Ungueltige Vorlagen-ID') from exc
        with transaction(db_path,True) as con:
            named_templates(con,co)
            found=one(con,'SELECT * FROM invoice_templates WHERE id=? AND company_id=?',
                      (template_id,co['id']))
            if found is None:
                raise HTTPException(404,'Vorlage nicht vorhanden')
            if found['active']:
                notify(request,'Die aktive Vorlage kann nicht geloescht werden. Erst eine andere aktivieren.','error')
                return redirect('/templates')
            con.execute('DELETE FROM invoice_templates WHERE id=? AND company_id=?',
                        (template_id,co['id']))
            audit(con,co['id'],user['id'],'Vorlage entfernt',found['name'])
        notify(request,'Vorlage "'+found['name']+'" entfernt.')
        return redirect('/templates')

    def render_template_pdf(co, overrides=None, kind='invoice'):
        if kind not in ('invoice','quote','credit'):
            raise HTTPException(422,'Ungueltige Vorschauart')
        template=dict(co)
        if overrides:
            template.update(overrides)
        template['iban']=''  # Nie einen zahlbaren QR-Code aus einem Musterdokument erzeugen.
        doc_logo = document_logo_path(root, template)
        template['logo_path'] = str(doc_logo) if doc_logo else ''
        template['designer_asset_root']=str(root/'uploads'/'designs'/str(co['id']))
        sample_customer={'name':'Musterkunde AG','street':'Musterstrasse','building':'8',
                         'zip':'8000','city':'Zuerich','country':'CH',
                         'email':'kontakt@musterkunde.example'}
        rate=str(co['default_tax'] if co['tax_registered'] else '0')
        raw=[{'description':'Beratungsleistung / Mustereintrag','qty':'2','unit':'Std.',
              'price':'125.00','tax_rate':rate,'tax_mode':'taxable','discount':'0'},
             {'description':'Projektpauschale / Mustereintrag','qty':'1','unit':'Stk.',
              'price':'45.00','tax_rate':rate,'tax_mode':'taxable','discount':'0'}]
        result=summarize(raw)
        inv={'id':0,'kind':kind,'number':'MUSTER-RECHNUNG','invoice_date':date.today().isoformat(),
             'due_date':future(int(co['default_due_days'])),'service_date':date.today().isoformat(),
             'currency':co['currency'],'notes':template.get('default_invoice_notes') or
             'MUSTER - Nur zur Gestaltungskontrolle. Nicht versenden.',
             'subtotal':result['subtotal'],'tax_total':result['tax_total'],'total':result['total'],
             'tax_breakdown':json.dumps(result['tax_breakdown'])}
        pdf,_=make_pdf(inv,template,sample_customer,result['lines'],preview=True,force_preview_label=True)
        return Response(pdf,media_type='application/pdf',headers={
            'Content-Disposition':'inline; filename="MUSTER_NICHT_VERSENDEN.pdf"'})

    @app.get('/templates/preview.pdf')
    async def template_pdf_preview(request:Request, kind:str='invoice'):
        user,co=current(request,'admin')
        return render_template_pdf(co,kind=kind)

    @app.post('/templates/preview.pdf')
    async def template_live_pdf_preview(request:Request):
        user,co=current(request,'admin')
        data=await form(request)  # CSRF geschuetzt; keine DB-Aenderung.
        try:
            options=parse_template_options(data)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        return render_template_pdf(co,options,kind=str(data.get('_preview_kind','invoice')))

    @app.get('/templates/designer')
    async def free_designer(request:Request):
        user,co=current(request,'admin')
        layout=parse_layout(co.get('designer_layout') or '')
        return view(request,'designer.html',settings=co,layout=layout,
                    layout_json=json.dumps(layout,ensure_ascii=False))

    def read_designer_form(data):
        layout=dumps_layout(data.get('designer_layout',''))
        enabled=1 if str(data.get('designer_enabled','0'))=='1' else 0
        return layout,enabled

    @app.post('/templates/designer/preview.pdf')
    async def designer_preview(request:Request):
        user,co=current(request,'admin')
        data=await form(request)
        try:
            layout, _ = read_designer_form(data)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        return render_template_pdf(co,{'designer_layout':layout,'designer_enabled':1},
                                   kind=str(data.get('_preview_kind','invoice')))

    @app.post('/templates/designer/save')
    async def designer_save(request:Request):
        user,co=current(request,'admin')
        data=await form(request)
        try:
            layout,enabled=read_designer_form(data)
            save_as=str(data.get('save_as','0'))=='1'
            name=ensure_named(data.get('template_name')) if save_as else ''
            with transaction(db_path,True) as con:
                named_templates(con,co)
                current_settings=dict(co)
                current_settings.update({'designer_layout':layout,'designer_enabled':enabled})
                options=snapshot(current_settings)
                if save_as:
                    if one(con,'SELECT id FROM invoice_templates WHERE company_id=? AND name=? COLLATE NOCASE',(co['id'],name)):
                        raise ValueError('Eine Vorlage mit diesem Namen existiert bereits.')
                    if one(con,'SELECT COUNT(*) n FROM invoice_templates WHERE company_id=?',(co['id'],))['n']>=20:
                        raise ValueError('Maximal 20 Vorlagen pro Geschaeft.')
                    con.execute('UPDATE invoice_templates SET active=0 WHERE company_id=?',(co['id'],))
                    con.execute('INSERT INTO invoice_templates(company_id,name,payload,active) VALUES(?,?,?,1)',
                                (co['id'],name,as_json(options)))
                else:
                    con.execute('UPDATE invoice_templates SET payload=?,updated_at=CURRENT_TIMESTAMP WHERE company_id=? AND active=1',
                                (as_json(options),co['id']))
                set_live_company(con,co['id'],options)
                audit(con,co['id'],user['id'],'Freies Layout gespeichert',
                      ('Neue Vorlage: '+name if save_as else 'Aktive Vorlage aktualisiert'))
        except ValueError as exc:
            notify(request,str(exc),'error')
            return redirect('/templates/designer')
        notify(request,'A4-Layout gespeichert.' + (' Die neue Vorlage ist aktiv.' if save_as else ''))
        return redirect('/templates/designer')

    @app.post('/templates/designer/image')
    async def designer_image_upload(request:Request):
        user,co=current(request,'admin')
        data=await form(request)
        upload=data.get('image')
        if not isinstance(upload,UploadFile) or not upload.filename:
            raise HTTPException(422,'Bitte eine JPG-/PNG-/WEBP-Datei auswaehlen.')
        try:
            upload.file.seek(0,2)
            length=upload.file.tell()
            upload.file.seek(0)
            if length>4*1024*1024 or length<1:
                raise ValueError('Bilddatei muss zwischen 1 Byte und 4 MB gross sein.')
            image=Image.open(upload.file)
            image.verify()
            upload.file.seek(0)
            image=Image.open(upload.file)
            if image.width*image.height>16000000:
                raise ValueError('Bild hat zu viele Pixel (max. 16 Millionen).')
            image.thumbnail((1800,1800))
            if image.mode in ('RGBA','LA') or 'transparency' in image.info:
                rgba=image.convert('RGBA')
                white=Image.new('RGB',rgba.size,(255,255,255))
                white.paste(rgba,mask=rgba.getchannel('A'))
                image=white
            elif image.mode!='RGB': image=image.convert('RGB')
            folder=root/'uploads'/'designs'/str(co['id'])
            folder.mkdir(parents=True,exist_ok=True)
            name=uuid.uuid4().hex+'.jpg'
            image.save(folder/name,'JPEG',quality=88,optimize=True)
        except (ValueError,UnidentifiedImageError,OSError) as exc:
            raise HTTPException(422,'Bild konnte nicht verarbeitet werden: '+str(exc)) from exc
        finally:
            await upload.close()
        return {'asset':name,'url':'/templates/designer/image/'+name}

    @app.get('/templates/designer/image/{name}')
    async def designer_image_get(request:Request,name:str):
        user,co=current(request)
        if not re.fullmatch(r'[a-f0-9]{32}\.jpg',name):raise HTTPException(404)
        path=root/'uploads'/'designs'/str(co['id'])/name
        if not path.is_file():raise HTTPException(404)
        return FileResponse(path,media_type='image/jpeg')

    @app.get('/backup')
    async def backup_page(request:Request):
        current(request,'admin')
        return view(request,'backup.html')

    @app.post('/backup/download')
    async def backup_download(request:Request):
        user,co=current(request,'admin')
        await form(request)
        # Backup ist installationsweit, da Benutzer und mehrere Mandanten in einer SQLite-Datei liegen.
        # Nur globaler Superadmin darf ALLE Firmen/Benutzer sichern.
        if not user['is_superadmin']:
            raise HTTPException(403,'Nur der Installationsadministrator darf das Gesamtbackup exportieren')
        dest=root/'backups'/('backup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
        temp_db=root/'backups'/('snapshot-'+uuid.uuid4().hex+'.sqlite3')
        src=db_connect(db_path)
        dst=db_connect(temp_db)
        try:
            src.backup(dst)
        finally:
            src.close();dst.close()
        try:
            with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED) as z:
                z.write(temp_db,'rechnung.sqlite3')
                for folder in ('uploads','archive'):
                    for file in (root/folder).rglob('*'):
                        if file.is_file():z.write(file,str(file.relative_to(root)))
                z.writestr('README.txt','Swiss-invoice-RX Backup. Enthält Daten ALLER Firmen inklusive Benutzer. Vertraulich aufbewahren.\n')
        finally:
            temp_db.unlink(missing_ok=True)
        with transaction(db_path,True) as con:audit(con,co['id'],user['id'],'Gesamtbackup erstellt',dest.name)
        return FileResponse(dest,media_type='application/zip',filename=dest.name)

    def filter_activity(cid,q='',date_from='',date_to=''):
        date_from,date_to=period_bounds(date_from,date_to)
        where=["a.company_id=?", "(a.action LIKE ? ESCAPE '!' OR a.detail LIKE ? ESCAPE '!' OR u.full_name LIKE ? ESCAPE '!')"]
        args=[cid,*([list_query(q)]*3)]
        if date_from:where.append('substr(a.at,1,10)>=?');args.append(date_from)
        if date_to:where.append('substr(a.at,1,10)<=?');args.append(date_to)
        return ''' FROM activity a LEFT JOIN users u ON u.id=a.user_id
            WHERE '''+' AND '.join(where),args

    @app.get('/activity')
    async def activity_page(request:Request,q:str='',date_from:str='',date_to:str='',page:int=1):
        user,co=current(request,'admin')
        base,args=filter_activity(co['id'],q,date_from,date_to)
        with transaction(db_path) as con:
            count=con.execute('SELECT COUNT(*) '+base,args).fetchone()[0]
            page,pages=checked_page(page,count)
            events=[dict(x) for x in allrows(con,'SELECT a.*,u.full_name '+base+' ORDER BY a.id DESC LIMIT 50 OFFSET ?',(*args,(page-1)*50))]
        query=urlencode({'q':q,'date_from':date_from,'date_to':date_to})
        return view(request,'activity.html',events=events,q=q,date_from=date_from,date_to=date_to,
                    count=count,page=page,pages=pages,filter_query=query)

    @app.get('/activity.csv')
    async def activity_export(request:Request,q:str='',date_from:str='',date_to:str=''):
        user,co=current(request,'admin')
        base,args=filter_activity(co['id'],q,date_from,date_to)
        with transaction(db_path) as con:
            records=allrows(con,'SELECT a.at,u.full_name,a.action,a.detail '+base+' ORDER BY a.id DESC',args)
        return csv_download('aktivitaeten.csv',['Datum','Benutzer','Aktion','Details'],
            [[r[k] for k in r.keys()] for r in records])

    @app.get('/systemcheck')
    async def systemcheck_page(request:Request):
        user,co=current(request,'admin')
        with transaction(db_path) as con:
            report=check_installation(con,root,co,bool(user['is_superadmin']))
        return view(request,'systemcheck.html',report=report)

    @app.get('/help')
    async def help_page(request:Request):
        user,co=current(request)
        return view(request,'help.html')

    @app.get('/health')
    async def health(request:Request):
        # keine Mandantendaten herausgeben
        return {'status':'ok','application':'Swiss-invoice-RX'}

    return app

app=create_app()
