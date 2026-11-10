#!/bin/sh
set -eu

export SWISS_INVOICE_DATA_DIR=/data
export SWISS_INVOICE_INGRESS=1
mkdir -p /data

# options.json wird vom Home-Assistant-Supervisor bereitgestellt.
CONFIG="$(python - <<'PY'
import json
from pathlib import Path
try:
    cfg=json.loads(Path('/data/options.json').read_text(encoding='utf-8'))
except (FileNotFoundError, ValueError):
    cfg={}
log=cfg.get('log_level','info')
if log not in ('debug','info','warning','error'): log='info'
restore='yes' if cfg.get('import_backup') is True else 'no'
print(log + ':' + restore)
PY
)"
LOG_LEVEL="${CONFIG%%:*}"
RESTORE="${CONFIG#*:}"

if [ "$RESTORE" = 'yes' ]; then
    if [ -f /data/rechnung.sqlite3 ]; then
        echo "[Swiss-invoice-RX] Bestehende Datenbank erkannt; Backup-Import uebersprungen."
    else
        echo "[Swiss-invoice-RX] Import des Windows-Backups aus /share/swiss-invoice-rx/import.zip ..."
        python import_backup.py /share/swiss-invoice-rx/import.zip /data
    fi
fi

echo "[Swiss-invoice-RX] Starte Webserver auf Port 8765 (nur Home-Assistant-Ingress)."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8765 \
    --no-proxy-headers --no-access-log --log-level "$LOG_LEVEL"
