# Swiss-invoice-RX 2.9.0 – Eigenes Geschäft beim ersten Login

## Was wurde korrigiert?

Vorher lag das Häkchen **„Eigenes Geschäft erstellen“** ausserhalb des Benutzerformulars. Es wurde bei der Speicherung nicht an den Server gesendet. Dadurch war der neue Benutzer unter Umständen versehentlich deinem bestehenden Geschäft zugeordnet. **Dieses Verhalten ist korrigiert.**

## Einen neuen, unabhängigen Geschäftsadministrator anlegen

1. Öffne **Einstellungen & System → Benutzer** in deinem Geschäft.
2. Aktiviere **„Eigenes Geschäft erstellen – volle Rechte nur im neuen Geschäft“**.
3. Gib **E-Mail, Namen und ein Startpasswort** ein; klicke auf **Benutzer für eigene Einrichtung erstellen**.
4. Die neue Person öffnet Swiss-invoice-RX (auch über den optionalen LAN-Zugriff) und meldet sich mit ihrer E-Mail und dem Startpasswort an.
5. Der **Ersteinrichtungs-Assistent** erscheint automatisch. Die Person wählt die Geschäftsart (Privatperson, Einzelunternehmen, Gesellschaft), erfasst die Rechnungsadresse, lädt ihr Logo hoch, ersetzt das Startpasswort und konfiguriert bei Bedarf IBAN, QR-Referenz, MWST und Zahlungsziel.
6. Nach Abschluss erscheint das **eigene leere Dashboard**. Die Person hat volle Geschäftsadministratorrechte in dieser neuen Umgebung. Sie darf dort Rechnungen, Kunden, Artikel, Zahlungen, Vorlagen, Logos, QR-Einstellungen, Berichte und Mitarbeiter selbst verwalten.

**Datenschutz:** Die neue Person kann dein Geschäft weder sehen noch über direkte URLs erreichen. Auch du erhältst **nicht automatisch Zugriff** auf das neue Geschäft. Hauptadministrator-Aufgaben für die *gesamte Installation* (z. B. Gesamtbackup aller Geschäfts- und Benutzerdaten) bleiben separat geschützt.

## Einen bereits falsch zugeordneten Benutzer korrigieren

1. Öffne **Einstellungen & System → Benutzer** im bisherigen Geschäft.
2. Suche die Person in **Benutzer dieses Geschäfts**.
3. Wähle **„Eigenes Geschäft einrichten lassen“** und bestätige die Aktion.
4. Ihr Zugriff auf dein Geschäft endet **sofort**. Beim nächsten Seitenaufruf oder Login erscheint nur noch die Einrichtung des eigenen Geschäfts.

Die Aktion ist absichtlich nicht verfügbar für dein eigenes Konto, den Hauptadministrator, den letzten Geschäftsadministrator oder Benutzer mit mehreren Geschäftszuordnungen. **Keine bestehenden Rechnungen, Kunden oder PDF-Archive werden übertragen oder gelöscht.** Falls eine Übernahme gebraucht wird, erfolgt sie ausschliesslich über einen ausdrücklich geprüften Datenexport, nicht automatisch.


