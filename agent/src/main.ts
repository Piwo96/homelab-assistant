import { mkdir } from 'node:fs/promises';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEnv } from './config/env';
import { openDb } from './memory/db';
import { loadSkills } from './skills/loader';
import { SkillRegistry } from './skills/registry';
import { embed, embedMany } from './llm/embedding';
import { isLmStudioReachable } from './llm/health';
import { wakeGamingPc } from './wol/wake';
import { sendText } from './telegram/send';
import { downloadTelegramFile } from './telegram/download';
import { transcribeAudio } from './llm/transcribe';
import { fetchHaCatalogue } from './skills/ha-catalogue';
import { computeCacheKey, loadCache, saveCache } from './router/cache';
import { buildGenerator } from './llm/generate';
import { startServer } from './server';
import { log } from './utils/logger';

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../');

function resolveRepoPath(p: string): string {
  if (isAbsolute(p)) return p;
  // Legacy support: values prefixed with `../` were cwd-relative in the old
  // agent/.env.example; treat them as repo-root-relative by stripping the prefix.
  const cleaned = p.replace(/^(\.\.\/)+/, '');
  return resolve(REPO_ROOT, cleaned);
}

async function main(): Promise<void> {
  const env = loadEnv();
  const dataDir = resolveRepoPath(env.DATA_DIR);
  const skillsRoot = resolveRepoPath(env.SKILLS_ROOT);
  await mkdir(dataDir, { recursive: true });
  // New agent uses its own DB file to avoid colliding with agent-old's
  // legacy conversations.db schema. Legacy data is intentionally not migrated.
  const db = openDb(join(dataDir, 'agent.db'));

  const skills = await loadSkills(skillsRoot, ['homeassistant']);
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
  const cachePath = join(dataDir, 'agent-embedding-cache.json');
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

  // Pull a snapshot of all controllable HA entities (lights, switches, covers,
  // climates, scenes, scripts) grouped by area. The agent injects this into
  // the system prompt so the LLM never has to guess entity_ids.
  const haCatalogue = await fetchHaCatalogue(skillsRoot);

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
      healthCheck: () => isLmStudioReachable({ baseUrl: env.LM_STUDIO_URL, timeoutMs: 3000 }),
      wakeGamingPc: () => wakeGamingPc({ skillsRoot, timeoutMs: 150_000 }),
      notifyStatus: async (chatId, text) => {
        await sendText({ botToken: env.TELEGRAM_BOT_TOKEN }, chatId, text);
      },
      transcribeVoice: async (fileId) => {
        const audio = await downloadTelegramFile({ botToken: env.TELEGRAM_BOT_TOKEN }, fileId);
        return transcribeAudio(
          { baseUrl: env.LM_STUDIO_URL, model: env.WHISPER_MODEL },
          { data: audio.data, filename: audio.filename, mimeType: audio.mimeType },
        );
      },
      ...(haCatalogue ? { entityCatalogue: haCatalogue } : {}),
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
