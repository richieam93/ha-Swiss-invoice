"""Mandantengetrennte, reine Lese-Suche fuer die lokale Oberflaeche.

Benutzereingaben werden weder als SQL-Code noch als HTML/URL verwendet.
"""
from urllib.parse import quote


def _like(text):
    # ! als ESCAPE-Zeichen: auch Prozent und Unterstrich sind Suchtext.
    value = text.replace('!', '!!').replace('%', '!%').replace('_', '!_')
    return '%' + value + '%'


def search_all(con, company_id, query, limit=8, can_edit=False):
    """Liefert die drei Trefferlisten fuer ausschliesslich EIN Geschaeft."""
    q = str(query or '').strip()[:80]
    result = {'invoices': [], 'customers': [], 'items': []}
    if len(q) < 2:
        return result
    needle = _like(q)
    bound = (company_id, needle, needle, needle, int(limit))
    rows = con.execute('''SELECT i.id,i.number,i.kind,i.status,i.currency,i.total,
                                 i.subject,c.name AS customer_name
        FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id AND c.company_id=i.company_id
        WHERE i.company_id=? AND (i.number LIKE ? ESCAPE '!'
            OR i.subject LIKE ? ESCAPE '!'
            OR c.name LIKE ? ESCAPE '!')
        ORDER BY CASE WHEN i.number=? THEN 0 ELSE 1 END, i.id DESC LIMIT ?''',
        (company_id,needle,needle,needle,q,int(limit))).fetchall()
    for r in rows:
        label_kind = {'invoice':'Rechnung','quote':'Offerte','credit':'Gutschrift'}.get(r['kind'],'Beleg')
        result['invoices'].append({
            'id':r['id'],'title':f"{label_kind} {r['number']}",
            'subtitle':f"{r['customer_name'] or 'Kein Kunde'} · {r['subject'] or r['status']} · {r['total']} {r['currency']}",
            'url':f"/invoices/{r['id']}"})
    rows = con.execute('''SELECT id,number,name,city,email FROM customers
        WHERE company_id=? AND active=1 AND (name LIKE ? ESCAPE '!'
        OR number LIKE ? ESCAPE '!' OR email LIKE ? ESCAPE '!')
        ORDER BY name COLLATE NOCASE LIMIT ?''', bound).fetchall()
    for r in rows:
        result['customers'].append({'id':r['id'],'title':r['name'],
            'subtitle':f"{r['number']} · {r['city']} · {r['email']}", 'url':f"/customers/{r['id']}"})
    rows = con.execute('''SELECT id,sku,name,category,price,kind FROM items
        WHERE company_id=? AND active=1 AND (name LIKE ? ESCAPE '!'
        OR sku LIKE ? ESCAPE '!' OR category LIKE ? ESCAPE '!')
        ORDER BY name COLLATE NOCASE LIMIT ?''', bound).fetchall()
    for r in rows:
        # Viewer duerfen Artikel ansehen, aber nicht bearbeiten: bestehende Artikelliste.
        url = (f"/items/{r['id']}/edit" if can_edit else
               '/items?q='+quote(r['sku'] or r['name']))
        result['items'].append({'id':r['id'],'title':r['name'],
            'subtitle':f"{r['sku']} · {r['category']} · {r['price']}", 'url':url})
    return result
