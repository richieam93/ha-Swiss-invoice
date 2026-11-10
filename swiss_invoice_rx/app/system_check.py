"""Lesender Systemcheck. Kein Reparaturversuch, keine stillen Datenveraenderungen."""
import hashlib
import hmac
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .diagnostics import company_checks


def check_installation(con, root, company, superadmin=False, archive_limit=300):
    """Prueft genau den gewaehlten Mandanten und optionale install.-weite Sicherungen."""
    root = Path(root).resolve()
    cid = int(company['id'])
    checks = []
    problems = []
    def add(level, title, detail, url=''):
        checks.append({'level':level,'title':title,'text':detail,'url':url})

    # Nur pruefen, niemals Datenbank automatisch korrigieren.
    status = con.execute('PRAGMA quick_check').fetchone()[0]
    if str(status).lower() == 'ok':
        add('ok','SQLite-Datenbank lesbar','Die interne SQLite-Struktur hat den Quick-Check bestanden.')
    else:
        add('error','Datenbank pruefen',f'Quick-Check meldet: {str(status)[:100]}. Backup nicht ueberschreiben.')

    for c in company_checks(company):
        if c['level']=='info':
            continue
        add(c['level'], c['title'], c['text'], '/settings' if c['level']!='ok' else '')
    if company.get('tax_registered') and not company.get('uid'):
        add('warn','MWST-Nummer fehlt','Bei MWST-Pflicht bitte UID/MWST-Nummer unter Firmendaten hinterlegen.','/settings')
    if company.get('template_show_logo') and company.get('logo_path'):
        logo = (root / company['logo_path']).resolve()
        if not logo.is_relative_to((root/'uploads').resolve()) or not logo.is_file():
            add('warn','Firmenlogo fehlt','Gespeichertes Logo konnte nicht gefunden werden.','/settings')

    scanned = 0
    verified = 0
    rows = con.execute('''SELECT id,number,pdf_file,pdf_sha256 FROM invoices
        WHERE company_id=? AND pdf_file!='' ORDER BY id DESC LIMIT ?''',(cid,int(archive_limit))).fetchall()
    archive_root = (root/'archive'/str(cid)).resolve()
    for r in rows:
        scanned += 1
        file = (root / r['pdf_file']).resolve()
        reason = ''
        if not file.is_relative_to(archive_root) or not file.is_file():
            reason = 'PDF fehlt oder Archivpfad ungueltig'
        elif not r['pdf_sha256']:
            reason = 'Pruefsumme fehlt'
        else:
            try:
                dig = hashlib.sha256()
                with file.open('rb') as f:
                    for part in iter(lambda: f.read(1024*256), b''):
                        dig.update(part)
                if not hmac.compare_digest(dig.hexdigest(),r['pdf_sha256']):
                    reason = 'PDF stimmt nicht mehr mit der gespeicherten Pruefsumme ueberein'
            except OSError:
                reason = 'PDF-Datei nicht lesbar'
        if reason:
            problems.append({'id':r['id'],'number':r['number'],'reason':reason})
        else:
            verified += 1

    if problems:
        add('error','Archivkontrolle fehlgeschlagen',
            f'{len(problems)} von {scanned} geprueften PDFs auffaellig. Bitte Sicherung kontrollieren.','/archive')
    elif scanned:
        add('ok','Archiv-PDFs unveraendert',f'{verified} PDF-Dateien mit SHA-256 erfolgreich verglichen.')
    else:
        add('info','Noch keine Archiv-PDFs','Freigegebene Belege werden hier zukuenftig kontrolliert.','/archive')

    found_total = con.execute("SELECT COUNT(*) FROM invoices WHERE company_id=? AND pdf_file!=''",(cid,)).fetchone()[0]
    if found_total > archive_limit:
        add('info','Archiv-Stichprobe',f'Die neuesten {archive_limit} von {found_total} Archivdateien wurden geprueft.')

    disk = shutil.disk_usage(root)
    free = disk.free // (1024*1024)
    if free < 250:
        add('error','Wenig Speicherplatz',f'Nur noch {free} MB frei. Bitte Speicherplatz schaffen und ein Backup erstellen.')
    elif free < 1024:
        add('warn','Speicherplatz beobachten',f'Noch {free} MB frei. Speicherplatz vor groesseren Importen pruefen.')
    else:
        add('ok','Speicherplatz ausreichend',f'{free:,} MB freier Speicherplatz.'.replace(',','\''))

    backup = None
    if superadmin:
        files = sorted((p for p in (root/'backups').glob('backup-*.zip') if p.is_file()),
                       key=lambda p:p.stat().st_mtime,reverse=True)
        if not files:
            add('warn','Keine lokale Sicherung gefunden',
                'Bitte Gesamtbackup erstellen und ausserhalb dieses PCs sicher ablegen.','/backup')
        else:
            latest = files[0]
            days = max(0,int((datetime.now(timezone.utc).timestamp()-latest.stat().st_mtime)//86400))
            backup = {'name':latest.name,'days_old':days,
                      'date':datetime.fromtimestamp(latest.stat().st_mtime).strftime('%d.%m.%Y %H:%M')}
            try:
                with zipfile.ZipFile(latest) as z:
                    if 'rechnung.sqlite3' not in z.namelist():
                        raise ValueError('Die SQLite-Datenbank fehlt im ZIP.')
                    if latest.stat().st_size <= 80*1024*1024 and z.testzip() is not None:
                        raise ValueError('Fehlerhafte Datei im ZIP-Backup erkannt.')
                    if latest.stat().st_size > 80*1024*1024:
                        add('info','Grosses Backup','ZIP-Struktur wurde geprueft; die CRC-Pruefung ist bei grossen Backups nicht automatisch enthalten.')
                if days>7:
                    add('warn','Backup aelter als eine Woche',
                        f'Letztes lokal gefundenes Backup: {backup["date"]} ({days} Tage).','/backup')
                else:
                    add('ok','Aktuelle lokale Sicherung gefunden',
                        f'Letztes Backup: {backup["date"]}. Eine zusaetzliche externe Sicherung bleibt wichtig.')
            except (ValueError,zipfile.BadZipFile,OSError) as exc:
                add('error','Lokales Backup beschaedigt',
                    'Die neueste Sicherung ist nicht vollstaendig lesbar: '+str(exc)[:110]+' Bitte ein neues Backup erstellen.','/backup')
    else:
        add('info','Sicherung nur durch Hauptadministrator',
            'Gesamtbackups enthalten alle Firmen. Nur der Installationsadministrator kann sie sehen.')

    counts = {}
    for table in ('customers','items','invoices','payments'):
        counts[table] = con.execute(f'SELECT COUNT(*) FROM {table} WHERE company_id=?',(cid,)).fetchone()[0]
    return {'checks':checks,'problems':problems[:20], 'scanned':scanned,
            'archive_total':found_total, 'verified':verified,'backup':backup,
            'counts':counts,'errors':sum(c['level']=='error' for c in checks),
            'warnings':sum(c['level']=='warn' for c in checks)}
