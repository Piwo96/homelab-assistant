import { describe, it, expect } from 'bun:test';
import { parseLeakedToolCall, formatRecoveredResult } from '../src/pipeline/leak-recovery';

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
