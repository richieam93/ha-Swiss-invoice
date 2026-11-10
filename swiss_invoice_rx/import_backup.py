"""Einmaliger, sicherer Import eines Swiss-invoice-RX-/HelveticInvoice-Gesamtbackups.

Nur fuer eine *leere* Add-on-Datenbank. Keine bestehende Firma/Rechnung wird ueberschrieben.
Wird vor dem Start von Uvicorn ausgefuehrt. Backup ist im read-only /share Mount.
"""
from __future__ import annotations

import shutil
import sqlite3
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

MAX_FILES = 10000
MAX_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
ALLOWED_DIRS = frozenset(('uploads', 'archive'))
REQUIRED_TABLES = frozenset(('companies', 'users', 'invoices', 'customers', 'items', 'memberships'))


class BackupImportError(ValueError):
    pass


def _safe_entries(zf: zipfile.ZipFile):
    entries = zf.infolist()
    if len(entries) > MAX_FILES:
        raise BackupImportError('Zu viele Dateien im Backup')
    seen = set()
    total = 0
    found_database = False
    for info in entries:
        name = info.filename
        path = PurePosixPath(name)
        if (not name or '\\' in name or name.startswith('/') or
                len(name) > 350 or '..' in path.parts or
                any(part in ('', '.') for part in path.parts)):
            raise BackupImportError('Unsicherer Dateiname im Backup')
        if name in seen:
            raise BackupImportError('Doppelter Dateiname im Backup')
        seen.add(name)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise BackupImportError('Symlinks sind im Backup nicht erlaubt')
        if info.is_dir():
            if path.parts[0] not in ALLOWED_DIRS:
                raise BackupImportError('Unbekannter Ordner im Backup')
            continue
        if name == 'rechnung.sqlite3':
            found_database = True
        elif name != 'README.txt' and (len(path.parts) < 2 or path.parts[0] not in ALLOWED_DIRS):
            raise BackupImportError('Unbekannte Datei im Backup: ' + name)
        total += info.file_size
        if total > MAX_UNCOMPRESSED:
            raise BackupImportError('Backup ist groesser als 2 GB')
        if info.flag_bits & 0x1:
            raise BackupImportError('Verschluesselte ZIP-Eintraege nicht erlaubt')
    if not found_database:
        raise BackupImportError('Das ZIP enthaelt keine rechnung.sqlite3')
    return entries


def _database_ok(path: Path):
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        check = con.execute('PRAGMA integrity_check').fetchone()
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not check or check[0] != 'ok' or not REQUIRED_TABLES.issubset(tables):
            raise BackupImportError('Datenbank ist defekt oder nicht kompatibel')
    finally:
        con.close()


def import_backup(backup_zip: str | Path, data_dir: str | Path) -> list[str]:
    """Import in leeres /data; alle Dateien vorher validieren; Datenbank zuletzt setzen."""
    data = Path(data_dir).resolve()
    backup = Path(backup_zip).resolve()
    data.mkdir(parents=True, exist_ok=True)
    if (data / 'rechnung.sqlite3').exists():
        raise BackupImportError('Abbruch: vorhandene Datenbank darf nicht ueberschrieben werden')
    if not backup.is_file() or not zipfile.is_zipfile(backup):
        raise BackupImportError('Import-ZIP nicht gefunden oder ungueltig')
    for directory in ALLOWED_DIRS:
        target = data / directory
        if target.is_symlink() or (target.exists() and any(target.iterdir())):
            raise BackupImportError('Zielordner ist nicht leer: ' + directory)

    with tempfile.TemporaryDirectory(prefix='rx-import-', dir=data) as tmp:
        stage = Path(tmp)
        with zipfile.ZipFile(backup) as zf:
            entries = _safe_entries(zf)
            for info in entries:
                if info.is_dir() or info.filename == 'README.txt':
                    continue
                dest = stage / info.filename
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Kein extractall: ZIP-Pfade werden vor dem Schreiben strikt validiert.
                with zf.open(info) as infile, dest.open('xb') as outfile:
                    shutil.copyfileobj(infile, outfile, length=1024 * 1024)
        _database_ok(stage / 'rechnung.sqlite3')
        moved = []
        try:
            for name in ('uploads', 'archive'):
                src = stage / name
                if not src.exists():
                    continue
                dest = data / name
                if dest.exists():
                    dest.rmdir()  # nur leere Ordner, wie oben kontrolliert
                src.rename(dest)
                moved.append(dest)
            # Datenbank zuletzt: startet das Programm nur mit vollstaendigen Anlagen.
            (stage / 'rechnung.sqlite3').rename(data / 'rechnung.sqlite3')
        except Exception:
            for path in moved:
                if path.is_dir():
                    shutil.rmtree(path)
            raise
    return ["rechnung.sqlite3", *[p.name for p in moved]]


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Aufruf: python import_backup.py /share/swiss-invoice-rx/import.zip /data', file=sys.stderr)
        sys.exit(2)
    try:
        installed = import_backup(sys.argv[1], sys.argv[2])
        print('Backup importiert: ' + ', '.join(installed), flush=True)
    except (BackupImportError, OSError, sqlite3.Error, zipfile.BadZipFile) as error:
        print('BACKUP-IMPORT ABGEBROCHEN: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
