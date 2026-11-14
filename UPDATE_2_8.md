# Swiss-invoice-RX 2.8.0 - Netzwerkzugriff im Heimnetz

## Neue Funktion

Home Assistant Ingress bleibt bestehen. Zusaetzlich ist Swiss-invoice-RX direkt
im eigenen Netzwerk erreichbar, zum Beispiel von einem Smartphone oder Computer:

`http://192.168.1.50:8765/`

Die IP `192.168.1.50` ist nur ein Beispiel. Verwende die **lokale IP-Adresse
deines Home-Assistant-Geraets**, nicht die IP des Endgeraets und nicht den
Home-Assistant-Standardport.

## Update

1. Erstelle vor dem Update in Home Assistant eine vollstaendige Sicherung der App.
2. Ersetze die Dateien deines GitHub-Repositories `richieam93/ha-Swiss-invoice`
   durch den Inhalt dieses ZIP-Pakets (ohne den uebergeordneten ZIP-Ordner).
3. In Home Assistant die App-Quelle neu laden und **Swiss-invoice-RX 2.8.0** aktualisieren.
4. App starten. **Einstellungen > Apps > Swiss-invoice-RX > Netzwerk** oeffnen.
5. Bei **8765/tcp** ist zunaechst **kein Host-Port** hinterlegt. Trage **8765**
   ein. Bei Portkonflikten kannst du z. B. **8766** waehlen. Speichern und App ggf. neu starten.
6. Vom Geraet im selben WLAN/LAN `http://<HA-IP>:8765/` oeffnen (oder Host-Port 8766).
7. Mit dem **Swiss-invoice-RX-Benutzerkonto** anmelden. Die Home-Assistant-Anmeldung
   alleine reicht fuer den direkten Port nicht aus.

Port-Zugriff deaktivieren: Unter **Netzwerk** die Zuordnung fuer **8765/tcp**
loeschen/deaktivieren und speichern. Diese Einstellung ist auch der Standard
nach der Installation. Die Home-Assistant-Seitenleiste bleibt nutzbar.

## Sicherheit

- Die Rechnungsdaten bleiben weiterhin im Home-Assistant-App-Datenordner `/data`.
- **Keine Portweiterleitung im Router** einrichten und keine oeffentliche
  Freigabe der HTTP-Adresse nutzen.
- Das LAN-HTTP-Protokoll ist **nicht verschluesselt**. Verwende nur ein
  vertrauenswuerdiges privates Netzwerk. Fuer entfernten/unsicheren Zugriff
  ist Home Assistant Ingress, VPN oder ein sicher konfigurierter HTTPS-Proxy
  vorzuziehen.
- Swiss-invoice-RX hat weiterhin ein eigenes Login mit Passwort und
  Geschaeftsberechtigungen. Der direkte LAN-Zugriff gewaehrt niemandem
  Administratorrechte durch die Netzwerkadresse.
- Das Programm verwirft gefaelschte Ingress-Header und direkte Verbindungen
  von oeffentlichen Quell-IP-Adressen. Router-NAT kann aber Quell-IP-Adressen
  umschreiben; dieser Check ersetzt keine Router- oder Firewall-Regeln.

## Daten und Kompatibilitaet

Das Datenbankschema und vorhandene Rechnungen, Benutzer, Logos, PDF-Vorlagen,
Geschäfte und QR-Daten bleiben unveraendert. Home-Assistant-Daten-Backups
werden weiterhin unter `/data` angelegt.

Ein wirklicher Docker-Build und Netzwerkzugriff auf deinem Home-Assistant-Geraet
sind erst nach dem Hochladen in dein Repository vor Ort pruefbar.
