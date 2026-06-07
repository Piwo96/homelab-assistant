# Agent Instructions

> This file is mirrored across CLAUDE.md, AGENTS.md, and GEMINI.md so the same instructions load in any AI environment. **Keep them identical** — edit one, copy to the other two.

## Project: Rolly

German-speaking Telegram bot ("Rolly") that controls the homelab via a locally hosted LLM. User messages → LM Studio (running on the Gaming PC) → tool calls → Python skill scripts → reply. Deployed as an unprivileged LXC on Proxmox, exposed via DuckDNS + Caddy + Let's Encrypt.

### Repository state (read before editing)

- **`agent/`** — **live** TypeScript/Bun rewrite. This is where new code goes.
- **`agent-old/`** — legacy Python implementation. Do not touch unless explicitly asked; it's kept only for reference.
- **`ARCHITECTURE.md`** — describes the **old Python** agent. Layered model and request flow still match the new design at a conceptual level, but file paths, function names, and Python snippets are stale. Trust `agent/src/` over `ARCHITECTURE.md` when they disagree.
- **`.claude/skills/`** — homelab skills (Python `*_api.py` scripts). Used by both the live and legacy agents.
- **`infra/rolly/`** — Proxmox LXC deployment scripts (Mac-side `deploy.sh` + in-LXC `setup-lxc.sh`).
- **`setup.sh`, `requirements.txt`** — legacy Python tooling for `agent-old/` and the skill scripts. The live agent does not need pip install for itself, but skills still need the Python deps in `requirements.txt`.

### Commands

All run from `agent/`:

```bash
bun install            # one-time
bun run dev            # watch-mode local agent (needs agent/.env)
bun run start          # one-shot
bun test               # full suite (Bun's test runner)
bun test tests/handle-message.test.ts   # single file
bun run typecheck      # tsc --noEmit
```

Deployment (from repo root):

```bash
cd infra/rolly && ./deploy.sh           # idempotent; reuses existing LXC if present
# After first deploy, run the printed setWebhook curl command once.
```

### Live agent architecture (`agent/src/`)

Request path: `Telegram → server.ts → pipeline/handle-message.ts → llm/generate.ts (LM Studio via Vercel AI SDK) → skills/executor.ts → Python *_api.py`.

Key modules:

| File | Role |
|---|---|
| `main.ts` | Bootstrap: load env, open SQLite, load skills, precompute embedding cache, build generator, start server. **Currently hardcodes `loadSkills(skillsRoot, ['homeassistant'])`** — only the `homeassistant` skill is exposed. Widen the allowlist there to enable more skills. |
| `server.ts` | `Bun.serve` HTTP server. Endpoints: `GET /health`, `POST /webhook` (Telegram). Verifies `X-Telegram-Bot-Api-Secret-Token`, deduplicates by `update_id`, sends a "⌛ Ich kümmere mich darum..." placeholder + typing indicator, then `editText`s the real reply in place once the pipeline returns. |
| `pipeline/handle-message.ts` | Core pipeline. Handles `/start` (clears chat history, generates fresh welcome). Pre-flight: if LM Studio is unreachable, triggers WoL via the `wol` skill before proceeding. Routes through semantic router unless `BYPASS_ROUTER=1` (the deployed default — Gemma picks the tool directly with the full catalogue). |
| `pipeline/system-prompt.ts` | German system prompts. `TOOLED_PROMPT` = identity + tool-calling rules + write-operation safety rules (singular vs. plural disambiguation). `SMALLTALK_PROMPT` = fallback when no tools selected. `WELCOME_PROMPT` = `/start` greeting. |
| `router/semantic.ts`, `router/cache.ts` | Embedding-based pre-filter. Assumes L2-normalized embeddings → uses dot product as cosine. Cache key = SHA-256 of all skill metadata; any SKILL.md change invalidates. Stored in `data/agent-embedding-cache.json`. |
| `skills/loader.ts` | At startup, runs each `*_api.py --help-json` to discover commands + arg schemas. Converts argparse-style JSON to Zod schemas via `tools/help-json-to-zod.ts`. Reads SKILL.md frontmatter for `name`, `description`, `triggers`, `intent_hints`. **Skills without scripts in `scripts/` are skipped.** |
| `skills/executor.ts` | Runs a skill command as `python3 <script> --json <command> <positional...> --flag value`. Underscores in arg names become dashes. Boolean args become bare flags. Default timeout 30s. **Use `PYTHON_BIN=...` to point at a venv interpreter (the deployed LXC uses `/opt/rolly/.venv/bin/python`).** |
| `tools/define-skill-tool.ts` | Wraps each loaded command as a Vercel AI SDK `tool({ description, parameters: zodSchema, execute })`. |
| `llm/lm-studio.ts` | `createOpenAICompatible` provider pointing at `${LM_STUDIO_URL}/v1`. `DUMP_LLM_REQUEST=1` writes the outgoing request body to `/tmp/llm-request.json` for debugging. |
| `llm/generate.ts` | Single-call wrapper; `toolChoice: 'auto'` if any tools, else `'none'`. `maxSteps: 5` (multi-turn tool calling). Passes `reasoningEffort` via `experimental_providerMetadata['lm-studio'].reasoning.effort`. |
| `memory/db.ts`, `memory/history.ts` | SQLite (`data/agent.db`, WAL). Tables: `conversations` (per-chat history) and `processed_updates` (webhook dedup). Schema is **new and incompatible** with `agent-old`'s `conversations.db` — do not migrate. |
| `wol/wake.ts` | Shells out to the `wol` skill's Python script to send a Wake-on-LAN packet to the Gaming PC, then polls LM Studio's `/health` until reachable (timeout 150s). |
| `telegram/send.ts`, `telegram/webhook.ts` | Telegram Bot API client (`sendMessage`, `editMessageText`, `sendChatAction`) and update parsing. |

### Skill contract (Python `*_api.py`)

The TypeScript agent only talks to skills via two CLI conventions:

1. **`python3 skill_api.py --help-json`** must print JSON of the form:
   ```json
   { "description": "...", "commands": {
     "start": { "description": "...", "is_write": true,
                "args": [{ "name": "vmid", "type": "int", "required": true, "description": "..." }] }
   }}
   ```
   Supported arg types: `str`, `int`, `float`, `bool`. Optional fields: `choices` (enum), `default`, `nargs` (`+` or `*` for arrays).

2. **`python3 skill_api.py --json <command> [positional...] [--flag value]`** runs the command and prints JSON to stdout. Non-zero exit → tool error surfaced to the LLM.

A skill is "loadable" iff it has `SKILL.md` (with frontmatter) **and** a `scripts/` directory containing at least one `*_api.py`. SKILL.md frontmatter fields used by the loader: `name`, `description`, `triggers`, `intent_hints`.

### Environment (`agent/.env`)

Validated by `config/env.ts` (Zod). Required: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_ALLOWED_USERS` (CSV of numeric IDs), `ADMIN_TELEGRAM_ID`, `LM_STUDIO_URL`, `LM_STUDIO_MODEL`, `INTERNAL_NOTIFY_TOKEN` (≥32 chars). Optional: `EMBEDDING_MODEL` (default `google/embedding-gemma-300m`), `WHISPER_MODEL`, `PORT` (default 8080), `SKILLS_ROOT` (default `.claude/skills`), `DATA_DIR` (default `data`).

Runtime-only flags (not in the schema): `BYPASS_ROUTER=1` (skip semantic router — production default), `PYTHON_BIN` (override `python3`), `DUMP_LLM_REQUEST=1` (write LLM request body to `/tmp/llm-request.json`).

### Conventions

- Bot identity is **Rolly**, replies in German. Don't change the persona prompts in `pipeline/system-prompt.ts` without intent.
- Tests live under `agent/tests/` and run with `bun test`. They use `:memory:` SQLite — no fixtures on disk.
- TS config is strict + `noUncheckedIndexedAccess` + `exactOptionalPropertyTypes`. Conditional property spreads (`...(x !== undefined ? { x } : {})`) are intentional to satisfy `exactOptionalPropertyTypes`.
- Logger (`utils/logger.ts`) is structured JSON to stdout/stderr. Use it, not `console.log`.
- LM Studio runs on the Gaming PC and is woken via WoL on demand; never assume it's reachable — let the pipeline's pre-flight handle it.

## Agent operating principles

This system follows a 3-layer architecture that separates concerns:

**Layer 1: Directives (What to do)**
- Skills define workflows as Markdown SOPs
- Each skill contains: goals, inputs, tools, outputs, edge cases
- Natural language instructions, like you'd give a mid-level developer

**Layer 2: Orchestration (Decision making)**
- This is you. Your job: intelligent routing.
- Read skills, execute tools in the right order, handle errors
- You're the glue between intent and execution

**Layer 3: Execution (Doing the work)**
- Deterministic code and scripts
- API calls, data processing, file operations
- Reliable, testable, fast

**Why this works:** Errors compound. 90% accuracy per step = 59% success over 5 steps. The solution: push complexity into deterministic skills and code. You focus on decision-making.

## Skills

Skills are your instruction set. They live in these locations:

- **Global skills (Claude)**: `~/.claude/skills/` - Available across all projects
- **Global skills (Gemini)**: `~/.gemini/antigravity/skills/` - Available across all projects
- **Project skills**: `.claude/skills/` - Project-specific workflows

### Creating New Skills

When creating a new skill, check if a global `/skill-creator` skill exists and use it. The skill-creator provides structured guidance for authoring skills following best practices.

### Using Skills

1. **Check for skills first**: Before doing a task manually, check if a skill exists
2. **Invoke via slash command**: `/skill-name` or describe the task naturally
3. **Follow the skill**: Read `SKILL.md`, then load additional resources as needed

### Skill Structure

```
skills/
└── skill-name/
    ├── SKILL.md           # Entry point (always read first)
    ├── PATTERNS.md        # Optional: patterns and mappings
    ├── BEST_PRACTICES.md  # Optional: guidelines
    └── scripts/           # Optional: utility scripts
```

## Self-Annealing

### When something breaks:
1. Read error message and stack trace
2. Fix the issue and test again
3. Update the relevant skill with what you learned (API limits, edge cases, better approaches)
4. System is now stronger

**For coding errors:** Use the global skill `/error-handling-patterns` for guidance on robust error handling, retry patterns, circuit breakers, and graceful degradation. This skill covers best practices across TypeScript, Python, Rust, and Go.

### When new functionality is needed:
1. User requests a capability not yet covered by the skill
2. If it fits thematically: extend the existing skill (API endpoints, scripts, documentation)
3. If it doesn't fit: create a new skill using `/skill-creator`
4. Test the new functionality
5. System now handles more scenarios

**Decision guide:** Follow single responsibility principle - each skill should do one thing well. If the new functionality would dilute the skill's focus or conflict with its naming, create a separate skill.

Skills are living documents. When you discover constraints, better approaches, common errors, or **new capabilities**: **update the skill** (ask first unless explicitly told to modify freely).

## Sub-Agents (MANDATORY)

> **⚠️ CRITICAL**: Sub-agents are NOT optional. You MUST spawn them after the specified trigger events. Failure to do so violates the self-annealing principle and degrades system quality over time.

Sub-Agents are specialized background workers that handle specific tasks autonomously. Unlike skills (which are instructions you follow), sub-agents are independent processes you spawn.

### Concept

| Aspect | Skills | Sub-Agents |
|--------|--------|------------|
| What | Instructions (Markdown SOPs) | Autonomous workers |
| How | You read and follow them | You spawn them via Task tool |
| When | Before doing work | After doing work (background) |
| Purpose | Guide your actions | Offload parallel tasks |

### Available Sub-Agents

| Agent | Purpose | Can Edit | Cannot Edit |
|-------|---------|----------|-------------|
| `code-reviewer` | Reviews code quality, security, best practices | Scripts (`.py`, `.sh`, `.ts`...) | Markdown (`.md`) |
| `skill-documenter` | Documents learnings into skill files | Markdown (`.md`) | Scripts |

### Storage Locations

- **Global agents (Claude)**: `~/.claude/agents/` - Available across all projects
- **Global agents (Gemini)**: `~/.gemini/antigravity/agents/` - Available across all projects
- **Project agents**: `.claude/agents/` - Project-specific agents

### Mandatory Triggers

**You MUST spawn sub-agents when these conditions are met. This is not optional.**

```
You complete a task
        │
        ├─► Code written or modified?
        │   └─► MUST spawn: code-reviewer (background)
        │       → Reviews scripts, fixes HIGH/CRITICAL issues
        │
        ├─► Skill created or modified?
        │   └─► MUST spawn: code-reviewer (background)
        │       → Reviews any scripts in the skill
        │
        └─► Error resolved? New pattern discovered? Skill scripts updated?
            └─► MUST spawn: skill-documenter (background)
                → Documents learning in relevant skill MD
```

### Usage

Spawn sub-agents as background tasks using the Task tool:

```
# After writing code - MANDATORY
Task:
  subagent_type: code-reviewer
  run_in_background: true
  prompt: "Review the code I created: [file paths]"

# After script updates (error resolved, new pattern found) - MANDATORY
Task:
  subagent_type: skill-documenter
  run_in_background: true
  prompt: "Document this learning: [what was learned]"
```

### Mandatory Sub-Agent Checklist

Before completing ANY task, verify:

- [ ] **Code written/modified?** → MUST spawn `code-reviewer`
- [ ] **Skill created/modified?** → MUST spawn `code-reviewer` (for scripts) AND `skill-documenter` (for documentation)
- [ ] **Error resolved?** → MUST spawn `skill-documenter`
- [ ] **New pattern/constraint discovered?** → MUST spawn `skill-documenter`

### Trigger Conditions (Reference)

**code-reviewer** - MUST spawn when:
- Any script file created (`.py`, `.sh`, `.ts`, `.js`, etc.)
- Any script file modified
- Bug fix implemented in code
- New skill with scripts created

**skill-documenter** - MUST spawn when:
- Error was encountered and resolved
- API limit or constraint discovered
- Better approach found through trial
- Edge case handled
- New skill created (to ensure documentation quality)
- Existing skill updated with new patterns

## Operating Principles

1. **Skills first**: Before manual work, check `~/.claude/skills/` and `.claude/skills/`
2. **Self-improve on errors**: Fix → Test → Update skill → System is stronger
3. **Prefer determinism**: Complex logic belongs in code/scripts, not ad-hoc decisions
4. **Progressive disclosure**: Load skill resources on-demand, not all upfront

## Summary

You sit between user intent (skills/directives) and deterministic execution (code/scripts). Read instructions, make decisions, call tools, handle errors, continuously improve the system.

Be pragmatic. Be reliable. Self-anneal.
