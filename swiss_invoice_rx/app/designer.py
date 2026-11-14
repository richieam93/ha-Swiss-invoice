"""A4 invoice-page designer: strict JSON validation and vector PDF rendering.

Coordinates are millimetres, measured from the top-left of A4. The regulated
Swiss QR payment part is deliberately rendered by the old dedicated renderer.
"""
import json
import math
import re
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from .billing import money, discount_details, discount_adjustment
from .pdf import MM, INK, MUTED, col, party_lines

PAGE_W, PAGE_H = 210, 297
ALLOWED = {'logo','sender','recipient','title','number','dates','subject',
           'table','totals','notes','terms','footer','uid','text','line','box','image'}
REQUIRED = {'sender','recipient','title','number','dates','table','totals'}
FLOW = {'table','totals','notes','terms'}
LABELS = {'logo':'Logo','sender':'Absender','recipient':'Empfänger',
          'title':'Titel','number':'Rechnungsnummer','dates':'Datum und Fälligkeit',
          'subject':'Betreff','table':'Positionstabelle','totals':'Betrag und Rabatte',
          'notes':'Bemerkungen','terms':'Zahlungsbedingungen','footer':'Fusszeile',
          'uid':'UID / MWST','text':'Eigener Text','line':'Linie','box':'Farbfläche','image':'Eigenes Bild'}
MIN_SIZES = {'table':(135,23),'totals':(80,25),'sender':(39,22),'recipient':(39,22),
             'title':(32,12),'number':(26,8),'dates':(40,22)}
DEFAULT_BLOCKS = [
  ('logo',15,14,51,19), ('sender',119,15,76,36),
  ('recipient',15,57,81,30), ('title',15,101,105,16),
  ('number',15,119,75,9), ('dates',127,101,68,28),
  ('subject',15,134,156,10), ('uid',15,146,90,8),
  ('table',15,155,180,45), ('totals',112,209,83,30),
  ('notes',15,242,124,10), ('terms',15,255,105,8),
  ('footer',15,287,180,7),
]

def _block(kind,x,y,w,h,n):
    return {'id':f'block-{n}','kind':kind,'x':x,'y':y,'w':w,'h':h,
            'size':24 if kind=='title' else (9 if kind not in ('number','dates') else 10),
            'color':'#2563eb' if kind in ('title','table','totals') else '#14233c','align':'left','text':'','asset':'','locked':False}

def default_layout():
    return {'version':1,'blocks':[_block(kind,x,y,w,h,i) for i,(kind,x,y,w,h) in enumerate(DEFAULT_BLOCKS,1)]}


def parse_layout(value):
    """Validate an untrusted browser payload before saving OR rendering it."""
    if value is None or value=='':
        value=default_layout()
    if isinstance(value,str):
        if len(value)>24000:
            raise ValueError('Layout ist zu gross (max. 24 KB).')
        try: value=json.loads(value)
        except (ValueError,TypeError) as exc: raise ValueError('Layout-JSON ist ungueltig.') from exc
    if not isinstance(value,dict) or value.get('version')!=1 or not isinstance(value.get('blocks'),list):
        raise ValueError('Bitte ein gueltiges A4-Layout benutzen.')
    blocks=value['blocks']
    if not 1<=len(blocks)<=35:
        raise ValueError('Bitte zwischen 1 und 35 Elemente verwenden.')
    kinds=set(); ids=set(); result=[]
    for b in blocks:
        if not isinstance(b,dict):raise ValueError('Ungueltiges Element im Layout.')
        kind=b.get('kind'); bid=b.get('id')
        if kind not in ALLOWED or not isinstance(bid,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,48}',bid):
            raise ValueError('Elementtyp oder Element-ID nicht erlaubt.')
        if bid in ids:raise ValueError('Element-IDs muessen eindeutig sein.')
        ids.add(bid)
        if kind not in ('text','box','line','image'):
            if kind in kinds:raise ValueError('Jedes Standardfeld darf nur einmal vorkommen.')
            kinds.add(kind)
        clean={'id':bid,'kind':kind}
        for key in ('x','y','w','h'):
            value=b.get(key)
            if isinstance(value,bool):raise ValueError('Ungueltige Position.')
            try: value=float(value)
            except (TypeError,ValueError) as exc:raise ValueError('Bitte gueltige A4-Koordinaten eingeben.') from exc
            if not math.isfinite(value):raise ValueError('Position muss endlich sein.')
            clean[key]=round(value,1)
        x,y,w,h=[clean[k] for k in ('x','y','w','h')]
        minw,minh=MIN_SIZES.get(kind,(3,2))
        if kind in ('logo','image'):
            # Bildelemente duerfen bis 30 mm ueber die Blattkante ragen (Beschnitt).
            # Mindestens 5 mm muessen sichtbar bleiben, damit sie bedienbar bleiben.
            if (x < -30 or y < -30 or x > 205 or y > 292 or
                    w < minw or w > 300 or h < minh or h > 330 or
                    x+w < 5 or y+h < 5):
                raise ValueError(f'{LABELS[kind]}: Bildposition oder Groesse ausserhalb des erlaubten Bereichs.')
        elif x<1 or y<1 or w<minw or h<minh or x+w>209.1 or y+h>296.1 or (kind=='table' and y>241):
            raise ValueError(f'{LABELS[kind]}: Element liegt ausserhalb von A4 oder ist zu klein.')
        sz=b.get('size',9)
        try:sz=int(sz)
        except (TypeError,ValueError) as exc:raise ValueError('Ungueltige Schriftgroesse.') from exc
        if sz<7 or sz>36:raise ValueError('Schriftgroesse muss zwischen 7 und 36 pt liegen.')
        clean['size']=sz
        color=str(b.get('color','#14233c'))
        if not re.fullmatch(r'#[a-fA-F0-9]{6}',color):
            raise ValueError('Nur hexadezimale Farben (#RRGGBB) sind erlaubt.')
        clean['color']=color.lower()
        align=b.get('align','left')
        if align not in ('left','right','center'):raise ValueError('Textausrichtung ist ungueltig.')
        clean['align']=align
        text=b.get('text','')
        if not isinstance(text,str) or len(text)>600 or any(ord(ch)<32 and ch not in '\n\t\r' for ch in text):
            raise ValueError('Der eigene Text ist ungueltig oder zu lang.')
        clean['text']=text
        asset=str(b.get('asset',''))
        if asset and not re.fullmatch(r'[a-f0-9]{32}\.jpg',asset):
            raise ValueError('Bildkennung ist ungueltig.')
        clean['asset']=asset
        fit=str(b.get('fit','contain'))
        if fit not in ('contain','cover','stretch'):
            raise ValueError('Bildanpassung nicht erlaubt.')
        clean['fit']=fit
        clean['locked']=bool(b.get('locked',False))
        result.append(clean)
    if REQUIRED-kinds:
        raise ValueError('Pflichtfelder fehlen: '+', '.join(LABELS[x] for x in sorted(REQUIRED-kinds)))
    return {'version':1,'blocks':result}


def dumps_layout(value):
    return json.dumps(parse_layout(value),ensure_ascii=False,separators=(',',':'))


def _fit_text(text, font, size, available):
    """Split at visual width using PDF font metrics (not character heuristics)."""
    out=[]
    for paragraph in str(text).replace('\t','  ').split('\n'):
        if not paragraph:out.append('');continue
        segment=''
        for word in paragraph.split(' '):
            proposed=word if not segment else segment+' '+word
            if stringWidth(proposed,font,size)<=available:
                segment=proposed
                continue
            if segment:out.append(segment);segment=''
            if stringWidth(word,font,size)<=available:
                segment=word
            else:
                chunk=''
                for ch in word:
                    if stringWidth(chunk+ch,font,size)>available and chunk:
                        out.append(chunk);chunk=''
                    chunk+=ch
                segment=chunk
        out.append(segment)
    return out


def _text(c,b,text,size=None,bold=False,color=None):
    """Clip all user-managed text to its own rectangle; never cross an A4 edge."""
    x,y,w,h=(b[k]*MM for k in ('x','y','w','h'))
    font='Helvetica-Bold' if bold else 'Helvetica'
    size=size or b['size']
    linegap=size*1.25
    avail=max(5,w-4)
    rows=_fit_text(text,font,size,avail)
    count=max(1,int((h-2)/linegap))
    if len(rows)>count:
        rows=rows[:count]
        last=rows[-1]
        while last and stringWidth(last+'...',font,size)>avail:last=last[:-1]
        rows[-1]=last+'...'
    c.saveState()
    rect=c.beginPath();rect.rect(x, A4[1]-y-h,w,h)
    c.clipPath(rect,stroke=0,fill=0)
    c.setFillColor(col(color or b['color']))
    c.setFont(font,size)
    yy=A4[1]-y-size-1
    for row in rows:
        if b['align']=='right':c.drawRightString(x+w-2, yy,row)
        elif b['align']=='center':c.drawCentredString(x+w/2,yy,row)
        else:c.drawString(x+2,yy,row)
        yy-=linegap
    c.restoreState()


def _draw_image(c,b,path):
    if not path or not Path(path).is_file():return
    x,y,w,h=(b[k]*MM for k in ('x','y','w','h'))
    try:
        # 'anchor' and negative baselines are handled by ReportLab; all images
        # are decoded to JPEG on upload, so PDF assets cannot embed scripts.
        img=ImageReader(str(path))
        iw,ih=img.getSize()
        fit=b.get('fit','contain')
        if fit=='stretch':
            c.drawImage(img,x,A4[1]-y-h,width=w,height=h,mask='auto')
        else:
            ratio=(max(w/iw,h/ih) if fit=='cover' else min(w/iw,h/ih))
            nw,nh=iw*ratio,ih*ratio
            if fit=='cover':
                c.saveState()
                region=c.beginPath();region.rect(x,A4[1]-y-h,w,h)
                c.clipPath(region,stroke=0,fill=0)
            c.drawImage(img,x+(w-nw)/2,A4[1]-y-(h+nh)/2,width=nw,height=nh,mask='auto')
            if fit=='cover':
                c.restoreState()
    except (OSError,ValueError):
        return


def _expand(template, inv, company, customer):
    replacements={
      '{nummer}':inv.get('number',''), '{kunde}':customer.get('name',''),
      '{firma}':company.get('name',''), '{datum}':inv.get('invoice_date',''),
      '{faellig}':inv.get('due_date',''), '{betrag}':money(inv.get('total','0')),
      '{waehrung}':inv.get('currency','CHF'), '{betreff}':inv.get('subject',''),
      '{iban}':company.get('iban',''), '{leistungsdatum}':inv.get('service_date',''),
    }
    for key,value in replacements.items():template=template.replace(key,str(value or ''))
    return template


def _draw_element(c,b,inv,co,cust,page,preview):
    kind=b['kind']
    if kind=='logo':
        if co.get('template_show_logo',1) and co.get('logo_path'):
            _draw_image(c,b,co['logo_path'])
        return
    if kind=='image':
        token=b.get('asset') or ''
        if token and re.fullmatch(r'[a-f0-9]{32}\.jpg',token):
            _draw_image(c,b,Path(co.get('designer_asset_root') or '/nonexistent')/token)
        return
    if kind=='line':
        c.setStrokeColor(col(b['color']));c.setLineWidth(max(.4,b['size']/5))
        yy=A4[1]-(b['y']+b['h']/2)*MM
        c.line(b['x']*MM,yy,(b['x']+b['w'])*MM,yy)
        return
    if kind=='box':
        c.saveState();c.setFillColor(col(b['color']))
        c.rect(b['x']*MM, A4[1]-(b['y']+b['h'])*MM,b['w']*MM,b['h']*MM,fill=1,stroke=0)
        c.restoreState();return
    if kind=='sender':
        text='\n'.join(party_lines(co)+[v for v in [co.get('email',''),co.get('phone','')] if v])
    elif kind=='recipient':
        text='\n'.join(party_lines(cust)+([cust['email']] if co.get('template_show_customer_email') and cust.get('email') else []))
    elif kind=='title':
        text={'invoice':co.get('template_title') or 'Rechnung','quote':'Offerte','credit':'Gutschrift'}[inv['kind']]
    elif kind=='number':text='Nr. '+str(inv['number'])
    elif kind=='dates':
        text='Datum: '+str(inv['invoice_date'])+'\nFaellig: '+str(inv['due_date'])
        if inv.get('service_date') and co.get('template_show_service_date',1):text+='\nLeistung: '+str(inv['service_date'])
    elif kind=='subject':text=inv.get('subject','')
    elif kind=='footer':text=co.get('template_footer') or co.get('footer_text','')
    elif kind=='uid':text=(('UID / MWST: ' if co.get('tax_registered',1) else 'UID: ')+co['uid']) if co.get('uid') else ''
    elif kind=='text':text=_expand(b['text'],inv,co,cust)
    else:return
    _text(c,b,text,bold=kind in ('title','number'))


def _header(c,b,co,y):
    """Table with columns scaled to the user's free width and x coordinate."""
    x,w=b['x']*MM,b['w']*MM
    c.setFillColor(col(b['color']))
    c.rect(x,A4[1]-y*MM-8*MM,w,8*MM,fill=1,stroke=0)
    labels=[('Beschreibung',x+3*MM,'left'),('Menge',x+w*.68,'right'),('Preis',x+w*.83,'right'),('Total',x+w-3*MM,'right')]
    c.setFillColor(colors.white);c.setFont('Helvetica-Bold',8)
    yy=A4[1]-(y+5)*MM
    for value,xx,align in labels:
        if align=='right':c.drawRightString(xx,yy,value)
        else:c.drawString(xx,yy,value)
    return y+9


def _row(c,b,line,y,co):
    """Return drawn row height in mm, with text wrapping and column alignment."""
    x,w=b['x']*MM,b['w']*MM
    body=min(12,max(7,int(b['size'])))
    desc=str(line['description'])
    parts=_fit_text(desc,'Helvetica',body,w*.51-8*MM)[:8]
    has_discount=Decimal(str(line.get('discount','0'))) != 0
    h=max(11,5+len(parts)*body*1.35/MM)+(5 if has_discount else 0)
    if str(co.get('template_table_style','lines'))=='zebra' and int(line.get('_index',0))%2:
        c.setFillColor(col('#f1f5fa'));c.rect(x,A4[1]-(y+h)*MM,w,h*MM,stroke=0,fill=1)
    c.setFillColor(col(INK));c.setFont('Helvetica',body)
    for idx,txt in enumerate(parts):
        c.drawString(x+3*MM,A4[1]-(y+4.5)*MM-idx*(body*1.35),txt)
    baseline=A4[1]-(y+4.5)*MM
    c.drawRightString(x+w*.68,baseline,str(line['qty'])+' '+str(line['unit']))
    c.drawRightString(x+w*.83,baseline,money(line['price']))
    c.setFont('Helvetica-Bold',body)
    c.drawRightString(x+w-3*MM,baseline,money(line.get('_position_net',line['line_net'])))
    if has_discount:
        c.setFillColor(col(MUTED));c.setFont('Helvetica',7)
        c.drawString(x+3*MM,A4[1]-(y+h-1.5)*MM,
                     'Positionsrabatt '+str(line['discount'])+' % ('+
                     discount_adjustment(line.get('_position_discount','0'))+' '+str(line.get('_currency','CHF'))+')')
    if co.get('template_table_style','lines')=='lines':
        c.setStrokeColor(col('#e2e8f0'));c.setLineWidth(.5)
        c.line(x,A4[1]-(y+h)*MM,x+w,A4[1]-(y+h)*MM)
    return h


def _summary_rows(inv, co, discounts):
    tax_enabled=bool(co.get('tax_registered',1))
    rate_items=sorted(json.loads(inv.get('tax_breakdown') or '{}').items()) if tax_enabled else []
    detail=co.get('template_show_tax_breakdown',1) or len(rate_items)>1
    has_global=Decimal(discounts['global_percent']) != 0
    first_total=discounts['after_positions'] if has_global else inv['subtotal']
    data=[('Zwischensumme', money(first_total)+' '+inv['currency'])]
    if has_global:
        data.extend([
            ('Gesamtrabatt '+discounts['global_percent']+' %',
             discount_adjustment(discounts['global_discount'])+' '+inv['currency']),
            ('Netto nach Rabatt',money(inv['subtotal'])+' '+inv['currency']),
        ])
    if not detail and rate_items:
        data.append(('MWST',money(inv['tax_total'])+' '+inv['currency']))
    else:
        for rate,entry in rate_items:
            label={'exempt':'MWST befreit','excluded':'MWST ausgenommen'}.get(rate,'MWST '+rate+' %')
            data.append((label,money(entry['tax'])+' '+inv['currency']))
    data.append(('TOTAL',money(inv['total'])+' '+inv['currency']))
    return data


def _summary(c,b,inv,co,start_y,data):
    x,y,w=(b[k]*MM for k in ('x','y','w'))
    y=start_y*MM
    base_size=max(7,min(12,b['size']))
    y_pt=A4[1]-y-7*MM
    for idx,(label,amount) in enumerate(data):
        last=idx==len(data)-1
        c.setFont('Helvetica-Bold' if last else 'Helvetica',base_size+3 if last else base_size)
        c.setFillColor(col(b['color'] if last else INK))
        c.drawString(x+2*MM,y_pt,label)
        c.drawRightString(x+w-2*MM,y_pt,amount)
        y_pt-=6.5*MM if last else 5.3*MM
    return max(b['h'],len(data)*6.2+6)


def designer_invoice_pages(c,inv,co,cust,lines,preview=False):
    """User-positioned first page; flow-based item table and summary across pages.

    Header blocks are absolutely positioned; the table/summary/notes reflow
    below the user's requested position as rows grow. The QR page is untouched.
    """
    layout=parse_layout(co.get('designer_layout',''))
    blocks=layout['blocks']
    bykind={b['kind']:b for b in blocks if b['kind'] not in ('text','image','box','line')}
    def decorate(page):
        if co.get('template_style')=='modern':
            c.setFillColor(col(co.get('template_accent','#2563eb')))
            c.rect(0,A4[1]-4*MM,A4[0],4*MM,stroke=0,fill=1)
        # Layers: decoration, free text, fixed statutory fields, footer.
        for b in blocks:
            if b['kind']=='box':_draw_element(c,b,inv,co,cust,page,preview)
        # Hintergrundbilder vor Belegtext zeichnen; grossflaechige Logos bleiben
        # dadurch nutzbar, ohne Pflichtangaben oder Betragsfelder zu verdecken.
        if page==1:
            for b in blocks:
                if b['kind'] in ('image','logo'):
                    _draw_element(c,b,inv,co,cust,page,preview)
        for b in blocks:
            if b['kind']=='footer' or (page==1 and b['kind'] not in FLOW and b['kind'] not in ('box','footer','image','logo')):
                _draw_element(c,b,inv,co,cust,page,preview)
        if page>1:
            c.setFillColor(col(MUTED));c.setFont('Helvetica-Bold',11)
            c.drawString(15*MM,A4[1]-25*MM,'Fortsetzung '+str(inv['number']))
        if co.get('template_show_page_numbers',1):
            c.setFont('Helvetica',8);c.setFillColor(col(MUTED))
            c.drawRightString(A4[0]-15*MM,11*MM,f'Seite {page}')
        if preview:
            c.setFillColor(col('#b91c1c'));c.setFont('Helvetica-Bold',9)
            c.drawCentredString(A4[0]/2,16*MM,'ENTWURF - NICHT VERSENDEN')
    discounts=discount_details(lines,inv.get('discount','0'))
    summary_data=_summary_rows(inv,co,discounts)
    page=1
    decorate(page)
    tb=bykind['table'];y=tb['y'];y=_header(c,tb,co,y)
    # Page bottom must stay clear of footer/preview marks.
    bottom=263
    for i,rawline in enumerate(lines):
        line=dict(rawline);line['_index']=i
        line['_position_net']=discounts['lines'][i]['after']
        line['_position_discount']=discounts['lines'][i]['discount']
        line['_currency']=inv['currency']
        # Calculate row height once for page break to prevent drawing past page.
        description=_fit_text(str(line['description']),'Helvetica',tb['size'],tb['w']*MM*.51-8*MM)[:8]
        row_h=max(11,5+len(description)*tb['size']*1.35/MM)+(
            5 if Decimal(str(line.get('discount','0'))) != 0 else 0)
        if y+row_h>bottom:
            c.showPage();page+=1;decorate(page)
            y=_header(c,tb,co,34)
        y+=_row(c,tb,line,y,co)
    summary=bykind['totals']
    size=max(summary['h'],len(summary_data)*6.2+6)
    extra=[]
    for kind in ('notes','terms'):
        b=bykind.get(kind)
        if not b:continue
        if kind=='terms':
            if inv.get('kind')!='invoice' or not co.get('template_show_payment_terms',1):continue
            text=str(co.get('payment_terms','')).replace('{days}',str(co.get('default_due_days',30)))
        else:text=inv.get('notes','')
        if text:extra.append((kind,b,text))
    start=max(y+5,summary['y'] if page==1 else 36)
    def final_bottom(start, use_configured):
        cursor=start+size
        for kind,b,text in extra:
            cursor=max(cursor+3,b['y'] if use_configured else cursor+3)+b['h']
        return cursor
    # Keep the first page complete when a small vertical adjustment is enough.
    # Respect deliberately distant custom summary coordinates (more than 20 mm).
    if page==1 and final_bottom(start,True)>265:
        compact=y+5
        if start-compact <= 20 and final_bottom(compact,True)<=265:
            start=compact
    # If it still does not fit, move totals and closing notes together.
    if final_bottom(start,page==1)>265:
        c.showPage();page+=1;decorate(page);start=36
    size=_summary(c,summary,inv,co,start,summary_data)
    cursor=start+size
    for kind,b,text in extra:
        remaining=_fit_text(text,'Helvetica',b['size'],b['w']*MM-4)
        next_y=max(cursor+3,b['y'] if page==1 else cursor+3)
        line_height=b['size']*1.25/MM
        while remaining:
            if next_y+8>265:
                c.showPage();page+=1;decorate(page);next_y=38
            maxlines=max(1,int(((263-next_y)*MM-3)/(b['size']*1.25)))
            chunk=remaining[:maxlines]
            remaining=remaining[maxlines:]
            needed=max(b['h'] if not remaining else 0,len(chunk)*line_height+2)
            if next_y+needed>264:
                needed=264-next_y
            adjustable=dict(b);adjustable['y']=next_y;adjustable['h']=needed
            _text(c,adjustable,'\n'.join(chunk))
            cursor=next_y+needed
            next_y=38
            if remaining:
                c.showPage();page+=1;decorate(page)
    c.showPage()
    return page
