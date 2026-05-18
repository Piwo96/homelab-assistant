import { describe, it, expect } from 'bun:test';
import { parseLeakedToolCall, formatRecoveredResult } from '../src/pipeline/leak-recovery';
import { extractActualReply } from '../src/pipeline/handle-message';

describe('parseLeakedToolCall', () => {
  it('extracts from {tool_name, parameters} shape with smart-home prefix', () => {
    const parsed = parseLeakedToolCall(`\`\`\`json
{"tool_name": "smart-home_lights-status", "parameters": {"where": "OG"}}
\`\`\``);
    expect(parsed).toEqual({ toolName: 'smart-home__lights-status', args: { where: 'OG' } });
  });

  it('extracts from {tool_calls: [{function, args}]} shape', () => {
    const parsed = parseLeakedToolCall(`{
      "tool_calls": [
        { "function": "smart-home_rollos-status", "args": { "where": "DG" } }
      ]
    }`);
    expect(parsed?.toolName).toBe('smart-home__rollos-status');
    expect(parsed?.args).toEqual({ where: 'DG' });
  });

  it('normalizes underscores in the command part (lights_status → lights-status)', () => {
    const parsed = parseLeakedToolCall('{"tool_name":"smart-home_lights_status","parameters":{}}');
    expect(parsed?.toolName).toBe('smart-home__lights-status');
  });

  it('handles already-namespaced form smart-home__lights-on', () => {
    const parsed = parseLeakedToolCall('{"tool_name":"smart-home__lights-on","parameters":{"where":"Esstisch"}}');
    expect(parsed?.toolName).toBe('smart-home__lights-on');
  });

  it('returns null when no JSON found', () => {
    expect(parseLeakedToolCall('Ich denke das Licht ist an.')).toBeNull();
  });
});

describe('formatRecoveredResult', () => {
  it('formats successful lights-status with counts', () => {
    const reply = formatRecoveredResult(
      { toolName: 'smart-home__lights-status', args: { where: 'OG', state: 'on' } },
      { ok: true, action: 'lights-status', count: 3, lights: [
        { entity_id: 'light.og_kind_1', friendly_name: 'OG Kind 1', state: 'on', brightness: 200 },
        { entity_id: 'light.og_buero', friendly_name: 'OG Büro', state: 'on', brightness: null },
        { entity_id: 'light.og_bad', friendly_name: 'OG Bad', state: 'on', brightness: null },
      ]},
    );
    expect(reply).toContain('OG Kind 1');
    expect(reply.toLowerCase()).toContain('on');
  });

  it('formats successful write actions (lights-on) with affected count', () => {
    const reply = formatRecoveredResult(
      { toolName: 'smart-home__lights-on', args: { where: 'Wohnzimmer' } },
      { ok: true, action: 'lights-on', label: 'Wohnzimmer', match_kind: 'area',
        entities_affected: ['light.eg_wohnzimmer_decke', 'light.eg_wohnzimmer_steh'] },
    );
    expect(reply).toMatch(/wohnzimmer/i);
    expect(reply).toContain('2');
  });

  it('surfaces tool error message verbatim when ok=false', () => {
    const reply = formatRecoveredResult(
      { toolName: 'smart-home__lights-on', args: { where: 'foo' } },
      { ok: false, error: "Keine Lichter gefunden für 'foo'", match_kind: 'none' },
    );
    expect(reply).toContain("Keine Lichter gefunden für 'foo'");
  });
});

describe('extractActualReply', () => {
  it('recovers the trailing answer from a Gemma reasoning-prose leak', () => {
    // Golden case from a real Telegram screenshot: model emitted three lines of
    // reasoning ("Die Anfrage ist...", "Daher kann...", "Die Antwort muss...")
    // plus a "Plan: ..." line, THEN the actual answer. The user saw all of it.
    const leaked = [
      'Die Anfrage ist eine allgemeine Begrüßung ("Wie geht es dir?") und betrifft keine Steuerung von Smart-Home-Geräten.',
      'Daher kann kein Tool aufgerufen werden.',
      'Die Antwort muss freundlich, aber sachlich im Rahmen der Rolle als Homelab-Assistent sein.',
      '',
      'Plan: Freundliche Rückmeldung geben und das Thema zurück zur Haussteuerung lenken.',
      'Mir geht es gut, danke der Nachfrage. Ich bin bereit, dir bei deinen Smart-Home-Aufgaben zu helfen. Was kann ich für dich tun?',
    ].join('\n');
    const out = extractActualReply(leaked);
    expect(out).not.toBeNull();
    expect(out!).toContain('Mir geht es gut');
    expect(out!).not.toContain('Plan:');
    expect(out!).not.toContain('Die Anfrage');
    expect(out!).not.toContain('Daher kann');
  });

  it('returns null when everything looks like reasoning (no clean tail)', () => {
    const allReasoning = 'Plan: A.\nSchritt 1: B.\nIch muss C.';
    expect(extractActualReply(allReasoning)).toBeNull();
  });

  it('returns null when the trailing tail is too short to be a real reply', () => {
    // "Ja." after pages of reasoning is almost certainly a mid-thought
    // utterance, not the user-facing answer.
    expect(extractActualReply('Plan: schalten.\nJa.')).toBeNull();
  });

  it('passes through a clean reply unchanged (no markers anywhere)', () => {
    const clean = 'Im Erdgeschoss sind momentan die Küche Spots 1 und Küche Spots 2 eingeschaltet.';
    expect(extractActualReply(clean)).toBe(clean);
  });

  it('strips "Tool-Aufruf:" / "Argumente:" prefix and returns the actual text after', () => {
    const leaked = 'Tool-Aufruf: lights-status\nArgumente: --where OG\nIm OG ist gerade alles aus.';
    const out = extractActualReply(leaked);
    expect(out).toBe('Im OG ist gerade alles aus.');
  });
});
