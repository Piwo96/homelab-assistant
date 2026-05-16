import { describe, it, expect } from 'bun:test';
import { sha256Hex } from '../src/utils/sha256';

describe('sha256Hex', () => {
  it('returns 64-char hex digest', async () => {
    const d = await sha256Hex('hello');
    expect(d).toMatch(/^[0-9a-f]{64}$/);
    expect(d).toBe('2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824');
  });

  it('is deterministic', async () => {
    const a = await sha256Hex('x');
    const b = await sha256Hex('x');
    expect(a).toBe(b);
  });
});
