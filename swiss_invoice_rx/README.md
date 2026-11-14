# Swiss-invoice-RX

Schweizer Rechnungssoftware als Home-Assistant-App.

Die Software kann direkt in der Home-Assistant-Seitenleiste gestartet werden. Sie umfasst Rechnungen, Schweizer QR-Zahlteile, Kunden, Artikel, Inventar, Vorlagen, Drag-and-Drop-Designer, Zahlungsverwaltung und Benutzerrechte pro Geschäft.

**Installation:** Dieses GitHub-Repository als zusätzliche App-Quelle in Home Assistant hinterlegen, **Swiss-invoice-RX** installieren, starten und über **Weboberfläche öffnen** einrichten.



### Neu in 2.6.0: Eigenes Geschäft beim ersten Login

Unter **Benutzer & Berechtigungen** gibt es die Option **Eigenes Geschäft erstellen**.
Der neue Benutzer wird noch keinem bestehenden Geschäft zugeordnet; er hat vor
seiner eigenen Einrichtung keinerlei Zugriff auf dessen Daten. Nach der Anmeldung
öffnet sich eine Schritt-für-Schritt-Einführung: Geschäftsart (Privatperson,
Einzelunternehmen, Gesellschaft), Rechnungsadresse, Logo, eigenes neues Passwort, Bank-/QR-Daten und
MWST-Status. Der Benutzer wird Administrator ausschliesslich seines neu angelegten
Geschäfts. Nachträgliche Änderungen unter **Firmendaten** sind möglich.

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
