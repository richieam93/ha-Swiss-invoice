"""Offline import of booked credit transactions from ISO 20022 camt.053/054.

This module deliberately does not book customer payments automatically.
A person must confirm the invoice assignment after import.
"""
from collections import Counter
from datetime import date
from decimal import InvalidOperation
import hashlib
import re
from xml.etree import ElementTree as ET

from .billing import cents, num
from .qr import normalize_iban

MAX_CAMT_BYTES = 3 * 1024 * 1024
MAX_CREDITS = 2000
CAMT_NAMESPACE = re.compile(r'^urn:iso:std:iso:20022:tech:xsd:camt\.(053|054)\.001\.\d{2,3}$')


def child(element, name):
    """Find direct XML child independently of its namespace prefix."""
    if element is None:
        return None
    return next((e for e in element if e.tag.rsplit('}', 1)[-1] == name), None)


def path(element, *names):
    for name in names:
        element = child(element, name)
        if element is None:
            return None
    return element


def value(element, *names):
    e = path(element, *names)
    return (e.text or '').strip() if e is not None else ''


def date_value(element):
    dt = value(element, 'Dt') or value(element, 'DtTm')
    if not dt:
        return ''
    dt = dt[:10]
    try:
        date.fromisoformat(dt)
    except ValueError as exc:
        raise ValueError('Bankdatei: Ungueltiges Buchungsdatum') from exc
    return dt


def parse_camt(payload):
    """Returns only positive, booked incoming transactions; no imports are persisted here.

    Supports camt.053 and camt.054 statement/notification entry transactions.
    Unsupported aggregated entries with ambiguous per-transaction amounts are rejected.
    """
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_CAMT_BYTES:
        raise ValueError('Bankdatei fehlt oder ist groesser als 3 MB.')
    if re.search(br'<!\s*(DOCTYPE|ENTITY)', payload, re.I):
        raise ValueError('Bankdatei: DTD und XML-Entities sind nicht erlaubt.')
    try:
        xml = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError('Keine gueltige XML-Bankdatei.') from exc
    if xml.tag.rsplit('}', 1)[-1] != 'Document':
        raise ValueError('Keine ISO-20022-camt.053/054-Datei.')
    xmlns = xml.tag.split('}', 1)[0][1:] if '}' in xml.tag else ''
    match = CAMT_NAMESPACE.fullmatch(xmlns)
    if not match:
        raise ValueError('Es werden nur ISO-20022-camt.053/054-Dateien unterstuetzt.')
    source = 'camt.' + match.group(1)
    message = child(xml, 'BkToCstmrStmt' if source == 'camt.053' else 'BkToCstmrDbtCdtNtfctn')
    if message is None:
        raise ValueError('Bankdatei: Kontoauszug / Gutschriftanzeige fehlt.')
    statements = [e for e in message if e.tag.rsplit('}', 1)[-1] in ('Stmt', 'Ntfctn')]
    if not statements:
        raise ValueError('Bankdatei: Kein Kontoauszug enthalten.')
    output = []
    occurrences = Counter()
    for stmt in statements:
        bank_iban = normalize_iban(value(stmt, 'Acct', 'Id', 'IBAN'))
        if not bank_iban:
            raise ValueError('Bankdatei ohne Konto-IBAN kann keinem Geschaeft sicher zugeordnet werden.')
        for entry in (e for e in stmt if e.tag.rsplit('}', 1)[-1] == 'Ntry'):
            if value(entry, 'CdtDbtInd') != 'CRDT' or value(entry, 'RvslInd').lower() == 'true':
                continue
            status = child(entry, 'Sts')
            status_code = ((status.text or '').strip() or value(status, 'Cd')).upper() if status is not None else ''
            if status_code not in ('BOOK', 'BOOKED', ''):
                continue
            booked_at = date_value(path(entry, 'BookgDt')) or date_value(path(entry, 'ValDt'))
            if not booked_at:
                raise ValueError('Bankdatei: Buchungsdatum bei einer Gutschrift fehlt.')
            ntry_ref = value(entry, 'AcctSvcrRef') or value(entry, 'NtryRef')
            details = [d for d in entry if d.tag.rsplit('}', 1)[-1] == 'NtryDtls']
            txns = [t for detail in details for t in detail if t.tag.rsplit('}', 1)[-1] == 'TxDtls']
            if not txns:
                txns = [None]
            for txn in txns:
                if txn is not None and value(txn, 'CdtDbtInd') not in ('', 'CRDT'):
                    continue
                # For a group with more than one transaction, each individual amount is mandatory.
                amt = path(txn, 'AmtDtls', 'TxAmt', 'Amt') if txn is not None else None
                if amt is None and txn is not None:
                    amt = path(txn, 'Amt')
                if amt is None:
                    if len(txns) > 1:
                        raise ValueError('Sammelbuchung ohne Einzelbetraege: Bankdatei bitte anders exportieren.')
                    amt = child(entry, 'Amt')
                if amt is None:
                    raise ValueError('Bankdatei: Zahlungsbetrag fehlt.')
                currency = amt.get('Ccy', '').upper()
                if currency not in ('CHF', 'EUR'):
                    continue  # Unsupported currencies are not silently converted.
                try:
                    amount = cents(amt.text or '')
                except (ValueError, InvalidOperation, TypeError) as exc:
                    raise ValueError('Bankdatei: Ungueltiger Zahlungsbetrag.') from exc
                if amount <= 0:
                    continue
                ref = value(txn, 'RmtInf', 'Strd', 'CdtrRefInf', 'Ref') if txn is not None else ''
                if not ref and txn is not None:
                    strd = path(txn, 'RmtInf', 'Strd')
                    if strd is not None:
                        ref = value(strd, 'CdtrRefInf', 'Ref')
                memo = value(txn, 'RmtInf', 'Ustrd') if txn is not None else ''
                if not memo:
                    memo = value(entry, 'AddtlNtryInf')
                txn_bank_ref = value(txn, 'Refs', 'AcctSvcrRef') if txn is not None else ''
                bank_reference = txn_bank_ref or ntry_ref or value(txn, 'Refs', 'EndToEndId')
                debtor = value(txn, 'RltdPties', 'Dbtr', 'Pty', 'Nm') or value(txn, 'RltdPties', 'Dbtr', 'Nm')
                if not debtor:
                    debtor = value(txn, 'RltdPties', 'UltmtDbtr', 'Pty', 'Nm')
                canonical = '\x1f'.join((bank_iban, booked_at, num(amount), currency,
                                        bank_reference.upper(), ref.upper().replace(' ', ''),
                                        debtor.strip().upper(), memo.strip().upper()))
                occurrences[canonical] += 1
                unique = canonical + '\x1f' + str(occurrences[canonical])
                output.append({
                    'fingerprint': hashlib.sha256(unique.encode('utf-8')).hexdigest(),
                    'source': source, 'account_iban': bank_iban, 'value_date': booked_at,
                    'amount': num(amount), 'currency': currency,
                    'bank_reference': bank_reference[:140], 'payment_reference': ref[:140],
                    'debtor': debtor[:200], 'message': memo[:500],
                })
                if len(output) > MAX_CREDITS:
                    raise ValueError('Zu viele Gutschriften: maximal 2000 pro Bankdatei.')
    if not output:
        raise ValueError('Keine gebuchten Gutschriften in CHF oder EUR gefunden.')
    return output
