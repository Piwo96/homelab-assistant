/**
 * One-off interactive test: send "Mach die Rollos im Spielzimmer zu und neig die
 * Lamellen auf 50%" through the real pipeline, capture every step, restore the
 * rollos to their original position/tilt afterward.
 *
 *     bun run scripts/spielzimmer-test.ts
 */
import { mkdir } from 'node:fs/promises';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Database } from 'bun:sqlite';
import { loadEnv } from '../src/config/env';
import { initDb } from '../src/memory/db';
import { loadSkills } from '../src/skills/loader';
import { SkillRegistry } from '../src/skills/registry';
import { embed, embedMany } from '../src/llm/embedding';
import { fetchHaCatalogue } from '../src/skills/ha-catalogue';
import { computeCacheKey, loadCache, saveCache } from '../src/router/cache';
import { buildGenerator } from '../src/llm/generate';
import { handleMessage, type HandleDeps } from '../src/pipeline/handle-message';

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../');
const repoPath = (p: string) => isAbsolute(p) ? p : resolve(REPO_ROOT, p.replace(/^(\.\.\/)+/, ''));
const env = loadEnv();
const HA_HOST = (() => {
  let h = process.env.HOMEASSISTANT_HOST || '192.168.10.150';
  if (!h.includes(':')) h += `:${process.env.HOMEASSISTANT_PORT || '8123'}`;
  return h;
})();
const HA_TOKEN = process.env.HOMEASSISTANT_TOKEN || '';

async function ha(method: string, path: string, body?: unknown) {
  const r = await fetch(`http://${HA_HOST}/api${path}`, {
    method,
    headers: { Authorization: `Bearer ${HA_TOKEN}`, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!r.ok) throw new Error(`HA ${method} ${path} → ${r.status}`);
  return r.json();
}

const SPIELZIMMER_ROLLOS = ['cover.og_kind_2_rollo_1', 'cover.og_kind_2_rollo_2'];

async function readSpielzimmer() {
  const states: Record<string, { pos: number | undefined; tilt: number | undefined }> = {};
  for (const id of SPIELZIMMER_ROLLOS) {
    const s = await ha('GET', `/states/${id}`) as { attributes: Record<string, unknown> };
    states[id] = {
      pos: s.attributes.current_position as number | undefined,
      tilt: s.attributes.current_tilt_position as number | undefined,
    };
  }
  return states;
}

async function main() {
  await mkdir(repoPath(env.DATA_DIR), { recursive: true });
  const db = new Database(':memory:'); initDb(db);
  const skillsRoot = repoPath(env.SKILLS_ROOT);
  const skills = await loadSkills(skillsRoot, ['homeassistant']);
  const registry = new SkillRegistry(); registry.replaceAll(skills);
  const cacheable = skills.map(s => ({
    id: s.id, description: s.description, triggers: s.triggers,
    intentHints: s.intentHints, commandDescriptions: s.tools.map(t => t.description),
  }));
  const cacheKey = await computeCacheKey(env.EMBEDDING_MODEL, cacheable);
  const cachePath = join(repoPath(env.DATA_DIR), 'agent-embedding-cache.json');
  let cache = await loadCache(cachePath);
  if (!cache || cache.key !== cacheKey) {
    const inputs = skills.map(s => [s.description, `Triggers: ${s.triggers.join(', ')}.`, s.intentHints.join('. '), `Commands: ${s.tools.map(t => t.description).join('. ')}.`].filter(Boolean).join(' '));
    const vectors = await embedMany(inputs, { baseUrl: env.LM_STUDIO_URL, model: env.EMBEDDING_MODEL });
    const bySkillId: Record<string, number[]> = {};
    skills.forEach((s, i) => { bySkillId[s.id] = vectors[i]!; });
    cache = { key: cacheKey, embeddingModel: env.EMBEDDING_MODEL, bySkillId };
    await saveCache(cachePath, cache);
  }
  const generate = buildGenerator({ baseUrl: env.LM_STUDIO_URL, modelId: env.LM_STUDIO_MODEL });
  const haCatalogue = await fetchHaCatalogue(skillsRoot);

  // Instrument generate to capture tool calls.
  const seenToolCalls: Array<{ name: string; args: unknown }> = [];
  const rawTexts: string[] = [];
  const wrappedGenerate: HandleDeps['generate'] = async (input) => {
    const out = await generate(input);
    for (const tc of out.toolCalls) seenToolCalls.push({ name: tc.toolName, args: tc.args });
    if (out.text.trim().length > 0) rawTexts.push(out.text);
    return out;
  };

  const deps: HandleDeps = {
    db, registry,
    embedQuery: (text) => embed(text, { baseUrl: env.LM_STUDIO_URL, model: env.EMBEDDING_MODEL }),
    skillEmbeddings: cache.bySkillId,
    generate: wrappedGenerate,
    thresholds: { high: 0.75, med: 0.4 },
    ...(haCatalogue ? { entityCatalogue: haCatalogue } : {}),
  };

  console.log('--- BEFORE ---');
  const before = await readSpielzimmer();
  for (const [k, v] of Object.entries(before)) console.log(`  ${k}: pos=${v.pos} tilt=${v.tilt}`);

  const text = 'Mach die Rollos im Spielzimmer zu und neig die Lamellen auf 50%';
  console.log(`\n--- USER ---\n${text}\n`);

  process.env.BYPASS_ROUTER = '1';
  const reply = await handleMessage(deps, {
    kind: 'text', updateId: 12345, chatId: 9000, userId: 5024544400, messageId: 1,
    text, ts: Math.floor(Date.now() / 1000), firstName: 'Philipp',
  });

  console.log(`--- TOOL CALLS (${seenToolCalls.length}) ---`);
  for (const tc of seenToolCalls) console.log(`  ${tc.name}(${JSON.stringify(tc.args)})`);

  console.log(`\n--- REPLY ---\n${reply}\n`);

  // wait so KNX/HA settles before we read final state
  await new Promise(r => setTimeout(r, 4500));
  console.log('--- AFTER ---');
  const after = await readSpielzimmer();
  for (const [k, v] of Object.entries(after)) console.log(`  ${k}: pos=${v.pos} tilt=${v.tilt}`);

  console.log('\n--- RESTORE ---');
  for (const id of SPIELZIMMER_ROLLOS) {
    const b = before[id]!;
    if (b.pos !== undefined) await ha('POST', '/services/cover/set_cover_position', { entity_id: id, position: b.pos });
    if (b.tilt !== undefined) await ha('POST', '/services/cover/set_cover_tilt_position', { entity_id: id, tilt_position: b.tilt });
    console.log(`  ${id}: pos→${b.pos} tilt→${b.tilt}`);
  }
}

main().catch(e => { console.error(e); process.exit(1); });
