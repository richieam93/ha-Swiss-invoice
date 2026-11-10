# Swiss-invoice-RX – Home Assistant Add-on

## 2.4.0 – Logos pro Geschäft und Anmeldelogo

- Separates Logo für die Anwendung pro Geschäft (Seitenleiste und Dashboard).
- Pro Benutzer wird nach der Anmeldung nur das Logo des tatsächlich zugewiesenen Geschäfts angezeigt.
- Oberflächenlogo fällt optional auf das bestehende Rechnungslogo zurück; Rechnungs-PDFs bleiben unverändert.
- Hauptadministrator kann ein allgemeines Logo für die Anmeldeseite hochladen; vor Authentifizierung wird keine Firmenzuordnung veröffentlicht.
- Bilder werden lokal unter `/data/uploads/` gespeichert, auf Dateityp/Grösse geprüft und über mandantensichere Medien-Endpunkte angezeigt.
- Bestehende Datenbanken erhalten die Spalte `app_logo_path` automatisch, ohne Rechnungen zu verändern.

## 2.3.0 – Erste Home-Assistant-Version

