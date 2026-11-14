# Version 2.8.0 – Zugriff im lokalen Netzwerk

Neben Home Assistant Ingress ist ein direkter Zugriff im lokalen Netzwerk möglich. Unter **App → Netzwerk** lässt sich der Host-Port für `8765/tcp` festlegen oder deaktivieren.

Beispiel: `http://192.168.1.50:8765/` – die IP-Adresse entspricht dem Home-Assistant-Gerät. Die Anmeldung und Geschäftsrechte bleiben bestehen.

**Sicherheit:** Direkter HTTP-Zugriff ist unverschlüsselt. Keine öffentliche Portfreigabe im Router einrichten.
