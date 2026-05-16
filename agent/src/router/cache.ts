import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
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
  const tmp = `${path}.tmp`;
  await writeFile(tmp, JSON.stringify(cache, null, 2));
  await rename(tmp, path);
}
