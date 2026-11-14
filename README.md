# Swiss-invoice-RX für Home Assistant 🇨🇭



**Schweizer Rechnungssoftware als Home-Assistant-Add-on.**

Swiss-invoice-RX Home-Assistant

## Funktionen

- Rechnungen, Offerten und Gutschriften mit änderbaren Entwurfsnummern
- Swiss-QR-Zahlteile und QR-Testzentrum, PDF-Erzeugung und Archiv
- Kunden- und Artikelverwaltung mit Inventar, Bildern und Lagerbewegungen
- Zahlungen, Mahnungen, Bankdateien (camt.053/054), Auswertungen, CSV-Exporte
- Vorlagen-Studio und frei gestaltbarer A4-Drag-and-Drop-Designer
- Mehrere Geschäfte mit getrennter Datenbankzuordnung
- Benutzerverwaltung 
- Lokale SQLite-Datenbank und Home-Assistant-Backups

## Installation in Home Assistant

1. In Home Assistant **Einstellungen → Apps → App installieren** öffnen.
2. Rechts oben **Repositories** wählen.
3. Folgende URL eintragen:

   `https://github.com/richieam93/ha-Swiss-invoice`

4. **Swiss-invoice-RX** auswählen → **Installieren** → **Starten** → **In Seitenleiste anzeigen**.
5. Die Weboberfläche öffnen und das erste Geschäft einrichten.

> Erfordert Home Assistant OS / Supervisor mit **amd64** oder **aarch64**. Die Installation baut zunächst ein Docker-Image auf deinem Gerät; dafür wird eine Internetverbindung benötigt.

## GitHub-Repository-Struktur

```text
ha-Swiss-invoice/
├── repository.yaml
├── README.md
└── swiss_invoice_rx/
    ├── config.yaml
    ├── Dockerfile
    ├── run.sh
    ├── DOCS.md
    ├── CHANGELOG.md
    ├── translations/
    ├── app/
    ├── tests/
    ├── import_backup.py
    └── requirements.txt
```

[Installationsanleitung, Windows-Backup-Import, Sicherheit und Updates](swiss_invoice_rx/DOCS.md)


## Sicherheit und Datenschutz

Die Weboberflaeche ist ueber **Home Assistant Ingress** und optional auch direkt
im **lokalen Netz** erreichbar. Die Host-Portfreigabe wird in den App-Netzwerkeinstellungen
gezielt eingeschaltet oder wieder ausgeschaltet. Fuer die Mandantenrechte gibt es weiterhin **eine eigene
Swiss-invoice-RX-Anmeldung**, unabhaengig von der Home-Assistant-Anmeldung.
Bitte keine Portweiterleitung im Router oder ungeschuetzte Internetfreigabe einrichten:
HTTP im Heimnetz ist nicht verschluesselt.




