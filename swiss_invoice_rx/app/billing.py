"""Geldbeträge IMMER mit Decimal und kaufmännischer Rappenrundung."""
import hashlib
import hmac
import os
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal('0.01')
TAX_RATES = ('0', '2.6', '3.8', '8.1')


def dec(value, default='0'):
    try:
        v = Decimal(str(value or default).strip().replace(',', '.'))
        if not v.is_finite():
            raise ValueError('Ungueltige Zahl')
        return v
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('Ungueltiger Zahlenwert') from exc


def cents(value):
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def num(value):
    return f'{cents(value):.2f}'


def money(value):
    v = cents(value)
    return f"{v:,.2f}".replace(',', "'")


def percent(value, field='Rabatt'):
    v = dec(value)
    if v < 0 or v > 100:
        raise ValueError(f'{field} muss zwischen 0 und 100 liegen')
    return v


def summarize(lines, global_discount='0'):
    discount = percent(global_discount)
    buckets = {}
    result = []
    for index, raw in enumerate(lines):
        description = str(raw.get('description', '')).strip()
        if not description:
            raise ValueError(f'Position {index+1}: Beschreibung fehlt')
        qty = dec(raw.get('qty', '1'))
        if qty == 0 or abs(qty) > 1000000:
            raise ValueError(f'Position {index+1}: Menge muss ungleich 0 sein')
        price = dec(raw.get('price', '0'))
        if price < 0 or price > 999999999:
            raise ValueError(f'Position {index+1}: Preis muss positiv sein')
        tax = dec(raw.get('tax_rate', '0'))
        mode = raw.get('tax_mode', 'taxable') or 'taxable'
        if mode not in ('taxable', 'exempt', 'excluded'):
            raise ValueError('Unzulaessige MWST-Behandlung')
        if mode != 'taxable':
            tax = Decimal('0')
        if tax < 0 or tax > 100:
            raise ValueError('Unzulaessiger MWST-Satz')
        disc = percent(raw.get('discount', '0'))
        raw_net = qty * price * (1 - disc / 100) * (1 - discount / 100)
        net = cents(raw_net)
        key = str(tax.normalize()) if mode == 'taxable' else mode
        buckets[key] = buckets.get(key, Decimal('0')) + net
        result.append({'item_id': raw.get('item_id') or None,
                       'description': description[:1000], 'qty': str(qty),
                       'unit': str(raw.get('unit', 'Stk.'))[:20],
                       'price': num(price), 'tax_rate': str(tax.normalize()), 'tax_mode': mode,
                       'discount': str(disc), 'line_net': num(net)})
    if not result:
        raise ValueError('Mindestens eine Rechnungsposition erfassen')
    taxes = {k: (cents(v * dec(k) / 100) if k not in ('exempt', 'excluded') else Decimal('0')) for k, v in buckets.items()}
    subtotal = sum(buckets.values(), Decimal('0'))
    tax_total = sum(taxes.values(), Decimal('0'))
    return {'lines': result, 'subtotal': num(subtotal), 'tax_total': num(tax_total),
            'total': num(subtotal + tax_total),
            'tax_breakdown': {k: {'net': num(v), 'tax': num(taxes[k])}
                              for k, v in buckets.items()}}


def hash_password(password):
    if len(password) < 10:
        raise ValueError('Passwort: mindestens 10 Zeichen erforderlich')
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 400_000)
    return 'pbkdf2_sha256$400000$' + salt.hex() + '$' + digest.hex()


def check_password(password, stored):
    try:
        method, count, salt, digest = stored.split('$')
        if method != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(count))
        return hmac.compare_digest(actual, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def future(days=30, base=None):
    return ((base or date.today()) + timedelta(days=int(days))).isoformat()


def valid_date(value):
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError('Bitte ein gueltiges Datum eingeben') from exc


def safe_color(value):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(value)):
        raise ValueError('Farbe muss im Format #123ABC angegeben werden')
    return value.lower()


def invoice_status(inv, today=None):
    if inv['status'] in ('draft', 'cancelled'):
        return inv['status']
    if inv['kind'] == 'quote':
        return 'sent'
    due = date.fromisoformat(inv['due_date'])
    if cents(inv['paid_total']) >= cents(inv['total']) and cents(inv['total']) > 0:
        return 'paid'
    if due < (today or date.today()) and inv['kind'] == 'invoice':
        return 'overdue'
    if cents(inv['paid_total']) > 0:
        return 'partial'
    return 'sent'
