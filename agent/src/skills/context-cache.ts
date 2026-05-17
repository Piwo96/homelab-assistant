import { log } from '../utils/logger';

export interface SkillContextCacheOpts {
  skills: ReadonlyArray<{ id: string; hasContext: boolean }>;
  /** Fetch a fresh markdown block for the skill. Throws on failure. */
  fetch: (skillId: string) => Promise<string>;
  /** Cache TTL in ms; entries older than this are refetched on the next get(). */
  ttlMs: number;
}

export interface SkillContextCache {
  get(skillId: string): Promise<string | null>;
}

interface Entry {
  markdown: string;
  fetchedAt: number;
}

export function createSkillContextCache(opts: SkillContextCacheOpts): SkillContextCache {
  const hasContextById = new Map(opts.skills.map(s => [s.id, s.hasContext] as const));
  const entries = new Map<string, Entry>();
  // Coalesce concurrent fetches for the same skill so a burst of requests
  // doesn't trigger N parallel python subprocesses.
  const inflight = new Map<string, Promise<string | null>>();

  async function fetchOnce(skillId: string): Promise<string | null> {
    const existing = inflight.get(skillId);
    if (existing) return existing;
    const p = (async () => {
      try {
        const md = await opts.fetch(skillId);
        entries.set(skillId, { markdown: md, fetchedAt: Date.now() });
        return md;
      } catch (err) {
        const prev = entries.get(skillId);
        if (prev) {
          log.warn('skill_context_refresh_failed_keeping_old', { skillId, err: String(err) });
          return prev.markdown;
        }
        log.warn('skill_context_fetch_failed_no_prior_value', { skillId, err: String(err) });
        return null;
      } finally {
        inflight.delete(skillId);
      }
    })();
    inflight.set(skillId, p);
    return p;
  }

  return {
    async get(skillId: string): Promise<string | null> {
      if (!hasContextById.get(skillId)) return null;
      const entry = entries.get(skillId);
      if (entry && Date.now() - entry.fetchedAt < opts.ttlMs) {
        return entry.markdown;
      }
      return fetchOnce(skillId);
    },
  };
}
