# Swiss-invoice-RX – Firmenlogos und Anmeldelogo (2.4.0)

## Geschäftslogo für die Software ändern

1. Als **Geschäftsleitung** oder **Hauptadministrator** anmelden.
2. Gewünschtes Geschäft unter **Aktives Geschäft** auswählen.
3. **Einstellungen & System → Firmendaten → Logos für die Software** öffnen.
4. Bei **Logo dieses Geschäfts** eine PNG-, JPG- oder WEBP-Datei auswählen (maximal 5 MB).
5. **Logos speichern** anklicken.

Nach dem Speichern sehen alle diesem Geschäft zugewiesenen Benutzer das neue Logo in der **Seitenleiste** und auf dem **Dashboard**. Bei mehreren Geschäftszugängen ändert sich das Logo beim Geschäftswechsel. Einem Benutzer mit fester Geschäftszuordnung wird ausschliesslich dieses Geschäft angezeigt.

**Wichtig:** Das Oberflächenlogo ist von dem Logo im Rechnungs-PDF getrennt. Du kannst das PDF-Logo unverändert lassen. Falls du kein Oberflächenlogo hochlädst, verwendet die Software automatisch das vorhandene Firmenlogo aus der Rechnung.

## Logo auf der Anmeldeseite

Nur der **Hauptadministrator** kann in demselben Abschnitt das **allgemeine Anmeldelogo** hochladen. Es ersetzt die Swiss-invoice-RX-Wortmarke auf dem Hintergrundbild und erscheint auf kleinen Bildschirmen über dem Loginformular.

Dieses Logo gilt **vor dem Anmelden für alle Benutzer**. Die Anwendung weiss erst nach einer erfolgreichen Anmeldung, welchem Geschäft die Person angehört. Eine Anzeige des persönlichen Geschäftslogos nur anhand einer eingegebenen E-Mail wäre aus Datenschutz- und Sicherheitsgründen ungeeignet. **Nach der Anmeldung** erscheint immer das Logo des richtigen Geschäfts.

## Logos entfernen, wiederverwenden und sichern

- Zum Zurücksetzen ein Häkchen bei **Eigenes Oberflächenlogo entfernen** setzen und speichern; dann gilt wieder das Rechnungslogo.
- **Anmeldelogo entfernen** ist nur für den Hauptadministrator sichtbar.
- Erlaubt sind PNG, JPG und WebP, maximal 5 MB. Die Software validiert den Dateityp und speichert ein bereinigtes PNG.
- Die Bilder liegen dauerhaft in `/data/uploads/` und sind Bestandteil von Home-Assistant- und lokalen Gesamtbackups.
- Diese Version migriert bestehende Datenbanken automatisch; Rechnungen und QR-Zahlteile werden nicht geändert.


