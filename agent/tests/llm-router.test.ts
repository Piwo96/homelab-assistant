import { describe, it, expect } from 'bun:test';
import { buildRouterPrompt } from '../src/router/llm-router';

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

  it('shows "(keine)" when recent messages are empty', () => {
    const prompt = buildRouterPrompt({
      msg: 'test',
      recentMessages: [],
      candidates: [{ id: 'smart-home', description: 'foo' }],
    });
    expect(prompt).toContain('(keine)');
  });
});
