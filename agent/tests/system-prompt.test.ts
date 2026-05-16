import { describe, it, expect } from 'bun:test';
import { buildSystemPrompt } from '../src/pipeline/system-prompt';

describe('buildSystemPrompt', () => {
  it('lists tool-bearing skills with their descriptions', () => {
    const p = buildSystemPrompt({
      skills: [
        { id: 'homeassistant', description: 'Smart Home steuern' },
      ],
      hasTools: true,
    });
    expect(p).toContain('homeassistant');
    expect(p).toContain('Smart Home steuern');
    expect(p).toContain('Wenn ein Tool passt');
  });

  it('produces redirect prompt when no tools available', () => {
    const p = buildSystemPrompt({ skills: [], hasTools: false });
    expect(p.toLowerCase()).toContain('homelab');
    expect(p).not.toContain('Wenn ein Tool passt');
  });
});
