# Swiss-invoice-RX – Dokumentation

## Installation

**Voraussetzung:** Home Assistant mit Supervisor auf `amd64` oder `aarch64`.

1. **Einstellungen → Apps → Repositories** öffnen.
2. `https://github.com/richieam93/ha-Swiss-invoice` hinzufügen.
3. **Swiss-invoice-RX** installieren, starten und in der Seitenleiste anzeigen.
4. Beim ersten Aufruf ein Geschäft und das Administratorkonto einrichten.

## Benutzer und Geschäfte

Unter **Einstellungen & System → Benutzer** werden Benutzer einem Geschäft und einer Rolle zugeordnet.

- **Geschäftsleitung:** volle Verwaltungsrechte innerhalb des eigenen Geschäfts
- **Mitarbeiter:** Belege und Geschäftsdaten bearbeiten
- **Leser:** Daten ansehen
- **Eigenes Geschäft erstellen:** eigener Einrichtungsassistent beim ersten Login, ohne Zugriff auf bestehende Geschäfte

Der Assistent erfasst Geschäftsart, Rechnungsadresse, Logo, Passwort, Bankverbindung und MWST-Status. Geschäftsart und MWST-Einstellungen sind später unter **Firmendaten** änderbar. Installationsweite Verwaltungsfunktionen bleiben dem Hauptadministrator vorbehalten.

**Benutzer löschen:** Der letzte Geschäftszugriff entfernt das Benutzerkonto und gibt die E-Mail-Adresse für eine neue Registrierung frei. Bei mehreren Geschäftszuordnungen wird nur die gewählte Berechtigung entfernt. Rechnungsbelege und Aktivitätsprotokolle bleiben erhalten.

## Rechnungen und QR-Zahlteile

Rechnungen, Offerten und Gutschriften werden im Bereich **Verkauf** erstellt. Entwürfe lassen sich bearbeiten, kopieren oder löschen. Freigegebene Belege werden als PDF archiviert. Rechnungsvorlagen und Logos werden pro Geschäft verwaltet.

Das **QR-Testzentrum** überprüft die Kombination aus IBAN, Referenzart und Zahlungsangaben. Der normierte QR-Zahlteil bleibt unabhängig vom gewählten Rechnungsdesign.

## Logos und PDF-Gestaltung

Unter **Firmendaten → Logos** können separate Oberflächen- und Rechnungslogos hinterlegt werden. Ohne eigenes Rechnungslogo übernimmt der PDF-Designer das Geschäftslogo. Die Entwurfskennzeichnung ist pro Geschäft unter **Darstellung & PDF** einstellbar.

## Netzwerkzugriff

Home Assistant Ingress ist standardmässig verfügbar. Für den direkten Zugriff im lokalen Netzwerk lässt sich unter **App → Netzwerk** ein Host-Port für `8765/tcp` festlegen.

Beispiel: `http://192.168.1.50:8765/` (IP-Adresse des Home-Assistant-Geräts). Direkter Zugriff erfordert die Swiss-invoice-RX-Anmeldung. Da HTTP unverschlüsselt ist, keine öffentliche Router-Portfreigabe verwenden.

## Datenspeicherung und Backups

| Inhalt | Verzeichnis |
|---|---|
| SQLite-Datenbank | `/data/rechnung.sqlite3` |
| Logos und Artikelbilder | `/data/uploads/` |
| Archivierte PDFs | `/data/archive/` |
| Lokale Sicherungen | `/data/backups/` |

Das persistente Verzeichnis `/data` bleibt bei regulären App-Aktualisierungen erhalten. Home-Assistant-Backups umfassen die App-Daten; die Gesamtsicherung ist in Swiss-invoice-RX dem Hauptadministrator vorbehalten.
