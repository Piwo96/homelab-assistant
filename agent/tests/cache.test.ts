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
