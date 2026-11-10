"""Sichere Offline-Wiederherstellung eines Swiss-invoice-RX-Gesamtbackups.

Aus Sicherheitsgruenden darf der Webserver dabei NICHT laufen.
"""
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from datetime import datetime


def restore(root, zip_path):
    root=Path(root).resolve()
    zip_path=Path(zip_path).resolve()
    if not zip_path.is_file():
        raise ValueError('Backupdatei nicht gefunden')
    try:
        with socket.create_connection(('127.0.0.1',8765),timeout=.25):
            raise RuntimeError('Webserver laeuft noch! Bitte zuerst START-Fenster schliessen.')
    except (ConnectionRefusedError, TimeoutError, OSError):
        pass
    if not zipfile.is_zipfile(zip_path):
        raise ValueError('Datei ist kein ZIP-Backup')
    with tempfile.TemporaryDirectory(prefix='helvetic_restore_') as stage_dir:
        stage=Path(stage_dir)
        with zipfile.ZipFile(zip_path) as z:
            members=z.infolist()
            if not any(m.filename=='rechnung.sqlite3' for m in members):
                raise ValueError('Das Backup enthaelt keine Datenbank')
            total=0
            for m in members:
                p=PurePosixPath(m.filename)
                if p.is_absolute() or '..' in p.parts or '\\' in m.filename or (m.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Unzulaessige Datei im Backup')
                if not (m.filename in ('rechnung.sqlite3','README.txt') or
                        (p.parts[0] in ('uploads','archive') and len(p.parts)>1)):
                    raise ValueError('Unbekannte Datei im Backup: '+m.filename)
                total+=m.file_size
                if total > 5*1024*1024*1024:
                    raise ValueError('Backup ist groesser als 5 GB')
            z.extractall(stage)
        database=stage/'rechnung.sqlite3'
        con=sqlite3.connect(database)
        try:
            state=con.execute('PRAGMA integrity_check').fetchone()[0]
            tables={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if state!='ok' or not {'companies','users','invoices','customers','items'}.issubset(tables):
                raise ValueError('Backup-Datenbank ist defekt oder nicht kompatibel')
            con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            con.close()
        root.mkdir(parents=True,exist_ok=True)
        rescue=root.parent/('helvetic_before_restore_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
        rescue.mkdir(parents=True,exist_ok=False)
        swapped=[]
        try:
            for name in ('rechnung.sqlite3','rechnung.sqlite3-wal','rechnung.sqlite3-shm','uploads','archive'):
                original=root/name
                if original.exists():
                    original.rename(rescue/name)
                    swapped.append(name)
            for name in ('rechnung.sqlite3','uploads','archive'):
                incoming=stage/name
                if incoming.exists():
                    shutil.move(str(incoming),str(root/name))
                elif name!='rechnung.sqlite3':
                    (root/name).mkdir(exist_ok=True)
        except Exception:
            for name in ('rechnung.sqlite3','uploads','archive'):
                path=root/name
                if path.is_dir():shutil.rmtree(path)
                elif path.exists():path.unlink()
            for name in swapped:
                (rescue/name).rename(root/name)
            raise
    return rescue


if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[2]!='--confirm':
        print('Aufruf: python restore_backup.py "DATEI.zip" --confirm')
        sys.exit(2)
    root=Path((os.environ.get('SWISS_INVOICE_DATA_DIR') or os.environ.get('HELVETIC_DATA_DIR') or Path(__file__).resolve().parent/'storage'))
    old=restore(root,sys.argv[1])
    print('Wiederherstellung abgeschlossen.')
    print('Vorheriger Datenstand als Rettungskopie unter:',old)
