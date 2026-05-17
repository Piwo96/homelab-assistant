import { describe, it, expect } from 'bun:test';
import { parseLeakedToolCall, formatRecoveredResult } from '../src/pipeline/leak-recovery';

describe('parseLeakedToolCall', () => {
  it('extracts from {tool_name, parameters} shape', () => {
    const parsed = parseLeakedToolCall(`\`\`\`json
{"tool_name": "homeassistant_get_state", "parameters": {"entity_id": "light.dg_buro_beleuchtung"}}
\`\`\``);
    expect(parsed).toEqual({ toolName: 'homeassistant__get-state', args: { entity_id: 'light.dg_buro_beleuchtung' } });
  });

  it('extracts from {tool_calls: [{function, args}]} shape', () => {
    const parsed = parseLeakedToolCall(`{
      "tool_calls": [
        { "function": "homeassistant_entities", "args": { "domain": "cover", "state": "open" } }
      ]
    }`);
    expect(parsed?.toolName).toBe('homeassistant__entities');
    expect(parsed?.args).toEqual({ domain: 'cover', state: 'open' });
  });

  it('normalizes underscore command names to hyphen form (get_state → get-state)', () => {
    // Real captured leak that broke recovery: Gemma writes
    // `homeassistant_get_state` but the registry has `homeassistant__get-state`.
    const parsed = parseLeakedToolCall('{"tool_name":"homeassistant_get_state","parameters":{"entity_id":"light.x"}}');
    expect(parsed?.toolName).toBe('homeassistant__get-state');
  });

  it('normalizes turn_on → turn-on, call_service → call-service', () => {
    expect(parseLeakedToolCall('{"tool_name":"homeassistant_turn_on","parameters":{}}')?.toolName)
      .toBe('homeassistant__turn-on');
    expect(parseLeakedToolCall('{"tool_name":"homeassistant_call_service","parameters":{}}')?.toolName)
      .toBe('homeassistant__call-service');
  });

  it('handles homeassistant__entities (already-namespaced) without re-splitting', () => {
    const parsed = parseLeakedToolCall('{"tool_name": "homeassistant__entities", "parameters": {"domain": "light"}}');
    expect(parsed?.toolName).toBe('homeassistant__entities');
  });

  it('returns null when no JSON found', () => {
    expect(parseLeakedToolCall('Ich denke das Licht ist an.')).toBeNull();
  });

  it('returns null when JSON has neither tool_name nor tool_calls', () => {
    expect(parseLeakedToolCall('{"foo": "bar"}')).toBeNull();
  });
});

describe('formatRecoveredResult', () => {
  it('formats entities list as bullet points with friendly_name + state', () => {
    const reply = formatRecoveredResult(
      { toolName: 'homeassistant__entities', args: { domain: 'cover', state: 'open' } },
      [
        { entity_id: 'cover.dg_buro_rollo', state: 'open', attributes: { friendly_name: 'DG Büro Rollo' } },
        { entity_id: 'cover.eg_wc_rollo', state: 'open', attributes: { friendly_name: 'EG WC Rollo' } },
      ],
    );
    expect(reply).toContain('DG Büro Rollo');
    expect(reply).toContain('open');
    expect(reply).toContain('•');
  });

  it('caps very long entity lists with a "filter more" hint', () => {
    const longList = Array.from({ length: 30 }, (_, i) => ({
      entity_id: `light.x${i}`, state: 'off', attributes: { friendly_name: `Light ${i}` },
    }));
    const reply = formatRecoveredResult(
      { toolName: 'homeassistant__entities', args: { domain: 'light' } },
      longList,
    );
    expect(reply).toContain('30 Treffer');
    expect(reply.toLowerCase()).toContain('enger filtern');
  });

  it('formats single get-state result', () => {
    const reply = formatRecoveredResult(
      { toolName: 'homeassistant__get-state', args: { entity_id: 'light.dg_buro_beleuchtung' } },
      { entity_id: 'light.dg_buro_beleuchtung', state: 'off', attributes: { friendly_name: 'DG Büro Beleuchtung' } },
    );
    expect(reply).toBe('DG Büro Beleuchtung: off');
  });

  it('formats turn-on / turn-off with the entity', () => {
    expect(formatRecoveredResult(
      { toolName: 'homeassistant__turn-on', args: { entity_id: 'light.eg_essen_tischleuchte' } },
      [{ ok: true }],
    )).toContain('eingeschaltet');
    expect(formatRecoveredResult(
      { toolName: 'homeassistant__turn-off', args: { entity_id: 'light.eg_essen_tischleuchte' } },
      [{ ok: true }],
    )).toContain('ausgeschaltet');
  });
});
