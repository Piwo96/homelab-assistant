import { describe, it, expect } from 'bun:test';
import { buildSystemPrompt, buildWelcomePrompt } from '../src/pipeline/system-prompt';

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
    expect(p).toContain('Tool-Aufrufe');
  });

  it('produces redirect prompt when no tools available', () => {
    const p = buildSystemPrompt({ skills: [], hasTools: false });
    expect(p.toLowerCase()).toContain('homelab');
    expect(p).not.toContain('Tool-Aufrufe');
  });

  it('injects firstName so the LLM addresses the right user', () => {
    const p = buildSystemPrompt({ skills: [], hasTools: false, firstName: 'Sophia' });
    expect(p).toContain('Sophia');
    // Owner-vs-user distinction must remain explicit even when firstName is set
    expect(p).toContain('Philipp');
  });

  it('explicitly tells the model not to assume a name when firstName missing', () => {
    const p = buildSystemPrompt({ skills: [], hasTools: false });
    expect(p).toContain('unbekannt');
  });
});

describe('buildWelcomePrompt', () => {
  it('uses the supplied firstName as greeting target', () => {
    const p = buildWelcomePrompt({ firstName: 'Sophia' });
    expect(p).toContain('Sophia');
    expect(p).toContain('/start');
  });

  it('falls back gracefully when no firstName is known', () => {
    const p = buildWelcomePrompt();
    expect(p).toContain('unbekannt');
  });
});
