"""Einfach erklaerte, rein lokale Versand- und QR-Vorabkontrollen."""
from decimal import Decimal
from .qr import valid_iban, is_qr_iban, addr, build_payload
from .billing import dec


def company_checks(company):
    items=[]
    def add(level,title,text):items.append({'level':level,'title':title,'text':text})
    if company.get('tax_registered') and not str(company.get('uid') or '').strip():
        add('warn','MWST-Nummer fehlt','Bei MWST-pflichtigen Unternehmen gehört die gültige UID mit Zusatz MWST auf die Rechnung. Bitte in Firmendaten ergänzen.')
    iban=str(company.get('iban') or '').strip()
    reference=str(company.get('qr_reference_type') or 'AUTO').upper()
    if not iban:
        add('warn','Keine Bankverbindung','Ohne IBAN wird die Rechnung ohne QR-Zahlteil erstellt. Unter Firmendaten eine IBAN hinterlegen.')
    elif not valid_iban(iban):
        add('error','IBAN pruefen','CH- oder LI-IBAN ist ungueltig. Bitte IBAN inklusive Pruefziffer kontrollieren.')
    else:
        qr=is_qr_iban(iban)
        add('ok','IBAN-Pruefziffer korrekt','QR-IBAN erkannt.' if qr else 'Normale IBAN erkannt.')
        if (qr and reference not in ('QRR','AUTO')) or (not qr and reference=='QRR'):
            add('error','Referenzart passt nicht','QR-IBAN benoetigt QRR, normale IBAN erlaubt SCOR oder NON.')
        elif qr and company.get('currency')=='EUR':
            add('warn','QR-IBAN mit EUR','QRR ist nur in CHF zulaessig. EUR-Rechnungen koennen damit keinen QR-Zahlteil erhalten.')
        else:
            add('ok','Referenzart passend','Auswahl '+reference+' ist zur Bankverbindung passend.')
    try:
        addr(company)
        add('ok','Strukturierte Firmenadresse','Name, PLZ, Ort und Land sind im QR-Datensatz vorhanden.')
    except ValueError as exc:
        add('error','Firmenadresse ergaenzen',str(exc))
    add('info','Testscan erforderlich','Die technische Pruefung ersetzt keinen Scan mit einer Bank-App und keine Zertifizierung.')
    return items


def invoice_checks(inv,company,customer,lines,items_by_id):
    checks=[]
    def add(level,title,text):checks.append({'level':level,'title':title,'text':text})
    if inv['kind']=='invoice':
        if not company.get('iban'):
            add('warn','QR-Zahlteil nicht aktiviert','Fuer einen QR-Zahlteil in den Firmendaten eine IBAN hinterlegen.')
        else:
            try:
                build_payload(company,customer or {},inv['total'],inv['currency'],
                              f"{company['id']:05d}{inv['id']:012d}",inv['number'])
                add('ok','QR-Zahlteil bereit','IBAN, Referenzart, Betrag und strukturierte Adressen technisch geprueft.')
            except ValueError as exc:
                add('error','QR-Zahlteil nicht bereit',str(exc))
        needed={}
        for line in lines:
            item=items_by_id.get(line.get('item_id'))
            if item and item['track_stock']:
                needed[item['id']]=needed.get(item['id'],Decimal('0'))+dec(line['qty'])
        shortages=[f"{items_by_id[item_id]['name']}: {qty} benoetigt, {items_by_id[item_id]['stock']} vorhanden"
                   for item_id,qty in needed.items() if dec(items_by_id[item_id]['stock'])<qty]
        if shortages:
            add('error','Lagerbestand zu niedrig','; '.join(shortages))
        elif needed:
            add('ok','Lagerbestand verfuegbar','Erfasste Lagerartikel sind in ausreichender Menge vorhanden.')
    if inv['due_date'] < inv['invoice_date']:
        add('warn','Fälligkeit vor Rechnungsdatum','Das Fälligkeitsdatum liegt vor dem Belegdatum; bitte kontrollieren.')
    if not inv.get('subject'):
        add('info','Betreff optional','Ein Projekt- oder Auftragsbetreff verbessert die Zuordnung beim Kunden.')
    if not lines:
        add('error','Keine Positionen','Bitte mindestens eine Position erfassen.')
    return checks
