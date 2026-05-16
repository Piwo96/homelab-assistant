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
