import { describe, it, expect } from 'bun:test';
import { parseRouterResponse, buildRouterPrompt } from '../src/router/llm-router';

describe('parseRouterResponse', () => {
  const candidates = ['smart-home', 'unifi-protect'];

  it('parses plain JSON {"skill":"smart-home"}', () => {
    expect(parseRouterResponse('{"skill":"smart-home"}', candidates)).toEqual({ skillId: 'smart-home' });
  });

  it('parses JSON wrapped in markdown code fences', () => {
    expect(parseRouterResponse('```json\n{"skill":"unifi-protect"}\n```', candidates))
      .toEqual({ skillId: 'unifi-protect' });
  });

  it('parses JSON with surrounding whitespace and prose', () => {
    expect(parseRouterResponse('Sure, here is the answer:\n  {"skill": "smart-home"}  \n', candidates))
      .toEqual({ skillId: 'smart-home' });
  });

  it('returns null for {"skill":null}', () => {
    expect(parseRouterResponse('{"skill":null}', candidates)).toBeNull();
  });

  it('returns null when skill name is unknown', () => {
    expect(parseRouterResponse('{"skill":"made-up"}', candidates)).toBeNull();
  });

  it('returns null when JSON is malformed', () => {
    expect(parseRouterResponse('not json at all', candidates)).toBeNull();
    expect(parseRouterResponse('{"skill"', candidates)).toBeNull();
  });
});

describe('buildRouterPrompt', () => {
  it('lists candidates and includes user message + recent context', () => {
    const prompt = buildRouterPrompt({
      msg: 'Licht im Wohnzimmer aus',
      recentMessages: [
        { role: 'user', content: 'Hallo' },
        { role: 'assistant', content: 'Hi, was brauchst du?' },
      ],
      candidates: [
        { id: 'smart-home', description: 'Lichter / Rollos / Heizung steuern' },
        { id: 'unifi-protect', description: 'Kameras und Bewegungen' },
      ],
    });
    expect(prompt).toContain('smart-home');
    expect(prompt).toContain('unifi-protect');
    expect(prompt).toContain('Licht im Wohnzimmer aus');
    expect(prompt).toContain('Hallo');
  });
});
