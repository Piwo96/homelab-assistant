# Skill Isolation & LLM Routing — Design

**Status:** Draft
**Date:** 2026-05-17
**Topic:** Trennung `smart-home`/`homeassistant` + Skill-Owned-Context + Two-Stage-LLM-Routing
**Predecessor:** `2026-05-16-new-agent-design.md` (Bun/TS-Rewrite)

## 1. Context

Der Agent (`agent/src/`) lädt heute nur den `smart-home` Skill als LLM-Tool (`main.ts:46`), aber:

1. **`smart-home` ist nicht self-contained.** Das Python-Script importiert via `sys.path`-Hack die Klasse `HomeAssistantAPI` aus `../homeassistant/scripts/homeassistant_api.py`. Außerdem startet `agent/src/skills/ha-catalogue.ts` einen Subprozess auf `homeassistant/scripts/homeassistant_catalogue.py`. Damit hängt `smart-home` an Files außerhalb seines Verzeichnisses — entgegen dem Skill-Prinzip "ein Skill = ein in sich geschlossenes Verzeichnis".

2. **System-Prompt referenziert tote Tools.** `agent/src/pipeline/system-prompt.ts:47-58` erklärt dem LLM, es solle `entities --domain X --state Y` und `get-state` aufrufen — beides Commands des nicht-mehr-geladenen `homeassistant` Skills.

3. **Leak-Recovery ist auf homeassistant verdrahtet.** `agent/src/pipeline/leak-recovery.ts` matched `homeassistant_*`-Tool-Namen und whitelistet `entities`, `get-state`, `turn-on`, … — alles smart-home-fremdes Vokabular.

4. **Catalogue-Injection skaliert nicht.** Der Entity-Catalogue wird unconditional in jeden System-Prompt gespritzt. Sobald ein zweiter Domain-Skill (UniFi Protect, Proxmox) dazu kommt, würde sein Catalogue ebenso bei jeder Anfrage mitgesendet — auch wenn die Anfrage smart-home betrifft.

5. **Router ist gebypassed.** `BYPASS_ROUTER=1` ist Prod-Default; der semantische Embedding-Router wird in der Praxis nie befragt. Für einen einzelnen Skill funktioniert das, skaliert aber nicht.

## 2. Goals

- `smart-home` lebt vollständig innerhalb von `.claude/skills/smart-home/`. Kein Code-/Daten-Querverweis zu `homeassistant`.
- `homeassistant` Skill bleibt unverändert auf Platte erhalten (für direkten Claude-Code-Einsatz), wird aber vom Agent nicht geladen.
- Architektur ist auf weitere Domain-Skills vorbereitet: jeder Skill kann seinen eigenen Prompt-Context beisteuern, der nur bei Bedarf injiziert wird.
- Routing entscheidet pro Anfrage welche Skill-Domain zuständig ist; smalltalk wird explizit erkannt.
- Bei aktuell genau einem geladenen Skill (`smart-home`) bleibt die Latenz auf einem LLM-Call (Fast-Path).
- System-Prompt und Leak-Recovery referenzieren nur noch smart-home-Tool-Vokabular.

## 3. Non-Goals

- Änderungen am `homeassistant` Skill selbst (bleibt unangetastet).
- Neue Smart-Home-Features oder Tool-Erweiterungen.
- Aufnahme weiterer Domain-Skills in den Agent (UniFi-Protect, Proxmox, …) — nur die Architektur dafür wird vorbereitet.
- Verbesserung der Smalltalk-Qualität unter Fast-Path. Solange nur smart-home geladen ist, läuft Smalltalk durch den `TOOLED_PROMPT` und akzeptiert die leicht schlechtere Qualität. Sobald ein zweiter Skill dazukommt, aktiviert Stage 1 automatisch den `SMALLTALK_PROMPT`-Pfad.
- Persistenz des Context-Caches auf Disk (in-memory reicht, Refresh ist günstig).

## 4. Architecture Overview

### 4.1 Skill-Owned-Context (neues Pattern)

Skill-Contract bekommt einen **optionalen** Discovery-Command:

```
python3 <skill>_api.py --json context  →  { "markdown": "<prompt-injection-block>" }
```

Skills mit Domain-Discovery (smart-home: Entity-Catalogue; künftige UniFi: Kamera-Liste) implementieren `context`. Skills ohne Discovery (`wol`) implementieren ihn nicht.

Der Loader entdeckt die Capability beim Start aus dem `--help-json`-Output und setzt `Skill.hasContext: boolean`.

### 4.2 Two-Stage-LLM-Routing mit Fast-Path

```
handleText(msg):
  loaded = registry.all()
  selected: Skill | null

  if loaded.length === 1:                    # FAST-PATH
    selected = loaded[0]
  else:                                       # MULTI-SKILL: Stage 1 LLM-Router
    selected = await llmRouter.pick(msg, recentMessages, loaded)
    if selected === null:
      return await smalltalkReply(msg)        # SMALLTALK_PROMPT, keine Tools

  # Stage 2 (oder einziger Call bei Fast-Path)
  context = selected.hasContext ? await contextCache.get(selected.id) : null
  tools   = toolsFromSkill(selected)
  return await llm.generate({
    system:   buildSystemPrompt({ skill: selected, contextBlocks: [context].filter(Boolean), hasTools: true }),
    messages: recentMessages,
    tools,
    reasoningEffort: 'low',
  })
```

**Fast-Path** ist aktiv solange nur ein Skill geladen ist (heute der Fall). Sobald in `main.ts` ein zweiter Skill registriert wird, schaltet sich Stage 1 automatisch ein — keine Code-Änderung nötig.

### 4.3 Latency-Profile

| Modus | LLM-Calls | Erwarteter Mehraufwand vs heute |
|---|---|---|
| Fast-Path (1 Skill, heute) | 1 (Stage 2) | ±0 (kein Stage 1, kein Embedding-Lookup mehr) |
| Multi-Skill, Tool-Anfrage | 2 (Stage 1 + Stage 2) | +1-3 s (Stage-1-Prompt klein, `maxTokens≈50`) |
| Multi-Skill, Smalltalk | 2 (Stage 1 + Smalltalk-Reply) | +1-3 s |

## 5. Detailed Design

### 5.1 `smart-home` Skill — Selbst-Versorgung

**Neue Datei-Struktur:**

```
.claude/skills/smart-home/scripts/
  smart_home_api.py    # CLI-Entry (bestehend), plus neuer `context` Subcommand
  ha_client.py         # NEU — minimaler HA-REST-Client
  catalogue.py         # NEU — baut Markdown-Snapshot, nutzt ha_client
```

Kein `sys.path`-Hack, keine Imports aus `../homeassistant`.

#### `ha_client.py` — Minimal-Surface

Reimplementiert nur die HA-API-Methoden, die smart-home tatsächlich nutzt — purer Python `requests` (oder `urllib`) gegen die HA-REST-API. Token + Base-URL aus Env (`HA_TOKEN`, `HA_BASE_URL`, wie heute in `homeassistant_api.py`).

| Methode | Zweck | HA-Endpoint |
|---|---|---|
| `HAClient(base_url, token)` | Konstruktor | — |
| `.get_states()` | Liste aller Entities mit `state` + `attributes` (group-Entities haben `attributes.entity_id` mit Members) | `GET /api/states` |
| `.call_service(domain, service, *, entity_id?, **extra)` | Schreibe-Aktionen (turn_on/off, set_cover_position/_tilt, set_temperature, scene.turn_on, …) | `POST /api/services/{domain}/{service}` |
| `.render_template(tpl)` | Template-Rendering für Area-Auflösung | `POST /api/template` |
| `.get_areas()` | Liste `[{ area_id, name }]` via Template `{% for a in areas() %}{{ a }}|{{ area_name(a) }}\n{% endfor %}` | via `render_template` |
| `.entity_areas()` | Map `entity_id → area_id` für alle Entities (Batch-Template) | via `render_template` |

**Bewusst NICHT in `ha_client.py`** (Admin-Operationen, gehören zum `homeassistant` Skill):
- `list_automations`, `trigger`, `enable`, `disable`, `reload_automations`
- `list_scripts`, `run_script`, `stop_script`
- `history`, `logbook`, `error_log`
- `config`, `components`, `status` (HA-Health)

#### `catalogue.py` — Markdown-Generator

- Holt `client.get_states()` + `client.entity_areas()` + `client.get_areas()`.
- Filter auf relevante Domains: `light`, `switch`, `cover`, `climate`, `scene`, `script`, `group`.
- Gruppiert nach Etage (Prefix-Heuristik `eg_*` → EG aus heutiger `FLOOR_LABELS`) + Area.
- Rendert self-contained Markdown mit eigenem Header — der Agent kettet Skill-Blocks nur noch zusammen, keine eigene Wrapper-Sektion mehr.

**Output-Form:**
```markdown
BEKANNTE ENTITIES (smart-home, Snapshot ${iso-timestamp} — keine entity_ids erfinden):

### Lichter (light)

#### EG (Erdgeschoss)
- light.eg_essen_tischleuchte — EG Essen Tischleuchte
- light.eg_wohnzimmer_decke — EG Wohnzimmer Decke
…

#### OG (Obergeschoss)
…

### Rollos / Jalousien (cover)
…

### Heizung (climate)
…

### Szenen (scene)
…

### Gruppen
- group.og_lichter — OG Lichter (7 Mitglieder)
…
```

#### `smart_home_api.py` Anpassungen

- Imports: `from ha_client import HAClient`, `from catalogue import build_markdown`. Kein `sys.path.insert`.
- Neuer Subparser: `context` → `print(json.dumps({"markdown": build_markdown(client)}))`.
- Bestehende Commands (`lights-on/off/set/status`, `rollos-*`, `klima-*`, `szenen-*`, `bereich-aus`, `etage-aus`, `gerät-*`) bleiben funktional identisch.
- API-Surface von `HAClient` muss kompatibel zu den Stellen sein, an denen heute `api.get_states()` / `api.call_service(...)` aufgerufen werden — bei der Migration die Signaturen 1:1 nachziehen.

### 5.2 Agent — neue Module

#### `agent/src/skills/context-cache.ts`

```ts
export interface SkillContextCache {
  get(skillId: string): Promise<string | null>;  // markdown or null on persistent failure
  start(): void;                                  // begin background refresh loop
  stop(): void;
}

export function createSkillContextCache(opts: {
  registry: SkillRegistry;
  ttlMs?: number;          // default 30 * 60_000
  executor: SkillExecutor; // injects runCommand(skill, 'context')
  logger: Logger;
}): SkillContextCache;
```

**Semantik:**
- Lazy-Fetch beim ersten `get()` für einen Skill mit `hasContext: true`.
- Background-Refresh: jeder Skill mit `hasContext` wird alle TTL-ms neu geholt.
- Bei Fetch-Fehler: vorherigen Wert behalten + `warn`-log (gleiche Resilienz wie `startCatalogueRefresh` heute).
- Skills ohne `hasContext` → `get` returnt direkt `null`.

#### `agent/src/router/llm-router.ts`

```ts
export interface LlmRouter {
  pick(input: {
    msg: string;
    recentMessages: Array<{ role: 'user' | 'assistant'; content: string }>;
    candidates: Array<{ id: string; description: string }>;
  }): Promise<{ skillId: string } | null>;
}
```

**Prompt-Template:**

```
Du bist ein Skill-Router. Wähle den passenden Skill für die User-Anfrage,
oder null wenn keine Domain passt (Smalltalk, Frage außerhalb des Homelabs).

Skills:
- smart-home: ${description}
- unifi-protect: ${description}
…

Letzte Nachrichten (Kontext):
${last 3 turns}

Anfrage: "${msg}"

Antwort als JSON (keine Erklärung, kein Markdown):
{ "skill": "<name>" } oder { "skill": null }
```

**Implementierung:**
- Eigener LM-Studio-Call mit `maxTokens: 50`, `reasoningEffort: 'low'`, `tools: {}`.
- Output parsen: strip whitespace + optional code-fences, `JSON.parse`, validieren dass `skill` entweder `null` oder ein `candidates[].id` ist.
- Bei Parse-Fail oder unbekanntem Namen → returnt `null` → Agent fällt auf Smalltalk-Pfad.

### 5.3 Agent — geänderte Module

| Datei | Änderungen |
|---|---|
| `main.ts` | Drop: `fetchHaCatalogue`, `startCatalogueRefresh`, `embed`/`embedMany`-Setup, `computeCacheKey`/`loadCache`/`saveCache`, `buildSkillEmbeddingInput`, `entityCatalogue`-Plumbing. Add: `createSkillContextCache(...)`, `contextCache.start()`, Übergabe an `handleDeps`. |
| `skills/loader.ts` | Nach `--help-json`: `skill.hasContext = 'context' in commands`. `context` Command wird **nicht** als LLM-Tool registriert (nur Helper). |
| `pipeline/handle-message.ts` | Routing-Block (Z.178-205) ersetzen durch Fast-Path/Stage-1-Logik aus 4.2. `looksLikeLeakedReasoning`-Regex (Z.73) auf `"function": "smart-home_` umstellen (homeassistant-Pattern raus). Comment Z.256 (`get-state-Schleife`) auf smart-home-Vokabular updaten (z.B. `lights-status`-Schleife statt einzelne `gerät-status`-Calls). |
| `pipeline/system-prompt.ts` | Signature: `buildSystemPrompt({ skills, hasTools, firstName?, contextBlocks: string[] })`. TOOLED_PROMPT-Section "KOLLEKTIVE ZUSTANDS-ABFRAGEN" referenziert ab jetzt `lights-status --state on/off`, `rollos-status`, `klima-status`, `gerät-status` (statt `entities`/`get-state`). Section "ZUSTANDS-WISSEN IST NIE STATISCH" analog. "BEKANNTE ENTITIES"-Wrapper raus (Smart-Home liefert eigenen Header). Concat: `${TOOLED_PROMPT}\n\n${contextBlocks.join('\n\n')}`. |
| `pipeline/leak-recovery.ts` | `RECOVERABLE_COMMANDS` neu: `lights-on`, `lights-off`, `lights-set`, `lights-status`, `rollos-open`, `rollos-close`, `rollos-set`, `rollos-status`, `klima-set`, `klima-status`, `szenen-aktivieren`, `szenen-liste`, `bereich-aus`, `etage-aus`, `gerät-an`, `gerät-aus`, `gerät-toggle`, `gerät-status`. `formatRecoveredResult` vereinfacht: smart-home liefert strukturiertes `{ok, action, entities, message?}` — kurzes Format-Template statt HA-State-Shape-Raterei. Doc-Comment auf smart-home umschreiben. |
| `config/env.ts` | `EMBEDDING_MODEL` raus. `BYPASS_ROUTER` wird gar nicht mehr eingelesen. `WHISPER_MODEL` bleibt (separater Endpoint via `llm/transcribe.ts`). |

### 5.4 Agent — gelöschte Module

- `agent/src/router/semantic.ts`
- `agent/src/router/cache.ts`
- `agent/src/llm/embedding.ts` (nicht mehr referenziert — Whisper läuft über `llm/transcribe.ts`)
- `agent/src/skills/ha-catalogue.ts`
- Disk-Artefakt `data/agent-embedding-cache.json` (im Deploy-Step aufräumen, nicht im Code)

### 5.5 Tests

**Zu entfernen:**
- Router-Tests die `router/semantic.ts` testen
- `ha-catalogue.test.ts` (falls vorhanden)

**Anzupassen:**
- `handle-message.test.ts`: Fast-Path-Branch + Mock-`llmRouter.pick` für künftigen Multi-Skill-Pfad
- `leak-recovery.test.ts`: Allowlist auf smart-home-Commands umstellen, Fixtures auf smart-home-Result-Shapes

**Neu:**
- `context-cache.test.ts`: TTL, lazy fetch, Fehler-Fallback (alter Wert bleibt)
- `llm-router.test.ts`: JSON-Parse-Robustheit (code-fences, leerzeichen), Fallback zu `null` bei Garbage-Output, Validierung gegen `candidates`-Liste

**Smoke-Test E2E** (manuell nach Deploy):
- Fast-Path happy path: "licht im EG an" → Tool-Call, Reply in <5 s.
- Smalltalk unter Fast-Path: "wie geht's dir?" → keine Tool-Calls, Text-Reply (Qualität: akzeptabel-aber-nicht-perfekt — siehe Non-Goals).
- Entity-Lookup: "welche Lichter sind an?" → `lights-status --state on`-Call, formatierte Liste.

## 6. Migration / Rollout

1. **Phase 1: smart-home autark machen** (`.claude/skills/smart-home/scripts/`):
   - `ha_client.py` schreiben + Tests gegen lokale HA-Instanz
   - `catalogue.py` schreiben + Output gegen heutigen `homeassistant_catalogue.py`-Output diff'en (Markdown-Strukturen müssen kompatibel sein)
   - `smart_home_api.py` umverdrahten + alle Subcommands gegen den neuen Client manuell durchsteppen (`lights-on Wohnzimmer`, `rollos-set --where OG --position 50 --tilt 30`, …)
   - Neuer `context` Subcommand verifizieren: `python3 smart_home_api.py --json context | jq .markdown`

2. **Phase 2: Agent-Code refactoren**:
   - `context-cache.ts` + `llm-router.ts` neu schreiben + Unit-Tests
   - `loader.ts` `hasContext` Detection
   - `system-prompt.ts` Vokabular-Update + neue Signature
   - `leak-recovery.ts` Allowlist + Formatter-Update
   - `handle-message.ts` Routing-Block ersetzen + Regex-Update
   - `main.ts` aufräumen + neue Wiring
   - Embedding-Module & Router-Module löschen
   - `env.ts` cleanup
   - `bun test` grün

3. **Phase 3: Deploy & verifizieren**:
   - LXC redeploy via `infra/rolly/deploy.sh`
   - Manuelle Smoke-Tests (siehe 5.5)
   - LXC: alte `agent-embedding-cache.json` löschen, `EMBEDDING_MODEL`/`BYPASS_ROUTER` aus `agent/.env` entfernen

**Rollback-Strategie:** Da der `homeassistant` Skill auf Platte unverändert bleibt, ist ein Rollback durch Re-Setzen von `loadSkills(skillsRoot, ['homeassistant'])` in `main.ts` plus Wiederherstellen der alten Prompt-/Recovery-Files via Git möglich. Vor dem Deploy einen Git-Tag setzen.

## 7. Open Questions

- **HA-Area-Resolution via REST**: Genauer Endpoint/Template-Approach wird während Implementation entschieden (Template-Rendering vs. WS-API-Workaround). Falls Template-API zu langsam für die Catalogue-Generierung wird → entweder einmalig cachen oder kleinen WS-Client einbauen. Während Planning evaluieren.
- **Context-Cache TTL-Default**: 30 min wie heute. Bei häufigen Entity-Renames manuell anpassbar — sollte das ein Skill-Frontmatter-Feld werden (`context_ttl_seconds`)? Vorerst hart-coded, später ggf. konfigurierbar.

## 8. Out of Scope

- Smalltalk-Qualität unter Fast-Path verbessern (siehe Non-Goals).
- Persistente Context-Cache auf Disk (in-memory reicht).
- Embedding-basierter Re-Ranker als Hybrid mit LLM-Router (kann später als Optimierung dazu kommen, wenn Multi-Skill-Routing-Latency zum Problem wird).
- Änderungen am `homeassistant` Skill — bleibt 1:1 erhalten.
- Auth-Gating einzelner Skills auf Owner-Chat (Owner vs. Familien-User) — separates Thema, hier nicht adressiert.
