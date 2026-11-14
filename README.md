# Swiss-invoice-RX

**Schweizer Rechnungsverwaltung für Home Assistant.** Lokal gespeichert, mit QR-Rechnungen und getrennten Geschäftsbereichen.

## Funktionen

- Rechnungen, Offerten und Gutschriften als PDF mit Schweizer QR-Zahlteil
- Kunden, Artikel, Inventar, Zahlungen und Mahnungen
- Vorlagen-Studio und frei gestaltbarer A4-PDF-Designer
- Mehrere Geschäfte mit getrennten Daten und Benutzerrechten
- Eigene Geschäftseinrichtung für neue Benutzer
- Bankdatei-Import (camt.053/054), Berichte und CSV-Export
- Geschäftslogos, lokale SQLite-Datenbank und Home-Assistant-Backups

## Installation

1. In Home Assistant unter **Einstellungen → Apps → Repositories** die Quelle hinzufügen:
   `https://github.com/richieam93/ha-Swiss-invoice`
2. **Swiss-invoice-RX** installieren und starten.
3. **In Seitenleiste anzeigen** aktivieren und die Ersteinrichtung öffnen.

Unterstützte Plattformen: Home Assistant mit Supervisor, **amd64** oder **aarch64**.

## Zugriff

Die Oberfläche ist über die Home-Assistant-Seitenleiste verfügbar. Optional kann unter **App → Netzwerk** der lokale Port `8765/tcp` freigegeben werden. Die Anmeldung bei Swiss-invoice-RX bleibt erforderlich. Ein direkter HTTP-Zugriff ist nur für vertrauenswürdige lokale Netze vorgesehen.

## Benutzerkonten

Beim Löschen des letzten Geschäftszugriffs wird das Benutzerkonto entfernt und seine E-Mail-Adresse für eine Neuanlage freigegeben. Bei mehreren Geschäftszuordnungen wird nur die gewählte Berechtigung entfernt. Belege und Aktivitätsprotokolle bleiben erhalten.

## Dokumentation

- [Einrichtung und Verwaltung](swiss_invoice_rx/DOCS.md)
- [Logo-Verwaltung](swiss_invoice_rx/LOGOS_ANLEITUNG.md)
- [Änderungsprotokoll](swiss_invoice_rx/CHANGELOG.md)

Projekt: [richieam93/ha-Swiss-invoice](https://github.com/richieam93/ha-Swiss-invoice)
