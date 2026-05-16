# New Agent — MVP Implementation Plan (Plan 1 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Working Telegram bot that routes a German/English text message to the `homeassistant` skill end-to-end via Gemma 4 E4B and returns a reply. No multimodal, no self-annealing, no notifications — just the spine.

**Architecture:** TypeScript + Bun under `agent/`. Vercel AI SDK talks to LM Studio (OpenAI-compatible). Skill metadata is auto-discovered by running `python *_api.py --help-json` once at boot and converted to Zod schemas. A semantic router (cosine over embeddings) narrows to one skill before the LLM ever sees a tool.

**Tech Stack:** Bun, TypeScript, Vercel AI SDK (`ai`, `@ai-sdk/openai-compatible`), Zod, `bun:sqlite`, Bun's built-in `fetch` and test runner. Python skills remain unchanged except for one new flag.

**Spec:** [docs/superpowers/specs/2026-05-16-new-agent-design.md](../specs/2026-05-16-new-agent-design.md)

**Out of scope for this plan (handled by later plans):**
- Skills other than `homeassistant`
- Photo / voice input
- Self-annealing / fix-on-error
- Proactive notifications
- Admin permissions enforcement (only allow-list applied; write/read split deferred to Plan 2)
- Smalltalk redirect path (deferred to Plan 2)

---

## File Structure

```
agent/                              # NEW — all code below is in agent/
├── package.json                    # Bun project, deps
├── tsconfig.json                   # strict TS, target ES2022, module ESNext
├── bun.lock                        # generated
├── src/
│   ├── main.ts                     # entry: load env, init db, start server
│   ├── server.ts                   # Bun.serve routes (/webhook, /health)
│   ├── config/
│   │   └── env.ts                  # Zod-validated process.env loader
│   ├── utils/
│   │   ├── logger.ts               # structured console logger
│   │   └── sha256.ts               # hex digest helper
│   ├── llm/
│   │   ├── lm-studio.ts            # AI SDK provider for LM Studio
│   │   └── embedding.ts            # /v1/embeddings client
│   ├── skills/
│   │   ├── loader.ts               # parse SKILL.md, run --help-json, build registry
│   │   ├── registry.ts             # in-memory skill store with reload
│   │   └── executor.ts             # subprocess runner with timeout + JSON parse
│   ├── tools/
│   │   ├── help-json-to-zod.ts     # converter: help-json → ZodObject
│   │   └── define-skill-tool.ts    # AI SDK tool() wrapper around a command
│   ├── router/
│   │   ├── semantic.ts             # cosine match query embedding vs skills
│   │   └── cache.ts                # SHA256-keyed embedding cache file
│   ├── memory/
│   │   ├── db.ts                   # bun:sqlite + schema migrations
│   │   └── history.ts              # per-chat conversation slice
│   ├── telegram/
│   │   ├── webhook.ts              # signature verify, dedup, parse update
│   │   └── send.ts                 # text reply
│   └── pipeline/
│       ├── system-prompt.ts        # build system prompt for given skill set
│       └── handle-message.ts       # orchestrator: text-only flow
└── tests/
    ├── help-json-to-zod.test.ts
    ├── semantic.test.ts
    ├── cache.test.ts
    ├── history.test.ts
    ├── executor.test.ts
    └── handle-message.test.ts

# Touched outside agent/:
.claude/skills/homeassistant/scripts/skill_helpers.py  # NEW shared helper
.claude/skills/homeassistant/scripts/homeassistant_api.py  # add --help-json
.claude/skills/homeassistant/scripts/dashboard_api.py      # add --help-json
data/                                # created at runtime, .gitignored
└── (conversations.db, embedding_cache.json)
```

---

## Task 1: Bun project setup

**Files:**
- Create: `agent/package.json`
- Create: `agent/tsconfig.json`
- Create: `agent/.gitignore`
- Modify: root `.gitignore` (add `data/`, `agent/node_modules`)

- [ ] **Step 1: Confirm `agent/` does not yet exist**

```bash
ls agent 2>/dev/null && echo "EXISTS — abort" || echo "ok, safe to create"
```

Expected: `ok, safe to create` (current state — `agent-old/` exists, `agent/` does not).

- [ ] **Step 2: Create `agent/package.json`**

```json
{
  "name": "homelab-agent",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "bun --watch src/main.ts",
    "start": "bun src/main.ts",
    "test": "bun test",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "ai": "^4.3.0",
    "@ai-sdk/openai-compatible": "^0.2.0",
    "zod": "^3.24.0",
    "gray-matter": "^4.0.3"
  },
  "devDependencies": {
    "@types/bun": "latest",
    "typescript": "^5.6.0"
  }
}
```

- [ ] **Step 3: Create `agent/tsconfig.json`**

```json
{
  "compilerOptions": {
    "lib": ["ESNext"],
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "types": ["bun-types"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "exactOptionalPropertyTypes": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true
  },
  "include": ["src/**/*", "tests/**/*"]
}
```

- [ ] **Step 4: Create `agent/.gitignore`**

```
node_modules/
*.log
.env
```

- [ ] **Step 5: Update root `.gitignore`**

Add these lines (append; do not remove existing entries):

```
# Runtime data shared by agent
/data/

# Bun
agent/node_modules/
```

- [ ] **Step 6: Install deps + verify typecheck works**

```bash
cd agent && bun install && bun run typecheck
```

Expected: `bun install` succeeds; `tsc --noEmit` exits 0 (no source files yet → no errors).

- [ ] **Step 7: Commit**

```bash
git add agent/package.json agent/tsconfig.json agent/.gitignore agent/bun.lock .gitignore
git commit -m "chore(agent): bootstrap Bun TypeScript project for new agent"
```

---

## Task 2: Env config with Zod

**Files:**
- Create: `agent/src/config/env.ts`
- Create: `agent/.env.example`
- Create: `agent/tests/env.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// agent/tests/env.test.ts
import { describe, it, expect } from 'bun:test';
import { loadEnv } from '../src/config/env';

describe('loadEnv', () => {
  it('parses a valid env object', () => {
    const env = loadEnv({
      TELEGRAM_BOT_TOKEN: 'abc',
      TELEGRAM_WEBHOOK_SECRET: 'secret',
      TELEGRAM_ALLOWED_USERS: '111,222',
      ADMIN_TELEGRAM_ID: '111',
      LM_STUDIO_URL: 'http://localhost:1234',
      LM_STUDIO_MODEL: 'gemma-4-e4b',
      EMBEDDING_MODEL: 'nomic-embed-text-v2-moe',
      WHISPER_MODEL: 'whisper-large-v3-turbo',
      INTERNAL_NOTIFY_TOKEN: 't'.repeat(32),
      PORT: '8080',
      SKILLS_ROOT: '/tmp/skills',
      DATA_DIR: '/tmp/data',
    });
    expect(env.TELEGRAM_ALLOWED_USERS).toEqual([111, 222]);
    expect(env.ADMIN_TELEGRAM_ID).toBe(111);
    expect(env.PORT).toBe(8080);
  });

  it('throws on missing required field', () => {
    expect(() => loadEnv({})).toThrow();
  });

  it('throws on invalid PORT', () => {
    expect(() => loadEnv({
      TELEGRAM_BOT_TOKEN: 'abc', TELEGRAM_WEBHOOK_SECRET: 's',
      TELEGRAM_ALLOWED_USERS: '1', ADMIN_TELEGRAM_ID: '1',
      LM_STUDIO_URL: 'http://x', LM_STUDIO_MODEL: 'm',
      EMBEDDING_MODEL: 'e', WHISPER_MODEL: 'w',
      INTERNAL_NOTIFY_TOKEN: 't'.repeat(32),
      PORT: 'abc', SKILLS_ROOT: '/s', DATA_DIR: '/d',
    })).toThrow(/PORT/);
  });
});
```

- [ ] **Step 2: Run test, verify it fails**

```bash
cd agent && bun test tests/env.test.ts
```

Expected: FAIL — `Cannot find module '../src/config/env'`.

- [ ] **Step 3: Implement `agent/src/config/env.ts`**

```ts
import { z } from 'zod';

const csvNumbers = z.string().transform((s, ctx) => {
  const parts = s.split(',').map(p => p.trim()).filter(Boolean);
  const nums = parts.map(p => Number(p));
  if (nums.some(n => !Number.isFinite(n))) {
    ctx.addIssue({ code: 'custom', message: 'expected comma-separated numbers' });
    return z.NEVER;
  }
  return nums;
});

const envSchema = z.object({
  TELEGRAM_BOT_TOKEN: z.string().min(1),
  TELEGRAM_WEBHOOK_SECRET: z.string().min(1),
  TELEGRAM_ALLOWED_USERS: csvNumbers,
  ADMIN_TELEGRAM_ID: z.coerce.number().int(),
  LM_STUDIO_URL: z.string().url(),
  LM_STUDIO_MODEL: z.string().min(1),
  EMBEDDING_MODEL: z.string().min(1),
  WHISPER_MODEL: z.string().min(1),
  INTERNAL_NOTIFY_TOKEN: z.string().min(32),
  PORT: z.coerce.number().int().positive(),
  SKILLS_ROOT: z.string().min(1),
  DATA_DIR: z.string().min(1),
});

export type Env = z.infer<typeof envSchema>;

export function loadEnv(source: Record<string, string | undefined> = process.env): Env {
  const parsed = envSchema.safeParse(source);
  if (!parsed.success) {
    const issues = parsed.error.issues.map(i => `  ${i.path.join('.')}: ${i.message}`).join('\n');
    throw new Error(`Invalid environment:\n${issues}`);
  }
  return parsed.data;
}
```

- [ ] **Step 4: Create `agent/.env.example`**

```bash
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_ALLOWED_USERS=
ADMIN_TELEGRAM_ID=

LM_STUDIO_URL=http://192.168.178.50:1234
LM_STUDIO_MODEL=gemma-4-e4b
EMBEDDING_MODEL=nomic-embed-text-v2-moe
WHISPER_MODEL=whisper-large-v3-turbo

INTERNAL_NOTIFY_TOKEN=

PORT=8080
SKILLS_ROOT=../.claude/skills
DATA_DIR=../data
```

- [ ] **Step 5: Run test, verify it passes**

```bash
cd agent && bun test tests/env.test.ts
```

Expected: 3 passing.

- [ ] **Step 6: Commit**

```bash
git add agent/src/config/env.ts agent/tests/env.test.ts agent/.env.example
git commit -m "feat(agent): zod-validated env loader"
```

---

## Task 3: SHA256 helper + structured logger

**Files:**
- Create: `agent/src/utils/sha256.ts`
- Create: `agent/src/utils/logger.ts`
- Create: `agent/tests/sha256.test.ts`

- [ ] **Step 1: Write test for sha256**

```ts
// agent/tests/sha256.test.ts
import { describe, it, expect } from 'bun:test';
import { sha256Hex } from '../src/utils/sha256';

describe('sha256Hex', () => {
  it('returns 64-char hex digest', async () => {
    const d = await sha256Hex('hello');
    expect(d).toMatch(/^[0-9a-f]{64}$/);
    expect(d).toBe('2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824');
  });

  it('is deterministic', async () => {
    const a = await sha256Hex('x');
    const b = await sha256Hex('x');
    expect(a).toBe(b);
  });
});
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd agent && bun test tests/sha256.test.ts
```

Expected: FAIL.

- [ ] **Step 3: Implement `agent/src/utils/sha256.ts`**

```ts
const enc = new TextEncoder();

export async function sha256Hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', enc.encode(input));
  return Array.from(new Uint8Array(buf))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}
```

- [ ] **Step 4: Implement `agent/src/utils/logger.ts`** (no test — trivial wrapper)

```ts
type Level = 'debug' | 'info' | 'warn' | 'error';

function emit(level: Level, msg: string, meta?: Record<string, unknown>) {
  const line = JSON.stringify({ ts: new Date().toISOString(), level, msg, ...meta });
  if (level === 'error' || level === 'warn') console.error(line);
  else console.log(line);
}

export const log = {
  debug: (msg: string, meta?: Record<string, unknown>) => emit('debug', msg, meta),
  info: (msg: string, meta?: Record<string, unknown>) => emit('info', msg, meta),
  warn: (msg: string, meta?: Record<string, unknown>) => emit('warn', msg, meta),
  error: (msg: string, meta?: Record<string, unknown>) => emit('error', msg, meta),
};
```

- [ ] **Step 5: Verify test passes**

```bash
cd agent && bun test tests/sha256.test.ts
```

Expected: 2 passing.

- [ ] **Step 6: Commit**

```bash
git add agent/src/utils/ agent/tests/sha256.test.ts
git commit -m "feat(agent): sha256 helper + structured logger"
```

---

## Task 4: SQLite database + history table

**Files:**
- Create: `agent/src/memory/db.ts`
- Create: `agent/src/memory/history.ts`
- Create: `agent/tests/history.test.ts`

- [ ] **Step 1: Write history test (DB schema implied)**

```ts
// agent/tests/history.test.ts
import { describe, it, expect, beforeEach } from 'bun:test';
import { Database } from 'bun:sqlite';
import { initDb } from '../src/memory/db';
import { appendMessage, recentMessages } from '../src/memory/history';

let db: Database;

beforeEach(() => {
  db = new Database(':memory:');
  initDb(db);
});

describe('history', () => {
  it('round-trips text user/assistant messages', () => {
    appendMessage(db, { chatId: 1, role: 'user', content: { text: 'hi' }, ts: 100 });
    appendMessage(db, { chatId: 1, role: 'assistant', content: { text: 'hello' }, ts: 101 });
    const msgs = recentMessages(db, 1, 10);
    expect(msgs).toHaveLength(2);
    expect(msgs[0]?.role).toBe('user');
    expect(msgs[1]?.content.text).toBe('hello');
  });

  it('orders by ts ASC and limits', () => {
    for (let i = 0; i < 5; i++) {
      appendMessage(db, { chatId: 1, role: 'user', content: { text: `m${i}` }, ts: i });
    }
    const msgs = recentMessages(db, 1, 3);
    expect(msgs.map(m => m.content.text)).toEqual(['m2', 'm3', 'm4']);
  });

  it('isolates by chatId', () => {
    appendMessage(db, { chatId: 1, role: 'user', content: { text: 'a' }, ts: 1 });
    appendMessage(db, { chatId: 2, role: 'user', content: { text: 'b' }, ts: 2 });
    expect(recentMessages(db, 1, 10)).toHaveLength(1);
    expect(recentMessages(db, 2, 10)).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd agent && bun test tests/history.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `agent/src/memory/db.ts`**

```ts
import { Database } from 'bun:sqlite';

export function initDb(db: Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS conversations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chat_id INTEGER NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      intent TEXT,
      success INTEGER,
      ts INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_chat_ts ON conversations (chat_id, ts ASC);

    CREATE TABLE IF NOT EXISTS processed_updates (
      update_id INTEGER PRIMARY KEY,
      ts INTEGER NOT NULL
    );
  `);
}

export function openDb(path: string): Database {
  const db = new Database(path);
  db.exec('PRAGMA journal_mode = WAL;');
  initDb(db);
  return db;
}
```

- [ ] **Step 4: Implement `agent/src/memory/history.ts`**

```ts
import type { Database } from 'bun:sqlite';

export type MessageRole = 'user' | 'assistant' | 'tool';

export interface MessageContent {
  text?: string;
  toolCall?: { name: string; args: unknown };
  toolResult?: { name: string; result: unknown };
}

export interface Message {
  chatId: number;
  role: MessageRole;
  content: MessageContent;
  intent?: string;
  success?: boolean;
  ts: number;
}

export function appendMessage(db: Database, msg: Message): void {
  db.prepare(
    `INSERT INTO conversations (chat_id, role, content, intent, success, ts)
     VALUES (?, ?, ?, ?, ?, ?)`,
  ).run(
    msg.chatId,
    msg.role,
    JSON.stringify(msg.content),
    msg.intent ?? null,
    msg.success === undefined ? null : msg.success ? 1 : 0,
    msg.ts,
  );
}

export function recentMessages(db: Database, chatId: number, limit: number): Message[] {
  const rows = db.prepare(
    `SELECT chat_id, role, content, intent, success, ts FROM conversations
     WHERE chat_id = ?
     ORDER BY ts ASC
     LIMIT ? OFFSET MAX(0, (SELECT COUNT(*) FROM conversations WHERE chat_id = ?) - ?)`,
  ).all(chatId, limit, chatId, limit) as Array<{
    chat_id: number; role: MessageRole; content: string;
    intent: string | null; success: number | null; ts: number;
  }>;
  return rows.map(r => ({
    chatId: r.chat_id,
    role: r.role,
    content: JSON.parse(r.content) as MessageContent,
    ...(r.intent !== null ? { intent: r.intent } : {}),
    ...(r.success !== null ? { success: r.success === 1 } : {}),
    ts: r.ts,
  }));
}
```

- [ ] **Step 5: Verify tests pass**

```bash
cd agent && bun test tests/history.test.ts
```

Expected: 3 passing.

- [ ] **Step 6: Commit**

```bash
git add agent/src/memory/ agent/tests/history.test.ts
git commit -m "feat(agent): SQLite db schema + per-chat history CRUD"
```

---

## Task 5: Add `--help-json` to skill_helpers + homeassistant scripts

**Files:**
- Create: `.claude/skills/homeassistant/scripts/skill_helpers.py`
- Modify: `.claude/skills/homeassistant/scripts/homeassistant_api.py` (add 3 lines in main)
- Modify: `.claude/skills/homeassistant/scripts/dashboard_api.py` (add 3 lines in main)

- [ ] **Step 1: Create the shared helper**

```python
# .claude/skills/homeassistant/scripts/skill_helpers.py
"""Shared helpers for skill *_api.py scripts.

Currently provides --help-json introspection so the TypeScript agent loader
can derive Zod schemas from argparse subparsers without parsing --help text.

Convention:
- Every script adds: parser.add_argument("--help-json", action="store_true")
- Subparsers that mutate state set: subparser.set_defaults(_is_write=True)
- main() checks args.help_json and calls emit_help_json(parser) before normal dispatch.
"""

import argparse
import json
import sys
from typing import Any


def _arg_to_dict(action: argparse.Action) -> dict[str, Any]:
    py_type = getattr(action, "type", None)
    type_name = "str"
    if py_type is int:
        type_name = "int"
    elif py_type is float:
        type_name = "float"
    elif py_type is bool:
        type_name = "bool"
    if isinstance(action, argparse._StoreTrueAction) or isinstance(action, argparse._StoreFalseAction):
        type_name = "bool"
    name = action.dest
    is_flag = bool(action.option_strings)
    required = action.required if is_flag else (action.default is None and action.nargs is None)
    out: dict[str, Any] = {
        "name": name,
        "type": type_name,
        "required": required,
        "description": action.help or "",
    }
    if action.choices is not None:
        out["choices"] = list(action.choices)
    if action.default is not argparse.SUPPRESS and action.default is not None:
        out["default"] = action.default
    if action.nargs in ("+", "*"):
        out["nargs"] = action.nargs
    return out


def emit_help_json(parser: argparse.ArgumentParser) -> None:
    """Walk subparsers and emit a JSON description of all commands to stdout."""
    commands: dict[str, Any] = {}
    subparsers_action = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subparsers_action = action
            break
    if subparsers_action is None:
        json.dump({"description": parser.description or "", "commands": {}}, sys.stdout)
        sys.stdout.write("\n")
        return
    for cmd_name, sub in subparsers_action.choices.items():
        defaults = getattr(sub, "_defaults", {})
        is_write = bool(defaults.get("_is_write", False))
        args = []
        for action in sub._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            if action.dest == "help_json":
                continue
            if action.dest.startswith("_"):
                continue
            args.append(_arg_to_dict(action))
        commands[cmd_name] = {
            "description": (subparsers_action.choices[cmd_name].description
                            or subparsers_action._choices_actions[
                                list(subparsers_action.choices.keys()).index(cmd_name)
                            ].help
                            or ""),
            "is_write": is_write,
            "args": args,
        }
    payload = {"description": parser.description or "", "commands": commands}
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
```

- [ ] **Step 2: Modify `homeassistant_api.py` — add the helper hookup**

Locate the existing `def main():` in `.claude/skills/homeassistant/scripts/homeassistant_api.py`. Find the line that currently looks like:

```python
    parser.add_argument("--json", action="store_true", help="Output as JSON")
```

Insert immediately AFTER that line:

```python
    parser.add_argument("--help-json", action="store_true", help="Print JSON command spec and exit")
```

Mark write-actions. After each of the following `add_parser` calls (e.g., `turn_on = subparsers.add_parser("turn-on", ...)`), append a line `subparser_var.set_defaults(_is_write=True)` for these commands: `turn-on`, `turn-off`, `toggle`, `call-service`, `trigger`, `enable`, `disable`. Example:

```python
    turn_on = subparsers.add_parser("turn-on", help="Turn on entity")
    turn_on.add_argument("entity_id", help="Entity ID")
    turn_on.add_argument("--brightness", type=int, help="Brightness (0-255)")
    turn_on.add_argument("--color-temp", type=int, help="Color temperature (mireds)")
    turn_on.set_defaults(_is_write=True)
```

Find the `args = parser.parse_args()` line and insert IMMEDIATELY after it:

```python
    if getattr(args, "help_json", False):
        from skill_helpers import emit_help_json
        emit_help_json(parser)
        return
```

(If the file structure puts `parse_args()` inside an `if __name__ == "__main__":` block, the insertion point is the same — right after parsing.)

- [ ] **Step 3: Modify `dashboard_api.py` analogously**

Same three changes:

1. After any `parser.add_argument("--json", ...)` line, add:
   ```python
   parser.add_argument("--help-json", action="store_true", help="Print JSON command spec and exit")
   ```
2. For `set` (the dashboard-mutating action), add `set_parser.set_defaults(_is_write=True)`.
3. After `args = parser.parse_args()`, add the same `if getattr(args, "help_json", ...)` block as above.

- [ ] **Step 4: Smoke test the help-json output**

```bash
cd .claude/skills/homeassistant/scripts && python homeassistant_api.py --help-json | python -m json.tool | head -40
```

Expected: pretty-printed JSON with `description`, `commands.status`, `commands.turn-on.args[0].name = "entity_id"`, `commands.turn-on.is_write = true`. No exception.

```bash
python dashboard_api.py --help-json | python -m json.tool
```

Expected: JSON with `commands.get` (read) and `commands.set` (with `is_write: true`).

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/homeassistant/scripts/skill_helpers.py \
        .claude/skills/homeassistant/scripts/homeassistant_api.py \
        .claude/skills/homeassistant/scripts/dashboard_api.py
git commit -m "feat(skills/homeassistant): add --help-json introspection for new agent loader"
```

---

## Task 6: help-json → Zod converter

**Files:**
- Create: `agent/src/tools/help-json-to-zod.ts`
- Create: `agent/tests/help-json-to-zod.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// agent/tests/help-json-to-zod.test.ts
import { describe, it, expect } from 'bun:test';
import { z } from 'zod';
import { commandToZod, type HelpJsonCommand } from '../src/tools/help-json-to-zod';

describe('commandToZod', () => {
  it('builds schema for required positional + optional flag', () => {
    const cmd: HelpJsonCommand = {
      description: 'Turn on entity',
      is_write: true,
      args: [
        { name: 'entity_id', type: 'str', required: true, description: 'Entity ID' },
        { name: 'brightness', type: 'int', required: false, description: 'Brightness 0-255' },
      ],
    };
    const schema = commandToZod(cmd);
    expect(schema.parse({ entity_id: 'light.kitchen' })).toEqual({ entity_id: 'light.kitchen' });
    expect(schema.parse({ entity_id: 'light.kitchen', brightness: 180 }))
      .toEqual({ entity_id: 'light.kitchen', brightness: 180 });
    expect(() => schema.parse({})).toThrow();
    expect(() => schema.parse({ entity_id: 'x', brightness: 'not-a-number' })).toThrow();
  });

  it('handles enum (choices)', () => {
    const cmd: HelpJsonCommand = {
      description: 'Set mode',
      is_write: true,
      args: [{ name: 'mode', type: 'str', required: true, description: '', choices: ['on', 'off', 'auto'] }],
    };
    const schema = commandToZod(cmd);
    expect(() => schema.parse({ mode: 'on' })).not.toThrow();
    expect(() => schema.parse({ mode: 'invalid' })).toThrow();
  });

  it('applies default when arg not provided', () => {
    const cmd: HelpJsonCommand = {
      description: 'List with limit',
      is_write: false,
      args: [{ name: 'limit', type: 'int', required: false, description: '', default: 10 }],
    };
    const schema = commandToZod(cmd);
    expect(schema.parse({}).limit).toBe(10);
  });

  it('handles boolean flags', () => {
    const cmd: HelpJsonCommand = {
      description: 'Verbose',
      is_write: false,
      args: [{ name: 'verbose', type: 'bool', required: false, description: '' }],
    };
    const schema = commandToZod(cmd);
    expect(schema.parse({ verbose: true }).verbose).toBe(true);
    expect(schema.parse({}).verbose).toBeUndefined();
  });

  it('handles nargs="+" as array', () => {
    const cmd: HelpJsonCommand = {
      description: 'Multi',
      is_write: false,
      args: [{ name: 'ids', type: 'str', required: true, description: '', nargs: '+' }],
    };
    const schema = commandToZod(cmd);
    expect(schema.parse({ ids: ['a', 'b'] }).ids).toEqual(['a', 'b']);
    expect(() => schema.parse({ ids: 'a' })).toThrow();
  });
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd agent && bun test tests/help-json-to-zod.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement converter**

```ts
// agent/src/tools/help-json-to-zod.ts
import { z, type ZodTypeAny, type ZodObject } from 'zod';

export interface HelpJsonArg {
  name: string;
  type: 'str' | 'int' | 'float' | 'bool';
  required: boolean;
  description: string;
  choices?: Array<string | number>;
  default?: unknown;
  nargs?: '+' | '*';
}

export interface HelpJsonCommand {
  description: string;
  is_write: boolean;
  args: HelpJsonArg[];
}

export interface HelpJsonScript {
  description: string;
  commands: Record<string, HelpJsonCommand>;
}

function baseSchema(arg: HelpJsonArg): ZodTypeAny {
  if (arg.choices && arg.choices.length > 0) {
    if (typeof arg.choices[0] === 'number') {
      return z.union(arg.choices.map(c => z.literal(c)) as [ZodTypeAny, ZodTypeAny, ...ZodTypeAny[]]);
    }
    return z.enum(arg.choices as [string, ...string[]]);
  }
  switch (arg.type) {
    case 'int': return z.number().int();
    case 'float': return z.number();
    case 'bool': return z.boolean();
    case 'str': default: return z.string();
  }
}

export function argToZod(arg: HelpJsonArg): ZodTypeAny {
  let schema: ZodTypeAny = baseSchema(arg);
  if (arg.nargs === '+' || arg.nargs === '*') {
    schema = arg.nargs === '+' ? z.array(schema).min(1) : z.array(schema);
  }
  if (arg.description) schema = schema.describe(arg.description);
  if (arg.default !== undefined) schema = schema.default(arg.default as never);
  if (!arg.required) schema = schema.optional();
  return schema;
}

export function commandToZod(cmd: HelpJsonCommand): ZodObject<Record<string, ZodTypeAny>> {
  const shape: Record<string, ZodTypeAny> = {};
  for (const arg of cmd.args) {
    shape[arg.name] = argToZod(arg);
  }
  return z.object(shape);
}
```

- [ ] **Step 4: Verify tests pass**

```bash
cd agent && bun test tests/help-json-to-zod.test.ts
```

Expected: 5 passing.

- [ ] **Step 5: Commit**

```bash
git add agent/src/tools/help-json-to-zod.ts agent/tests/help-json-to-zod.test.ts
git commit -m "feat(agent): convert skill --help-json output to Zod schemas"
```

---

## Task 7: Skill loader + registry

**Files:**
- Create: `agent/src/skills/loader.ts`
- Create: `agent/src/skills/registry.ts`
- Create: `agent/tests/loader.test.ts`

The loader scans a directory of skills, parses each `SKILL.md` frontmatter, runs `python <script> --help-json` for every `*_api.py` it finds, and returns `LoadedSkill` records.

- [ ] **Step 1: Write integration test against real homeassistant skill**

```ts
// agent/tests/loader.test.ts
import { describe, it, expect } from 'bun:test';
import { loadSkills } from '../src/skills/loader';
import { resolve } from 'node:path';

const SKILLS_ROOT = resolve(import.meta.dir, '../../.claude/skills');

describe('loadSkills', () => {
  it('loads homeassistant skill with both scripts', async () => {
    const skills = await loadSkills(SKILLS_ROOT, ['homeassistant']);
    expect(skills).toHaveLength(1);
    const ha = skills[0]!;
    expect(ha.id).toBe('homeassistant');
    expect(ha.description).toContain('Smart Home');
    expect(ha.tools.length).toBeGreaterThan(5);
    const turnOn = ha.tools.find(t => t.name === 'homeassistant__turn-on');
    expect(turnOn).toBeDefined();
    expect(turnOn?.isWrite).toBe(true);
    expect(turnOn?.scriptPath).toMatch(/homeassistant_api\.py$/);
    const dashboardGet = ha.tools.find(t => t.name === 'dashboard__get');
    expect(dashboardGet).toBeDefined();
    expect(dashboardGet?.isWrite).toBe(false);
  });

  it('skips skills with no *_api.py scripts', async () => {
    const skills = await loadSkills(SKILLS_ROOT, ['homelab']);
    expect(skills).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd agent && bun test tests/loader.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement loader**

```ts
// agent/src/skills/loader.ts
import { readdir, readFile, stat } from 'node:fs/promises';
import { join, basename } from 'node:path';
import matter from 'gray-matter';
import { commandToZod, type HelpJsonScript } from '../tools/help-json-to-zod';
import type { ZodObject, ZodTypeAny } from 'zod';
import { log } from '../utils/logger';

export interface SkillTool {
  name: string;                    // e.g. "homeassistant__turn-on"
  scriptPath: string;
  command: string;                 // e.g. "turn-on"
  description: string;
  schema: ZodObject<Record<string, ZodTypeAny>>;
  isWrite: boolean;
}

export interface LoadedSkill {
  id: string;
  description: string;
  triggers: string[];
  intentHints: string[];
  scriptPaths: string[];
  tools: SkillTool[];
}

interface Frontmatter {
  name?: string;
  description?: string;
  triggers?: string[];
  intent_hints?: string[];
}

async function listScriptFiles(dir: string): Promise<string[]> {
  try {
    const entries = await readdir(dir);
    return entries
      .filter(e => e.endsWith('_api.py'))
      .map(e => join(dir, e))
      .sort();
  } catch {
    return [];
  }
}

async function fetchHelpJson(scriptPath: string): Promise<HelpJsonScript> {
  const proc = Bun.spawn({
    cmd: ['python', scriptPath, '--help-json'],
    stdout: 'pipe', stderr: 'pipe',
    cwd: scriptPath.substring(0, scriptPath.lastIndexOf('/')),
  });
  const [stdout, stderr, code] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  if (code !== 0) {
    throw new Error(`--help-json failed (exit ${code}) for ${scriptPath}: ${stderr}`);
  }
  return JSON.parse(stdout) as HelpJsonScript;
}

function scriptStem(scriptPath: string): string {
  return basename(scriptPath).replace(/_api\.py$/, '');
}

export async function loadSkills(skillsRoot: string, only?: string[]): Promise<LoadedSkill[]> {
  const entries = await readdir(skillsRoot);
  const result: LoadedSkill[] = [];
  for (const name of entries) {
    if (only && !only.includes(name)) continue;
    const skillDir = join(skillsRoot, name);
    const skillMdPath = join(skillDir, 'SKILL.md');
    let frontmatter: Frontmatter = {};
    try {
      const md = await readFile(skillMdPath, 'utf8');
      frontmatter = matter(md).data as Frontmatter;
    } catch {
      continue; // not a skill dir
    }
    const scriptDir = join(skillDir, 'scripts');
    try { await stat(scriptDir); } catch { continue; }
    const scriptPaths = await listScriptFiles(scriptDir);
    if (scriptPaths.length === 0) continue;

    const tools: SkillTool[] = [];
    for (const scriptPath of scriptPaths) {
      let helpJson: HelpJsonScript;
      try {
        helpJson = await fetchHelpJson(scriptPath);
      } catch (err) {
        log.warn('skill_load_help_json_failed', { scriptPath, err: String(err) });
        continue;
      }
      const stem = scriptStem(scriptPath);
      for (const [cmdName, cmd] of Object.entries(helpJson.commands)) {
        tools.push({
          name: `${stem}__${cmdName}`,
          scriptPath,
          command: cmdName,
          description: cmd.description || cmdName,
          schema: commandToZod(cmd),
          isWrite: cmd.is_write,
        });
      }
    }

    result.push({
      id: frontmatter.name ?? name,
      description: frontmatter.description ?? '',
      triggers: frontmatter.triggers ?? [],
      intentHints: frontmatter.intent_hints ?? [],
      scriptPaths,
      tools,
    });
  }
  return result;
}
```

- [ ] **Step 4: Implement registry**

```ts
// agent/src/skills/registry.ts
import type { LoadedSkill, SkillTool } from './loader';

export class SkillRegistry {
  private skills: LoadedSkill[] = [];

  replaceAll(skills: LoadedSkill[]): void {
    this.skills = skills;
  }

  all(): LoadedSkill[] {
    return [...this.skills];
  }

  byId(id: string): LoadedSkill | undefined {
    return this.skills.find(s => s.id === id);
  }

  toolsForSkillIds(ids: string[]): SkillTool[] {
    return this.skills
      .filter(s => ids.includes(s.id))
      .flatMap(s => s.tools);
  }
}
```

- [ ] **Step 5: Run loader test**

```bash
cd agent && bun test tests/loader.test.ts
```

Expected: 2 passing.

- [ ] **Step 6: Commit**

```bash
git add agent/src/skills/loader.ts agent/src/skills/registry.ts agent/tests/loader.test.ts
git commit -m "feat(agent): skill loader + in-memory registry"
```

---

## Task 8: Subprocess executor

**Files:**
- Create: `agent/src/skills/executor.ts`
- Create: `agent/tests/executor.test.ts`

- [ ] **Step 1: Write tests**

```ts
// agent/tests/executor.test.ts
import { describe, it, expect } from 'bun:test';
import { runSkillCommand } from '../src/skills/executor';
import { writeFileSync, chmodSync, mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

function makeFakeScript(body: string): string {
  const dir = mkdtempSync(join(tmpdir(), 'exec-'));
  const p = join(dir, 'fake_api.py');
  writeFileSync(p, `#!/usr/bin/env python3\nimport sys, json\n${body}\n`);
  chmodSync(p, 0o755);
  return p;
}

describe('runSkillCommand', () => {
  it('parses JSON stdout from a successful command', async () => {
    const script = makeFakeScript(`print(json.dumps({"ok": True, "value": 42}))`);
    const out = await runSkillCommand(script, 'noop', {});
    expect(out.success).toBe(true);
    expect(out.data).toEqual({ ok: true, value: 42 });
  });

  it('returns error when subprocess exits non-zero', async () => {
    const script = makeFakeScript(`print("fail", file=sys.stderr); sys.exit(2)`);
    const out = await runSkillCommand(script, 'broken', {});
    expect(out.success).toBe(false);
    expect(out.exitCode).toBe(2);
    expect(out.stderr).toContain('fail');
  });

  it('passes positional + flag args correctly', async () => {
    const script = makeFakeScript(
      `import argparse; p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd"); ` +
      `t=sub.add_parser("t"); t.add_argument("entity_id"); t.add_argument("--brightness", type=int); ` +
      `p.add_argument("--json", action="store_true"); a=p.parse_args(); ` +
      `print(json.dumps({"entity_id": a.entity_id, "brightness": a.brightness}))`,
    );
    const out = await runSkillCommand(
      script,
      't',
      { entity_id: 'light.kitchen', brightness: 200 },
      {},
      ['entity_id'],
    );
    expect(out.success).toBe(true);
    expect(out.data).toEqual({ entity_id: 'light.kitchen', brightness: 200 });
  });

  it('times out long-running subprocesses', async () => {
    const script = makeFakeScript(`import time; time.sleep(60)`);
    const out = await runSkillCommand(script, 'sleep', {}, { timeoutMs: 200 });
    expect(out.success).toBe(false);
    expect(out.timedOut).toBe(true);
  });
});
```

- [ ] **Step 2: Run, expect failure**

```bash
cd agent && bun test tests/executor.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement executor**

```ts
// agent/src/skills/executor.ts
export interface ExecResult {
  success: boolean;
  data?: unknown;
  stdout: string;
  stderr: string;
  exitCode: number;
  timedOut?: boolean;
}

export interface ExecOptions {
  timeoutMs?: number;
}

function argsToFlags(args: Record<string, unknown>): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(args)) {
    if (v === undefined || v === null) continue;
    // Heuristic: positional args have no leading underscore in argparse-friendly names
    // and are required; we can't reliably distinguish here, so treat snake_case keys
    // without a known flag prefix as flags. Convention: argparse positionals were
    // declared as plain `add_argument("entity_id")` — argparse will complain if we
    // pass them as --entity-id. We always pass them as the bare value first if their
    // key matches what the caller intended. For the agent, the commandToZod schema
    // maps everything to a flat object; we forward in declaration order if available.
    // To keep this simple and match argparse: pass each k as `--k` (replacing _ with -).
    // Positional args supplied this way will fail; the executor relies on caller
    // ordering positionals first via the special key ordering convention below.
    const flag = `--${k.replace(/_/g, '-')}`;
    if (typeof v === 'boolean') {
      if (v) out.push(flag);
    } else if (Array.isArray(v)) {
      out.push(flag, ...v.map(String));
    } else {
      out.push(flag, String(v));
    }
  }
  return out;
}

// Positional args — passed as bare values BEFORE flags. Convention: keys whose
// names appear in the `positionalArgs` list are emitted positionally.
function buildArgv(
  command: string,
  args: Record<string, unknown>,
  positionalArgs: string[] = [],
): string[] {
  const positional: string[] = [];
  const remaining: Record<string, unknown> = { ...args };
  for (const name of positionalArgs) {
    if (name in remaining) {
      const v = remaining[name];
      if (v !== undefined && v !== null) positional.push(String(v));
      delete remaining[name];
    }
  }
  return [command, ...positional, ...argsToFlags(remaining), '--json'];
}

export async function runSkillCommand(
  scriptPath: string,
  command: string,
  args: Record<string, unknown>,
  options: ExecOptions = {},
  positionalArgs: string[] = [],
): Promise<ExecResult> {
  const timeoutMs = options.timeoutMs ?? 30_000;
  const argv = buildArgv(command, args, positionalArgs);
  const proc = Bun.spawn({
    cmd: ['python', scriptPath, ...argv],
    stdout: 'pipe', stderr: 'pipe',
  });
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; proc.kill('SIGKILL'); }, timeoutMs);
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  clearTimeout(timer);
  if (timedOut) {
    return { success: false, stdout, stderr, exitCode: -1, timedOut: true };
  }
  if (exitCode !== 0) {
    return { success: false, stdout, stderr, exitCode };
  }
  let data: unknown = undefined;
  if (stdout.trim()) {
    try { data = JSON.parse(stdout); } catch { data = stdout; }
  }
  return { success: true, data, stdout, stderr, exitCode };
}
```

- [ ] **Step 4: Run tests**

```bash
cd agent && bun test tests/executor.test.ts
```

Expected: 4 passing.

- [ ] **Step 5: Commit**

```bash
git add agent/src/skills/executor.ts agent/tests/executor.test.ts
git commit -m "feat(agent): subprocess executor for python skill scripts"
```

---

## Task 9: AI SDK tool wrapper

**Files:**
- Create: `agent/src/tools/define-skill-tool.ts`
- Create: `agent/tests/define-skill-tool.test.ts`

A `SkillTool` from the loader is wrapped into a Vercel AI SDK `tool()` that calls the executor. Tracks positional vs flag args by inspecting the Zod schema's first key (convention: positionals declared first in argparse map to first keys in Zod object).

- [ ] **Step 1: Write the tests**

```ts
// agent/tests/define-skill-tool.test.ts
import { describe, it, expect } from 'bun:test';
import { z } from 'zod';
import { defineSkillTool } from '../src/tools/define-skill-tool';
import type { SkillTool } from '../src/skills/loader';
import { writeFileSync, chmodSync, mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

function makeEchoScript(): string {
  const dir = mkdtempSync(join(tmpdir(), 'echo-'));
  const p = join(dir, 'echo_api.py');
  writeFileSync(p, `#!/usr/bin/env python3
import argparse, json, sys
p = argparse.ArgumentParser()
p.add_argument("--json", action="store_true")
sub = p.add_subparsers(dest="cmd")
t = sub.add_parser("turn-on"); t.add_argument("entity_id"); t.add_argument("--brightness", type=int)
a = p.parse_args()
print(json.dumps({"called": a.cmd, "id": a.entity_id, "b": a.brightness}))
`);
  chmodSync(p, 0o755);
  return p;
}

describe('defineSkillTool', () => {
  it('rejects invalid args via Zod before exec', async () => {
    const skillTool: SkillTool = {
      name: 'echo__turn-on',
      scriptPath: makeEchoScript(),
      command: 'turn-on',
      description: 'turn on',
      schema: z.object({ entity_id: z.string(), brightness: z.number().int().optional() }),
      isWrite: true,
    };
    const tool = defineSkillTool(skillTool, { positionalArgs: ['entity_id'] });
    await expect(tool.execute({ brightness: 100 } as never, {} as never)).rejects.toThrow();
  });

  it('runs subprocess and returns parsed JSON on valid args', async () => {
    const skillTool: SkillTool = {
      name: 'echo__turn-on',
      scriptPath: makeEchoScript(),
      command: 'turn-on',
      description: 'turn on',
      schema: z.object({ entity_id: z.string(), brightness: z.number().int().optional() }),
      isWrite: true,
    };
    const tool = defineSkillTool(skillTool, { positionalArgs: ['entity_id'] });
    const result = await tool.execute({ entity_id: 'light.kitchen', brightness: 200 } as never, {} as never);
    expect(result).toEqual({ called: 'turn-on', id: 'light.kitchen', b: 200 });
  });
});
```

- [ ] **Step 2: Run, expect failure**

```bash
cd agent && bun test tests/define-skill-tool.test.ts
```

Expected: FAIL.

- [ ] **Step 3: Implement wrapper**

```ts
// agent/src/tools/define-skill-tool.ts
import { tool, type Tool } from 'ai';
import type { SkillTool } from '../skills/loader';
import { runSkillCommand } from '../skills/executor';
import { log } from '../utils/logger';

export interface DefineOptions {
  positionalArgs?: string[];
  timeoutMs?: number;
}

export function defineSkillTool(skillTool: SkillTool, opts: DefineOptions = {}): Tool {
  return tool({
    description: skillTool.description,
    parameters: skillTool.schema,
    execute: async (args) => {
      // args is already Zod-validated by AI SDK before reaching here.
      const result = await runSkillCommand(
        skillTool.scriptPath,
        skillTool.command,
        args as Record<string, unknown>,
        { ...(opts.timeoutMs !== undefined ? { timeoutMs: opts.timeoutMs } : {}) },
        opts.positionalArgs ?? [],
      );
      if (!result.success) {
        log.warn('skill_tool_failed', { tool: skillTool.name, exitCode: result.exitCode, stderr: result.stderr });
        throw new Error(
          `Skill ${skillTool.name} failed (exit ${result.exitCode})${result.timedOut ? ' [timeout]' : ''}: ${result.stderr.trim() || 'unknown'}`,
        );
      }
      return result.data ?? { ok: true };
    },
  });
}

/**
 * Build a Zod-shape-aware positionalArgs hint.
 * Convention: argparse positional args are declared first; we approximate by
 * treating REQUIRED keys (no .optional()) as positionals.
 */
export function inferPositionals(skillTool: SkillTool): string[] {
  const shape = skillTool.schema.shape;
  const required: string[] = [];
  for (const [key, val] of Object.entries(shape)) {
    if (!val.isOptional()) required.push(key);
  }
  return required;
}
```

- [ ] **Step 4: Verify tests pass**

```bash
cd agent && bun test tests/define-skill-tool.test.ts
```

Expected: 2 passing.

- [ ] **Step 5: Commit**

```bash
git add agent/src/tools/define-skill-tool.ts agent/tests/define-skill-tool.test.ts
git commit -m "feat(agent): AI SDK tool wrapper around skill executor"
```

---

## Task 10: LM Studio embedding client + cosine router

**Files:**
- Create: `agent/src/llm/embedding.ts`
- Create: `agent/src/router/semantic.ts`
- Create: `agent/src/router/cache.ts`
- Create: `agent/tests/semantic.test.ts`
- Create: `agent/tests/cache.test.ts`

- [ ] **Step 1: Write embedding cache test**

```ts
// agent/tests/cache.test.ts
import { describe, it, expect } from 'bun:test';
import { computeCacheKey, type CacheableSkill } from '../src/router/cache';

const skills: CacheableSkill[] = [
  { id: 'a', description: 'A', triggers: ['x', 'y'], intentHints: ['hint'], commandDescriptions: ['c1', 'c2'] },
];

describe('computeCacheKey', () => {
  it('is stable across runs', async () => {
    const k1 = await computeCacheKey('model', skills);
    const k2 = await computeCacheKey('model', skills);
    expect(k1).toBe(k2);
  });

  it('changes when description changes', async () => {
    const k1 = await computeCacheKey('model', skills);
    const k2 = await computeCacheKey('model', [{ ...skills[0]!, description: 'B' }]);
    expect(k1).not.toBe(k2);
  });

  it('changes when embedding model changes', async () => {
    const k1 = await computeCacheKey('m1', skills);
    const k2 = await computeCacheKey('m2', skills);
    expect(k1).not.toBe(k2);
  });

  it('is order-independent for triggers', async () => {
    const k1 = await computeCacheKey('m', [{ ...skills[0]!, triggers: ['x', 'y'] }]);
    const k2 = await computeCacheKey('m', [{ ...skills[0]!, triggers: ['y', 'x'] }]);
    expect(k1).toBe(k2);
  });
});
```

- [ ] **Step 2: Write semantic router test (pure cosine; no network)**

```ts
// agent/tests/semantic.test.ts
import { describe, it, expect } from 'bun:test';
import { cosine, route, type RoutableSkill } from '../src/router/semantic';

describe('cosine', () => {
  it('returns 1 for identical vectors', () => {
    expect(cosine([1, 0], [1, 0])).toBeCloseTo(1, 6);
  });
  it('returns 0 for orthogonal', () => {
    expect(cosine([1, 0], [0, 1])).toBeCloseTo(0, 6);
  });
  it('returns -1 for opposite', () => {
    expect(cosine([1, 0], [-1, 0])).toBeCloseTo(-1, 6);
  });
});

describe('route', () => {
  const skills: RoutableSkill[] = [
    { id: 'lights', embedding: [1, 0, 0] },
    { id: 'cameras', embedding: [0, 1, 0] },
    { id: 'network', embedding: [0, 0, 1] },
  ];

  it('HIGH band picks single skill', () => {
    const r = route([0.95, 0.1, 0.1], skills, { high: 0.75, med: 0.4 });
    expect(r.band).toBe('high');
    expect(r.selectedIds).toEqual(['lights']);
  });

  it('MED band returns top 2', () => {
    const r = route([0.5, 0.4, 0.0], skills, { high: 0.75, med: 0.4 });
    expect(r.band).toBe('med');
    expect(r.selectedIds).toHaveLength(2);
    expect(r.selectedIds[0]).toBe('lights');
  });

  it('LOW band returns no skills', () => {
    const r = route([0.1, 0.1, 0.1], skills, { high: 0.75, med: 0.4 });
    expect(r.band).toBe('low');
    expect(r.selectedIds).toEqual([]);
  });
});
```

- [ ] **Step 3: Run tests, expect failure**

```bash
cd agent && bun test tests/cache.test.ts tests/semantic.test.ts
```

Expected: both FAIL — modules not found.

- [ ] **Step 4: Implement cache**

```ts
// agent/src/router/cache.ts
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import { sha256Hex } from '../utils/sha256';

export interface CacheableSkill {
  id: string;
  description: string;
  triggers: string[];
  intentHints: string[];
  commandDescriptions: string[];
}

export interface EmbeddingCache {
  key: string;
  embeddingModel: string;
  bySkillId: Record<string, number[]>;
}

export async function computeCacheKey(embeddingModel: string, skills: CacheableSkill[]): Promise<string> {
  const normalized = skills
    .map(s => ({
      id: s.id,
      description: s.description,
      triggers: [...s.triggers].sort(),
      intentHints: s.intentHints,
      commandDescriptions: [...s.commandDescriptions].sort(),
    }))
    .sort((a, b) => a.id.localeCompare(b.id));
  return sha256Hex(JSON.stringify({ embeddingModel, skills: normalized }));
}

export async function loadCache(path: string): Promise<EmbeddingCache | null> {
  try {
    const txt = await readFile(path, 'utf8');
    return JSON.parse(txt) as EmbeddingCache;
  } catch {
    return null;
  }
}

export async function saveCache(path: string, cache: EmbeddingCache): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, JSON.stringify(cache, null, 2));
}
```

- [ ] **Step 5: Implement semantic router**

```ts
// agent/src/router/semantic.ts
export interface RoutableSkill {
  id: string;
  embedding: number[];
}

export type Band = 'high' | 'med' | 'low';

export interface Thresholds {
  high: number;
  med: number;
}

export interface RouteResult {
  band: Band;
  selectedIds: string[];
  scores: Array<{ id: string; score: number }>;
}

export function cosine(a: number[], b: number[]): number {
  if (a.length !== b.length || a.length === 0) return 0;
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    const ai = a[i] ?? 0;
    const bi = b[i] ?? 0;
    dot += ai * bi;
    na += ai * ai;
    nb += bi * bi;
  }
  const denom = Math.sqrt(na) * Math.sqrt(nb);
  if (denom === 0) return 0;
  return dot / denom;
}

export function route(query: number[], skills: RoutableSkill[], thresholds: Thresholds): RouteResult {
  const scored = skills
    .map(s => ({ id: s.id, score: cosine(query, s.embedding) }))
    .sort((a, b) => b.score - a.score);

  const top = scored[0];
  if (!top) return { band: 'low', selectedIds: [], scores: [] };

  if (top.score >= thresholds.high) {
    return { band: 'high', selectedIds: [top.id], scores: scored };
  }
  if (top.score >= thresholds.med) {
    return { band: 'med', selectedIds: scored.slice(0, 2).map(s => s.id), scores: scored };
  }
  return { band: 'low', selectedIds: [], scores: scored };
}
```

- [ ] **Step 6: Implement embedding client**

```ts
// agent/src/llm/embedding.ts
export interface EmbedOptions {
  baseUrl: string;
  model: string;
}

export async function embed(text: string, opts: EmbedOptions): Promise<number[]> {
  const res = await fetch(`${opts.baseUrl}/v1/embeddings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: opts.model, input: text }),
  });
  if (!res.ok) {
    throw new Error(`Embedding request failed: ${res.status} ${await res.text()}`);
  }
  const json = await res.json() as { data: Array<{ embedding: number[] }> };
  const vec = json.data[0]?.embedding;
  if (!vec) throw new Error('Embedding response missing data[0].embedding');
  return vec;
}

export async function embedMany(texts: string[], opts: EmbedOptions): Promise<number[][]> {
  return Promise.all(texts.map(t => embed(t, opts)));
}
```

- [ ] **Step 7: Verify tests pass**

```bash
cd agent && bun test tests/cache.test.ts tests/semantic.test.ts
```

Expected: 7 passing.

- [ ] **Step 8: Commit**

```bash
git add agent/src/router/ agent/src/llm/embedding.ts agent/tests/cache.test.ts agent/tests/semantic.test.ts
git commit -m "feat(agent): embedding client + cosine semantic router with cache"
```

---

## Task 11: LM Studio chat provider (Vercel AI SDK)

**Files:**
- Create: `agent/src/llm/lm-studio.ts`

No test — `@ai-sdk/openai-compatible` provider is a thin factory; testing it would mostly assert the library wires correctly. We rely on the library's own tests and validate end-to-end in Task 14.

- [ ] **Step 1: Implement provider factory**

```ts
// agent/src/llm/lm-studio.ts
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';
import type { LanguageModelV1 } from 'ai';

export interface LmStudioConfig {
  baseUrl: string;
  modelId: string;
}

export function lmStudioModel(config: LmStudioConfig): LanguageModelV1 {
  const provider = createOpenAICompatible({
    name: 'lm-studio',
    baseURL: `${config.baseUrl}/v1`,
  });
  return provider(config.modelId);
}
```

- [ ] **Step 2: Smoke type-check**

```bash
cd agent && bun run typecheck
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add agent/src/llm/lm-studio.ts
git commit -m "feat(agent): Vercel AI SDK provider for LM Studio"
```

---

## Task 12: System prompt builder

**Files:**
- Create: `agent/src/pipeline/system-prompt.ts`
- Create: `agent/tests/system-prompt.test.ts`

- [ ] **Step 1: Write tests**

```ts
// agent/tests/system-prompt.test.ts
import { describe, it, expect } from 'bun:test';
import { buildSystemPrompt } from '../src/pipeline/system-prompt';

describe('buildSystemPrompt', () => {
  it('lists tool-bearing skills with their descriptions', () => {
    const p = buildSystemPrompt({
      skills: [
        { id: 'homeassistant', description: 'Smart Home steuern' },
      ],
      hasTools: true,
    });
    expect(p).toContain('homeassistant');
    expect(p).toContain('Smart Home steuern');
    expect(p).toContain('Wenn ein Tool passt');
  });

  it('produces redirect prompt when no tools available', () => {
    const p = buildSystemPrompt({ skills: [], hasTools: false });
    expect(p.toLowerCase()).toContain('homelab');
    expect(p).not.toContain('Wenn ein Tool passt');
  });
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd agent && bun test tests/system-prompt.test.ts
```

Expected: FAIL.

- [ ] **Step 3: Implement builder**

```ts
// agent/src/pipeline/system-prompt.ts
export interface SkillSummary {
  id: string;
  description: string;
}

export interface BuildOptions {
  skills: SkillSummary[];
  hasTools: boolean;
}

const TOOLED_PROMPT = `Du bist Philipp's persönlicher Homelab-Assistent.
Antworten immer auf Deutsch, knapp und sachlich. Wenn ein Tool passt, rufe es auf — erfinde keine Werte, frage zurück wenn Argumente fehlen.

Verfügbare Skill-Domain(s) für diese Anfrage:
{skill_list}

Bei mehrdeutigen Anfragen frage genau eine klärende Frage statt ein Tool zu raten.`;

const SMALLTALK_PROMPT = `Du bist Philipp's Homelab-Assistent. Diese Anfrage passt zu keinem Homelab-Tool. Antworte freundlich, kurz auf Deutsch und biete an, beim Homelab zu helfen — nenne 2-3 konkrete Beispiele aus: VMs (Proxmox), Smart Home (Lichter, Szenen), Kameras (UniFi Protect), DNS (Pi-hole), Netzwerk-Geräte, Wake-on-LAN.`;

export function buildSystemPrompt(opts: BuildOptions): string {
  if (!opts.hasTools) return SMALLTALK_PROMPT;
  const list = opts.skills.map(s => `- ${s.id}: ${s.description}`).join('\n');
  return TOOLED_PROMPT.replace('{skill_list}', list);
}
```

- [ ] **Step 4: Verify tests pass**

```bash
cd agent && bun test tests/system-prompt.test.ts
```

Expected: 2 passing.

- [ ] **Step 5: Commit**

```bash
git add agent/src/pipeline/system-prompt.ts agent/tests/system-prompt.test.ts
git commit -m "feat(agent): build per-request system prompt"
```

---

## Task 13: Telegram webhook + send (text-only)

**Files:**
- Create: `agent/src/telegram/webhook.ts`
- Create: `agent/src/telegram/send.ts`
- Create: `agent/tests/webhook.test.ts`

- [ ] **Step 1: Write tests for the dedup + verify helpers**

```ts
// agent/tests/webhook.test.ts
import { describe, it, expect, beforeEach } from 'bun:test';
import { Database } from 'bun:sqlite';
import { initDb } from '../src/memory/db';
import { isDuplicate, markProcessed, parseUpdate, verifySecret } from '../src/telegram/webhook';

let db: Database;
beforeEach(() => { db = new Database(':memory:'); initDb(db); });

describe('verifySecret', () => {
  it('accepts matching secret header', () => {
    expect(verifySecret('expected', 'expected')).toBe(true);
  });
  it('rejects mismatched secret header', () => {
    expect(verifySecret('a', 'b')).toBe(false);
    expect(verifySecret('expected', null)).toBe(false);
  });
});

describe('dedup', () => {
  it('detects duplicates after marking', () => {
    expect(isDuplicate(db, 42)).toBe(false);
    markProcessed(db, 42);
    expect(isDuplicate(db, 42)).toBe(true);
  });
});

describe('parseUpdate', () => {
  it('extracts text message info', () => {
    const u = parseUpdate({
      update_id: 1,
      message: {
        message_id: 10,
        chat: { id: 555, type: 'private' },
        from: { id: 999, is_bot: false, first_name: 'P' },
        date: 1700000000,
        text: 'Hallo',
      },
    });
    expect(u).toEqual({
      kind: 'text',
      updateId: 1,
      chatId: 555,
      userId: 999,
      messageId: 10,
      text: 'Hallo',
      ts: 1700000000,
    });
  });

  it('returns null for callback queries (handled later)', () => {
    expect(parseUpdate({ update_id: 2, callback_query: { id: 'x' } } as never)).toBeNull();
  });

  it('returns null for unsupported message types in MVP', () => {
    expect(parseUpdate({
      update_id: 3,
      message: { message_id: 1, chat: { id: 1, type: 'private' }, from: { id: 1, is_bot: false }, date: 0, photo: [] },
    } as never)).toBeNull();
  });
});
```

- [ ] **Step 2: Run, expect failure**

```bash
cd agent && bun test tests/webhook.test.ts
```

- [ ] **Step 3: Implement webhook helpers**

```ts
// agent/src/telegram/webhook.ts
import type { Database } from 'bun:sqlite';

export interface ParsedTextUpdate {
  kind: 'text';
  updateId: number;
  chatId: number;
  userId: number;
  messageId: number;
  text: string;
  ts: number;
}

export type ParsedUpdate = ParsedTextUpdate;

export function verifySecret(expected: string, header: string | null): boolean {
  if (!header) return false;
  // Constant-time-ish compare
  if (header.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= expected.charCodeAt(i) ^ header.charCodeAt(i);
  }
  return diff === 0;
}

export function isDuplicate(db: Database, updateId: number): boolean {
  const row = db.prepare('SELECT 1 FROM processed_updates WHERE update_id = ?').get(updateId);
  return row !== null && row !== undefined;
}

export function markProcessed(db: Database, updateId: number): void {
  db.prepare('INSERT OR IGNORE INTO processed_updates (update_id, ts) VALUES (?, ?)').run(
    updateId, Math.floor(Date.now() / 1000),
  );
}

interface RawMessage {
  message_id: number;
  chat: { id: number; type: string };
  from?: { id: number; is_bot: boolean };
  date: number;
  text?: string;
  photo?: unknown[];
  voice?: unknown;
}

export function parseUpdate(update: { update_id: number; message?: RawMessage; callback_query?: unknown }): ParsedUpdate | null {
  if (update.callback_query) return null;
  const msg = update.message;
  if (!msg) return null;
  if (typeof msg.text !== 'string') return null;
  if (!msg.from) return null;
  return {
    kind: 'text',
    updateId: update.update_id,
    chatId: msg.chat.id,
    userId: msg.from.id,
    messageId: msg.message_id,
    text: msg.text,
    ts: msg.date,
  };
}
```

- [ ] **Step 4: Implement send (text-only)**

```ts
// agent/src/telegram/send.ts
export interface SendOptions {
  botToken: string;
}

export async function sendText(opts: SendOptions, chatId: number, text: string): Promise<void> {
  const res = await fetch(`https://api.telegram.org/bot${opts.botToken}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: 'HTML' }),
  });
  if (!res.ok) {
    throw new Error(`sendMessage failed: ${res.status} ${await res.text()}`);
  }
}
```

- [ ] **Step 5: Run tests**

```bash
cd agent && bun test tests/webhook.test.ts
```

Expected: 6 passing.

- [ ] **Step 6: Commit**

```bash
git add agent/src/telegram/ agent/tests/webhook.test.ts
git commit -m "feat(agent): telegram webhook parsing + text reply"
```

---

## Task 14: Pipeline — handle-message (text only)

**Files:**
- Create: `agent/src/pipeline/handle-message.ts`
- Create: `agent/tests/handle-message.test.ts`

The pipeline takes a parsed text update and returns a string reply (the caller sends it). We test by mocking the LLM and embedding clients via dependency injection.

- [ ] **Step 1: Write integration test (LLM/embedding mocked)**

```ts
// agent/tests/handle-message.test.ts
import { describe, it, expect, beforeEach } from 'bun:test';
import { Database } from 'bun:sqlite';
import { initDb } from '../src/memory/db';
import { handleMessage, type HandleDeps } from '../src/pipeline/handle-message';
import { SkillRegistry } from '../src/skills/registry';
import { z } from 'zod';
import type { LoadedSkill } from '../src/skills/loader';

let db: Database;
let registry: SkillRegistry;

beforeEach(() => {
  db = new Database(':memory:'); initDb(db);
  registry = new SkillRegistry();
  const skills: LoadedSkill[] = [{
    id: 'homeassistant',
    description: 'Smart Home steuern',
    triggers: ['licht', 'lampe'],
    intentHints: [],
    scriptPaths: ['/fake/homeassistant_api.py'],
    tools: [{
      name: 'homeassistant__status',
      scriptPath: '/fake/homeassistant_api.py',
      command: 'status',
      description: 'HA Status',
      schema: z.object({}),
      isWrite: false,
    }],
  }];
  registry.replaceAll(skills);
});

describe('handleMessage', () => {
  it('routes high-confidence query and calls generateText', async () => {
    let receivedTools: Record<string, unknown> = {};
    const deps: HandleDeps = {
      db,
      registry,
      embedQuery: async () => [1, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async ({ tools }) => {
        receivedTools = tools as Record<string, unknown>;
        return { text: 'Status: alles ok', toolCalls: [] };
      },
      thresholds: { high: 0.75, med: 0.4 },
    };
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 1, chatId: 100, userId: 999, messageId: 1, text: 'HA Status?', ts: 1,
    });
    expect(reply).toBe('Status: alles ok');
    expect(Object.keys(receivedTools)).toContain('homeassistant__status');
  });

  it('returns smalltalk redirect when LOW band', async () => {
    const deps: HandleDeps = {
      db,
      registry,
      embedQuery: async () => [0, 0, 0.1],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async ({ tools }) => {
        // tools should be empty in smalltalk path
        expect(Object.keys(tools as object)).toHaveLength(0);
        return { text: 'Ich helfe beim Homelab — frag mich z. B. nach Lichtern.', toolCalls: [] };
      },
      thresholds: { high: 0.75, med: 0.4 },
    };
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 2, chatId: 100, userId: 999, messageId: 2, text: 'Wie geht es dir?', ts: 1,
    });
    expect(reply).toContain('Homelab');
  });

  it('persists user msg + assistant reply to history', async () => {
    const deps: HandleDeps = {
      db, registry,
      embedQuery: async () => [1, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async () => ({ text: 'Reply', toolCalls: [] }),
      thresholds: { high: 0.75, med: 0.4 },
    };
    await handleMessage(deps, {
      kind: 'text', updateId: 3, chatId: 200, userId: 999, messageId: 1, text: 'Status', ts: 1,
    });
    const rows = db.prepare('SELECT role, content FROM conversations WHERE chat_id=200 ORDER BY ts').all() as Array<{ role: string; content: string }>;
    expect(rows).toHaveLength(2);
    expect(rows[0]?.role).toBe('user');
    expect(rows[1]?.role).toBe('assistant');
  });
});
```

- [ ] **Step 2: Run, expect failure**

```bash
cd agent && bun test tests/handle-message.test.ts
```

- [ ] **Step 3: Implement pipeline**

```ts
// agent/src/pipeline/handle-message.ts
import type { Database } from 'bun:sqlite';
import { route, type Thresholds } from '../router/semantic';
import { SkillRegistry } from '../skills/registry';
import { defineSkillTool, inferPositionals } from '../tools/define-skill-tool';
import { buildSystemPrompt } from './system-prompt';
import { appendMessage, recentMessages } from '../memory/history';
import type { ParsedTextUpdate } from '../telegram/webhook';
import type { Tool } from 'ai';

export interface GenerateInput {
  system: string;
  messages: Array<{ role: 'user' | 'assistant'; content: string }>;
  tools: Record<string, Tool>;
  reasoningEffort: 'low' | 'high';
}

export interface GenerateOutput {
  text: string;
  toolCalls: Array<{ toolName: string; args: unknown }>;
}

export interface HandleDeps {
  db: Database;
  registry: SkillRegistry;
  embedQuery: (text: string) => Promise<number[]>;
  skillEmbeddings: Record<string, number[]>;
  generate: (input: GenerateInput) => Promise<GenerateOutput>;
  thresholds: Thresholds;
}

const HISTORY_LIMIT = 20;

export async function handleMessage(deps: HandleDeps, update: ParsedTextUpdate): Promise<string> {
  const ts = update.ts ?? Math.floor(Date.now() / 1000);
  appendMessage(deps.db, { chatId: update.chatId, role: 'user', content: { text: update.text }, ts });

  const queryEmbedding = await deps.embedQuery(update.text);
  const skills = deps.registry.all();
  const routable = skills
    .filter(s => deps.skillEmbeddings[s.id] !== undefined)
    .map(s => ({ id: s.id, embedding: deps.skillEmbeddings[s.id]! }));
  const routed = route(queryEmbedding, routable, deps.thresholds);

  const selectedSkills = deps.registry.all().filter(s => routed.selectedIds.includes(s.id));
  const tools: Record<string, Tool> = {};
  for (const s of selectedSkills) {
    for (const t of s.tools) {
      tools[t.name] = defineSkillTool(t, { positionalArgs: inferPositionals(t) });
    }
  }
  const hasTools = Object.keys(tools).length > 0;

  const system = buildSystemPrompt({
    skills: selectedSkills.map(s => ({ id: s.id, description: s.description })),
    hasTools,
  });

  const history = recentMessages(deps.db, update.chatId, HISTORY_LIMIT)
    .filter(m => m.role !== 'tool')
    .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content.text ?? '' }))
    .filter(m => m.content.length > 0);

  const out = await deps.generate({
    system,
    messages: history,
    tools,
    reasoningEffort: 'low',
  });

  appendMessage(deps.db, {
    chatId: update.chatId,
    role: 'assistant',
    content: { text: out.text },
    intent: routed.selectedIds[0] ?? undefined,
    success: true,
    ts: ts + 1,
  });

  return out.text;
}
```

- [ ] **Step 4: Verify tests pass**

```bash
cd agent && bun test tests/handle-message.test.ts
```

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add agent/src/pipeline/handle-message.ts agent/tests/handle-message.test.ts
git commit -m "feat(agent): handle-message pipeline (text-only, mocked LLM)"
```

---

## Task 15: Real LM Studio adapter for `generate`

**Files:**
- Create: `agent/src/llm/generate.ts`

This wraps the Vercel AI SDK `generateText` call into the `GenerateInput → GenerateOutput` shape required by `handleMessage`. No unit test (integration; verified end-to-end in Task 17).

- [ ] **Step 1: Implement adapter**

```ts
// agent/src/llm/generate.ts
import { generateText } from 'ai';
import { lmStudioModel, type LmStudioConfig } from './lm-studio';
import type { GenerateInput, GenerateOutput } from '../pipeline/handle-message';

const MAX_STEPS = 5;

export function buildGenerator(cfg: LmStudioConfig) {
  const model = lmStudioModel(cfg);
  return async function generate(input: GenerateInput): Promise<GenerateOutput> {
    const result = await generateText({
      model,
      system: input.system,
      messages: input.messages.map(m => ({ role: m.role, content: m.content })),
      tools: input.tools,
      toolChoice: Object.keys(input.tools).length > 0 ? 'auto' : 'none',
      maxSteps: MAX_STEPS,
      providerOptions: {
        'lm-studio': {
          reasoning: { effort: input.reasoningEffort },
        },
      },
    });
    return {
      text: result.text,
      toolCalls: result.toolCalls?.map(tc => ({ toolName: tc.toolName, args: tc.args })) ?? [],
    };
  };
}
```

- [ ] **Step 2: Typecheck**

```bash
cd agent && bun run typecheck
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add agent/src/llm/generate.ts
git commit -m "feat(agent): real LM Studio generate adapter"
```

---

## Task 16: Bun HTTP server + main entry

**Files:**
- Create: `agent/src/server.ts`
- Create: `agent/src/main.ts`

- [ ] **Step 1: Implement server**

```ts
// agent/src/server.ts
import type { Database } from 'bun:sqlite';
import { verifySecret, isDuplicate, markProcessed, parseUpdate } from './telegram/webhook';
import { sendText } from './telegram/send';
import type { HandleDeps } from './pipeline/handle-message';
import { handleMessage } from './pipeline/handle-message';
import { log } from './utils/logger';
import type { Env } from './config/env';

export interface ServerDeps {
  env: Env;
  db: Database;
  handleDeps: HandleDeps;
}

const TELEGRAM_SECRET_HEADER = 'X-Telegram-Bot-Api-Secret-Token';

export function startServer(deps: ServerDeps): { stop: () => void } {
  const allowed = new Set(deps.env.TELEGRAM_ALLOWED_USERS);
  const server = Bun.serve({
    port: deps.env.PORT,
    async fetch(req) {
      const url = new URL(req.url);
      if (req.method === 'GET' && url.pathname === '/health') {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      if (req.method === 'POST' && url.pathname === '/webhook') {
        return handleWebhook(req, deps, allowed);
      }
      return new Response('not found', { status: 404 });
    },
  });
  log.info('server_started', { port: deps.env.PORT });
  return { stop: () => server.stop() };
}

async function handleWebhook(req: Request, deps: ServerDeps, allowed: Set<number>): Promise<Response> {
  const secret = req.headers.get(TELEGRAM_SECRET_HEADER);
  if (!verifySecret(deps.env.TELEGRAM_WEBHOOK_SECRET, secret)) {
    log.warn('webhook_bad_secret');
    return new Response('forbidden', { status: 403 });
  }
  let body: unknown;
  try { body = await req.json(); } catch { return new Response('bad json', { status: 400 }); }
  const update = body as { update_id: number };
  if (typeof update.update_id !== 'number') return new Response('bad update', { status: 400 });
  if (isDuplicate(deps.db, update.update_id)) {
    log.info('webhook_duplicate', { updateId: update.update_id });
    return new Response('ok', { status: 200 });
  }
  markProcessed(deps.db, update.update_id);
  const parsed = parseUpdate(update as never);
  if (!parsed) return new Response('ok', { status: 200 }); // unsupported update kind

  if (!allowed.has(parsed.userId)) {
    log.warn('webhook_unauthorized_user', { userId: parsed.userId });
    return new Response('ok', { status: 200 });
  }

  // Process in background; respond to Telegram immediately.
  setTimeout(() => {
    handleMessage(deps.handleDeps, parsed)
      .then(reply => sendText({ botToken: deps.env.TELEGRAM_BOT_TOKEN }, parsed.chatId, reply))
      .catch(err => log.error('handle_failed', { err: String(err), updateId: parsed.updateId }));
  }, 0);

  return new Response('ok', { status: 200 });
}
```

- [ ] **Step 2: Implement main entry**

```ts
// agent/src/main.ts
import { join } from 'node:path';
import { loadEnv } from './config/env';
import { openDb } from './memory/db';
import { loadSkills } from './skills/loader';
import { SkillRegistry } from './skills/registry';
import { embed, embedMany } from './llm/embedding';
import { computeCacheKey, loadCache, saveCache } from './router/cache';
import { buildGenerator } from './llm/generate';
import { startServer } from './server';
import { log } from './utils/logger';

async function main(): Promise<void> {
  const env = loadEnv();
  const db = openDb(join(env.DATA_DIR, 'conversations.db'));

  // Load only homeassistant for MVP; subsequent plans expand the allow-list.
  const skills = await loadSkills(env.SKILLS_ROOT, ['homeassistant']);
  if (skills.length === 0) throw new Error('No skills loaded');
  const registry = new SkillRegistry();
  registry.replaceAll(skills);

  const cacheable = skills.map(s => ({
    id: s.id,
    description: s.description,
    triggers: s.triggers,
    intentHints: s.intentHints,
    commandDescriptions: s.tools.map(t => t.description),
  }));
  const cacheKey = await computeCacheKey(env.EMBEDDING_MODEL, cacheable);
  const cachePath = join(env.DATA_DIR, 'embedding_cache.json');
  let cache = await loadCache(cachePath);
  if (!cache || cache.key !== cacheKey) {
    log.info('embedding_cache_rebuild');
    const inputs = skills.map(s => buildSkillEmbeddingInput(s));
    const vectors = await embedMany(inputs, { baseUrl: env.LM_STUDIO_URL, model: env.EMBEDDING_MODEL });
    const bySkillId: Record<string, number[]> = {};
    skills.forEach((s, i) => { bySkillId[s.id] = vectors[i]!; });
    cache = { key: cacheKey, embeddingModel: env.EMBEDDING_MODEL, bySkillId };
    await saveCache(cachePath, cache);
  } else {
    log.info('embedding_cache_hit');
  }

  const generate = buildGenerator({ baseUrl: env.LM_STUDIO_URL, modelId: env.LM_STUDIO_MODEL });

  startServer({
    env,
    db,
    handleDeps: {
      db,
      registry,
      embedQuery: (text) => embed(text, { baseUrl: env.LM_STUDIO_URL, model: env.EMBEDDING_MODEL }),
      skillEmbeddings: cache.bySkillId,
      generate,
      thresholds: { high: 0.75, med: 0.4 },
    },
  });
}

function buildSkillEmbeddingInput(s: { description: string; triggers: string[]; intentHints: string[]; tools: Array<{ description: string }> }): string {
  return [
    s.description,
    s.triggers.length > 0 ? `Triggers: ${s.triggers.join(', ')}.` : '',
    s.intentHints.join('. '),
    `Commands: ${s.tools.map(t => t.description).join('. ')}.`,
  ].filter(Boolean).join(' ');
}

main().catch(err => {
  log.error('startup_failed', { err: String(err) });
  process.exit(1);
});
```

- [ ] **Step 3: Typecheck**

```bash
cd agent && bun run typecheck
```

Expected: exit 0.

- [ ] **Step 4: Run a syntactic boot dry-run (no env will fail fast — verify error message is clean)**

```bash
cd agent && bun src/main.ts
```

Expected: process exits 1 with structured log line `{"level":"error","msg":"startup_failed","err":"Error: Invalid environment:\n  TELEGRAM_BOT_TOKEN: ..."}`.

- [ ] **Step 5: Commit**

```bash
git add agent/src/server.ts agent/src/main.ts
git commit -m "feat(agent): bun HTTP server + main entry wiring"
```

---

## Task 17: End-to-end smoke test against real LM Studio + HA

**Goal:** Send a fabricated Telegram update to `/webhook` and observe the agent route → LLM → tool → HA call → reply.

**Files:** none (manual test).

- [ ] **Step 1: Prepare env**

Copy `.env.example` to `agent/.env` and fill in the real values. Critically:
- `LM_STUDIO_URL` points to the Gaming PC and LM Studio is reachable
- `LM_STUDIO_MODEL=gemma-4-e4b` is loaded in LM Studio (Keep Loaded ✅)
- `EMBEDDING_MODEL=nomic-embed-text-v2-moe` is loaded with GPU offload = 0
- `TELEGRAM_*` and `ADMIN_TELEGRAM_ID` set
- `TELEGRAM_ALLOWED_USERS` contains the same ID
- `INTERNAL_NOTIFY_TOKEN` set to any 32+ char string
- `HOMEASSISTANT_HOST` and `HOMEASSISTANT_TOKEN` set in repo root `.env` (the homeassistant skill reads them)
- `SKILLS_ROOT=../.claude/skills` and `DATA_DIR=../data` (relative to `agent/`)

- [ ] **Step 2: Boot the agent**

```bash
cd agent && bun src/main.ts
```

Expected logs (in order):
- `embedding_cache_rebuild` (first run) — followed by an HTTP call to LM Studio embeddings endpoint
- `server_started {"port":8080}`

If `embedding_cache_rebuild` fails: LM Studio embedding model is not loaded or wrong name. Fix and restart.

- [ ] **Step 3: Send a fake webhook from another terminal**

```bash
curl -i -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: $(grep TELEGRAM_WEBHOOK_SECRET agent/.env | cut -d= -f2)" \
  -d "$(cat <<'EOF'
{
  "update_id": 999000,
  "message": {
    "message_id": 1,
    "chat": { "id": REPLACE_WITH_ADMIN_ID, "type": "private" },
    "from": { "id": REPLACE_WITH_ADMIN_ID, "is_bot": false, "first_name": "P" },
    "date": 1700000000,
    "text": "Wie ist der Home Assistant Status?"
  }
}
EOF
)"
```

Replace `REPLACE_WITH_ADMIN_ID` with `ADMIN_TELEGRAM_ID` from `.env`. Expected:
- HTTP 200 immediately
- Agent log: `routed` style line, then `generateText` to LM Studio, then `runSkillCommand homeassistant_api.py status`, then `sendMessage` to Telegram
- A real Telegram message arrives in your chat with the HA status

- [ ] **Step 4: If anything fails, capture and triage**

If the LLM picks no tool: confirm the embedding match — check `data/embedding_cache.json` exists and contains a vector for `homeassistant`. If embedding fails: confirm `nomic-embed-text-v2-moe` is loaded in LM Studio with GPU offload = 0. If the subprocess fails: run `python .claude/skills/homeassistant/scripts/homeassistant_api.py status --json` directly to verify the skill itself works (env vars in repo `.env` must be set).

- [ ] **Step 5: Commit anything accumulated during smoke test**

If any code adjustments were necessary (e.g., env defaults, log lines), commit them now. Otherwise skip.

---

## Self-Review Notes

After writing this plan I did the spec-coverage check:

- ✅ Sections 1-3 of spec (context, architecture, layout) — covered by Tasks 1, 4, 5, 16
- ✅ Section 4 (request flow) — Tasks 14, 15
- ✅ Section 5 (skill → tool mapping, --help-json contract) — Tasks 5, 6, 7
- ⏭ Section 6.1 (self-annealing) — out of scope, Plan 4
- ⏭ Section 6.2 (multimodal) — out of scope, Plan 3
- ⏭ Section 6.3 (proactive notifications) — out of scope, Plan 5
- ✅ Section 6.4 (history) — Task 4
- ⚠ Section 6.5 (admin/write-perms enforcement) — partial: allow-list applied in server.ts; write-vs-read enforcement deferred to Plan 2
- ✅ Section 6.6 (VRAM strategy) — runtime concern; configured in LM Studio, agent only references model names
- ✅ Section 7 (.env config) — Task 2 + .env.example

Type consistency check passed:
- `Tool` type from 'ai' used consistently in tools/ and pipeline/
- `LoadedSkill` / `SkillTool` shapes match across loader, registry, define-skill-tool, and main.ts
- `HandleDeps` interface matches what main.ts constructs

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-16-new-agent-mvp-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
