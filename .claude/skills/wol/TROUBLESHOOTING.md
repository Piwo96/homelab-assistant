# WoL Troubleshooting

## `--json` before subcommand crashes argparse (exit code 2)

**Symptom:** `wake.ts` reports "Gaming-PC kommt nicht hoch" immediately; no Magic Packet is ever sent. Script exits with code 2 and stderr "unrecognized arguments: --json".

**Root cause:** The generic `skills/executor.ts` passes `--json` as the first argument (`script --json <command> …`). The `wake` subparser did not declare `--json`, so argparse rejected it before executing anything.

**Fix applied:**
- `--json` is now a no-op global flag on the parent parser in `wol_api.py` (output is always JSON).
- `wol/wake.ts` no longer prepends `--json` — it calls `wol_api.py wake --wait` directly.

> **Guard:** `wol_api.py` is invoked via the dedicated `wol/wake.ts` path, **not** `skills/executor.ts`. Keep `wake.ts` and the script's argparse in sync. When adding new flags to `wake`, add them to both.

---

## Magic Packet sent but PC does not boot (S5 / full shutdown)

**Symptom:** WoL works from S3 sleep but not after a full Windows shutdown.

**Most likely cause:** Windows **Fast Startup** (Schnellstart) converts a normal shutdown into a hybrid hibernate. The NIC is put into a state where it ignores Magic Packets from most drivers.

### Checklist — Windows Gaming PC

1. **Disable Fast Startup** — Systemsteuerung → Energieoptionen → Auswählen, was beim Drücken des Netzschalters geschehen soll → "Schnellstart aktivieren" **deaktivieren**. This is the #1 fix.

2. **NIC driver settings** — Geräte-Manager → Netzwerkadapter → [NIC] → Eigenschaften:
   - *Energieverwaltung*: "Gerät kann den Computer aus dem Ruhezustand aktivieren" ✔ + "Nur Magic Packet" ✔
   - *Erweitert*: "Wake on Magic Packet" = Enabled; (Realtek) "Shutdown Wake-On-LAN" = Enabled / (Intel) "Wake on Magic Packet from power off state" = Enabled; "Energy Efficient Ethernet" / "Green Ethernet" = Disabled

3. **BIOS/UEFI**:
   - "Wake on LAN" / "Power On by PCI-E" = Enabled
   - "ErP Ready" / "EuP Ready" = **Disabled** (ErP cuts NIC standby power in S5 → WoL from full off impossible)

4. **Diagnostic:** WoL from S3 working but S5 failing → Fast Startup or the NIC's "from power-off" setting.

---

## Packet dropped / intermittent wakeup

**Symptom:** PC wakes up ~70% of the time; occasional misses.

**Fix applied:** Script now retransmits 3× on **both** UDP ports 9 and 7. UDP broadcasts can be dropped at the switch level, and some NICs listen on port 7 instead of 9.

---

## `lm_studio_available` key missing in wake.ts response

**Symptom:** `wake.ts` reads `result.lm_studio_available` → always `undefined` → treated as failure.

**Root cause:** Under `--wait`, the script returns `{ success, lm_studio: { available } }` (nested), not a top-level `lm_studio_available`.

**Fix:** Read `result.lm_studio?.available`. Use `!== true` as the safe-failure default (undefined → false).

---

## Timeout too short for cold boot (S5 → LM Studio ready)

**Symptom:** `wake.ts` times out after 240s; PC is still booting or LM Studio is still loading the model.

**Root cause:** A cold start from S5 plus LM Studio loading a 4B-class model can easily exceed 240s.

**Fix applied:** `WOL_TIMEOUT` default raised from 120s → 360s in `wol_api.py`; `wake.ts` outer cap raised from 270s → 390s.
