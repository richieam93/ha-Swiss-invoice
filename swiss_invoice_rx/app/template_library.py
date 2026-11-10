"""Persisted named invoice-design snapshots; each row belongs to one business.

`companies` remains the authoritative active design, so existing invoice and PDF
code is compatible with installations made before the template library existed.
"""
import json

TEMPLATE_FIELDS = (
    'template_style', 'template_accent', 'template_title', 'template_footer',
    'template_show_logo', 'template_header_layout', 'template_title_size',
    'template_density', 'template_show_service_date', 'template_show_tax_breakdown',
    'template_show_payment_terms', 'template_show_customer_email',
    'default_invoice_notes', 'template_table_style', 'template_logo_size',
    'template_body_size', 'template_show_page_numbers',
    'designer_enabled', 'designer_layout',
)

DEFAULTS = {
    'template_style':'modern', 'template_accent':'#2563eb',
    'template_title':'Rechnung', 'template_footer':'', 'template_show_logo':1,
    'template_header_layout':'standard', 'template_title_size':26,
    'template_density':'normal', 'template_show_service_date':1,
    'template_show_tax_breakdown':1, 'template_show_payment_terms':1,
    'template_show_customer_email':0, 'default_invoice_notes':'',
    'template_table_style':'lines', 'template_logo_size':110,
    'template_body_size':9, 'template_show_page_numbers':1,
    'designer_enabled':0, 'designer_layout':'',
}


def snapshot(company):
    return {key: company.get(key, DEFAULTS[key]) for key in TEMPLATE_FIELDS}


def as_json(data):
    return json.dumps({key: data[key] for key in TEMPLATE_FIELDS}, ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'))


def create_initial(con, company):
    """Lazy one-time initialization; NEVER overwrite the existing live settings."""
    cid = company['id']
    count = con.execute('SELECT COUNT(*) FROM invoice_templates WHERE company_id=?',
                        (cid,)).fetchone()[0]
    if not count:
        con.execute('INSERT INTO invoice_templates(company_id,name,payload,active) VALUES(?,?,?,1)',
                    (cid, 'Standard', as_json(snapshot(company))))


def set_live_company(con, cid, options):
    con.execute('UPDATE companies SET '+','.join(f'{key}=?' for key in TEMPLATE_FIELDS)+
                ' WHERE id=?', tuple(options[key] for key in TEMPLATE_FIELDS)+(cid,))


def ensure_named(name):
    name = str(name or '').strip()
    if not (1 <= len(name) <= 60) or any(ord(ch)<32 for ch in name):
        raise ValueError('Vorlagenname: Bitte 1 bis 60 gueltige Zeichen eingeben.')
    return name
