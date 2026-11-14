"""Company form and Swiss VAT settings for the self-service wizard.

A legal form does not in itself determine VAT liability. Never register or
change tax registration automatically based on legal form or turnover.
"""
import re
from .billing import dec
from .qr import normalize_iban, valid_iban, is_qr_iban

BUSINESS_TYPES = {
    'private': 'Privatperson (gelegentliche private Rechnungen)',
    'sole': 'Einzelunternehmen / selbständig',
    'company': 'Firma / Gesellschaft (z. B. GmbH oder AG)',
}


def parse_profile(data, *, editing=False):
    kind = str(data.get('business_type', 'company') or 'company').strip()
    if kind not in BUSINESS_TYPES:
        raise ValueError('Bitte eine gültige Geschäftsart auswählen.')
    tax_registered = bool(data.get('tax_registered'))
    if kind == 'private' and tax_registered:
        raise ValueError('Private Gelegenheitsrechnungen ohne MWST ausstellen. Für steuerpflichtige Erwerbstätigkeit bitte Einzelunternehmen oder Firma wählen.')
    name = str(data.get('name', '')).strip()
    if not name or len(name) > 120:
        raise ValueError('Geschäftsname erforderlich (maximal 120 Zeichen).')
    street = str(data.get('street', '')).strip()
    building = str(data.get('building', '')).strip()
    postal = str(data.get('zip', '')).strip()
    city = str(data.get('city', '')).strip()
    country = str(data.get('country', 'CH') or 'CH').upper().strip()
    if not street or not postal or not city:
        raise ValueError('Strasse, PLZ und Ort werden für die Rechnungsadresse benötigt.')
    if len(street) > 70 or len(building)>16 or len(postal)>16 or len(city)>35 or not re.fullmatch('[A-Z]{2}', country):
        raise ValueError('Bitte die strukturierte Adresse und den zweistelligen Ländercode prüfen.')
    iban=normalize_iban(data.get('iban', ''))
    if iban and not valid_iban(iban):
        raise ValueError('Bitte eine gültige CH-/LI-IBAN eingeben oder das Feld vorerst leer lassen.')
    currency=str(data.get('currency', 'CHF')).upper().strip()
    if currency not in ('CHF','EUR'):
        raise ValueError('Die Standardwährung muss CHF oder EUR sein.')
    qr_type=str(data.get('qr_reference_type','AUTO') or 'AUTO').upper().strip()
    if qr_type not in ('AUTO','QRR','SCOR','NON'):
        raise ValueError('Bitte eine gültige QR-Referenzart auswählen.')
    if iban and ((is_qr_iban(iban) and qr_type in ('SCOR','NON')) or
                 (not is_qr_iban(iban) and qr_type=='QRR')):
        raise ValueError('QR-Referenzart passt nicht zur IBAN. Wähle AUTO oder teste die Bankverbindung.')
    if iban and is_qr_iban(iban) and currency == 'EUR':
        raise ValueError('QR-IBAN mit QRR ist nur für CHF geeignet.')
    rate=str(dec(data.get('default_tax','8.1') or '0')) if tax_registered else '0'
    if dec(rate)<0 or dec(rate)>100:
        raise ValueError('Ungültiger MWST-Satz.')
    return dict(name=name, business_type=kind, street=street, building=building,
                zip=postal, city=city, country=country, iban=iban,
                currency=currency, qr_reference_type=qr_type,
                tax_registered=int(tax_registered), default_tax=rate,
                uid=str(data.get('uid','')).strip()[:60],
                email=str(data.get('email','')).strip()[:150],
                phone=str(data.get('phone','')).strip()[:60])
