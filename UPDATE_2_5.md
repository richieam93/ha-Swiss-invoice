# Swiss-invoice-RX 2.5.0 – Update für Home Assistant

Diese Version basiert auf dem Home-Assistant-Add-on **Swiss-invoice-RX 2.4.0**.

## Neu

- **Logo auch im Rechnungs-PDF:** Falls kein getrenntes Rechnungslogo vorhanden ist, verwenden Vorlagen-Studio, freier Designer und neu erstellte Rechnungs-PDFs automatisch das bereits hinterlegte Geschäftslogo.
- **Rechnungslogo mit Vorrang:** Das optional in den Firmendaten hochgeladene Rechnungslogo wird weiterhin bevorzugt.
- **Entwurf ein-/ausblenden:** Unter **Einstellungen & System → Firmendaten → Darstellung & PDF** kannst du pro Geschäft die rote Kennzeichnung `ENTWURF - NICHT VERSENDEN` in Entwurfs-PDFs ein- oder ausschalten. Voreinstellung ist **ein**.
- **Wichtig:** Das Ausschalten des Aufdrucks gibt eine Rechnung nicht frei! Bis zur ausdrücklichen Freigabe bleibt sie ein Entwurf. Muster-PDFs aus dem Designer und Vorlagen-Studio bleiben immer mit Sicherheitshinweis versehen.
- **Belegdetailseite:** Die Rechnungsnummer wird in der Überschrift nicht mehr doppelt angezeigt.

## Update über GitHub

1. Erstelle in Home Assistant eine Sicherung des Add-ons.
2. Entpacke die ZIP-Datei und übernimm den **Inhalt** des darin enthaltenen Ordners `ha-Swiss-invoice` in dein Repository [richieam93/ha-Swiss-invoice](https://github.com/richieam93/ha-Swiss-invoice).
3. Überprüfe, dass `repository.yaml` im Stammverzeichnis und `swiss_invoice_rx/config.yaml` im Add-on-Ordner liegen.
4. Aktualisiere das Repository beziehungsweise die App in Home Assistant und installiere die Version **2.5.0**.
5. Unter **Firmendaten → Logos für die Software** ist das Geschäftslogo weiterhin gespeichert. Prüfe jetzt Vorlagen-Studio → PDF-Vorschau und freien Designer → PDF-Vorschau.
6. Unter **Firmendaten → Darstellung & PDF** den Entwurfs-Schalter nach Wunsch einstellen und **Firmeneinstellungen speichern**.

Die Datenbank wird beim Start um ein einziges Einstellungsfeld erweitert (Version 13), ohne deine Rechnungen oder die archivierten PDF-Dateien zu verändern.

## Tests

Die Änderungen wurden durch automatisierte Tests für die Logo-Einbettung in PDFs, Vorlagen und Designer, die Einstellung der Entwurfsmarkierung sowie für getrennte Geschäftsrechte geprüft. Der tatsächliche Home-Assistant-Docker-Build ist hier nicht ausgeführt worden.
