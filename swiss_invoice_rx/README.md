# Swiss-invoice-RX

## Neu in 2.8.0: Direkt im Heimnetz erreichbar

Die App behaelt den Home-Assistant-Ingress-Zugang. Neu laesst sich die Weboberflaeche
im lokalen Netz oeffnen, sobald unter **App > Netzwerk** der Host-Port `8765`
aktiviert wird: `http://<HA-IP>:8765/`. Der Port ist anfangs deaktiviert,
kann geaendert und jederzeit wieder ausgeschaltet werden. Der direkte Zugriff verlangt
weiterhin die Swiss-invoice-RX-Anmeldung. Keine Router-Portweiterleitung einrichten.

[Anleitung](../UPDATE_2_8.md)

## Neu in 2.7.0: Entwuerfe direkt loeschen

Unter **Verkauf > Rechnungen** lassen sich Entwuerfe nun direkt in der Liste sowie auf der Detailseite **nach einer Bestaetigung loeschen**. Das gilt ebenso fuer Entwurfs-Offerten und Entwurfs-Gutschriften. Bereits freigegebene Belege bleiben geschuetzt. Die Aktion setzt mindestens Bearbeitungsrechte im aktiven Geschaeft voraus und wird protokolliert. Mehr dazu in [Update 2.7](../UPDATE_2_7.md).


Schweizer Rechnungssoftware als Home-Assistant-App (ehemals Add-on).

Die Software kann direkt in der Home-Assistant-Seitenleiste gestartet werden. Sie umfasst Rechnungen, Schweizer QR-Zahlteile, Kunden, Artikel, Inventar, Vorlagen, Drag-and-Drop-Designer, Zahlungsverwaltung und Benutzerrechte pro Geschäft.

**Installation:** Dieses GitHub-Repository als zusätzliche App-Quelle in Home Assistant hinterlegen, **Swiss-invoice-RX** installieren, starten und über **Weboberfläche öffnen** einrichten.



## Logo je Geschäft

Ab Version **2.4.0** kann unter **Firmendaten → Logos für die Software** ein eigenes Oberflächenlogo pro Geschäft hochgeladen werden. Das Logo erscheint nach der Anmeldung bei den zugewiesenen Benutzern. Ein allgemeines Anmeldelogo ist nur für den Hauptadministrator editierbar. [Vollständige Anleitung](LOGOS_ANLEITUNG.md).


### Neu in 2.6.0: Eigenes Geschäft beim ersten Login

Unter **Benutzer & Berechtigungen** gibt es die Option **Eigenes Geschäft erstellen**.
Der neue Benutzer wird noch keinem bestehenden Geschäft zugeordnet; er hat vor
seiner eigenen Einrichtung keinerlei Zugriff auf dessen Daten. Nach der Anmeldung
öffnet sich eine Schritt-für-Schritt-Einführung: Geschäftsart (Privatperson,
Einzelunternehmen, Gesellschaft), Rechnungsadresse, Logo, eigenes neues Passwort, Bank-/QR-Daten und
MWST-Status. Der Benutzer wird Administrator ausschliesslich seines neu angelegten
Geschäfts. Nachträgliche Änderungen unter **Firmendaten** sind möglich.

Die Geschäftsart ist nicht mit der MWST-Registrierung gleichzusetzen. Für eine
unternehmerische Tätigkeit gilt grundsätzlich die Umsatzgrenze von CHF 100'000;
auch freiwillige MWST-Registrierung kann möglich sein. Privatpersonen mit
gelegentlichen Verkäufen weisen keine MWST aus. Verbindliche Einzelfälle bitte bei
[ESTV - Steuerpflicht](https://www.estv.admin.ch/de/mwst-steuerpflicht) abklären.

### Neu in 2.5.0: Logos auf Rechnungen und Entwurfs-PDF

Unter **Firmendaten > Logos für die Software** kannst du pro Geschäft ein Geschäftslogo hochladen.
Wenn im ersten Bereich der Firmendaten kein **separates Rechnungslogo** ausgewählt wurde,
verwendet Swiss-invoice-RX automatisch das Geschäftslogo in **Vorlagen-Studio**,
**freiem PDF-Designer** und neu erzeugten **Rechnungs-PDFs**. Ein separates
Rechnungslogo hat Vorrang. Die bisherigen archivierten PDFs werden nicht geändert.

Unter **Firmendaten > Darstellung & PDF** ist neu der Schalter
**"Kennzeichnung ENTWURF - NICHT VERSENDEN in Entwurfs-PDFs anzeigen"**.
Er ist standardmäßig eingeschaltet, gilt pro Geschäft und ändert ausschließlich
die sichtbare Beschriftung: Entwürfe müssen weiterhin ausdrücklich freigegeben werden.
Muster-PDFs zur Gestaltungskontrolle bleiben immer gekennzeichnet.

Vor einem Add-on-Update bitte in Home Assistant ein Backup erstellen.
