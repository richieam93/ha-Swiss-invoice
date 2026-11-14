"""SQLite-Storage. Jede Mandantentabelle hat company_id; alle Abfragen filtern darauf."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = r"""
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, full_name TEXT NOT NULL,
 restricted_company_id INTEGER DEFAULT NULL,
 can_create_company INTEGER NOT NULL DEFAULT 0,
 invited_from_company_id INTEGER DEFAULT NULL,
 is_superadmin INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
 failed_logins INTEGER NOT NULL DEFAULT 0, locked_until TEXT DEFAULT '',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS companies (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, street TEXT NOT NULL DEFAULT '',
 building TEXT NOT NULL DEFAULT '', zip TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '',
 country TEXT NOT NULL DEFAULT 'CH', email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
 uid TEXT NOT NULL DEFAULT '', iban TEXT NOT NULL DEFAULT '', currency TEXT NOT NULL DEFAULT 'CHF',
 business_type TEXT NOT NULL DEFAULT 'company',
 tax_registered INTEGER NOT NULL DEFAULT 0, default_tax TEXT NOT NULL DEFAULT '0',
 color TEXT NOT NULL DEFAULT '#2563eb', logo_path TEXT NOT NULL DEFAULT '',
 app_logo_path TEXT NOT NULL DEFAULT '',
 pdf_show_draft_mark INTEGER NOT NULL DEFAULT 1,
 footer_text TEXT NOT NULL DEFAULT 'Vielen Dank fuer Ihren Auftrag.',
 payment_terms TEXT NOT NULL DEFAULT 'Zahlbar innert {days} Tagen.',
 default_due_days INTEGER NOT NULL DEFAULT 30, number_prefix TEXT NOT NULL DEFAULT 'RE',
 quote_prefix TEXT NOT NULL DEFAULT 'OF', credit_prefix TEXT NOT NULL DEFAULT 'GS',
 number_padding INTEGER NOT NULL DEFAULT 5,
 qr_reference_type TEXT NOT NULL DEFAULT 'AUTO', qr_message TEXT NOT NULL DEFAULT '{number}',
 next_invoice INTEGER NOT NULL DEFAULT 1, next_quote INTEGER NOT NULL DEFAULT 1,
 next_credit INTEGER NOT NULL DEFAULT 1, template_style TEXT NOT NULL DEFAULT 'modern',
 template_title TEXT NOT NULL DEFAULT 'Rechnung', template_accent TEXT NOT NULL DEFAULT '#2563eb',
 template_show_logo INTEGER NOT NULL DEFAULT 1, template_footer TEXT NOT NULL DEFAULT '',
 template_header_layout TEXT NOT NULL DEFAULT 'standard',
 template_title_size INTEGER NOT NULL DEFAULT 26,
 template_density TEXT NOT NULL DEFAULT 'normal',
 template_show_service_date INTEGER NOT NULL DEFAULT 1,
 template_show_tax_breakdown INTEGER NOT NULL DEFAULT 1,
 template_show_payment_terms INTEGER NOT NULL DEFAULT 1,
 template_show_customer_email INTEGER NOT NULL DEFAULT 0,
 template_table_style TEXT NOT NULL DEFAULT 'lines',
 template_logo_size INTEGER NOT NULL DEFAULT 110,
 template_body_size INTEGER NOT NULL DEFAULT 9,
 template_show_page_numbers INTEGER NOT NULL DEFAULT 1,
 designer_enabled INTEGER NOT NULL DEFAULT 0,
 designer_layout TEXT NOT NULL DEFAULT '',
 default_invoice_notes TEXT NOT NULL DEFAULT '',
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS invoice_templates (
 id INTEGER PRIMARY KEY,
 company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 name TEXT NOT NULL COLLATE NOCASE,
 payload TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(company_id,name)
);
CREATE INDEX IF NOT EXISTS ix_template_company ON invoice_templates(company_id, active);
CREATE TABLE IF NOT EXISTS memberships (
 company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK(role IN ('admin','editor','viewer')),
 PRIMARY KEY(company_id, user_id)
);
CREATE TABLE IF NOT EXISTS customers (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 number TEXT NOT NULL DEFAULT '', name TEXT NOT NULL,
 contact TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
 street TEXT NOT NULL DEFAULT '', building TEXT NOT NULL DEFAULT '', zip TEXT NOT NULL DEFAULT '',
 city TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT 'CH',
 group_name TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
 payment_days INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(company_id, number)
);
CREATE TABLE IF NOT EXISTS items (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 sku TEXT NOT NULL DEFAULT '', name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'product',
 category TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
 cost TEXT NOT NULL DEFAULT '0.00', price TEXT NOT NULL DEFAULT '0.00',
 tax_rate TEXT NOT NULL DEFAULT '0', tax_mode TEXT NOT NULL DEFAULT 'taxable', stock TEXT NOT NULL DEFAULT '0',
 track_stock INTEGER NOT NULL DEFAULT 0, reorder_point TEXT NOT NULL DEFAULT '5', image_path TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(company_id, sku)
);
CREATE TABLE IF NOT EXISTS invoices (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK(kind IN ('invoice','quote','credit')),
 number TEXT NOT NULL, customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
 customer_snapshot TEXT NOT NULL DEFAULT '{}', company_snapshot TEXT NOT NULL DEFAULT '{}',
 invoice_date TEXT NOT NULL, service_date TEXT NOT NULL DEFAULT '', due_date TEXT NOT NULL,
 currency TEXT NOT NULL DEFAULT 'CHF', status TEXT NOT NULL DEFAULT 'draft',
 notes TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', discount TEXT NOT NULL DEFAULT '0',
 subtotal TEXT NOT NULL DEFAULT '0.00', tax_total TEXT NOT NULL DEFAULT '0.00',
 total TEXT NOT NULL DEFAULT '0.00', paid_total TEXT NOT NULL DEFAULT '0.00',
 tax_breakdown TEXT NOT NULL DEFAULT '{}', pdf_file TEXT NOT NULL DEFAULT '',
 pdf_sha256 TEXT NOT NULL DEFAULT '', issued_at TEXT NOT NULL DEFAULT '',
 parent_id INTEGER DEFAULT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(company_id, number)
);
CREATE TABLE IF NOT EXISTS invoice_lines (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
 item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
 position INTEGER NOT NULL, description TEXT NOT NULL,
 qty TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'Stk.',
 price TEXT NOT NULL, tax_rate TEXT NOT NULL, tax_mode TEXT NOT NULL DEFAULT 'taxable', discount TEXT NOT NULL DEFAULT '0',
 line_net TEXT NOT NULL DEFAULT '0.00'
);
CREATE TABLE IF NOT EXISTS payments (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
 paid_at TEXT NOT NULL, amount TEXT NOT NULL, method TEXT NOT NULL DEFAULT 'Bank',
 note TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 reversed_at TEXT NOT NULL DEFAULT '', reversed_by INTEGER, reversal_note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS reminders (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
 level INTEGER NOT NULL, sent_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
 balance_at TEXT NOT NULL DEFAULT '', pdf_file TEXT NOT NULL DEFAULT '', pdf_sha256 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recurrings (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 source_invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
 interval_months INTEGER NOT NULL DEFAULT 1, next_date TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, UNIQUE(company_id, source_invoice_id)
);
CREATE TABLE IF NOT EXISTS bank_transactions (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 fingerprint TEXT NOT NULL, source TEXT NOT NULL, account_iban TEXT NOT NULL,
 value_date TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL,
 bank_reference TEXT NOT NULL DEFAULT '', payment_reference TEXT NOT NULL DEFAULT '',
 debtor TEXT NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT '', import_name TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','matched','ignored')),
 payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
 ignore_reason TEXT NOT NULL DEFAULT '', imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(company_id, fingerprint)
);
CREATE INDEX IF NOT EXISTS ix_bank_company_status ON bank_transactions(company_id, status, value_date);
CREATE TABLE IF NOT EXISTS stock_movements (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
 invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
 quantity TEXT NOT NULL, note TEXT NOT NULL, at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS activity (
 id INTEGER PRIMARY KEY, company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
 user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
 action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_cust_company ON customers(company_id, name);
CREATE INDEX IF NOT EXISTS ix_items_company ON items(company_id, name);
CREATE INDEX IF NOT EXISTS ix_invoices_company ON invoices(company_id, invoice_date);
CREATE INDEX IF NOT EXISTS ix_payments_company ON payments(company_id, invoice_id);
CREATE INDEX IF NOT EXISTS ix_lines_company ON invoice_lines(company_id, invoice_id);
"""


def db_connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=15000')
    return con


def initialize(path):
    con = db_connect(path)
    try:
        con.executescript(SCHEMA)
        # SQLite erweitert vorhandene Installationen additiv, ohne Belege zu loeschen.
        extra_columns = {
            'users': {'restricted_company_id': 'INTEGER DEFAULT NULL',
                      'can_create_company': 'INTEGER NOT NULL DEFAULT 0',
                      'invited_from_company_id': 'INTEGER DEFAULT NULL'},
            'customers': {'payment_days': 'INTEGER NOT NULL DEFAULT 0'},
            'items': {'reorder_point': "TEXT NOT NULL DEFAULT '5'"},
            'invoices': { 'subject': "TEXT NOT NULL DEFAULT ''" },
            'companies': {
                'business_type': "TEXT NOT NULL DEFAULT 'company'",
                'quote_prefix': "TEXT NOT NULL DEFAULT 'OF'",
                'credit_prefix': "TEXT NOT NULL DEFAULT 'GS'",
                'number_padding': 'INTEGER NOT NULL DEFAULT 5',
                'qr_reference_type': "TEXT NOT NULL DEFAULT 'AUTO'",
                'qr_message': "TEXT NOT NULL DEFAULT '{number}'",
                'template_header_layout': "TEXT NOT NULL DEFAULT 'standard'",
                'template_title_size': 'INTEGER NOT NULL DEFAULT 26',
                'template_density': "TEXT NOT NULL DEFAULT 'normal'",
                'template_show_service_date': 'INTEGER NOT NULL DEFAULT 1',
                'template_show_tax_breakdown': 'INTEGER NOT NULL DEFAULT 1',
                'template_show_payment_terms': 'INTEGER NOT NULL DEFAULT 1',
                'template_show_customer_email': 'INTEGER NOT NULL DEFAULT 0',
                'default_invoice_notes': "TEXT NOT NULL DEFAULT ''",
                'template_table_style': "TEXT NOT NULL DEFAULT 'lines'",
                'template_logo_size': 'INTEGER NOT NULL DEFAULT 110',
                'template_body_size': 'INTEGER NOT NULL DEFAULT 9',
                'template_show_page_numbers': 'INTEGER NOT NULL DEFAULT 1',
                'designer_enabled': 'INTEGER NOT NULL DEFAULT 0',
                'designer_layout': "TEXT NOT NULL DEFAULT ''",
                'app_logo_path': "TEXT NOT NULL DEFAULT ''",
                'pdf_show_draft_mark': 'INTEGER NOT NULL DEFAULT 1',
            },
            'payments': {
                'reversed_at': "TEXT NOT NULL DEFAULT ''",
                'reversed_by': 'INTEGER',
                'reversal_note': "TEXT NOT NULL DEFAULT ''",
            },
            'reminders': {
                'balance_at': "TEXT NOT NULL DEFAULT ''",
                'pdf_file': "TEXT NOT NULL DEFAULT ''",
                'pdf_sha256': "TEXT NOT NULL DEFAULT ''",
            },
        }
        for table, columns in extra_columns.items():
            existing = {row['name'] for row in con.execute(f'PRAGMA table_info({table})')}
            for field, declaration in columns.items():
                if field not in existing:
                    con.execute(f'ALTER TABLE {table} ADD COLUMN {field} {declaration}')
        con.execute('PRAGMA user_version=14')
        con.execute('PRAGMA journal_mode=WAL')
        con.commit()
    finally:
        con.close()


@contextmanager
def transaction(path, write=False):
    con = db_connect(path)
    try:
        if write:
            con.execute('BEGIN IMMEDIATE')
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def one(con, sql, args=()):
    return con.execute(sql, args).fetchone()


def allrows(con, sql, args=()):
    return con.execute(sql, args).fetchall()


def audit(con, company_id, user_id, action, detail=''):
    con.execute('INSERT INTO activity(company_id,user_id,action,detail) VALUES(?,?,?,?)',
                (company_id, user_id, action, str(detail)[:300]))
