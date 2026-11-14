# Swiss-invoice-RX – Home Assistant Installation

## Voraussetzungen

- Home Assistant OS oder eine Installation mit Home Assistant Supervisor / App-Store.
- CPU-Architektur **amd64** oder **aarch64** (z. B. Raspberry Pi 4/5 64-bit).
- Internetzugang beim **ersten Installieren/Update**, damit Home Assistant das Docker-Image aus den Quellcodes bauen und Python-Pakete herunterladen kann. Im laufenden Betrieb werden Rechnungen lokal verarbeitet.

## Installieren

1. Home Assistant öffnen → **Einstellungen → Apps → App installieren** (je nach Version: Add-ons).
2. Menü oben rechts → **Repositories / Repositories verwalten**.
3. `https://github.com/richieam93/ha-Swiss-invoice` hinzufügen.
4. **Swiss-invoice-RX** auswählen und installieren. Der erste Docker-Build kann einige Zeit dauern.
5. **Starten** und **In Seitenleiste anzeigen** aktivieren.
6. **Weboberfläche öffnen** → erstes Geschäft und Administrator einrichten.




## Datenspeicherung

- Datenbank: `/data/rechnung.sqlite3`
- Logos / Artikelbilder: `/data/uploads/`
- Archivierte PDF-Rechnungen: `/data/archive/`
- Lokale Software-Backups: `/data/backups/`
- Session-Schlüssel: `/data/.session_key`

Der Ordner `/data` ist das **persistente Add-on-Datenvolumen**. Er wird bei regulären Updates beibehalten. Für Sicherungen im Home Assistant Backup-Manager ist `backup: cold` eingestellt: Das Add-on wird für eine konsistente Sicherung gestoppt.




