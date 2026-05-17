import { describe, it, expect, beforeEach } from 'bun:test';
import { Database } from 'bun:sqlite';
import { initDb } from '../src/memory/db';
import { handleMessage, type HandleDeps } from '../src/pipeline/handle-message';
import { SkillRegistry } from '../src/skills/registry';
import { z } from 'zod';
import type { LoadedSkill } from '../src/skills/loader';

let db: Database;
let registry: SkillRegistry;

beforeEach(() => {
  db = new Database(':memory:'); initDb(db);
  registry = new SkillRegistry();
  const skills: LoadedSkill[] = [{
    id: 'homeassistant',
    description: 'Smart Home steuern',
    triggers: ['licht', 'lampe'],
    intentHints: [],
    scriptPaths: ['/fake/homeassistant_api.py'],
    tools: [{
      name: 'homeassistant__status',
      scriptPath: '/fake/homeassistant_api.py',
      command: 'status',
      description: 'HA Status',
      schema: z.object({}),
      isWrite: false,
    }],
  }];
  registry.replaceAll(skills);
});

describe('handleMessage', () => {
  it('routes high-confidence query and calls generateText', async () => {
    let receivedTools: Record<string, unknown> = {};
    const deps: HandleDeps = {
      db,
      registry,
      embedQuery: async () => [1, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async ({ tools }) => {
        receivedTools = tools as Record<string, unknown>;
        return { text: 'Status: alles ok', toolCalls: [], finishReason: 'stop' };
      },
      thresholds: { high: 0.75, med: 0.4 },
    };
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 1, chatId: 100, userId: 999, messageId: 1, text: 'HA Status?', ts: 1,
    });
    expect(reply).toBe('Status: alles ok');
    expect(Object.keys(receivedTools)).toContain('homeassistant__status');
  });

  it('returns smalltalk redirect when LOW band', async () => {
    const deps: HandleDeps = {
      db,
      registry,
      embedQuery: async () => [0, 0, 0.1],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async ({ tools }) => {
        expect(Object.keys(tools as object)).toHaveLength(0);
        return { text: 'Ich helfe beim Homelab — frag mich z. B. nach Lichtern.', toolCalls: [], finishReason: 'stop' };
      },
      thresholds: { high: 0.75, med: 0.4 },
    };
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 2, chatId: 100, userId: 999, messageId: 2, text: 'Wie geht es dir?', ts: 1,
    });
    expect(reply).toContain('Homelab');
  });

  it('explains "tools ran but no summary" when text empty after tool calls', async () => {
    const deps: HandleDeps = {
      db, registry,
      embedQuery: async () => [1, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      // Model called tools but produced no final text (the "Keine Antwort
      // vom Modell, finishReason=stop" scenario).
      generate: async () => ({ text: '', toolCalls: [{ toolName: 'homeassistant__get-state', args: {} }], finishReason: 'stop' }),
      thresholds: { high: 0.75, med: 0.4 },
    };
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 300, chatId: 700, userId: 999, messageId: 1, text: 'welche Rollos sind offen?', ts: 1,
    });
    expect(reply).not.toContain('finishReason');
    expect(reply.toLowerCase()).toContain('zusammenfassen');
  });

  it('explains truncation to user when model returns empty text + finishReason=length', async () => {
    const deps: HandleDeps = {
      db, registry,
      embedQuery: async () => [1, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async () => ({ text: '', toolCalls: [], finishReason: 'length' }),
      thresholds: { high: 0.75, med: 0.4 },
    };
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 99, chatId: 300, userId: 999, messageId: 1, text: 'liste alles auf', ts: 1,
    });
    expect(reply.toLowerCase()).toContain('abgeschnitten');
    expect(reply).not.toContain('Keine Antwort');
  });

  it('voice: transcribes, runs text pipeline, and prefixes reply with transcript', async () => {
    const deps: HandleDeps = {
      db, registry,
      embedQuery: async () => [1, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async () => ({ text: 'Esstisch ist an.', toolCalls: [], finishReason: 'stop' }),
      thresholds: { high: 0.75, med: 0.4 },
      transcribeVoice: async (fileId) => {
        expect(fileId).toBe('AwACAGV');
        return 'Mach das Esszimmerlicht an';
      },
    };
    const reply = await handleMessage(deps, {
      kind: 'voice', updateId: 50, chatId: 400, userId: 999, messageId: 1, ts: 1,
      fileId: 'AwACAGV', durationSec: 3,
    });
    expect(reply).toContain('🎤');
    expect(reply).toContain('Mach das Esszimmerlicht an');
    expect(reply).toContain('Esstisch ist an.');
    // Persisted user message should be the TRANSCRIPT (so future tool-calls
    // can reference what the user just asked), not the raw voice metadata.
    const userRow = db.prepare('SELECT content FROM conversations WHERE chat_id=400 AND role=?').get('user') as { content: string } | undefined;
    expect(userRow?.content).toContain('Mach das Esszimmerlicht an');
  });

  it('voice: returns friendly error when transcribeVoice is not wired', async () => {
    const deps: HandleDeps = {
      db, registry,
      embedQuery: async () => [1, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async () => ({ text: 'should not be called', toolCalls: [], finishReason: 'stop' }),
      thresholds: { high: 0.75, med: 0.4 },
    };
    const reply = await handleMessage(deps, {
      kind: 'voice', updateId: 51, chatId: 401, userId: 999, messageId: 1, ts: 1,
      fileId: 'X', durationSec: 1,
    });
    expect(reply.toLowerCase()).toContain('sprachnachrichten');
  });

  it('voice: empty transcript asks user to speak clearer / write', async () => {
    const deps: HandleDeps = {
      db, registry,
      embedQuery: async () => [1, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async () => ({ text: 'never', toolCalls: [], finishReason: 'stop' }),
      thresholds: { high: 0.75, med: 0.4 },
      transcribeVoice: async () => '   ',
    };
    const reply = await handleMessage(deps, {
      kind: 'voice', updateId: 52, chatId: 402, userId: 999, messageId: 1, ts: 1,
      fileId: 'X', durationSec: 1,
    });
    expect(reply).toContain('🎤');
    expect(reply.toLowerCase()).toContain('verstehen');
  });

  it('detects Gemma-style JSON pseudo-tool-call blocks in smalltalk replies', async () => {
    // Real Gemma output observed in prod for "Erzähl mir einen Witz":
    // dumped a JSON code block describing an intended tool call into a mode
    // where no tools were even available. Detector must catch this.
    const fakeJsonLeak = '```json\n{"tool_name": "homeassistant_get_state", "parameters": {"entity_id": "sensor.witz"}}\n```\nIch kann dir leider keinen Witz erzählen.';
    const deps: HandleDeps = {
      db, registry,
      embedQuery: async () => [0, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async () => ({ text: fakeJsonLeak, toolCalls: [], finishReason: 'stop' }),
      thresholds: { high: 0.75, med: 0.4 },
    };
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 400, chatId: 800, userId: 999, messageId: 1, text: 'Erzähl mir einen Witz', ts: 1,
    });
    expect(reply).not.toContain('tool_name');
    expect(reply).not.toContain('```json');
    expect(reply.toLowerCase()).toContain('gedanken');
  });

  it('replaces leaked chain-of-thought with a clean error instead of shipping it', async () => {
    const leakedMonologue = `Die letzte Aktion betraf das Ausschalten von "alle" Lichtern im Esszimmer.

Gemäß Regel F beziehen sich Bezugswörter wie "alle" auf die Entities aus den letzten Nachrichten.

Tool-Aufruf: homeassistant_turn_off
Argumente: entity_id = "light.eg_essen_tischleuchte"`;
    const deps: HandleDeps = {
      db, registry,
      embedQuery: async () => [1, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async () => ({ text: leakedMonologue, toolCalls: [], finishReason: 'stop' }),
      thresholds: { high: 0.75, med: 0.4 },
    };
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 200, chatId: 500, userId: 999, messageId: 1, text: 'alle aus', ts: 1,
    });
    expect(reply).not.toContain('Gemäß Regel');
    expect(reply).not.toContain('Tool-Aufruf:');
    expect(reply.toLowerCase()).toContain('gedanken');
  });

  it('persists user msg + assistant reply to history', async () => {
    const deps: HandleDeps = {
      db, registry,
      embedQuery: async () => [1, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async () => ({ text: 'Reply', toolCalls: [], finishReason: 'stop' }),
      thresholds: { high: 0.75, med: 0.4 },
    };
    await handleMessage(deps, {
      kind: 'text', updateId: 3, chatId: 200, userId: 999, messageId: 1, text: 'Status', ts: 1,
    });
    const rows = db.prepare('SELECT role, content FROM conversations WHERE chat_id=200 ORDER BY ts').all() as Array<{ role: string; content: string }>;
    expect(rows).toHaveLength(2);
    expect(rows[0]?.role).toBe('user');
    expect(rows[1]?.role).toBe('assistant');
  });
});
