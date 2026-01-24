# Wake-on-LAN Setup für Gaming PC

Diese Anleitung beschreibt die Einrichtung von Wake-on-LAN (WOL) für den Gaming PC mit Realtek-Netzwerkadapter auf einem ASUS ROG Strix B450-F Gaming Mainboard.

## Voraussetzungen

- PC muss per Ethernet (Kabel) verbunden sein, nicht WLAN
- MAC-Adresse des PCs muss bekannt sein

## Windows-Einstellungen

### Schnellstart deaktivieren

**Wichtig:** Schnellstart muss deaktiviert sein, sonst funktioniert WOL nicht zuverlässig.

1. **Systemsteuerung** → **Energieoptionen**
2. **Auswählen, was beim Drücken von Netzschaltern geschehen soll**
3. **Einige Einstellungen sind momentan nicht verfügbar** anklicken
4. **Schnellstart aktivieren** → Haken entfernen
5. **Änderungen speichern**

### Realtek Netzwerkadapter konfigurieren

1. **Win + X** → **Geräte-Manager**
2. **Netzwerkadapter** aufklappen
3. Rechtsklick auf **Realtek PCIe GbE Family Controller** → **Eigenschaften**

#### Reiter "Erweitert"

| Einstellung | Wert |
|-------------|------|
| Akt. über Magic Packet | Aktiviert |
| PME aktivieren | Aktiviert |
| Energieeffizientes Ethernet | Deaktiviert |
| Geschw. beim Abschalten reduzieren | Aktiviert |

**Hinweis:** "PME aktivieren" (Power Management Event) ist entscheidend für WOL im ausgeschalteten Zustand (S5).

#### Reiter "Energieverwaltung"

- ✓ Gerät kann den Computer aus dem Ruhezustand aktivieren
- ✓ Nur Magic Packet kann Computer aus dem Ruhezustand aktivieren

## BIOS-Einstellungen (ASUS ROG Strix B450-F)

1. Beim Booten **F2** oder **DEL** drücken
2. **Advanced** → **APM Configuration**
   - **ErP Ready** → **Disabled**
   - **Power On By PCI-E** → **Enabled**

**Hinweis:** ErP (Energy-related Products) spart Standby-Strom, kappt aber die Stromversorgung zur Netzwerkkarte im ausgeschalteten Zustand.

## Testen

WOL-Paket senden:

```bash
python3 -c "
from wakeonlan import send_magic_packet
send_magic_packet('A85E45E4CF98')  # MAC-Adresse ohne Doppelpunkte
"
```

Oder mit dem Agent:

```python
from agent.wol import wake_gaming_pc, is_lm_studio_available
from agent.config import get_settings

settings = get_settings()
await wake_gaming_pc(settings)
```

## Troubleshooting

| Problem | Lösung |
|---------|--------|
| WOL funktioniert nur aus Standby | PME aktivieren + ErP deaktivieren |
| PC wacht gar nicht auf | Power On By PCI-E im BIOS prüfen |
| Unzuverlässig | Schnellstart deaktivieren |
| Keine WOL-Optionen im Treiber | Aktuellen Treiber von realtek.com installieren |

## Konfiguration

Die MAC-Adresse wird in `.env` konfiguriert:

```bash
GAMING_PC_MAC=A8:5E:45:E4:CF:98
GAMING_PC_IP=192.168.1.135
LM_STUDIO_URL=http://192.168.1.135:1234
```
