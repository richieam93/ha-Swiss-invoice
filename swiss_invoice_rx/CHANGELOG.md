## 2.6.0 - Benutzer mit eigener Geschaeftseinrichtung

- Einladung von Benutzern ohne Zugriff auf das einladende Geschäft.
- Vierstufiger Einrichtungsassistent für eigenes Geschäft, Rechts-/Nutzungsform, Adresse, Logo, IBAN/QR und MWST-Status.
- Nach der Einrichtung volle Administratorrechte ausschliesslich für das eigene Geschäft.
- Geschäftsart und MWST-Status können in Firmendaten später angepasst werden.
- Ausstehende Einladungen sichtbar und widerrufbar, ohne andere Geschäftsdaten zu verändern.
- Serverseitige Zugriffskontrollen, sichere tenant-scoped Logo-Dateien und additive SQLite-Migration.

## 2.5.0 - Rechnungslogo im Studio und PDF, Entwurfs-Kennzeichnung einstellbar

- Vorlagen-Studio und freier Designer nutzen nun automatisch das Geschäftslogo, wenn kein eigenes Rechnungslogo hinterlegt ist.
- Neue und bestehende Entwurfs-PDFs erhalten das gleiche Logo wie die Vorschauen; bereits archivierte PDFs bleiben unverändert.
- Pro Geschäft kann unter Firmendaten > Darstellung & PDF die sichtbare Beschriftung "ENTWURF - NICHT VERSENDEN" an- oder ausgeschaltet werden (standardmäßig eingeschaltet).
- Muster-PDFs aus dem Vorlagen-Studio/Designer bleiben immer als Muster gekennzeichnet und enthalten keinen zahlbaren QR-Code.
- Beim Geschäftswechsel und nach Logo-Uploads werden Logo-Dateien nicht aus dem Browsercache falsch wiederverwendet.
- SQLite-Migration 13 ergänzt nur eine neue boolesche Einstellung; Geschäftsdaten bleiben erhalten.

# Swiss-invoice-RX – Home Assistant Add-on

## 2.4.0 – Logos pro Geschäft und Anmeldelogo

- Separates Logo für die Anwendung pro Geschäft (Seitenleiste und Dashboard).
- Pro Benutzer wird nach der Anmeldung nur das Logo des tatsächlich zugewiesenen Geschäfts angezeigt.
- Oberflächenlogo fällt optional auf das bestehende Rechnungslogo zurück; Rechnungs-PDFs bleiben unverändert.
- Hauptadministrator kann ein allgemeines Logo für die Anmeldeseite hochladen; vor Authentifizierung wird keine Firmenzuordnung veröffentlicht.
- Bilder werden lokal unter `/data/uploads/` gespeichert, auf Dateityp/Grösse geprüft und über mandantensichere Medien-Endpunkte angezeigt.
- Bestehende Datenbanken erhalten die Spalte `app_logo_path` automatisch, ohne Rechnungen zu verändern.

## 2.3.0 – Erste Home-Assistant-Version

