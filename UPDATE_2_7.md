# Swiss-invoice-RX 2.7.0: Entwuerfe loeschen

## Neu

Im Menue **Verkauf > Rechnungen** kannst du einen Entwurf ueber **Loeschen** dauerhaft entfernen. Im Bereich **Status** kannst du **Entwurf** waehlen, um nur offene Entwuerfe zu sehen. Die Schaltflaeche ist auch auf der Detailseite eines Entwurfs sichtbar. Sie erscheint ebenfalls bei Entwurfs-Offerten und Entwurfs-Gutschriften.

Vor dem Loeschen wird eine Bestaetigungsfrage angezeigt. **Das Loeschen kann nicht rueckgaengig gemacht werden.** Die Rechnungspositionen werden mit dem Entwurf entfernt. Kunden, Artikel, andere Rechnungen und Nummernkreise bleiben bestehen. Ein Protokolleintrag haelt Nummer und Aktion fest.

Ein freigegebener oder stornierter Beleg kann niemals ueber diese Funktion geloescht werden. Wer nur Leserechte hat, sieht keine Loeschen-Schaltflaeche und darf keine Loeschanfrage ausfuehren. Die Loeschaktion ist immer auf das zugewiesene aktive Geschaeft beschraenkt.

Falls der Entwurf noch fuer eine wiederkehrende Rechnung verwendet wird, wird das Loeschen aus Sicherheitsgruenden verweigert. Bitte zuerst den entsprechenden Wiederholungsauftrag pruefen. Auch mit freigegebenen Folgebelegen verbundene Entwuerfe sind geschuetzt.

## Aktualisieren in Home Assistant

1. **Vorher ein Backup erstellen:** Home Assistant > Einstellungen > System > Backups.
2. ZIP entpacken und **den Inhalt des Ordners `ha-Swiss-invoice`** in dein GitHub-Repository `richieam93/ha-Swiss-invoice` uebernehmen.
3. Aenderungen auf GitHub committen und hochladen.
4. In Home Assistant die App-Quelle neu laden und **Swiss-invoice-RX 2.7.0** aktualisieren.
5. Die App starten, unter **Verkauf > Rechnungen** einen Test-Entwurf anlegen und das Loeschen pruefen.

Die Datenbank wird in dieser Version **nicht migriert**. Vorhandene Kundendaten, Rechnungen, Firmenlogos und QR-Einstellungen werden nicht angefasst.

> Hinweis: Die Funktion entfernt Entwuerfe endgueltig. Fuer irrtuemlich geloeschte Entwuerfe ist gegebenenfalls eine vollstaendige Wiederherstellung aus dem Backup noetig. Ein echter Build auf deinem Home-Assistant-Geraet wurde hier nicht ausgefuehrt.
