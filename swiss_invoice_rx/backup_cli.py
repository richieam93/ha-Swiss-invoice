"""Erstellt ein installationsweites ZIP-Backup mit der SQLite-Backup-API."""
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime


def make_backup(root):
    root=Path(root).resolve()
    db=root/'rechnung.sqlite3'
    if not db.exists():
        raise RuntimeError('Keine Datenbank vorhanden. Bitte Software zuerst starten.')
    folder=root/'backups'
    folder.mkdir(parents=True,exist_ok=True)
    dest=folder/('backup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
    with tempfile.TemporaryDirectory() as t:
        snap=Path(t)/'rechnung.sqlite3'
        src=sqlite3.connect(str(db))
        dst=sqlite3.connect(str(snap))
        try:
            src.backup(dst)
        finally:
            src.close();dst.close()
        with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.write(snap,'rechnung.sqlite3')
            for foldername in ('uploads','archive'):
                for file in (root/foldername).rglob('*'):
                    if file.is_file() and not file.is_symlink():
                        z.write(file,str(file.relative_to(root)))
            z.writestr('README.txt','Swiss-invoice-RX Gesamtbackup. Vertraulich! Enthaelt alle Firmen.\n')
    return dest


if __name__=='__main__':
    root=Path((os.environ.get('SWISS_INVOICE_DATA_DIR') or os.environ.get('HELVETIC_DATA_DIR') or Path(__file__).resolve().parent/'storage'))
    print('Backup:',make_backup(root))
