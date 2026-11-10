"""Company-scoped document numbering; reserved numbers are never reused silently."""
import re

KINDS = {
    'invoice': ('next_invoice', 'number_prefix', 'RE'),
    'quote': ('next_quote', 'quote_prefix', 'OF'),
    'credit': ('next_credit', 'credit_prefix', 'GS'),
}


def valid_prefix(value, default='RE'):
    prefix = str(value if value is not None else default).strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{0,9}', prefix):
        raise ValueError('Praefix: 1-10 Zeichen (A-Z, 0-9, Bindestrich, Unterstrich).')
    return prefix


def valid_number(value):
    number = str(value or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}', number):
        raise ValueError('Belegnummer: 1-40 Zeichen, keine Schraegstriche oder Sonderzeichen; erlaubt sind Buchstaben, Zahlen, Leerzeichen, Punkt, _ und -.')
    return number


def valid_counter(value):
    try:
        result = int(str(value).strip())
    except (ValueError, TypeError) as exc:
        raise ValueError('Naechste Nummer muss eine ganze Zahl sein.') from exc
    if not 1 <= result <= 999999999:
        raise ValueError('Naechste Nummer: erlaubt sind 1 bis 999999999.')
    return result


def valid_padding(value):
    try:
        result = int(str(value).strip())
    except (ValueError, TypeError) as exc:
        raise ValueError('Stellenzahl muss eine ganze Zahl sein.') from exc
    if not 3 <= result <= 9:
        raise ValueError('Stellenzahl: 3 bis 9 Ziffern.')
    return result


def _candidate(company, kind, sequence, year):
    _, field, default = KINDS[kind]
    prefix = valid_prefix(company.get(field, default), default)
    padding = valid_padding(company.get('number_padding', 5))
    return f'{prefix}-{year}-{sequence:0{padding}d}'


def is_taken(con, company_id, number, exclude_id=None):
    sql = 'SELECT id FROM invoices WHERE company_id=? AND number=? COLLATE NOCASE'
    args = [company_id, number]
    if exclude_id is not None:
        sql += ' AND id<>?'
        args.append(exclude_id)
    return con.execute(sql, args).fetchone() is not None


def ensure_available(con, company_id, number, exclude_id=None):
    number = valid_number(number)
    if is_taken(con, company_id, number, exclude_id):
        raise ValueError(f'Die Nummer "{number}" ist in diesem Geschaeft bereits vergeben. Bitte eine andere waehlen.')
    return number


def peek_number(con, company_id, kind, company, year):
    column = KINDS[kind][0]
    record = con.execute(f'SELECT {column} FROM companies WHERE id=?', (company_id,)).fetchone()
    if not record:
        raise ValueError('Geschaeft nicht gefunden')
    start = int(record[0])
    for sequence in range(start, start + 100000):
        candidate = _candidate(company, kind, sequence, year)
        if not is_taken(con, company_id, candidate):
            return candidate, sequence
    raise ValueError('Kein freier Nummernbereich gefunden. Bitte die Startnummer erhoehen.')


def assign_number(con, company_id, kind, company, year):
    number, sequence = peek_number(con, company_id, kind, company, year)
    column = KINDS[kind][0]
    con.execute(f'UPDATE companies SET {column}=? WHERE id=?', (sequence + 1, company_id))
    return number
