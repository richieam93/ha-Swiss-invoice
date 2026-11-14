## 2.9.0 – Eigenständige Geschäftseinrichtung beim ersten Login

- Fehler behoben: Die Checkbox „Eigenes Geschäft erstellen“ war in der Benutzerverwaltung ausserhalb des Formulars und wurde beim Speichern nicht übertragen.
- Neuer Benutzer erhält ohne bestehende Firmenmitgliedschaft eine eigene, leere Erst-Einrichtung (Geschäftsart, Rechnungsadresse, Logo, Passwort, Zahlungen und MWST).
- Nach dem Assistenten automatisch **Administrator nur des neuen Geschäfts**; Zugriffe auf bestehende Geschäfte bleiben verboten.
- Bereits falsch zugeordnete Mitarbeiter lassen sich sicher auf „Eigenes Geschäft einrichten lassen“ umstellen, falls sie ausschliesslich dem aktuellen Geschäft angehören.
- Zugriff wird dabei sofort entzogen, auch bei bereits aktiven Sitzungen. Vorhandene Kunden, Rechnungen und PDFs des bisherigen Geschäfts bleiben unberührt.
- Benutzerumstellung ist gegen unzulässige Änderungen am Hauptadministrator, am letzten Geschäftsadministrator und an Mehrfachmitgliedschaften geschützt.
- Zusätzliche Ende-zu-Ende-Tests für das tatsächlich gerenderte HTML-Formular, Ersteinrichtung, Rollen und Mandantentrennung.
- Keine neue Datenbankmigration notwendig; bestehende Add-on-Daten bleiben erhalten.

## 2.8.0 - Lokaler Netzwerkzugang mit konfigurierbarem Port

- Home Assistant kann Port `8765/tcp` gezielt an das Heimnetz freigeben; standardmäßig ist die Freigabe aus (Ingress bleibt aktiv), Host-Port unter `Netzwerk` einschaltbar, änderbar oder deaktivierbar.
- Home-Assistant-Ingress und Seitenleisten-Zugriff bleiben erhalten.
- Direkter LAN-Zugriff verwendet weiterhin das eigene Swiss-invoice-RX-Login und die bisherigen Geschäftsrechte.
- Ingress-Pfad-Header werden nur von der Supervisor-IP akzeptiert; private LAN-Clients erhalten direkte Pfade ohne Ingress-Prefix.
- Verbindungen mit oeffentlichen Client-Adressen werden abgewiesen; kein Ersatz fuer eine Router-Firewall.
- Keine Aenderung an Datenbankschema, Rechnungen, PDF, QR-Zahlteilen, Logos oder vorhandenen Benutzern.

## 2.7.0 - Entwuerfe direkt aus der Rechnungsliste loeschen

- Entwuerfe von Rechnungen, Offerten und Gutschriften in der Belegliste und Detailansicht dauerhaft loeschen.
- Vor dem Loeschen eine Bestaetigung anzeigen; danach wird die Positionstabelle mit entfernt.
- Freigegebene, bezahlte oder archivierte Belege sind nicht loeschbar.
- Mandantentrennung, Benutzerrechte und CSRF-Pruefung greifen auch beim Loeschen serverseitig.
- Geplante Wiederholungen, bestehende Zahlungs-/Lagerdaten und freigegebene Folgebelege werden gegen versehentliche Mitloeschung geschuetzt.
- Aktivitaetsprotokoll vermerkt das Loeschen mit Belegnummer; bestehende Kunden, Artikel und Belegnummernkreise bleiben unveraendert.
- Such- und Statusfilter werden nach dem Loeschen beibehalten.
- Keine Datenbankmigration erforderlich; bestehende Daten bleiben erhalten.

## 2.6.0 - Benutzer mit eigener Geschaeftseinrichtung

- Einladung von Benutzern ohne Zugriff auf das einladende Geschäft.
- Vierstufiger Einrichtungsassistent für eigenes Geschäft, Rechts-/Nutzungsform, Adresse, Logo, IBAN/QR und MWST-Status.
- Nach der Einrichtung volle Administratorrechte ausschliesslich für das eigene Geschäft.
- Geschäftsart und MWST-Status können in Firmendaten später angepasst werden.
- Ausstehende Einladungen sichtbar und widerrufbar, ohne andere Geschäftsdaten zu verändern.
- Serverseitige Zugriffskontrollen, sichere tenant-scoped Logo-Dateien und additive SQLite-Migration.
- Steuerliche Hinweise basieren auf den ESTV-Angaben, ersetzen keine Einzelfallprüfung.

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

