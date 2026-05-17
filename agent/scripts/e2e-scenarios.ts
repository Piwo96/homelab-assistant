/**
 * End-to-end scenario harness for Rolly.
 *
 * Bootstraps the same dependency graph as main.ts (real LM Studio, real skill
 * loader, real HA via the homeassistant skill), runs a hand-picked set of
 * scenarios through handleMessage(), and reports per-scenario pass/fail plus
 * an aggregate score.
 *
 * Write scenarios (turn-on/off, cover open/close) capture HA states for
 * light/switch/cover BEFORE the scenario and revert any deltas AFTER, so the
 * test run doesn't leave lights/blinds in a different state than it found them.
 *
 * Usage from the agent/ directory:
 *
 *     bun run scripts/e2e-scenarios.ts                 # full run, terminal + markdown
 *     bun run scripts/e2e-scenarios.ts --only=lights   # filter to one category
 *     bun run scripts/e2e-scenarios.ts --dry           # parse + describe; don't call LM Studio
 *
 * Results land in .tmp/test-results.md (one entry per scenario) and stdout.
 */

import { mkdir, writeFile, appendFile } from 'node:fs/promises';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Database } from 'bun:sqlite';
import { loadEnv } from '../src/config/env';
import { initDb } from '../src/memory/db';
import { loadSkills } from '../src/skills/loader';
import { SkillRegistry } from '../src/skills/registry';
import { embed, embedMany } from '../src/llm/embedding';
import { isLmStudioReachable } from '../src/llm/health';
import { wakeGamingPc } from '../src/wol/wake';
import { fetchHaCatalogue } from '../src/skills/ha-catalogue';
import { computeCacheKey, loadCache, saveCache } from '../src/router/cache';
import { buildGenerator } from '../src/llm/generate';
import { handleMessage, type HandleDeps } from '../src/pipeline/handle-message';
import type { ParsedTextUpdate } from '../src/telegram/webhook';

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../');
function repoPath(p: string): string {
  if (isAbsolute(p)) return p;
  return resolve(REPO_ROOT, p.replace(/^(\.\.\/)+/, ''));
}

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------

interface Scenario {
  id: string;
  category: string;
  text: string;
  /** If set, the scenario produces a write action — harness snapshots state
   *  before and reverts after. Climate writes are intentionally NOT marked
   *  as restorable because temperature setpoints don't have an obvious
   *  inverse short of remembering the prior value. */
  write?: boolean;
  expect: {
    /** Required substrings/regexes in the final reply (case-insensitive). */
    replyHas?: Array<string | RegExp>;
    /** Forbidden substrings/regexes in the final reply (case-insensitive). */
    replyMissing?: Array<string | RegExp>;
    /** At least one tool call must match this name. */
    toolCalled?: string | RegExp;
    /** No tool call is expected (smalltalk, ambiguous → clarification). */
    noTools?: boolean;
    /** If any entity_id was passed to a tool, it must match this regex
     *  (sanity check against hallucinations). */
    entityIdMatches?: RegExp;
  };
  /** Optional follow-up chat id link. Scenarios sharing a followupGroup run
   *  in order on the SAME chat_id so history carries across turns. */
  followupGroup?: string;
}

const SCENARIOS: Scenario[] = [
  // ===== Lichter — Einzel-Schaltung (write) =====
  { id: 'L1',  category: 'lichter', text: 'Mach das Licht im Büro an',
    write: true,
    expect: { toolCalled: /turn-on|toggle/, entityIdMatches: /^light\.dg_buro_/, replyMissing: [/Tool-Aufruf|Gemäß Regel/i] } },
  { id: 'L2',  category: 'lichter', text: 'Schalte die Tischleuchte am Esstisch aus',
    write: true,
    expect: { toolCalled: /turn-off|toggle/, entityIdMatches: /^light\.eg_essen_tischleuchte/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'L3',  category: 'lichter', text: 'Mach das Garderobenlicht an',
    write: true,
    expect: { toolCalled: /turn-on|toggle/, entityIdMatches: /^light\.eg_garderobe/ , replyMissing: [/Tool-Aufruf/i] } },
  { id: 'L4',  category: 'lichter', text: 'Schalte das Schlafzimmerlicht aus',
    write: true,
    expect: { toolCalled: /turn-off|toggle/, entityIdMatches: /schlafzimmer|wandleuchten_schlafzimmer/ , replyMissing: [/Tool-Aufruf/i] } },
  { id: 'L5',  category: 'lichter', text: 'Mach das Licht in Mailas Zimmer an',
    write: true,
    expect: { toolCalled: /turn-on|toggle/, entityIdMatches: /^light\.og_kind_1/ , replyMissing: [/Tool-Aufruf/i] } },
  { id: 'L6',  category: 'lichter', text: 'Schalte das Licht im Hobbyraum aus',
    write: true,
    expect: { toolCalled: /turn-off|toggle/, entityIdMatches: /^light\.kg_hobby/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'L7',  category: 'lichter', text: 'Schalte das Flurlicht im EG aus',
    write: true,
    expect: { toolCalled: /turn-off|toggle/, entityIdMatches: /^light\.eg_flur/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'L8',  category: 'lichter', text: 'Mach das Licht in der Speisekammer an',
    write: true,
    expect: { toolCalled: /turn-on|toggle/, entityIdMatches: /speisekammer/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'L9',  category: 'lichter', text: 'Schalte die Terrassenbeleuchtung an',
    write: true,
    expect: { toolCalled: /turn-on|toggle/, entityIdMatches: /aussen_terrasse|aussen_wandleuchten_terrasse/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'L10', category: 'lichter', text: 'Mach die Wandleuchten im Wohnzimmer aus',
    write: true,
    expect: { toolCalled: /turn-off|toggle/, entityIdMatches: /^light\.eg_wohn_ess_wandleuchten/, replyMissing: [/Tool-Aufruf/i] } },

  // ===== Lichter — Status (read) =====
  { id: 'R1', category: 'lichter-status', text: 'Ist das Licht im Büro an?',
    expect: { toolCalled: /get-state|entities/, entityIdMatches: /^light\.dg_buro_/, replyMissing: [/schiefgegangen|Tool-Aufruf/i] } },
  { id: 'R2', category: 'lichter-status', text: 'Welche Lichter sind gerade an?',
    expect: { toolCalled: /entities/, replyMissing: [/schiefgegangen|Tool-Aufruf|abgeschnitten/i] } },
  { id: 'R3', category: 'lichter-status', text: 'Wie ist der Status der Küchenbeleuchtung?',
    expect: { toolCalled: /entities|get-state/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'R4', category: 'lichter-status', text: 'Sind im Erdgeschoss Lichter an?',
    expect: { toolCalled: /entities/, replyMissing: [/Tool-Aufruf|schiefgegangen/i] } },
  { id: 'R5', category: 'lichter-status', text: 'Ist das Außenlicht über der Haustür an?',
    expect: { toolCalled: /get-state|entities/, entityIdMatches: /aussen_beleuchtung_uber_haustur/, replyMissing: [/Tool-Aufruf/i] } },

  // ===== Brightness =====
  { id: 'B1', category: 'brightness', text: 'Mach das Licht im Büro auf 50%',
    write: true,
    expect: { toolCalled: /turn-on/, entityIdMatches: /^light\.dg_buro_/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'B2', category: 'brightness', text: 'Dimme das Esstischlicht auf 30%',
    write: true,
    expect: { toolCalled: /turn-on/, entityIdMatches: /^light\.eg_essen_tischleuchte/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'B3', category: 'brightness', text: 'Schalte das Wohnzimmerlicht voll an',
    write: true,
    expect: { toolCalled: /turn-on/, entityIdMatches: /^light\.eg_wohn_/, replyMissing: [/Tool-Aufruf/i] } },

  // ===== Rollos (cover) =====
  { id: 'C1', category: 'rollos', text: 'Mach das Rollo im Schlafzimmer hoch',
    write: true,
    expect: { toolCalled: /turn-on|call-service|toggle/, entityIdMatches: /^cover\.dg_schlafen/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'C2', category: 'rollos', text: 'Welche Rollos sind offen?',
    expect: { toolCalled: /entities/, replyMissing: [/Tool-Aufruf|schiefgegangen|abgeschnitten/i] } },
  { id: 'C3', category: 'rollos', text: 'Welche Rollos sind zu?',
    expect: { toolCalled: /entities/, replyMissing: [/Tool-Aufruf|schiefgegangen|abgeschnitten/i] } },
  { id: 'C4', category: 'rollos', text: 'Wie weit ist das Rollo im Büro?',
    expect: { toolCalled: /get-state|entities/, entityIdMatches: /^cover\.dg_buro_/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'C5', category: 'rollos', text: 'Mach das Rollo in der Garderobe zu',
    write: true,
    expect: { toolCalled: /call-service|turn-off|toggle/, entityIdMatches: /^cover\.eg_garderobe/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'C6', category: 'rollos', text: 'Öffne das Rollo im Gäste-WC',
    write: true,
    expect: { toolCalled: /call-service|turn-on|toggle/, entityIdMatches: /^cover\.eg_wc/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'C7', category: 'rollos', text: 'Ist das Rollo im Bad der Eltern offen?',
    expect: { toolCalled: /get-state|entities/, entityIdMatches: /^cover\.dg_bad/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'C8', category: 'rollos', text: 'Schließ das Rollo in der Küche',
    write: true,
    expect: { toolCalled: /call-service|turn-off|toggle/, entityIdMatches: /^cover\.eg_kuche|^cover\.eg_rollo_kuche/, replyMissing: [/Tool-Aufruf/i] } },

  // ===== Heizung (climate, read-only because setpoints aren't trivially restorable) =====
  { id: 'H1', category: 'heizung', text: 'Wie warm ist es im Wohnzimmer?',
    expect: { toolCalled: /get-state|entities/, replyMissing: [/Tool-Aufruf|schiefgegangen/i] } },
  { id: 'H2', category: 'heizung', text: 'Welche Heizung ist gerade aktiv?',
    expect: { toolCalled: /entities/, replyMissing: [/Tool-Aufruf|schiefgegangen|abgeschnitten/i] } },
  { id: 'H3', category: 'heizung', text: 'Wie ist die Temperatur im Schlafzimmer?',
    expect: { toolCalled: /get-state|entities/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'H4', category: 'heizung', text: 'Auf welche Temperatur ist das Bad eingestellt?',
    expect: { toolCalled: /get-state|entities/, replyMissing: [/Tool-Aufruf/i] } },

  // ===== Steckdosen (switch, write) =====
  { id: 'S1', category: 'steckdosen', text: 'Schalte die Steckdose im Büro ein',
    write: true,
    expect: { toolCalled: /turn-on|toggle/, entityIdMatches: /^switch\.dg_buro_/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'S2', category: 'steckdosen', text: 'Welche Steckdosen sind an?',
    expect: { toolCalled: /entities/, replyMissing: [/Tool-Aufruf|schiefgegangen|abgeschnitten/i] } },
  { id: 'S3', category: 'steckdosen', text: 'Mach die Steckdose am Esstisch aus',
    write: true,
    expect: { toolCalled: /turn-off|toggle/, entityIdMatches: /^switch\.eg_essen_/, replyMissing: [/Tool-Aufruf/i] } },

  // ===== Folge-Anfragen (shared chat_id within group) =====
  { id: 'F1', category: 'followup-esszimmer', text: 'Mach das Esszimmerlicht an',
    write: true, followupGroup: 'esszimmer',
    expect: { toolCalled: /turn-on|toggle/, entityIdMatches: /^light\.eg_essen_tischleuchte/, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'F2', category: 'followup-esszimmer', text: 'Und auch die Wandleuchten',
    write: true, followupGroup: 'esszimmer',
    expect: { toolCalled: /turn-on|toggle/, entityIdMatches: /eg_wohn_ess_wandleuchten/, replyMissing: [/Tool-Aufruf|Gemäß Regel/i] } },
  { id: 'F3', category: 'followup-esszimmer', text: 'Alle wieder aus',
    write: true, followupGroup: 'esszimmer',
    expect: { toolCalled: /turn-off|toggle/, replyMissing: [/Tool-Aufruf|Gemäß Regel/i] } },
  { id: 'F4', category: 'followup-buero', text: 'Schau im Büro nach welche Lichter an sind',
    followupGroup: 'buero',
    expect: { toolCalled: /entities|get-state/, replyMissing: [/Tool-Aufruf|schiefgegangen/i] } },
  { id: 'F5', category: 'followup-buero', text: 'Mach es aus',
    write: true, followupGroup: 'buero',
    expect: { toolCalled: /turn-off|toggle/, entityIdMatches: /^light\.dg_buro_/, replyMissing: [/Tool-Aufruf|Gemäß Regel/i] } },

  // ===== Mehrdeutige Anfragen (model should ask, not blast) =====
  { id: 'A1', category: 'ambiguous', text: 'Mach das Licht aus',
    expect: { replyMissing: [/Tool-Aufruf/i] /* should ask "welches?"; no strong tool req */ } },
  { id: 'A2', category: 'ambiguous', text: 'Mach alles aus',
    expect: { replyMissing: [/Tool-Aufruf/i] /* should not mass-toggle 60 entities */ } },
  { id: 'A3', category: 'ambiguous', text: 'Mach das Rollo zu',
    expect: { replyMissing: [/Tool-Aufruf/i] } },
  { id: 'A4', category: 'ambiguous', text: 'Schalte das Bad-Licht aus',
    expect: { replyMissing: [/Tool-Aufruf/i] /* DG Bad Eltern vs OG Bad Kinder vs KG Bad */ } },

  // ===== Hallucination-Tests (entity does NOT exist) =====
  { id: 'X1', category: 'hallucination', text: 'Mach das Licht im Wintergarten an',
    expect: { replyMissing: [/Tool-Aufruf/i], replyHas: [/nicht|gibt|finde|verfügbar/i] } },
  { id: 'X2', category: 'hallucination', text: 'Schalte den Heizlüfter aus',
    expect: { replyMissing: [/Tool-Aufruf/i], replyHas: [/nicht|gibt|finde|verfügbar/i] } },
  { id: 'X3', category: 'hallucination', text: 'Wie ist der Status der Markise?',
    expect: { replyMissing: [/Tool-Aufruf/i], replyHas: [/nicht|gibt|finde|verfügbar/i] } },
  { id: 'X4', category: 'hallucination', text: 'Schalte den Pool ein',
    expect: { replyMissing: [/Tool-Aufruf/i], replyHas: [/nicht|gibt|finde|verfügbar/i] } },

  // ===== Smalltalk / out-of-scope =====
  { id: 'T1', category: 'smalltalk', text: 'Wie geht es dir?',
    expect: { noTools: true, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'T2', category: 'smalltalk', text: 'Was kannst du eigentlich?',
    expect: { noTools: true, replyMissing: [/Tool-Aufruf/i], replyHas: [/homelab|smart home|licht|szene|kamera|vm|netzwerk/i] } },
  { id: 'T3', category: 'smalltalk', text: 'Erzähl mir einen Witz',
    expect: { noTools: true, replyMissing: [/Tool-Aufruf/i] } },
  { id: 'T4', category: 'smalltalk', text: 'Danke!',
    expect: { noTools: true, replyMissing: [/Tool-Aufruf/i] } },
];

// ---------------------------------------------------------------------------
// HA state snapshot + restore
// ---------------------------------------------------------------------------

interface EntitySnapshot {
  state: string;
  attributes: Record<string, unknown>;
}

function resolveHaUrl(): string {
  // Match the same defaulting the Python homeassistant_api.py uses:
  // HOMEASSISTANT_HOST may be a bare hostname/IP — port comes from
  // HOMEASSISTANT_PORT (default 8123) and is appended only when not present.
  let host = process.env.HOMEASSISTANT_HOST || '192.168.10.150';
  if (!host.includes(':')) host = `${host}:${process.env.HOMEASSISTANT_PORT || '8123'}`;
  return host;
}
const HA_HOST = resolveHaUrl();
const HA_TOKEN = process.env.HOMEASSISTANT_TOKEN || '';

async function haGet(path: string): Promise<unknown> {
  const res = await fetch(`http://${HA_HOST}/api${path}`, {
    headers: { Authorization: `Bearer ${HA_TOKEN}` },
  });
  if (!res.ok) throw new Error(`HA GET ${path} → ${res.status}`);
  return res.json();
}

async function haPost(path: string, body: unknown): Promise<unknown> {
  const res = await fetch(`http://${HA_HOST}/api${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${HA_TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HA POST ${path} → ${res.status}`);
  return res.json();
}

const WRITE_DOMAINS = ['light', 'switch', 'cover'];

async function snapshotWritableStates(): Promise<Map<string, EntitySnapshot>> {
  const all = await haGet('/states') as Array<{ entity_id: string; state: string; attributes: Record<string, unknown> }>;
  const map = new Map<string, EntitySnapshot>();
  for (const s of all) {
    const domain = s.entity_id.split('.')[0]!;
    if (WRITE_DOMAINS.includes(domain)) {
      map.set(s.entity_id, { state: s.state, attributes: s.attributes });
    }
  }
  return map;
}

async function restoreFromSnapshot(snap: Map<string, EntitySnapshot>): Promise<string[]> {
  const restored: string[] = [];
  const all = await haGet('/states') as Array<{ entity_id: string; state: string; attributes: Record<string, unknown> }>;
  for (const s of all) {
    const before = snap.get(s.entity_id);
    if (!before) continue;
    if (before.state === s.state) continue;
    const domain = s.entity_id.split('.')[0]!;
    try {
      if (domain === 'light' || domain === 'switch') {
        if (before.state === 'on' && s.state !== 'on') {
          const data: Record<string, unknown> = { entity_id: s.entity_id };
          if (typeof before.attributes.brightness === 'number') data.brightness = before.attributes.brightness;
          await haPost(`/services/${domain}/turn_on`, data);
        } else if (before.state === 'off' && s.state !== 'off') {
          await haPost(`/services/${domain}/turn_off`, { entity_id: s.entity_id });
        }
      } else if (domain === 'cover') {
        // Best-effort: snapshot position if available, else use open/close
        const beforePos = before.attributes.current_position as number | undefined;
        if (typeof beforePos === 'number') {
          await haPost('/services/cover/set_cover_position', { entity_id: s.entity_id, position: beforePos });
        } else if (before.state === 'open' && s.state !== 'open') {
          await haPost('/services/cover/open_cover', { entity_id: s.entity_id });
        } else if (before.state === 'closed' && s.state !== 'closed') {
          await haPost('/services/cover/close_cover', { entity_id: s.entity_id });
        }
      }
      restored.push(s.entity_id);
    } catch (err) {
      console.error(`  ⚠️ restore failed for ${s.entity_id}: ${err}`);
    }
  }
  return restored;
}

// ---------------------------------------------------------------------------
// Bootstrap (mirrors main.ts minus the HTTP server)
// ---------------------------------------------------------------------------

async function bootstrap(): Promise<HandleDeps> {
  const env = loadEnv();
  const skillsRoot = repoPath(env.SKILLS_ROOT);
  const dataDir = repoPath(env.DATA_DIR);
  await mkdir(dataDir, { recursive: true });

  // In-memory DB so the test run doesn't pollute the production history.
  const db = new Database(':memory:');
  initDb(db);

  const skills = await loadSkills(skillsRoot, ['homeassistant']);
  if (skills.length === 0) throw new Error('No skills loaded');
  const registry = new SkillRegistry();
  registry.replaceAll(skills);

  const cachePath = join(dataDir, 'agent-embedding-cache.json');
  const cacheable = skills.map(s => ({
    id: s.id, description: s.description, triggers: s.triggers,
    intentHints: s.intentHints,
    commandDescriptions: s.tools.map(t => t.description),
  }));
  const cacheKey = await computeCacheKey(env.EMBEDDING_MODEL, cacheable);
  let cache = await loadCache(cachePath);
  if (!cache || cache.key !== cacheKey) {
    const inputs = skills.map(s => [
      s.description,
      `Triggers: ${s.triggers.join(', ')}.`,
      s.intentHints.join('. '),
      `Commands: ${s.tools.map(t => t.description).join('. ')}.`,
    ].filter(Boolean).join(' '));
    const vectors = await embedMany(inputs, { baseUrl: env.LM_STUDIO_URL, model: env.EMBEDDING_MODEL });
    const bySkillId: Record<string, number[]> = {};
    skills.forEach((s, i) => { bySkillId[s.id] = vectors[i]!; });
    cache = { key: cacheKey, embeddingModel: env.EMBEDDING_MODEL, bySkillId };
    await saveCache(cachePath, cache);
  }

  const generate = buildGenerator({ baseUrl: env.LM_STUDIO_URL, modelId: env.LM_STUDIO_MODEL });
  const haCatalogue = await fetchHaCatalogue(skillsRoot);

  return {
    db, registry,
    embedQuery: (text) => embed(text, { baseUrl: env.LM_STUDIO_URL, model: env.EMBEDDING_MODEL }),
    skillEmbeddings: cache.bySkillId,
    generate,
    thresholds: { high: 0.75, med: 0.4 },
    healthCheck: () => isLmStudioReachable({ baseUrl: env.LM_STUDIO_URL, timeoutMs: 3000 }),
    wakeGamingPc: () => wakeGamingPc({ skillsRoot, timeoutMs: 150_000 }),
    ...(haCatalogue ? { entityCatalogue: haCatalogue } : {}),
  };
}

// ---------------------------------------------------------------------------
// Per-scenario evaluation
// ---------------------------------------------------------------------------

interface RunResult {
  id: string;
  category: string;
  text: string;
  reply: string;
  durationMs: number;
  checks: Array<{ name: string; ok: boolean; detail?: string }>;
  restored: string[];
  passed: boolean;
}

function matches(value: string, m: string | RegExp): boolean {
  return m instanceof RegExp ? m.test(value) : value.toLowerCase().includes(m.toLowerCase());
}

// We don't have direct access to the model's toolCalls from inside handleMessage
// (it returns just the reply). For the harness we shadow the generate fn with
// a wrapper that records the last call's toolCalls.
interface InstrumentedDeps extends HandleDeps {
  __recordedToolCalls: Array<{ toolName: string; args: unknown }>;
}

function instrument(deps: HandleDeps): InstrumentedDeps {
  const recorded: Array<{ toolName: string; args: unknown }> = [];
  const originalGenerate = deps.generate;
  const wrapped: HandleDeps['generate'] = async (input) => {
    const out = await originalGenerate(input);
    for (const tc of out.toolCalls) recorded.push(tc);
    return out;
  };
  return Object.assign({}, deps, { generate: wrapped, __recordedToolCalls: recorded }) as InstrumentedDeps;
}

function evaluateScenario(
  scenario: Scenario,
  reply: string,
  toolCalls: Array<{ toolName: string; args: unknown }>,
): Array<{ name: string; ok: boolean; detail?: string }> {
  const checks: Array<{ name: string; ok: boolean; detail?: string }> = [];

  checks.push({ name: 'reply non-empty', ok: reply.trim().length > 0 });

  if (scenario.expect.replyHas) {
    for (const m of scenario.expect.replyHas) {
      checks.push({ name: `reply contains ${m}`, ok: matches(reply, m) });
    }
  }
  if (scenario.expect.replyMissing) {
    for (const m of scenario.expect.replyMissing) {
      checks.push({ name: `reply lacks ${m}`, ok: !matches(reply, m) });
    }
  }
  if (scenario.expect.toolCalled) {
    const m = scenario.expect.toolCalled;
    const hit = toolCalls.some(tc => matches(tc.toolName, m));
    checks.push({
      name: `tool called ${m}`,
      ok: hit,
      detail: hit ? '' : `actual: ${toolCalls.map(tc => tc.toolName).join(', ') || '(none)'}`,
    });
  }
  if (scenario.expect.noTools) {
    const writeCalls = toolCalls.filter(tc => /turn-on|turn-off|toggle|call-service/.test(tc.toolName));
    checks.push({
      name: 'no write tools',
      ok: writeCalls.length === 0,
      detail: writeCalls.length ? `unexpected: ${writeCalls.map(tc => tc.toolName).join(', ')}` : '',
    });
  }
  if (scenario.expect.entityIdMatches) {
    const m = scenario.expect.entityIdMatches;
    const ids = toolCalls
      .map(tc => (tc.args && typeof tc.args === 'object' ? (tc.args as Record<string, unknown>)['entity_id'] : undefined))
      .filter((v): v is string => typeof v === 'string');
    const hit = ids.length === 0 ? true : ids.some(id => m.test(id));
    checks.push({
      name: `entity_id matches ${m}`,
      ok: hit,
      detail: hit ? '' : `actual: ${ids.join(', ') || '(none)'}`,
    });
  }

  return checks;
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------

const args = new Set(process.argv.slice(2));
const filter = process.argv.find(a => a.startsWith('--only='))?.slice('--only='.length);
const isDryRun = args.has('--dry');

async function main() {
  const deps = await bootstrap();
  const inst = instrument(deps);

  const RESULTS_PATH = repoPath('.tmp/test-results.md');
  await writeFile(RESULTS_PATH,
    `# Rolly E2E Scenario Results — ${new Date().toISOString()}\n\n` +
    `Total scenarios: ${SCENARIOS.length}\n\n---\n\n`,
  );

  const scenarios = SCENARIOS.filter(s => !filter || s.category === filter);
  if (filter) console.log(`[filter] running ${scenarios.length} scenarios in category '${filter}'`);

  // Map followupGroup → chatId so grouped scenarios share history.
  const groupChatIds = new Map<string, number>();
  const fixedUserId = 5024544400;

  const results: RunResult[] = [];
  for (let i = 0; i < scenarios.length; i++) {
    const sc = scenarios[i]!;
    const tag = `[${i + 1}/${scenarios.length}] ${sc.id} (${sc.category})`;
    console.log(`\n${tag}  →  ${sc.text}`);
    if (isDryRun) continue;

    // Capture snapshot for write scenarios
    let snap: Map<string, EntitySnapshot> | undefined;
    if (sc.write) {
      try { snap = await snapshotWritableStates(); }
      catch (err) { console.error(`  ⚠️ snapshot failed: ${err}`); }
    }

    // Reset recorded tool calls for this scenario
    inst.__recordedToolCalls.length = 0;

    // chatId: shared per followup group, otherwise unique per scenario
    let chatId: number;
    if (sc.followupGroup) {
      const existing = groupChatIds.get(sc.followupGroup);
      if (existing) chatId = existing;
      else { chatId = 9_000_000 + i; groupChatIds.set(sc.followupGroup, chatId); }
    } else {
      chatId = 9_000_000 + i;
    }

    const update: ParsedTextUpdate = {
      kind: 'text',
      updateId: 800_000_000 + i,
      chatId,
      userId: fixedUserId,
      messageId: 1,
      text: sc.text,
      ts: Math.floor(Date.now() / 1000),
      firstName: 'Philipp',
    };

    const t0 = Date.now();
    let reply = '';
    try {
      reply = await handleMessage(inst, update);
    } catch (err) {
      reply = `EXCEPTION: ${err instanceof Error ? err.message : String(err)}`;
    }
    const durationMs = Date.now() - t0;

    const toolCalls = [...inst.__recordedToolCalls];
    const checks = evaluateScenario(sc, reply, toolCalls);
    const passed = checks.every(c => c.ok);

    let restored: string[] = [];
    if (snap) {
      try { restored = await restoreFromSnapshot(snap); }
      catch (err) { console.error(`  ⚠️ restore failed: ${err}`); }
    }

    const result: RunResult = { id: sc.id, category: sc.category, text: sc.text, reply, durationMs, checks, restored, passed };
    results.push(result);

    console.log(`  ${passed ? '✅' : '❌'} ${durationMs}ms · tools=${toolCalls.map(tc => tc.toolName).join(',') || '(none)'}`);
    for (const c of checks) if (!c.ok) console.log(`     - FAIL ${c.name}${c.detail ? ` :: ${c.detail}` : ''}`);
    if (restored.length) console.log(`  ↻ restored: ${restored.join(', ')}`);

    // Append to results file
    const md = `## ${sc.id} · ${sc.category} · ${passed ? '✅ PASS' : '❌ FAIL'}\n\n` +
      `**Input:** \`${sc.text}\`  \n` +
      `**Duration:** ${durationMs} ms  \n` +
      `**Tool calls:** ${toolCalls.length ? toolCalls.map(tc => `\`${tc.toolName}(${JSON.stringify(tc.args)})\``).join(', ') : '_none_'}  \n` +
      `**Reply:**\n\n> ${reply.split('\n').join('\n> ')}\n\n` +
      `**Checks:**\n` +
      checks.map(c => `- ${c.ok ? '✓' : '✗'} ${c.name}${c.detail ? ` — ${c.detail}` : ''}`).join('\n') +
      (restored.length ? `\n\n**Restored:** ${restored.join(', ')}` : '') +
      `\n\n---\n\n`;
    await appendFile(RESULTS_PATH, md);
  }

  // Summary
  if (!isDryRun) {
    const pass = results.filter(r => r.passed).length;
    const fail = results.length - pass;
    const byCat = new Map<string, { p: number; f: number }>();
    for (const r of results) {
      const stat = byCat.get(r.category) ?? { p: 0, f: 0 };
      if (r.passed) stat.p++; else stat.f++;
      byCat.set(r.category, stat);
    }
    let summary = `\n# Summary\n\n**${pass}/${results.length} passed** (${fail} failed)\n\n`;
    summary += `| Category | Pass | Fail |\n|---|---|---|\n`;
    for (const [cat, stat] of byCat) summary += `| ${cat} | ${stat.p} | ${stat.f} |\n`;
    summary += `\n### Failing scenarios\n\n`;
    for (const r of results.filter(r => !r.passed)) {
      summary += `- **${r.id}** (${r.category}): \`${r.text}\` — ${r.checks.filter(c => !c.ok).map(c => c.name).join(', ')}\n`;
    }
    await appendFile(RESULTS_PATH, summary);
    console.log(summary);
  }
}

main().catch(err => {
  console.error('Harness failed:', err);
  process.exit(1);
});
