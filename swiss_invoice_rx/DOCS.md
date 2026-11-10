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

Das Add-on veröffentlicht **keinen offenen TCP-Port im Heimnetz**. Der Zugriff läuft über Home Assistant Ingress.

## Anmelden und Rechte

Home Assistant schützt den Zugriff auf die Seitenleiste. Swiss-invoice-RX hat zusätzlich **eine eigene Anmeldung**, damit Geschäftsleiter, Mitarbeiter und verschiedene Geschäfte weiterhin voneinander getrennt bleiben. Das ist bewusst **kein** Home-Assistant-Single-Sign-On. Erstelle bei der Ersteinrichtung den ersten Swiss-invoice-RX-Administrator. Danach können weitere Mitarbeiter einem einzelnen Geschäft zugeteilt werden.

## Datenspeicherung

- Datenbank: `/data/rechnung.sqlite3`
- Logos / Artikelbilder: `/data/uploads/`
- Archivierte PDF-Rechnungen: `/data/archive/`
- Lokale Software-Backups: `/data/backups/`
- Session-Schlüssel: `/data/.session_key`

Der Ordner `/data` ist das **persistente Add-on-Datenvolumen**. Er wird bei regulären Updates beibehalten. Für Sicherungen im Home Assistant Backup-Manager ist `backup: cold` eingestellt: Das Add-on wird für eine konsistente Sicherung gestoppt.



## Logos und unterschiedliche Geschäftsansichten (Version 2.4.0)

Unter **Einstellungen → Firmendaten → Logos** kann eine Geschäftsleitung ein eigenes **Oberflächenlogo** hochladen. Es erscheint bei allen dem betreffenden Geschäft zugewiesenen Benutzern auf dem Dashboard und in der Seitenleiste. Beim Firmenwechsel aktualisiert sich das Logo automatisch. Ohne separates Oberflächenlogo wird das vorhandene Rechnungslogo verwendet. PDFs und QR-Zahlteile werden durch das neue Oberflächenlogo nicht verändert.

Nur der Hauptadministrator kann zusätzlich das **allgemeine Anmeldelogo** einstellen. Vor Eingabe der Zugangsdaten lässt die App bewusst keine Firmenlogos erkennen: Das würde ohne Authentifizierung Benutzer- und Geschäftszuordnungen offenlegen. Erst nach erfolgreicher Anmeldung wird das richtige Firmenlogo geladen. Logos werden in `/data/uploads/` gespeichert und in Home-Assistant-Backups mitgesichert.
