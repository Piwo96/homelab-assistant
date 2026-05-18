import { describe, it, expect } from 'bun:test';
import { buildWelcomeText } from '../src/pipeline/welcome';
import type { LoadedSkill } from '../src/skills/loader';

function skill(id: string, welcomeGroups: LoadedSkill['welcomeGroups']): LoadedSkill {
  return {
    id,
    description: '',
    triggers: [],
    intentHints: [],
    scriptPaths: [],
    tools: [],
    hasContext: false,
    welcomeGroups,
    body: '',
  };
}

describe('buildWelcomeText', () => {
  it('renders the "Hi Rolly Mitglied" greeting at the top', () => {
    const out = buildWelcomeText([skill('x', [{ heading: 'A', examples: ['eins'] }])]);
    expect(out.startsWith('Hi Rolly Mitglied ☺️')).toBe(true);
  });

  it('emits one bullet line per group with quoted examples', () => {
    const out = buildWelcomeText([
      skill('smart-home', [
        { heading: 'Lichter', examples: ['Wohnzimmer an', 'OG aus'] },
        { heading: 'Heizung', examples: ['Bad auf 22'] },
      ]),
    ]);
    expect(out).toContain('• Lichter: „Wohnzimmer an", „OG aus"');
    expect(out).toContain('• Heizung: „Bad auf 22"');
  });

  it('concatenates groups across multiple skills in load order', () => {
    const out = buildWelcomeText([
      skill('a', [{ heading: 'A1', examples: ['a1'] }]),
      skill('b', [{ heading: 'B1', examples: ['b1'] }]),
    ]);
    expect(out.indexOf('• A1:')).toBeLessThan(out.indexOf('• B1:'));
  });

  it('falls back to a minimal greeting when no skill advertises examples', () => {
    const out = buildWelcomeText([skill('silent', [])]);
    expect(out).toContain('Hi Rolly Mitglied ☺️');
    expect(out).toContain('keine aktiven Skills');
    expect(out).not.toContain('•');
  });

  it('always ends with the voice-message hint when groups exist', () => {
    const out = buildWelcomeText([skill('x', [{ heading: 'A', examples: ['eins'] }])]);
    expect(out.trimEnd().endsWith('ich transkribiere und führe aus.')).toBe(true);
  });
});
