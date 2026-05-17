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
  /** Start a background refresh loop. Each hasContext skill is refetched once
   *  per ttlMs (offset slightly so all skills don't refetch simultaneously).
   *  Safe to call multiple times — subsequent calls are no-ops. */
  start(): void;
  /** Stop the background refresh loop. Useful in tests. */
  stop(): void;
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
  const refreshTimers: ReturnType<typeof setInterval>[] = [];

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

    start(): void {
      if (refreshTimers.length > 0) return; // already started
      const skillsWithContext = opts.skills.filter(s => s.hasContext);
      // Stagger the timer offsets so N skills don't all refetch at the same
      // moment. With 1 skill, jitter is 0. With 4 skills + TTL=30min, each
      // skill is offset by 7.5 minutes from the next.
      const jitterStep = skillsWithContext.length > 0 ? Math.floor(opts.ttlMs / skillsWithContext.length) : 0;
      skillsWithContext.forEach((s, i) => {
        // Initial fetch fires immediately on start (not after one TTL period)
        // so the very first user message after startup has the catalogue
        // already in memory.
        fetchOnce(s.id).catch(() => { /* logged in fetchOnce */ });

        const offset = i * jitterStep;
        const t = setTimeout(() => {
          const interval = setInterval(() => {
            fetchOnce(s.id).catch(() => { /* logged in fetchOnce */ });
          }, opts.ttlMs);
          if (typeof interval.unref === 'function') interval.unref();
          refreshTimers.push(interval);
        }, offset);
        if (typeof t.unref === 'function') t.unref();
        // Track the setTimeout too so stop() can cancel pre-interval timers.
        refreshTimers.push(t as unknown as ReturnType<typeof setInterval>);
      });
      log.info('skill_context_cache_started', {
        skills: skillsWithContext.map(s => s.id),
        ttlMs: opts.ttlMs,
      });
    },

    stop(): void {
      for (const t of refreshTimers) {
        clearInterval(t);
        clearTimeout(t as unknown as ReturnType<typeof setTimeout>);
      }
      refreshTimers.length = 0;
    },
  };
}
