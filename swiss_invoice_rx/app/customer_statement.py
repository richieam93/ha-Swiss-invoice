"""Read-only printable customer account statement (not a financial ledger)."""
import io
from datetime import date
from decimal import Decimal
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from .billing import cents, money
from .pdf import party_lines, txt, right, col, W, H, M, INK, MUTED


def create_customer_statement(company, customer, events, currency, start, end, today=None):
    """Events are {date, type, number, delta}; credits carry negative deltas.

    All events must already be company/customer-filtered by caller. No DB side effects.
    """
    if currency not in ('CHF', 'EUR'):
        raise ValueError('Ungueltige Waehrung')
    start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
    if start_d > end_d:
        raise ValueError('Startdatum liegt nach Enddatum')
    events = sorted(events, key=lambda e: (e['date'], 0 if e['type'] == 'Rechnung' else 1, e['number']))
    opening = sum((cents(e['delta']) for e in events if e['date'] < start), Decimal('0'))
    relevant = [e for e in events if start <= e['date'] <= end]
    if len(relevant) > 5000:
        raise ValueError('Zu viele Buchungen fuer einen Kontoauszug (max. 5000).')
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f'Kundenkonto {customer["name"]} {start} - {end}')
    accent = company.get('template_accent') or '#2563eb'
    balance = opening
    page = 0

    def header():
        nonlocal page
        page += 1
        c.setFillColor(col(accent))
        c.rect(0, H - 9, W, 9, fill=1, stroke=0)
        txt(c, M, H - 52, company.get('name', ''), 15, accent, True)
        right(c, W-M, H-52, 'Kundenkontoauszug', 19, INK, True)
        right(c, W-M, H-75, f'{start} bis {end}  |  {currency}', 9, MUTED)
        y = H - 103
        for line in party_lines(customer):
            txt(c, M, y, line, 10)
            y -= 15
        c.setStrokeColor(colors.HexColor('#dae2ec'))
        c.line(M, H-180, W-M, H-180)
        c.setFillColor(col('#eef3fa'))
        c.roundRect(M, H-224, W-2*M, 27, 4, stroke=0, fill=1)
        txt(c, M+10, H-213, 'Datum', 9, INK, True)
        txt(c, M+88, H-213, 'Vorgang / Beleg', 9, INK, True)
        right(c, W-M-95, H-213, 'Bewegung', 9, INK, True)
        right(c, W-M-11, H-213, 'Saldo', 9, INK, True)
        txt(c, M, 32, 'Kundenkontoauszug - informativ, keine Finanzbuchhaltung.', 8, MUTED)
        right(c, W-M, 32, f'Seite {page}', 8, MUTED)
        return H-254

    y = header()
    txt(c, M+88, y, 'Anfangssaldo', 9, MUTED)
    right(c, W-M-11, y, money(opening), 9, INK, True)
    y -= 26
    for ev in relevant:
        if y < 68:
            c.showPage()
            y = header()
        delta = cents(ev['delta'])
        balance += delta
        label = str(ev['type']) + ' ' + str(ev['number'])
        if len(label) > 46:
            label = label[:45] + '...'
        txt(c, M+10, y, ev['date'], 8.5)
        txt(c, M+88, y, label, 8.5)
        right(c, W-M-95, y, ('+' if delta > 0 else '') + money(delta), 8.5,
              INK if delta >= 0 else '#167453')
        right(c, W-M-11, y, money(balance), 9, INK, True)
        c.setStrokeColor(colors.HexColor('#eff2f7'))
        c.line(M+6, y-9, W-M-6, y-9)
        y -= 25
    if y < 78:
        c.showPage()
        y = header()
    y -= 11
    c.setStrokeColor(colors.HexColor('#bfccdd'))
    c.line(W-225, y+14, W-M, y+14)
    right(c, W-M-11, y, f'Schlusssaldo     {money(balance)} {currency}', 12, accent, True)
    if not relevant:
        txt(c, M, y-30, 'Keine Bewegungen im gewaehlten Zeitraum.', 9, MUTED)
    c.save()
    return buffer.getvalue()
