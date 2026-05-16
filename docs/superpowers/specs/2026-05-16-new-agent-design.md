# New Homelab Agent — Design Spec

**Date:** 2026-05-16
**Author:** Philipp Rollmann (with Claude)
**Status:** Draft, pending user review
**Replaces:** `agent-old/` (Python/FastAPI implementation, archived in repo)

## 1. Context & Goals

The current `agent-old/` is a Python/FastAPI Telegram-bot that routes natural-language requests to skill scripts via a two-stage pipeline (embedding pre-filter → LM Studio tool-calling). It works, but performance and reliability are below what is achievable with current local models and frameworks.

The new agent keeps the proven core idea (embedding pre-router + focused tool-call) but moves the orchestration layer to TypeScript so it can leverage:

- **Vercel AI SDK** for model-agnostic tool-calling, streaming and tool-loops
- **Zod schemas** for runtime arg validation that catches small-model hallucinations before subprocess execution
- **Bun** for sub-100ms cold-start webhook handling
- Patterns from `chaingrow` and `glirastes` (Chainmatics' own agentic SDK) — specifically the *module → tools → router → pipeline* shape

The 7 existing Python skill scripts (`.claude/skills/*/scripts/*_api.py`) are **not migrated**. They are invoked as subprocesses and remain the single source of truth for skill behavior and CLI arg specs.

### Goals

1. Replace `agent-old/` with a TypeScript orchestrator under `agent/`.
2. Target **Gemma 4 E4B (8-bit / SFP8)** running in LM Studio on the Gaming PC (~7.5 GB VRAM, 128 K context, native function calling, configurable thinking mode).
3. Preserve all current skill functionality, accessible from Telegram.
4. Add multimodal input (photo, voice) and proactive notifications.
5. Keep self-annealing (auto-fix on skill errors via Claude API + admin approval).
6. Drop skill-creator-via-PR for v1 (high complexity, low usage; can return in v2).

### Non-Goals (v1)

- Migrating any Python skill script to TypeScript
- Multi-user concurrency beyond the existing allow-list
- Web UI (Telegram remains the only surface)
- LangGraph or any multi-agent orchestration
- Auto-generated `keywords.json` / `examples.json` per skill (replaced by frontmatter `triggers` + `intent_hints` + Zod descriptions)

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ Telegram User (text / photo / voice)                             │
└──────────────────────────────┬───────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ Bun HTTP Server (agent/src/server.ts)                            │
│  • POST /webhook         — Telegram webhook (HMAC verify, dedup) │
│  • POST /internal/notify — Skills push notifications             │
│  • POST /reload-skills   — Hot-reload SKILL.md changes           │
│  • GET  /health                                                  │
└──────────────────────────────┬───────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ Pipeline (agent/src/pipeline/handle-message.ts)                  │
│  1. Normalize input (text | photo | voice→Whisper transcript)    │
│  2. Load chat history (SQLite, last 20 messages)                 │
│  3. Semantic Router (cosine match vs cached skill embeddings)    │
│       HIGH ≥ 0.75 → 1 skill                                      │
│       MED  0.40-0.74 → top-2 skills                              │
│       LOW  < 0.40 → smalltalk, polite homelab redirect           │
│  4. Build tool set (Zod schemas from `--help-json` introspection)│
│  5. AI SDK generateText (LM Studio, maxSteps: 5, thinking auto)  │
│  6. Tool execution: Zod parse → admin check → subprocess         │
│  7. On error → Self-Annealing flow                               │
│  8. Persist + reply (text / photo / inline keyboard)             │
└────────────────┬──────────────────────────┬──────────────────────┘
                 ▼                          ▼
┌────────────────────────────┐   ┌─────────────────────────────────┐
│ Subprocess Runner          │   │ Self-Annealing                  │
│  python *_api.py … --json  │   │  Claude API → search-replace    │
│  30 s timeout              │   │  edits → admin Telegram approve │
│  Stream stdout to log      │   │  → git commit on feature branch │
└────────────────────────────┘   └─────────────────────────────────┘
```

## 3. Project Layout

`agent-old/` is preserved as a reference snapshot. New code lives in `agent/`:

```
agent/
├── src/
│   ├── main.ts                    # entry: parse env, init db, start server
│   ├── server.ts                  # Bun HTTP routes
│   ├── config/env.ts              # zod-validated env loader
│   ├── telegram/
│   │   ├── webhook.ts             # signature verify, dedup
│   │   └── send.ts                # text / photo / inline keyboard
│   ├── llm/
│   │   ├── lm-studio.ts           # AI SDK provider for LM Studio (OpenAI-compatible)
│   │   └── embedding.ts           # /v1/embeddings client
│   ├── router/
│   │   ├── semantic.ts            # cosine-similarity skill match
│   │   └── cache.ts               # SHA256-keyed embedding cache (data/embedding_cache.json)
│   ├── skills/
│   │   ├── loader.ts              # parse SKILL.md + run --help-json on each *_api.py
│   │   ├── registry.ts            # in-memory skill registry, hot-reload aware
│   │   └── executor.ts            # subprocess runner with timeout + JSON parse
│   ├── tools/
│   │   ├── define-skill-tool.ts   # AI SDK Tool wrapper around a skill action
│   │   └── help-json-to-zod.ts    # convert --help-json output to Zod schemas
│   ├── memory/
│   │   ├── db.ts                  # bun:sqlite, schema migrations
│   │   └── history.ts             # per-chat conversation slice
│   ├── perms/admin.ts             # admin/allow-list checks
│   ├── pipeline/
│   │   ├── handle-message.ts      # full request flow (declared again below)
│   │   └── complexity-heuristic.ts # decides reasoning.effort low|high
│   ├── annealing/
│   │   ├── tracker.ts             # log skill_errors to SQLite
│   │   ├── classifier.ts          # transient | data | bug
│   │   ├── fix-generator.ts       # Anthropic SDK, search-replace EDIT format
│   │   └── approval.ts            # Telegram inline-keyboard handlers
│   ├── notifications/push.ts      # /internal/notify endpoint + rate-limit
│   └── multimodal/
│       ├── photo.ts               # download + base64 + image_url part
│       └── audio.ts               # Whisper via /v1/audio/transcriptions
├── package.json
├── tsconfig.json
└── bun.lock
```

## 4. Request Flow (detailed)

```
Telegram update
  → webhook.ts
     • verify X-Telegram-Bot-Api-Secret-Token            ~1 ms
     • dedup via processed_updates (7 d retention)        ~2 ms
     • allow-list check                                   ~0 ms
  → handle-message.ts:

  Step 1 — Normalize input
    text   → use as-is
    photo  → download → base64 → image_part attached to chat msg     ~200 ms
    voice  → Whisper (LM Studio /v1/audio/transcriptions)            ~500 ms
    Result: { kind, text, attachments }

  Step 2 — Load context
    • chat history (last 20, filtered for token budget)              ~5 ms
    • admin status from env                                          ~0 ms

  Step 3 — Semantic Router
    • embed(text) via /v1/embeddings (gemma-embedding)               ~50 ms
    • cosine match vs cached skill embeddings                        ~1 ms
    • bands:
        HIGH ≥ 0.75            → 1 skill, expose all its tools
        MED  0.40-0.74         → top-2 skills, expose all their tools
        LOW  < 0.40            → no tools; smalltalk redirect path

  Step 4 — Build tool set
    For each candidate skill:
      For each *_api.py script in skill:
        For each command in script's --help-json:
          tools[`${scriptStem}__${command.name}`] = aiTool({
            description: command.description,
            parameters: zodSchemaFromHelpJson(command),
            execute: async (args) => {
              if (command.is_write && !ctx.isAdmin)
                throw new ToolError('admin_required');
              return executor.run(scriptPath, command.name, args);
            },
          });

  Step 5 — LLM call
    const result = await generateText({
      model: lmStudio('gemma-4-e4b'),
      system: buildSystemPrompt({ skills, attachments, smalltalk: false }),
      messages: [...history, currentUserMsg],
      tools,
      toolChoice: 'auto',
      providerOptions: {
        openai: { reasoning: { effort: complex(text) ? 'high' : 'low' } },
      },
      maxSteps: 5,
    });

  Step 6 — Tool execution (inside the AI SDK loop)
    tool.execute parses args via Zod → throws structured ToolError
    on validation fail → AI SDK feeds back to LLM, which can retry.
    Subprocess runner: 30 s timeout, --json output, stderr captured.

  Step 7 — Format response
    AI SDK already produces text incorporating tool results.
    Fallback structured renderer if final text is empty.

  Step 8 — Error handling (subprocess fail / Zod fail / Tool error)
    classifier.classify(error):
      transient → retry once silently
      data      → friendly user message ("VM 100 not found"), no fix
      bug       → annealing.requestFix() — admin Telegram message with [Approve][Reject][Diff]

  Step 9 — Persist + reply
    Insert user msg + assistant reply + tool calls into conversations table.
    telegram/send.ts → reply (text, photo, inline keyboard).
```

### Smalltalk path (LOW band)

Single `generateText` call without tools, system prompt instructs the model to politely redirect to homelab capabilities and list a few examples ("frag mich z. B. nach VMs, Kameras, Smart-Home oder DNS"). No tool-loop, no Zod validation.

### Adaptive thinking budget

`reasoning.effort` is set heuristically per request:

- `low` (default): single-intent query, ≤ 1 entity, short text
- `high`: multi-clause query, conjunctions ("und dann", "danach"), negation, ambiguous entities

Heuristic lives in a small `complexityHeuristic.ts` (regex + word-count); easy to swap for an embedding-based classifier later if it matters.

## 5. Skill → Tool Mapping

### Loader convention

```ts
loadAllSkills(skillsRoot):
  for each <skillName>/SKILL.md:
    frontmatter = parseFrontmatter(SKILL.md)            // gray-matter
    scripts = glob(`${skillsRoot}/${skillName}/scripts/*_api.py`)
    if scripts.length === 0:
      // meta-skill (e.g. homelab) — register for embedding only? skip for v1.
      continue
    tools = []
    for each scriptPath:
      helpJson = await execHelpJson(scriptPath)          // see below
      for each command in helpJson.commands:
        tools.push(buildTool(scriptPath, command, frontmatter))
    register({
      id: frontmatter.name,
      description: frontmatter.description,
      triggers: frontmatter.triggers,
      intentHints: frontmatter.intent_hints ?? [],
      embedding: precomputedOrCompute(...),
      tools,
    })
```

### `--help-json` contract

Every `*_api.py` adds a `--help-json` flag emitting:

```json
{
  "script": "proxmox_api.py",
  "description": "Proxmox VE management",
  "commands": {
    "start": {
      "description": "Start a VM or container",
      "is_write": true,
      "args": [
        { "name": "vmid", "type": "int", "required": true, "description": "Numeric VM/CT ID" },
        { "name": "node", "type": "str", "required": false, "default": null, "description": "Cluster node name" }
      ]
    },
    "overview": {
      "description": "Show cluster overview",
      "is_write": false,
      "args": []
    }
  }
}
```

A shared helper `agent/scripts/skill_helpers.py` (NEW, Python) exposes:

```python
def emit_help_json(parser: argparse.ArgumentParser) -> None:
    """Walk subparsers and print the contract above to stdout, then exit(0)."""
```

Every `*_api.py` adds two lines in `main()`:

```python
parser.add_argument('--help-json', action='store_true')
# ... rest of arg setup ...
if args.help_json: emit_help_json(parser); return
```

`is_write` is set per subparser via `subparser.set_defaults(_is_write=True)`. Defaults to `False` if omitted.

### Type mapping (Python argparse → Zod)

| argparse `type` | Zod |
|-----------------|-----|
| `int` | `z.number().int()` |
| `float` | `z.number()` |
| `str` | `z.string()` |
| `bool` (`store_true`/`store_false`) | `z.boolean()` |
| `choices=[...]` | `z.enum([...])` |
| nargs `+` / `*` | `z.array(...)` |
| `default=…` | `.default(…)` |
| not required | `.optional()` |

### Tool naming

`<scriptStem>__<commandName>` — double underscore. `scriptStem` is the script filename with the `_api.py` suffix removed (e.g. `proxmox_api.py` → `proxmox`, `dashboard_api.py` → `dashboard`).

- `proxmox__start`, `proxmox__overview`
- `homeassistant__turn_on`, `dashboard__create` (both belong to skill `homeassistant`)
- `protect__events`, `protect__snapshot`

Skill-name is used for routing/embeddings; script-stem is used for tool names. Multiple scripts per skill are normal (current state: `homeassistant` has 2, `self-annealing` has 2).

### Embedding string per skill

```
{description}. Triggers: {triggers.join(', ')}. {intentHints.join('. ')}. Commands: {allCommandDescriptions.join('. ')}.
```

Single embedding per skill (no per-command sub-routing in v1; LLM handles tool selection within a skill via function calling).

### Cache invalidation

```ts
cacheKey = sha256(JSON.stringify({
  embeddingModel: env.EMBEDDING_MODEL,
  skills: skills.map(s => ({
    id: s.id,
    description: s.description,
    triggers: [...s.triggers].sort(),
    intentHints: s.intentHints,
    commandDescriptions: Object.values(s.tools).map(t => t.description).sort(),
  })),
}))
```

Stored in `data/embedding_cache.json`. Any SKILL.md or argparse-help change → key changes → re-embed on next startup or `/reload-skills`.

## 6. Cross-Cutting Features

### 6.1 Self-Annealing (`agent/src/annealing/`)

```
ToolError caught in pipeline
  → tracker.log({ skill, action, args, stderr, stack, ts })
  → classifier.classify(error):
       transient (timeout, ECONNREFUSED) → retry once silently
       data ("VM 100 not found")          → friendly user message
       bug (Python exception)             → fix flow

Fix flow:
  → fix-generator.ts: Anthropic SDK call (claude-sonnet-4-6, prompt-cached)
       Input: SKILL.md, full script, stderr, last args, EDIT-format schema
       Output: { edits: [{ path, old_string, new_string }, ...] }
  → approval.ts:
       Telegram message to ADMIN_TELEGRAM_ID:
         "Fehler in proxmox/start: ... 3 Edits vorgeschlagen"
         [Approve] [Reject] [Show Diff]   (inline_keyboard, callback_data)
  → On callback_query:
       Show Diff → render unified diff in chat
       Approve   → apply edits (search-replace; old_string must exist + be unique)
                   → git commit on feature/anneal-{ts} → push → confirm in chat
       Reject    → mark error as "rejected" in DB; no retry
```

**Critical rule (kept from agent-old):** edits are search-replace, never full-file rewrites. `old_string` must exist exactly once in the file or the edit fails — prevents code loss from LLM hallucination.

**Model:** `claude-sonnet-4-6` for fix generation. Prompt caching enabled for the SKILL.md + script-content blocks (saves ~60 % tokens on repeat fixes to the same script).

### 6.2 Multimodal Input (`agent/src/multimodal/`)

| Telegram message | Path |
|------------------|------|
| text | direct to handle-message |
| photo | `photo.ts`: getFile → download → base64 → AI SDK `image_part` attached to current user message; LLM sees it during the same generateText call |
| voice / audio | `audio.ts`: getFile → download → POST to LM Studio `/v1/audio/transcriptions` (Whisper, e.g. `whisper-large-v3-turbo`) → transcript becomes the input text; pipeline continues normally |

Whisper runs alongside Gemma 4 E4B in LM Studio. See section 8 for the per-model GPU/CPU offload strategy on the target GPU (RTX 2070 Super, 8 GB).

For photo without caption: the embedding router is bypassed (no skill match without text); the LLM is given the image with a system prompt "User schickte ein Bild ohne Text. Was siehst du, hilft das beim Homelab?".

### 6.3 Proactive Notifications (`agent/src/notifications/`)

Skill scripts and external sources can push notifications to Telegram via:

```
POST http://localhost:PORT/internal/notify
Authorization: Bearer ${INTERNAL_NOTIFY_TOKEN}
Body:
{
  "audience": "admin" | "all_users" | { "chatId": 123 },
  "text": "Bewegung an Einfahrt erkannt",
  "photo_url": "https://...",       // optional
  "buttons": [                       // optional inline_keyboard
    { "label": "Snapshot", "callback": "protect:snapshot:einfahrt" }
  ]
}
```

`INTERNAL_NOTIFY_TOKEN` is in `.env`, only valid on `localhost`.

**Source of notifications (v1):** a Bun worker inside the agent polls every 30 s. For first iteration, only one watcher is wired up: `protect_api.py events --since "30s ago" --new-only` for motion events. Other watchers (HA sensors, Pi-hole spikes) are added one by one as needs surface.

**Rate-limit:** max 1 notification per (audience, topic) per 60 s.

**Future option:** swap polling for inbound webhooks from Home Assistant / UniFi Protect. Out of scope for v1.

### 6.4 Conversation History (`agent/src/memory/`)

`bun:sqlite` (built-in, no npm dep). Single file `data/conversations.db` (shared with agent-old; schema additive).

```sql
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY,
  chat_id INTEGER NOT NULL,
  role TEXT NOT NULL,        -- 'user' | 'assistant' | 'tool'
  content TEXT NOT NULL,     -- JSON: { text, attachments?, tool_call?, tool_result? }
  intent TEXT,               -- skill id if applicable
  success BOOLEAN,
  ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_ts ON conversations (chat_id, ts DESC);

CREATE TABLE IF NOT EXISTS processed_updates (
  update_id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_errors (
  id INTEGER PRIMARY KEY,
  skill TEXT NOT NULL,
  action TEXT NOT NULL,
  args TEXT,                 -- JSON
  stderr TEXT,
  stack TEXT,
  classification TEXT,       -- 'transient' | 'data' | 'bug'
  status TEXT,               -- 'open' | 'fixed' | 'rejected'
  ts INTEGER NOT NULL
);
```

Per-chat history fed to LLM: last 20 messages, with tool results truncated to a brief summary so token usage stays bounded.

### 6.5 Permissions (`agent/src/perms/admin.ts`)

- `ADMIN_TELEGRAM_ID` (single admin) — required for write ops, self-annealing approval, callback queries.
- `TELEGRAM_ALLOWED_USERS` (comma-separated) — anyone in this list may interact (read-only ops, all read commands).
- `is_write` flag derived from `--help-json` per command.
- In `tool.execute`: if `is_write && !ctx.isAdmin` → throw `ToolError('admin_required')` → AI SDK loops with the error → LLM can produce a polite refusal message in the next step.

## 6.6 VRAM Strategy (RTX 2070 Super, 8 GB)

Total budget is 8 GB. Gemma 4 E4B at 8-bit/SFP8 takes ~7.5 GB. Embedding and Whisper cannot all be GPU-resident simultaneously. Strategy splits by access pattern:

| Model | Placement | Reason |
|-------|-----------|--------|
| `gemma-4-e4b` (8-bit) | **GPU, always loaded** | Hot path, ~7.5 GB, every request |
| `nomic-embed-text-v2-moe` (305M, multilingual) **or** `granite-embedding:107m` | **CPU, always loaded** | Hot path (every request), 50-150 ms CPU inference is acceptable. Frees GPU for Gemma. ~600 MB RAM. |
| `whisper-large-v3-turbo` (Q5, ~800 MB) | **GPU, JIT (load-on-demand)** | Cold path (voice only). First voice msg ~3 s cold-start; subsequent warm. Unload after N min idle. |

LM Studio supports per-model GPU offload (set to 0 layers = CPU-only) and per-model "keep loaded" (false = JIT). Configure each model accordingly in the LM Studio UI; the agent uses the same `LM_STUDIO_URL` for all three.

If voice usage grows enough that Whisper cold-starts become annoying, the upgrade path is a GPU with more VRAM (≥ 12 GB) or replacing Whisper with the future native-audio Gemma 4 path (see Open Questions).

## 7. Configuration (`.env`)

```bash
# --- Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
TELEGRAM_ALLOWED_USERS=123,456
ADMIN_TELEGRAM_ID=123

# --- LM Studio
LM_STUDIO_URL=http://192.168.178.50:1234
LM_STUDIO_MODEL=gemma-4-e4b                   # GPU, always loaded
EMBEDDING_MODEL=nomic-embed-text-v2-moe       # CPU offload (GPU layers = 0)
WHISPER_MODEL=whisper-large-v3-turbo          # GPU, JIT (keep-loaded = false)

# --- Wake-on-LAN (Gaming PC where LM Studio runs)
GAMING_PC_IP=192.168.178.50
GAMING_PC_MAC=AA:BB:CC:DD:EE:FF

# --- Self-annealing
ANTHROPIC_API_KEY=...                      # for fix generation
ANNEALING_MODEL=claude-sonnet-4-6

# --- Internal endpoints
INTERNAL_NOTIFY_TOKEN=<random-32-byte-hex>

# --- Operational
PORT=8080
GIT_PULL_INTERVAL_MINUTES=5
NOTIFICATION_POLL_INTERVAL_SECONDS=30
```

Loaded via a single `config/env.ts` with a Zod schema; missing required vars → fail fast at startup.

## 8. Deviations from `agent-old/`

| Area | agent-old | new agent |
|------|-----------|-----------|
| Language / runtime | Python + FastAPI | TypeScript + Bun |
| LLM client | raw `httpx` to LM Studio | Vercel AI SDK |
| Tool definitions | hand-built dicts | Zod schemas from `--help-json` |
| Routing | embeddings + LLM-narrowed | embeddings only (LLM picks tools within 1 skill) |
| Args extraction | regex `arg_extractor.py` | LLM via Function Calling, Zod-validated |
| Auto-metadata | `keywords.json` + `examples.json` per skill | dropped — frontmatter + Zod descriptions cover it |
| Skill creator | Claude-API → PR | dropped for v1 |
| Skills (Python) | unchanged | unchanged (only `--help-json` flag added) |
| Multimodal input | none | photo + voice (Whisper) |
| Proactive notifications | none | `/internal/notify` endpoint + 1 watcher (UniFi Protect) |

## 9. Open Questions / Follow-Ups

1. **Whisper model choice** — `whisper-large-v3-turbo` Q5 (~800 MB) chosen as default for VRAM-constrained setup. Confirm it's available in user's LM Studio or install via the LM Studio model browser.
2. **`git_api.py` duplicate** in `self-annealing/` vs `git/` — clean up via symlink or shared import. Out of scope for the agent design itself; tracked here for future cleanup.
3. **Gemma 4 E4B + native audio input** — once stable in LM Studio's OpenAI-compatible API, we can replace Whisper transcription with direct audio_part attachments. Same pipeline position, easy swap.
4. **Per-command embeddings (sub-routing)** — deliberately deferred. Add only if telemetry shows the LLM systematically picks the wrong action within a skill.
5. **`examples` in frontmatter** — design reserves the option. Add only if v1 shows tool-selection misses on specific phrasings.
7. **Meta-skills like `homelab`** — currently registered as "skip if no scripts". Decide later whether they should still contribute their description to embedding routing context (could help disambiguate "homelab status" type queries).
6. **Migration of `data/conversations.db`** — schema is additive; agent-old's existing DB can be reused without conversion. Verify on first boot.

## 10. Rollout

1. Build `agent/` alongside `agent-old/` — they don't share runtime state beyond the SQLite file.
2. Run `agent/` on a different port locally for shadow testing (manually compare responses to old agent).
3. Add `--help-json` to one script first (`wol_api.py`, smallest), verify loader → tool flow.
4. Roll out remaining `--help-json` flags one script at a time.
5. Switch the Telegram webhook URL once the new agent is stable; archive `agent-old/` with a note in `ARCHITECTURE.md`.

A detailed implementation plan (task-level, with verification steps) will follow via the writing-plans skill after this spec is approved.
