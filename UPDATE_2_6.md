# Swiss-invoice-RX 2.6.0 – Home Assistant Update

Ausgehend von der bisherigen Home-Assistant-Version **2.5.0**.

1. In Home Assistant ein **vollständiges Backup** von Swiss-invoice-RX erstellen.
2. Das bereitgestellte ZIP entpacken und den Inhalt von `ha-Swiss-invoice/` in das bestehende GitHub-Repository `richieam93/ha-Swiss-invoice` übernehmen.
3. Änderungen committen und pushen. In Home Assistant die App-Quelle aktualisieren, dann Swiss-invoice-RX auf 2.6.0 aktualisieren und neu starten.
4. Unter **Einstellungen & System → Benutzer** einen neuen Benutzer anlegen und **Eigenes Geschäft erstellen** aktivieren.
5. Der neue Benutzer meldet sich mit dem vergebenen Startpasswort an. Es erscheint die Einführung mit Geschäftsart, Adresse, Logo, eigenem Passwort und Zahlungsdetails. Das Startpasswort verliert dadurch seine Gültigkeit.
6. Nach der Einrichtung unter **Firmendaten** jederzeit das Geschäftsmodell bzw. den MWST-Status anpassen. QR-Zahlteil im QR-Testzentrum prüfen.

**Sicherheit:** Der eingeladene Benutzer ist keiner bestehenden Firma zugeordnet. Er sieht nur die eigene Einrichtung, bis er ein Geschäft neu anlegt. Erst dann wird er Administrator genau dieses Geschäfts. Ausstehende Einladungen lassen sich widerrufen.

**Steuern:** Die Art des Geschäfts ist nicht automatisch gleichzusetzen mit der MWST-Pflicht. Ein Schweizer Unternehmen erreicht grundsätzlich ab CHF 100'000 relevantem Umsatz die Anmeldegrenze; die freiwillige Registrierung ist unter Voraussetzungen möglich. Steuerpflicht und ESTV-Eintragung bitte selbst prüfen. Der Standard-MWST-Satz beträgt 8,1 %, reduziert 2,6 % und Beherbergung 3,8 % (Stand November 2026). Quellen: https://www.estv.admin.ch/de/mwst-steuerpflicht und https://www.estv.admin.ch/de/mwst-steuersaetze-schweiz

**Daten:** SQLite-Migration ist additiv. Vorhandene Rechnungen, Kunden, Logos und archivierte Belege bleiben unverändert. Das ZIP enthält keine Nutzerdaten.

**Hinweis:** Docker-Build und Installation auf einem echten Home-Assistant-Host müssen noch vor Ort geprüft werden.
