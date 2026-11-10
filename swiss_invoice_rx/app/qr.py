"""Swiss QR-bill (SIX IG 2.4): strukturierte Adresse, gültige Referenzen, CHF/EUR."""
import re
from decimal import Decimal
import qrcode
from PIL import Image, ImageDraw
from .billing import dec


def normalize_iban(value):
    return re.sub(r'\s+', '', str(value or '')).upper()


def valid_iban(value):
    iban = normalize_iban(value)
    if not re.fullmatch(r'(CH|LI)[0-9A-Z]{19}', iban):
        return False
    converted = ''.join(str(int(c, 36)) if c.isalpha() else c for c in iban[4:] + iban[:4])
    return int(converted) % 97 == 1


def is_qr_iban(iban):
    iban = normalize_iban(iban)
    return valid_iban(iban) and iban[4:9].isdigit() and 30000 <= int(iban[4:9]) <= 31999


def qrr_reference(seed):
    digits = ''.join(c for c in str(seed) if c.isdigit())
    base = (digits or '1')[-26:].zfill(26)
    table = [0,9,4,6,8,2,7,1,3,5]
    carry = 0
    for digit in base:
        carry = table[(carry + int(digit)) % 10]
    return base + str((10 - carry) % 10)


def valid_qrr(value):
    if not re.fullmatch('[0-9]{27}', value or '') or int(value) == 0:
        return False
    return qrr_reference(value[:26]) == value


def scor_reference(seed):
    raw = re.sub('[^A-Z0-9]', '', str(seed).upper())[-21:] or '1'
    converted = ''.join(str(int(x, 36)) if x.isalpha() else x for x in raw + 'RF00')
    check = 98 - (int(converted) % 97)
    return f'RF{check:02d}{raw}'


def valid_scor(ref):
    v = (ref or '').upper()
    if not re.fullmatch(r'RF[0-9]{2}[A-Z0-9]{1,21}', v):
        return False
    converted = ''.join(str(int(x, 36)) if x.isalpha() else x for x in v[4:] + v[:4])
    return int(converted) % 97 == 1


def addr(party, required=True):
    # Standard sieht ausschließlich strukturierte Anschriften (Typ S) vor.
    name = str(party.get('name') or '').strip()
    street = str(party.get('street') or '').strip()
    building = str(party.get('building') or '').strip()
    postal = str(party.get('zip') or '').strip()
    city = str(party.get('city') or '').strip()
    country = str(party.get('country') or 'CH').upper().strip()
    if required and (not name or not postal or not city or not re.fullmatch('[A-Z]{2}', country)):
        raise ValueError('Fuer den Swiss QR-Code benoetigt es Name, PLZ, Ort und Laendercode (strukturierte Adresse).')
    if len(name) > 70 or len(street) > 70 or len(building) > 16 or len(postal) > 16 or len(city) > 35:
        raise ValueError('QR-Adresse: Feldlaenge ueberschritten')
    return ['S', name, street, building, postal, city, country]


def build_payload(company, customer, amount, currency='CHF', reference_seed='', message=''):
    iban = normalize_iban(company.get('iban', ''))
    if not valid_iban(iban):
        raise ValueError('Bitte zuerst eine gueltige Schweizer oder Liechtensteiner IBAN in den Firmendaten hinterlegen.')
    if currency not in ('CHF', 'EUR'):
        raise ValueError('QR-Rechnungen sind nur in CHF oder EUR moeglich.')
    amount = dec(amount)
    if amount <= 0 or amount > Decimal('999999999.99'):
        raise ValueError('QR-Zahlteil: Betrag muss zwischen CHF/EUR 0.01 und 999999999.99 liegen.')
    requested = str(company.get('qr_reference_type', 'AUTO') or 'AUTO').upper()
    if requested not in ('AUTO', 'QRR', 'SCOR', 'NON'):
        raise ValueError('QR-Referenzart ist ungueltig. Bitte die QR-Einstellungen pruefen.')
    qr_iban = is_qr_iban(iban)
    ref_type = ('QRR' if qr_iban else 'SCOR') if requested == 'AUTO' else requested
    if qr_iban and ref_type != 'QRR':
        raise ValueError('QR-IBAN erfordert eine QR-Referenz (QRR). Einstellung AUTO oder QRR verwenden.')
    if not qr_iban and ref_type == 'QRR':
        raise ValueError('Eine QR-Referenz (QRR) benoetigt eine QR-IBAN. Mit normaler IBAN SCOR oder NON verwenden.')
    if ref_type == 'QRR' and currency != 'CHF':
        raise ValueError('QR-IBAN mit QR-Referenz ist nach SIX IG 2.4 nur in CHF zulaessig.')
    reference = (qrr_reference(reference_seed) if ref_type == 'QRR' else
                 scor_reference('INV' + str(reference_seed)) if ref_type == 'SCOR' else '')
    template = str(company.get('qr_message', '{number}'))
    message = template.replace('{number}', str(message)).strip()
    if any(ord(char) < 32 for char in message):
        raise ValueError('QR-Mitteilung enthaelt ungueltige Steuerzeichen.')
    if len(message) > 140:
        raise ValueError('QR-Mitteilung zu lang: maximal 140 Zeichen inklusive Rechnungsnummer.')
    lines = [
        'SPC', '0200', '1', iban,
        *addr(company),
        *([''] * 7),  # Ultimate creditor: 7 reservierte Leerfelder
        f'{amount:.2f}', currency,
        *addr(customer),
        ref_type, reference, message,
        'EPD', '',  # Trailer, Billing information
    ]
    # Alternative Verfahren 1/2 werden weggelassen, da sie nicht verwendet werden.
    payload = '\r\n'.join(lines)
    if len(payload) > 997:
        raise ValueError('QR-Daten zu lang')
    return {'payload': payload, 'reference_type': ref_type, 'reference': reference, 'iban': iban, 'message': message}


def qr_image(payload, pixel_size=920):
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=12, border=0)
    qr.add_data(payload)
    qr.make(fit=True)
    if qr.version > 25:
        raise ValueError('QR-Code hat die maximal erlaubte Groesse ueberschritten')
    im = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    im = im.resize((pixel_size, pixel_size), Image.Resampling.NEAREST)
    # SIX: zentriertes 7x7mm-Logo, schwarzes Quadrat mit weissem Schweizerkreuz.
    s = round(pixel_size * 7 / 46)
    x = (pixel_size - s) // 2
    draw = ImageDraw.Draw(im)
    draw.rectangle((x, x, x+s, x+s), fill='white')
    margin = max(3, round(s * .09))
    draw.rectangle((x+margin, x+margin, x+s-margin, x+s-margin), fill='black')
    cx = pixel_size // 2
    arm = max(2, round(s * 0.12))
    length = round(s * 0.30)
    draw.rectangle((cx-arm, cx-length, cx+arm, cx+length), fill='white')
    draw.rectangle((cx-length, cx-arm, cx+length, cx+arm), fill='white')
    return im
