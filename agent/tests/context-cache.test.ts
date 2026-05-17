import { describe, it, expect } from 'bun:test';
import { createSkillContextCache } from '../src/skills/context-cache';

describe('SkillContextCache', () => {
  it('returns null for skills without context', async () => {
    const cache = createSkillContextCache({
      skills: [{ id: 'wol', hasContext: false }],
      fetch: async () => '',
      ttlMs: 1000,
    });
    expect(await cache.get('wol')).toBeNull();
  });

  it('fetches lazily on first get and caches', async () => {
    let calls = 0;
    const cache = createSkillContextCache({
      skills: [{ id: 'smart-home', hasContext: true }],
      fetch: async () => { calls++; return `markdown-${calls}`; },
      ttlMs: 60_000,
    });
    expect(await cache.get('smart-home')).toBe('markdown-1');
    expect(await cache.get('smart-home')).toBe('markdown-1');
    expect(calls).toBe(1);
  });

  it('refetches after ttl expires', async () => {
    let calls = 0;
    const cache = createSkillContextCache({
      skills: [{ id: 'smart-home', hasContext: true }],
      fetch: async () => { calls++; return `markdown-${calls}`; },
      ttlMs: 10,
    });
    expect(await cache.get('smart-home')).toBe('markdown-1');
    await new Promise(r => setTimeout(r, 20));
    expect(await cache.get('smart-home')).toBe('markdown-2');
  });

  it('keeps previous value when fetch fails', async () => {
    let calls = 0;
    const cache = createSkillContextCache({
      skills: [{ id: 'smart-home', hasContext: true }],
      fetch: async () => {
        calls++;
        if (calls === 1) return 'good';
        throw new Error('HA unreachable');
      },
      ttlMs: 10,
    });
    expect(await cache.get('smart-home')).toBe('good');
    await new Promise(r => setTimeout(r, 20));
    expect(await cache.get('smart-home')).toBe('good');
  });

  it('returns null on first-fetch failure (no previous value)', async () => {
    const cache = createSkillContextCache({
      skills: [{ id: 'smart-home', hasContext: true }],
      fetch: async () => { throw new Error('boom'); },
      ttlMs: 1000,
    });
    expect(await cache.get('smart-home')).toBeNull();
  });

  it('start() triggers an immediate initial fetch', async () => {
    let calls = 0;
    const cache = createSkillContextCache({
      skills: [{ id: 'smart-home', hasContext: true }],
      fetch: async () => { calls++; return `markdown-${calls}`; },
      ttlMs: 60_000,
    });
    cache.start();
    // Give the immediate fetch a tick to resolve.
    await new Promise(r => setTimeout(r, 5));
    expect(calls).toBe(1);
    // get() should hit cache, not refetch.
    expect(await cache.get('smart-home')).toBe('markdown-1');
    expect(calls).toBe(1);
    cache.stop();
  });

  it('start() is idempotent (subsequent calls no-op)', async () => {
    let calls = 0;
    const cache = createSkillContextCache({
      skills: [{ id: 'smart-home', hasContext: true }],
      fetch: async () => { calls++; return `markdown-${calls}`; },
      ttlMs: 60_000,
    });
    cache.start();
    cache.start();  // should be no-op
    await new Promise(r => setTimeout(r, 5));
    expect(calls).toBe(1); // not 2
    cache.stop();
  });

  it('skips background refresh for skills without context', async () => {
    let calls = 0;
    const cache = createSkillContextCache({
      skills: [
        { id: 'smart-home', hasContext: true },
        { id: 'wol', hasContext: false },
      ],
      fetch: async (id) => { calls++; return `md-${id}-${calls}`; },
      ttlMs: 60_000,
    });
    cache.start();
    await new Promise(r => setTimeout(r, 5));
    expect(calls).toBe(1); // only smart-home was fetched
    cache.stop();
  });
});
