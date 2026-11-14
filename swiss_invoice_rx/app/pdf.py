"""Rechnungs-PDF mit SIX-QR-Zahlteil (105 x 210 mm am Ende einer A4-Seite)."""
import io
import json
import textwrap
from decimal import Decimal
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from .billing import money, cents
from .qr import build_payload, qr_image, normalize_iban

W, H = A4
MM = 72 / 25.4
M = 48
INK = '#14233C'
MUTED = '#64748B'


def col(value):
    try:
        return colors.HexColor(str(value))
    except Exception:
        return colors.HexColor('#2563eb')


def txt(c, x, y, value, size=10, color=INK, bold=False):
    c.setFillColor(col(color))
    c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
    c.drawString(x, y, str(value or ''))


def right(c, x, y, value, size=10, color=INK, bold=False):
    c.setFillColor(col(color))
    c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
    c.drawRightString(x, y, str(value or ''))


def wrap_words(value, max_chars):
    chunks = []
    for paragraph in str(value or '').split('\n'):
        chunks.extend(textwrap.wrap(paragraph, width=max_chars, break_long_words=True, break_on_hyphens=False) or [''])
    return chunks


def title_parts(value, preferred=26, width=350):
    # Fit large customer-specific headings in the left half of the A4 sheet.
    # Never paint over dates on the right or off the edge of the page.
    title=str(value or 'Rechnung').strip() or 'Rechnung'
    for size in range(int(preferred),max(13,int(preferred)-5),-1):
        if stringWidth(title, 'Helvetica-Bold', size)<=width:
            return [title], size
    def fitted(size):
        remaining=title
        parts=[]
        while remaining:
            n=0
            while n<len(remaining) and stringWidth(remaining[:n+1], 'Helvetica-Bold',size)<=width:
                n+=1
            if n==len(remaining):
                parts.append(remaining)
                break
            if n==0:n=1
            word_break=remaining.rfind(' ',0,n+1)
            if word_break>0:
                n=word_break
            parts.append(remaining[:n].strip())
            remaining=remaining[n:].strip()
        return parts
    for size in range(int(preferred),13,-1):
        parts=fitted(size)
        if len(parts)<=2:
            return parts,size
    # Exceptional titles containing mostly very wide glyphs: explicit ellipsis.
    parts=fitted(14)
    if len(parts)>2:
        last=parts[1]
        while stringWidth(last+'...', 'Helvetica-Bold',14)>width:
            last=last[:-1]
        return [parts[0],last+'...'],14
    return parts,14


def party_lines(p):
    street = ' '.join([p.get('street', ''), p.get('building', '')]).strip()
    postcode = ' '.join([p.get('zip', ''), p.get('city', '')]).strip()
    return [line for line in [p.get('name', ''), street, postcode,
                              p.get('country', 'CH') if p.get('country', 'CH') not in ('CH', '') else ''] if line]


def section_header(c, inv, company, customer, page=1, preview=False):
    style = company.get('template_style', 'modern')
    accent = company.get('template_accent', company.get('color', '#2563eb'))
    if style != 'modern':
        accent = INK if style in ('classic', 'minimal') else accent
    if style == 'modern':
        c.setFillColor(col(accent))
        c.rect(0, H - 13, W, 13, stroke=0, fill=1)
    mirror = company.get('template_header_layout', 'standard') == 'mirrored'
    logo = company.get('logo_path', '')
    logo_size = int(company.get('template_logo_size',110) or 110)
    if logo_size not in (80,110,140):logo_size=110
    logo_x = W-M-logo_size if mirror else M
    if company.get('template_show_logo', 1) and logo:
        p = Path(logo)
        if p.is_file():
            try:
                c.drawImage(str(p), logo_x, H-99, width=logo_size, height=54,
                            preserveAspectRatio=True, anchor='sw', mask='auto')
            except (OSError, ValueError):
                pass
    else:
        if mirror:
            right(c, W-M, H-64, company.get('name', ''), 17, accent, True)
        else:
            txt(c, M, H-64, company.get('name', ''), 17, accent, True)
    for index, line in enumerate(party_lines(company) + [company.get('email', ''), company.get('phone', '')]):
        if line:
            if mirror:
                txt(c, M, H-54-index*13, line, 9, MUTED, index==0)
            else:
                right(c, W-M, H-54-index*13, line, 9, MUTED, index==0)
    if page == 1:
        y = H-171
        recipient = party_lines(customer)
        if company.get('template_show_customer_email', 0) and customer.get('email'):
            recipient.append(customer['email'])
        for line in recipient:
            txt(c, M, y, line, 10, INK, False)
            y -= 15
        kind = {'invoice': company.get('template_title', 'Rechnung'),
                'quote': 'Offerte', 'credit': 'Gutschrift'}[inv['kind']]
        title_size = int(company.get('template_title_size', 26) or 26)
        if title_size not in (22, 26, 30, 34):
            title_size = 26
        title_lines, title_size=title_parts(kind,title_size)
        if len(title_lines)==1:
            txt(c, M, H-284, title_lines[0], title_size, accent, True)
            num_y=H-314
        else:
            # The two-line heading stays clear of the right-hand date block.
            txt(c, M, H-268, title_lines[0], title_size, accent, True)
            txt(c, M, H-295, title_lines[1], title_size, accent, True)
            num_y=H-326
        txt(c, M, num_y, f"Nr. {inv['number']}", 11, MUTED)
        right(c, W-M, H-290, 'Datum: ' + inv['invoice_date'], 10)
        if inv.get('service_date') and company.get('template_show_service_date', 1):
            right(c, W-M, H-307, 'Leistungsdatum: ' + inv['service_date'], 9)
        right(c, W-M, H-324, 'Faellig: ' + inv['due_date'], 9)
        if company.get('uid'):
            txt(c, M, H-(342 if len(title_lines)>1 else 334), 'UID / MWST: ' + company['uid'], 8, MUTED)
    else:
        txt(c, M, H-166, 'Fortsetzung ' + inv['number'], 12, accent, True)
    c.setStrokeColor(colors.HexColor('#e2e8f0'))
    c.line(M, H-349 if page == 1 else H-180, W-M, H-349 if page == 1 else H-180)
    footer = str(company.get('template_footer') or company.get('footer_text', '')).replace('\n',' ')
    footer_width = W-2*M-92
    footer_lines = []
    while footer and len(footer_lines)<2:
        chunk = footer
        while chunk and stringWidth(chunk,'Helvetica',8)>footer_width:
            chunk=chunk[:-1]
        if not chunk:
            break
        if len(chunk)<len(footer):
            space=chunk.rfind(' ')
            if space>0:chunk=chunk[:space]
        footer_lines.append(chunk.strip())
        footer=footer[len(chunk):].strip()
    if footer and footer_lines:
        last=footer_lines[-1]
        while last and stringWidth(last+'...', 'Helvetica',8)>footer_width:
            last=last[:-1]
        footer_lines[-1]=last+'...'
    for idx,line in enumerate(footer_lines):
        txt(c,M,39-idx*12,line,8,MUTED)
    if company.get('template_show_page_numbers',1):
        right(c, W-M, 30, f'Seite {page}', 8, MUTED)
    if preview:
        c.setFillColor(col('#b91c1c'))
        c.setFont('Helvetica-Bold', 10)
        c.drawCentredString(W/2, 52, 'ENTWURF - NICHT VERSENDEN')


def line_table_header(c, y, accent, style='modern'):
    if style == 'modern':
        c.setFillColor(col(accent))
        c.roundRect(M, y-12, W-2*M, 29, 4, fill=1, stroke=0)
    elif style == 'classic':
        c.setFillColor(colors.HexColor('#e9edf4'))
        c.rect(M, y-12, W-2*M, 29, fill=1, stroke=0)
    else:
        c.setStrokeColor(col(INK))
        c.setLineWidth(1.3)
        c.line(M, y-12, W-M, y-12)
    head_color = '#ffffff' if style == 'modern' else INK
    txt(c, M+12, y-2, 'Beschreibung', 9, head_color, True)
    right(c, 359, y-2, 'Menge', 9, head_color, True)
    right(c, 431, y-2, 'Preis', 9, head_color, True)
    right(c, W-M-11, y-2, 'Total', 9, head_color, True)
    return y-37


def invoice_pages(c, inv, company, customer, lines, preview=False):
    accent = company.get('template_accent', '#2563eb') if company.get('template_style','modern') == 'modern' else INK
    density = company.get('template_density', 'normal')
    row_min_height, row_gap = {'compact': (29,11),'normal': (37,13),
                               'spacious': (49,16)}.get(density,(37,13))
    table_style=company.get('template_table_style','lines')
    body_size=int(company.get('template_body_size',9) or 9)
    if body_size not in (8,9,10): body_size=9
    page = 1
    section_header(c, inv, company, customer, page, preview=preview)
    if inv.get('subject'):
        for idx, sub_line in enumerate(wrap_words(inv['subject'],75)[:2]):
            txt(c,M,H-369-idx*13,sub_line,9,INK,idx==0)
    y = line_table_header(c, H-(407 if inv.get('subject') else 378), accent, company.get('template_style','modern'))
    for row_index, line in enumerate(lines):
        desc = wrap_words(line['description'], 41 if body_size<=9 else 37)
        if len(desc) > 10:
            desc = desc[:9] + ['...']
        row_height = max(row_min_height, 19 + row_gap * len(desc))
        if y-row_height < 197:
            c.showPage()
            page += 1
            section_header(c, inv, company, customer, page, preview=preview)
            y = line_table_header(c, H-209, accent, company.get('template_style','modern'))
        if table_style=='zebra' and row_index%2==1:
            c.setFillColor(col('#f0f5fb'))
            c.rect(M,y-row_height+2,W-2*M,row_height-2,fill=1,stroke=0)
        for i, part in enumerate(desc):
            txt(c, M+12, y-12-i*row_gap, part, body_size)
        right(c, 359, y-13, f"{line['qty']} {line['unit']}", body_size)
        right(c, 431, y-13, money(line['price']), body_size)
        right(c, W-M-11, y-13, money(line['line_net']), body_size, INK, True)
        if Decimal(str(line['discount'])) or line.get('tax_mode','taxable') != 'taxable':
            tax_text = {'exempt':'MWST befreit','excluded':'MWST ausgenommen'}.get(line.get('tax_mode'), 'MWST '+str(line['tax_rate'])+' %')
            txt(c, M+12, y-row_height+5, f"Rabatt {line['discount']} %  |  {tax_text}", 7, MUTED)
        if table_style=='lines':
            c.setStrokeColor(colors.HexColor('#ecf0f6'))
            c.line(M, y-row_height+2, W-M, y-row_height+2)
        y -= row_height
    tax_details = sorted(json.loads(inv['tax_breakdown'] or '{}').items(),
                         key=lambda x: (x[0] in ('exempt','excluded'), x[0]))
    # Mehrere Steuersaetze muessen separat lesbar bleiben; bei einem Satz kann
    # der Benutzer auf eine einzelne MWST-Gesamtzeile wechseln.
    show_detail = bool(company.get('template_show_tax_breakdown', 1)) or len(tax_details) > 1
    tax_row_count = len(tax_details) if show_detail else (1 if tax_details else 0)
    note_lines = wrap_words(inv.get('notes') or '', 88)[:7] if inv.get('notes') else []
    show_terms = inv['kind'] == 'invoice' and bool(company.get('template_show_payment_terms', 1))
    required = 120 + tax_row_count*17 + len(note_lines)*13 + (25 if show_terms else 0)
    if y-required < 78:
        c.showPage()
        page += 1
        section_header(c, inv, company, customer, page, preview=preview)
        y = H-215
    y -= 18
    right(c, W-M-11, y, f"Zwischensumme     {money(inv['subtotal'])} {inv['currency']}", 10)
    y -= 18
    if not show_detail and tax_details:
        rate = tax_details[0][0]
        name = {'exempt':'MWST befreit', 'excluded':'MWST ausgenommen'}.get(rate, 'MWST gesamt ('+rate+' %)')
        right(c, W-M-11, y, f"{name}     {money(inv['tax_total'])} {inv['currency']}", 9, MUTED)
        y -= 17
    else:
        for rate, values in tax_details:
            name = {'exempt':'MWST befreit', 'excluded':'MWST ausgenommen'}.get(rate, 'MWST '+rate+' %')
            right(c, W-M-11, y, f"{name}     {money(values['tax'])} {inv['currency']}", 9, MUTED)
            y -= 17
    c.setStrokeColor(colors.HexColor('#dbe3ef'))
    c.line(W-265, y+7, W-M, y+7)
    right(c, W-M-11, y-12, f"TOTAL     {money(inv['total'])} {inv['currency']}", 15, accent, True)
    y -= 57
    if note_lines:
        for part in note_lines:
            txt(c, M, y, part, 9, MUTED)
            y -= 13
    if show_terms:
        txt(c, M, y-8, company.get('payment_terms', '').replace('{days}', str(company.get('default_due_days', 30))), 9)
    c.showPage()
    return page


def _address_small(c, x, y, p, size=8, gap=11, max_lines=4):
    for index, line in enumerate(party_lines(p)[:max_lines]):
        for splitline in wrap_words(line, 33)[:2]:
            txt(c, x, y, splitline, size, INK, index == 0)
            y -= gap
    return y


def _label(c, x, y, label, value=None, size=8, gap=10):
    txt(c, x, y, label, 7, INK, True)
    y -= gap
    if value is not None:
        for line in wrap_words(value, 27)[:3]:
            txt(c, x, y, line, size)
            y -= gap
    return y-5


def qr_payment_page(c, inv, company, customer, qr, preview=False):
    """Ein separates A4-Blatt mit 210x105mm Zahlteil am Blattfuss."""
    c.setStrokeColor(colors.HexColor('#777777'))
    c.setDash(3, 4)
    c.line(0, 105*MM, W, 105*MM)
    c.line(62*MM, 0, 62*MM, 105*MM)
    c.setDash()
    txt(c, M, H-70, 'Zahlteil und Empfangsschein', 17, '#334155', True)
    txt(c, M, H-91, f"Rechnung {inv['number']}", 10, MUTED)
    txt(c, M, H-110, 'Zum Bezahlen den Swiss QR-Code mit Ihrer Banking-App scannen.', 9, MUTED)
    if preview:
        txt(c, M, H-137, 'ENTWURF - NICHT VERSENDEN', 13, '#b91c1c', True)

    # Empfangsschein, 62 x 105 mm
    x0 = 6*MM
    top = 99*MM
    txt(c, x0, top, 'Empfangsschein', 11, INK, True)
    y = top - 13*MM
    y = _label(c, x0, y, 'Konto / Zahlbar an', normalize_iban(company['iban']), 7, 9)
    y = _address_small(c, x0, y, company, 7, 9)
    y -= 7
    if qr['reference']:
        y = _label(c, x0, y, 'Referenz', qr['reference'], 6.4, 8)
    y = _label(c, x0, max(y, 33*MM), 'Zahlbar durch', None)
    _address_small(c, x0, y, customer, 7, 9)
    txt(c, x0, 17*MM, 'Währung', 7, INK, True)
    txt(c, x0, 12*MM, inv['currency'], 9, INK, True)
    txt(c, 33*MM, 17*MM, 'Betrag', 7, INK, True)
    txt(c, 33*MM, 12*MM, money(inv['total']), 9, INK, True)
    right(c, 60*MM, 4*MM, 'Annahmestelle', 7)

    # Zahlteil, 148 x 105 mm
    px = 67*MM
    txt(c, px, top, 'Zahlteil', 11, INK, True)
    qr_img = qr_image(qr['payload'])
    # 46x46 mm ohne quiet zone, zusaetzlich rundum weiss. QR mittig auf der linken Seite.
    c.drawImage(ImageReader(qr_img), px, 37*MM, 46*MM, 46*MM)
    txt(c, px, 22*MM, 'Währung', 8, INK, True)
    txt(c, px, 16*MM, inv['currency'], 11, INK, True)
    txt(c, px+25*MM, 22*MM, 'Betrag', 8, INK, True)
    txt(c, px+25*MM, 16*MM, money(inv['total']), 11, INK, True)

    rx = 117*MM
    yy = top-1*MM
    yy = _label(c, rx, yy, 'Konto / Zahlbar an', normalize_iban(company['iban']), 8, 11)
    yy = _address_small(c, rx, yy, company, 8, 10)
    if qr['reference']:
        yy = _label(c, rx, yy-2, 'Referenz', qr['reference'], 7.5, 9)
    if inv.get('notes'):
        yy = _label(c, rx, yy-2, 'Zusaetzliche Informationen', qr.get('message', ''), 7.5, 9)
    yy = min(yy-3, 39*MM)
    txt(c, rx, yy, 'Zahlbar durch', 8, INK, True)
    _address_small(c, rx, yy-11, customer, 8, 10)
    c.showPage()


def make_pdf(inv, company, customer, lines, preview=False, force_preview_label=False):
    """Returns (PDF bytes, QR metadata or None); raises on malformed configured QR."""
    company = dict(company)
    customer = dict(customer)
    inv = dict(inv)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, pageCompression=1)
    c.setTitle(f"{inv['number']} - {company['name']}")
    c.setAuthor(company['name'])
    # Display setting is per business, not per document template. A design
    # sample always shows the safety label, even when regular drafts do not.
    marked_preview = bool(preview and (force_preview_label or company.get('pdf_show_draft_mark', 1)))
    if company.get('designer_enabled'):
        from .designer import designer_invoice_pages
        designer_invoice_pages(c, inv, company, customer, lines, preview=marked_preview)
    else:
        invoice_pages(c, inv, company, customer, lines, preview=marked_preview)
    qr = None
    if inv['kind'] == 'invoice' and cents(inv['total']) > 0 and company.get('iban'):
        qr = build_payload(company, customer, inv['total'], inv['currency'],
                           f"{company.get('id', 1):05d}{inv.get('id', 1):012d}",
                           inv['number'])
        qr_payment_page(c, inv, company, customer, qr, preview=marked_preview)
    c.save()
    return buf.getvalue(), qr


def make_reminder_pdf(inv, company, customer, reminder, outstanding):
    """Erstellt eine datierte Mahnung inkl. optionalem QR-Zahlteil fuer den Restsaldo."""
    inv, company, customer, reminder = (dict(x) for x in (inv, company, customer, reminder))
    amount = cents(outstanding)
    if amount <= 0:
        raise ValueError('Nur offene Betraege koennen gemahnt werden')
    title = ('Zahlungserinnerung' if int(reminder['level']) == 1
             else f"{reminder['level']}. Mahnung")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, pageCompression=1)
    c.setTitle(title + ' - ' + inv['number'])
    c.setAuthor(company['name'])
    accent = company.get('template_accent', '#2563eb')
    c.setFillColor(col(accent))
    c.rect(0, H - 12, W, 12, stroke=0, fill=1)
    logo = company.get('logo_path', '')
    if logo and company.get('template_show_logo', 1) and Path(logo).is_file():
        try:
            c.drawImage(logo, M, H - 115, width=130, height=60,
                        preserveAspectRatio=True, anchor='sw', mask='auto')
        except (OSError, ValueError):
            txt(c, M, H-65, company['name'], 17, accent, True)
    else:
        txt(c, M, H-65, company['name'], 17, accent, True)
    for i, line in enumerate(party_lines(company) + [company.get('email',''), company.get('phone','')]):
        if line:
            right(c, W-M, H-62-i*13, line, 9, MUTED)
    y = H-175
    for line in party_lines(customer):
        txt(c, M, y, line, 11)
        y-=16
    txt(c, M, H-305, title, 25, accent, True)
    right(c, W-M, H-323, 'Datum: '+reminder['sent_at'], 10, MUTED)
    txt(c, M, H-357, f"Bezug: Rechnung {inv['number']}", 12, INK, True)
    txt(c, M, H-376, f"Rechnungsdatum: {inv['invoice_date']}   |   Faellig am: {inv['due_date']}", 9, MUTED)
    c.setStrokeColor(col('#d9e2ef'))
    c.line(M, H-392, W-M, H-392)
    txt(c, M, H-422, 'Guten Tag', 11)
    message = ('Bei unserer Zahlungskontrolle ist uns aufgefallen, dass der folgende '
               'Rechnungsbetrag noch offen ist. Bitte pruefen Sie, ob die Zahlung '
               'bereits veranlasst wurde.')
    for i, line in enumerate(wrap_words(message, 85)):
        txt(c, M, H-446-16*i, line, 10)
    c.setFillColor(col('#f3f6fa'))
    c.roundRect(M, H-565, W-2*M, 70, 7, fill=1, stroke=0)
    txt(c, M+17, H-523, 'Noch offen', 10, MUTED, True)
    right(c, W-M-17, H-529, f'{money(amount)} {inv["currency"]}', 20, accent, True)
    txt(c, M, H-595, 'Bitte begleichen Sie den offenen Betrag unter Angabe der Rechnungsnummer.', 10)
    if company.get('iban'):
        txt(c, M, H-613, 'IBAN: ' + normalize_iban(company['iban']), 10)
        txt(c, M, H-631, 'Ein QR-Zahlteil mit dem offenen Betrag befindet sich auf Seite 2.', 9, MUTED)
    if reminder.get('note'):
        for i, line in enumerate(wrap_words(reminder['note'], 85)[:4]):
            txt(c, M, H-662-15*i, line, 9)
    txt(c, M, 96, 'Falls Sie bereits bezahlt haben, betrachten Sie dieses Schreiben als gegenstandslos.', 9, MUTED)
    txt(c, M, 73, 'Freundliche Gruesse', 10)
    txt(c, M, 56, company['name'], 10, INK, True)
    right(c, W-M, 32, 'Seite 1', 8, MUTED)
    c.showPage()
    qr = None
    if company.get('iban'):
        qr = build_payload(company, customer, str(amount), inv['currency'],
                           f"{company.get('id', 1):05d}{inv.get('id', 1):012d}", inv['number'])
        remaining_inv = dict(inv)
        remaining_inv['total'] = str(amount)
        qr_payment_page(c, remaining_inv, company, customer, qr)
    c.save()
    return buf.getvalue(), qr


def make_qr_test_pdf(company, customer, qr, amount, currency, test_number):
    """One-page printable check sheet. Contains real QR data: never send to payers."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, pageCompression=1)
    c.setTitle('QR-TEST - NICHT VERSENDEN')
    txt(c, M, H-175, 'TEST / NICHT VERSENDEN', 23, '#b91c1c', True)
    txt(c, M, H-200, 'Nur zur technischen Kontrolle Ihrer QR-Einstellungen.', 11, INK)
    txt(c, M, H-222, 'Der QR-Code kann echte Zahlungsdaten enthalten.', 10, '#b91c1c', True)
    inv = {'number': test_number, 'currency': currency, 'total': str(amount), 'notes': ''}
    qr_payment_page(c, inv, company, customer, qr)
    c.save()
    return buf.getvalue()
