"""Sichere CSV-Verarbeitung fuer lokalen Kunden- und Artikelstamm."""
import csv
import io
from decimal import Decimal, InvalidOperation
from starlette.datastructures import UploadFile

MAX_CSV_BYTES = 2_000_000
MAX_CSV_ROWS = 2000

CUSTOMER_FIELDS = ('name', 'contact', 'email', 'phone', 'street', 'building',
                   'zip', 'city', 'country', 'group_name', 'notes', 'payment_days')
ITEM_FIELDS = ('sku', 'name', 'kind', 'category', 'description', 'cost',
               'price', 'tax_rate', 'tax_mode', 'stock', 'track_stock')


def read_csv(upload):
    if not isinstance(upload, UploadFile) or not upload.filename:
        raise ValueError('Bitte eine CSV-Datei auswaehlen')
    f = upload.file
    f.seek(0, 2)
    length = f.tell()
    f.seek(0)
    if not length or length > MAX_CSV_BYTES:
        raise ValueError('CSV ist leer oder groesser als 2 MB')
    raw = f.read()
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        content = raw.decode('cp1252')
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=';,\t')
        delimiter = dialect.delimiter
    except csv.Error:
        header = sample.splitlines()[0] if sample.splitlines() else ''
        delimiter = ';' if ';' in header else ','
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError('CSV-Kopfzeile fehlt')
    fields = [str(f or '').strip().lower() for f in reader.fieldnames]
    if len(fields) != len(set(fields)) or 'name' not in fields:
        raise ValueError('CSV braucht eine eindeutige Spalte name')
    rows = []
    for index, rawrow in enumerate(reader, 2):
        if index > MAX_CSV_ROWS + 1:
            raise ValueError('Maximal 2000 Datensaetze pro CSV-Import')
        if None in rawrow:
            raise ValueError(f'CSV-Zeile {index}: zu viele Spalten')
        cleaned = {str(k).strip().lower(): str(v or '').strip()
                   for k, v in rawrow.items()}
        if any(cleaned.values()):
            rows.append((index, cleaned))
    if not rows:
        raise ValueError('Keine importierbaren CSV-Zeilen gefunden')
    return rows


def safe_csv(value, numeric=False):
    """Verhindert Excel-Formelinjektion in exportierten Textspalten."""
    s = str(value if value is not None else '')
    if numeric:
        try:
            v = Decimal(s)
            if v.is_finite():
                return s
        except InvalidOperation:
            pass
    if s.lstrip().startswith(('=', '+', '-', '@')) or s.startswith(('\t', '\r', '\n')):
        return "'" + s
    return s
