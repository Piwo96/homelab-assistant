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
    expect(p).toContain('TOOL-NUTZUNG');
  });

  it('produces redirect prompt when no tools available', () => {
    const p = buildSystemPrompt({ skills: [], hasTools: false });
    expect(p.toLowerCase()).toContain('homelab');
    expect(p).not.toContain('TOOL-NUTZUNG');
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

  it('includes anti-endless-thinking guidance for follow-up queries', () => {
    const p = buildSystemPrompt({ skills: [{ id: 'x', description: 'y' }], hasTools: true });
    // Must instruct the model to resolve "alle/sie/wieder" via chat history,
    // not re-search; and to ask a clarifying question instead of looping forever.
    expect(p).toContain('FOLGE-ANFRAGEN');
    expect(p).toContain('wieder');
    expect(p).toContain('Rückfrage');
  });

  it('injects HA entity catalogue verbatim and instructs not to invent IDs', () => {
    const catalogue = `### Lichter (light)\n- Büro: \`light.dg_buro_beleuchtung\` (DG Büro Beleuchtung)\n- Esszimmer: \`light.eg_essen_tischleuchte\` (EG Essen Tischleuchte)`;
    const p = buildSystemPrompt({
      skills: [{ id: 'homeassistant', description: 'Smart Home' }],
      hasTools: true,
      entityCatalogue: catalogue,
    });
    expect(p).toContain('light.dg_buro_beleuchtung');
    expect(p).toContain('light.eg_essen_tischleuchte');
    expect(p).toContain('BEKANNTE ENTITIES');
    expect(p.toLowerCase()).toContain('keine entity-ids erfinden');
  });

  it('omits catalogue section cleanly when no catalogue is provided', () => {
    const p = buildSystemPrompt({
      skills: [{ id: 'homeassistant', description: 'Smart Home' }],
      hasTools: true,
    });
    expect(p).not.toContain('BEKANNTE ENTITIES');
    // No trailing whitespace/empty placeholder lines should leak through
    expect(p).not.toMatch(/\{entity_catalogue\}/);
  });

  it('requires confirmation before unbounded mass actions (alle/alles)', () => {
    const p = buildSystemPrompt({ skills: [{ id: 'x', description: 'y' }], hasTools: true });
    expect(p).toContain('UNBESCHRÄNKTE Mehrzahl');
    expect(p).toContain('ZWINGEND zuerst Rückfrage');
  });

  it('forbids inventing current states from the catalogue', () => {
    // Catalogue is name+id only — model must always call get-state/entities
    // for current states. Without this rule Gemma sometimes answered
    // "welche Rollos sind zu?" by guessing from the catalogue entries.
    const p = buildSystemPrompt({
      skills: [{ id: 'homeassistant', description: 'Smart Home' }],
      hasTools: true,
      entityCatalogue: '### Lichter\n- Büro: `light.dg_buro_beleuchtung` (Büro)',
    });
    expect(p).toContain('NIE STATISCH');
    expect(p.toLowerCase()).toContain('keine aktuellen zustände');
  });

  it('teaches the model which cover tool to use (height vs tilt)', () => {
    const p = buildSystemPrompt({ skills: [{ id: 'homeassistant', description: 'Smart Home' }], hasTools: true });
    // Prompt should point at the dedicated tools, NOT leak HA service names.
    expect(p).toContain('cover-set-position');
    expect(p).toContain('cover-set-tilt');
    expect(p).not.toMatch(/set_cover_tilt_position|set_cover_position/);
    // Vocabulary mapping for German user phrasing.
    expect(p.toLowerCase()).toContain('neigen');
    expect(p.toLowerCase()).toContain('lamellen');
  });

  it('steers bulk state queries toward a single entities --state call', () => {
    // The model used to brute-force "welche Rollos sind offen?" with 20+
    // parallel get-state calls; the prompt now nudges it to a single
    // entities --domain X --state Y call instead.
    const p = buildSystemPrompt({ skills: [{ id: 'x', description: 'y' }], hasTools: true });
    expect(p).toContain('KOLLEKTIVE ZUSTANDS-ABFRAGEN');
    expect(p).toContain('entities --domain');
    expect(p).toContain('--state');
    expect(p).toContain('NIEMALS einzelne get-state-Calls');
  });

  it('anchors the output format so the model does not leak its reasoning', () => {
    // Without this anchor the 4B model produced visible Chain-of-Thought
    // monologues ("Gemäß Regel F...", "Tool-Aufruf:") instead of a tool call
    // or clean reply. The OUTPUT-FORMAT block + the explicit "no reasoning
    // monologue" rule is the prompt-side fix.
    const p = buildSystemPrompt({ skills: [{ id: 'x', description: 'y' }], hasTools: true });
    expect(p).toContain('OUTPUT-FORMAT');
    expect(p.toLowerCase()).toContain('reasoning-monolog');
    // Labeled rules ("Regel A", "Regel F") invite the model to quote them
    // back. The new prompt must NOT use them.
    expect(p).not.toMatch(/Regel\s+[A-G]\b/);
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
