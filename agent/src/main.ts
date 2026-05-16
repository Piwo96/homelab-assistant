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
