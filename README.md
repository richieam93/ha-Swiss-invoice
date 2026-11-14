# Swiss-invoice-RX für Home Assistant 🇨🇭

## Neu in 2.9.0: Eigenes Geschäft für neue Benutzer – vollständig getrennt

Unter **Einstellungen & System → Benutzer** kannst du beim Erstellen eines Kontos
**„Eigenes Geschäft erstellen – volle Rechte nur im neuen Geschäft“** aktivieren.
Das Häkchen wird nun zuverlässig mit dem Formular übertragen. Das Konto bekommt
**keine Mitgliedschaft** in deinem vorhandenen Geschäft. Beim ersten Login erscheint
ein vierstufiger Assistent mit Geschäftsart, Rechnungsadresse, Logo, eigenem Passwort,
MWST-Status sowie IBAN/QR-Daten. Danach wird die Person **Administrator nur ihres
neuen Geschäfts** und kann dort Rechnungen, Kunden, Artikel, Vorlagen, Einstellungen,
Zahlungen und Mitarbeiter selbst verwalten.

**Schon falsch zugeordnet?** Unter **Benutzer dieses Geschäfts** bietet die Liste
für passende Konten die Aktion **„Eigenes Geschäft einrichten lassen“**. Sie entzieht
den alten Geschäftszugriff sofort und startet beim nächsten Aufruf den Assistenten.
Bestehende Kunden, Rechnungen und Belege werden dadurch **nicht** verschoben oder gelöscht.
Hauptadministratoren, das eigene Konto sowie Konten mit mehreren Geschäftszuordnungen
können nicht über diese Funktion umgestellt werden.

[Update-Anleitung](UPDATE_2_9.md)

## Neu in 2.8.0: Weboberflaeche im Heimnetz

Swiss-invoice-RX ist **zusatzlich zum Home-Assistant-Ingress** ueber einen konfigurierbaren
TCP-Port im lokalen Netz erreichbar. Die Portfreigabe ist aus Sicherheitsgruenden
zunaechst ausgeschaltet: Trage unter **Einstellungen > Apps > Swiss-invoice-RX > Netzwerk**
als Host-Port `8765` ein. Danach ist `http://<HOME-ASSISTANT-IP>:8765/` erreichbar.
Der Host-Port kann dort auch wieder geaendert oder deaktiviert werden. Bei direktem Zugriff gilt die
Swiss-invoice-RX-Anmeldung; Home-Assistant-Benutzerrechte werden dadurch **nicht**
automatisch uebernommen. Bitte keinen Router-Port nach aussen freigeben.

[Schritt-fuer-Schritt-Anleitung](UPDATE_2_8.md)

## Neu in 2.7.0: Entwuerfe direkt loeschen

Unter **Verkauf > Rechnungen** lassen sich Entwuerfe nun direkt in der Liste sowie auf der Detailseite **nach einer Bestaetigung loeschen**. Das gilt ebenso fuer Entwurfs-Offerten und Entwurfs-Gutschriften. Bereits freigegebene Belege bleiben geschuetzt. Die Aktion setzt mindestens Bearbeitungsrechte im aktiven Geschaeft voraus und wird protokolliert. Mehr dazu in [Update 2.7](UPDATE_2_7.md).


**Schweizer Rechnungssoftware als Home-Assistant-Add-on.**

Swiss-invoice-RX Home-Assistant

## Funktionen

- Rechnungen, Offerten und Gutschriften mit änderbaren Entwurfsnummern
- Swiss-QR-Zahlteile und QR-Testzentrum, PDF-Erzeugung und Archiv
- Kunden- und Artikelverwaltung mit Inventar, Bildern und Lagerbewegungen
- Zahlungen, Mahnungen, Bankdateien (camt.053/054), Auswertungen, CSV-Exporte
- Vorlagen-Studio und frei gestaltbarer A4-Drag-and-Drop-Designer
- Mehrere Geschäfte mit getrennter Datenbankzuordnung
- Benutzerverwaltung inklusive **Geschäftsleitung mit Vollrechten nur für das zugewiesene Geschäft**
- Lokale SQLite-Datenbank und Home-Assistant-Backups
- **Individuelle Geschäftslogos:** Jeder Benutzer sieht nach der Anmeldung das Logo seines zugewiesenen Geschäfts. Zusätzlich gibt es ein allgemeines Anmeldelogo.

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


## Logos und Branding

**Einstellungen → Firmendaten → Logos**: Oberflächenlogo pro Geschäft hochladen (Geschäftsleitung). Nur der Hauptadministrator darf das allgemeine Anmeldelogo ändern. Vor der Anmeldung wird aus Datenschutzgründen noch kein benutzerspezifisches Logo angezeigt; nach dem Login erscheint automatisch das richtige Geschäft. Details: [Logo-Anleitung](swiss_invoice_rx/LOGOS_ANLEITUNG.md).


## Swiss-invoice-RX 2.5.0: PDF-Logo und Entwurfsanzeige

Das Geschäftslogo wird auch im Vorlagen-Studio, freien PDF-Designer und auf neuen PDFs
verwendet, falls kein gesondertes Rechnungslogo gesetzt ist. Unter Firmendaten kann die
Entwurfs-Kennzeichnung für heruntergeladene Entwurfs-PDFs pro Geschäft deaktiviert werden.
Musterbelege behalten ihre Kennzeichnung. Bereits archivierte PDFs werden nicht verändert.
