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
        return { text: 'Status: alles ok', toolCalls: [] };
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
        return { text: 'Ich helfe beim Homelab — frag mich z. B. nach Lichtern.', toolCalls: [] };
      },
      thresholds: { high: 0.75, med: 0.4 },
    };
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 2, chatId: 100, userId: 999, messageId: 2, text: 'Wie geht es dir?', ts: 1,
    });
    expect(reply).toContain('Homelab');
  });

  it('persists user msg + assistant reply to history', async () => {
    const deps: HandleDeps = {
      db, registry,
      embedQuery: async () => [1, 0, 0],
      skillEmbeddings: { homeassistant: [1, 0, 0] },
      generate: async () => ({ text: 'Reply', toolCalls: [] }),
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
