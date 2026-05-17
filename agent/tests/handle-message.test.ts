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
    id: 'smart-home',
    description: 'Smart Home steuern',
    triggers: ['licht', 'lampe'],
    intentHints: [],
    scriptPaths: ['/fake/smart_home_api.py'],
    hasContext: true,
    tools: [{
      name: 'smart-home__lights-status',
      scriptPath: '/fake/smart_home_api.py',
      command: 'lights-status',
      description: 'Lichter Status',
      schema: z.object({}),
      isWrite: false,
      positionalArgs: [],
    }],
  }];
  registry.replaceAll(skills);
});

function baseDeps(overrides: Partial<HandleDeps> = {}): HandleDeps {
  return {
    db,
    registry,
    generate: async () => ({ text: 'OK', toolCalls: [], finishReason: 'stop' }),
    llmRouter: { pick: async () => ({ skillId: 'smart-home' }) },
    contextCache: { get: async () => null },
    ...overrides,
  };
}

describe('handleMessage — fast-path (single skill)', () => {
  it('skips llmRouter when only 1 skill is loaded', async () => {
    let routerCalls = 0;
    const deps = baseDeps({
      llmRouter: { pick: async () => { routerCalls++; return null; } },
      generate: async ({ tools }) => {
        expect(Object.keys(tools as object)).toContain('smart-home__lights-status');
        return { text: 'Status: alles ok', toolCalls: [], finishReason: 'stop' };
      },
    });
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 1, chatId: 100, userId: 999, messageId: 1, text: 'welche Lichter sind an?', ts: 1,
    });
    expect(reply).toBe('Status: alles ok');
    expect(routerCalls).toBe(0);
  });

  it('injects skill context block when contextCache returns markdown', async () => {
    let receivedSystem = '';
    const deps = baseDeps({
      contextCache: { get: async () => 'BEKANNTE ENTITIES (smart-home, Snapshot ...)' },
      generate: async ({ system }) => {
        receivedSystem = system;
        return { text: 'OK', toolCalls: [], finishReason: 'stop' };
      },
    });
    await handleMessage(deps, {
      kind: 'text', updateId: 2, chatId: 100, userId: 999, messageId: 1, text: 'Licht im OG an', ts: 1,
    });
    expect(receivedSystem).toContain('BEKANNTE ENTITIES (smart-home');
  });

  it('explains "tools ran but no summary" when text empty after tool calls', async () => {
    const deps = baseDeps({
      generate: async () => ({ text: '', toolCalls: [{ toolName: 'smart-home__lights-status', args: {} }], finishReason: 'stop' }),
    });
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 300, chatId: 700, userId: 999, messageId: 1, text: 'welche Rollos sind offen?', ts: 1,
    });
    expect(reply).not.toContain('finishReason');
    expect(reply.toLowerCase()).toContain('zusammenfassen');
  });

  it('explains truncation when model returns empty text + finishReason=length', async () => {
    const deps = baseDeps({
      generate: async () => ({ text: '', toolCalls: [], finishReason: 'length' }),
    });
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 99, chatId: 300, userId: 999, messageId: 1, text: 'liste alles auf', ts: 1,
    });
    expect(reply.toLowerCase()).toContain('abgeschnitten');
  });

  it('voice: transcribes, runs pipeline, prefixes reply with transcript', async () => {
    const deps = baseDeps({
      generate: async () => ({ text: 'Esstisch ist an.', toolCalls: [], finishReason: 'stop' }),
      transcribeVoice: async (fileId) => {
        expect(fileId).toBe('AwACAGV');
        return 'Mach das Esszimmerlicht an';
      },
    });
    const reply = await handleMessage(deps, {
      kind: 'voice', updateId: 50, chatId: 400, userId: 999, messageId: 1, ts: 1,
      fileId: 'AwACAGV', durationSec: 3,
    });
    expect(reply).toContain('Esszimmerlicht');
    expect(reply).toContain('Esstisch');
  });
});

describe('handleMessage — multi-skill (router-driven)', () => {
  beforeEach(() => {
    registry.replaceAll([
      ...registry.all(),
      {
        id: 'unifi-protect',
        description: 'Kameras',
        triggers: [],
        intentHints: [],
        scriptPaths: ['/fake/unifi_protect_api.py'],
        hasContext: false,
        tools: [{
          name: 'unifi-protect__cameras',
          scriptPath: '/fake/unifi_protect_api.py',
          command: 'cameras',
          description: 'list cameras',
          schema: z.object({}),
          isWrite: false,
          positionalArgs: [],
        }],
      },
    ]);
  });

  it('calls llmRouter and loads only the selected skill\'s tools', async () => {
    let toolNames: string[] = [];
    const deps = baseDeps({
      llmRouter: { pick: async (input) => {
        expect(input.candidates.map(c => c.id).sort()).toEqual(['smart-home', 'unifi-protect']);
        return { skillId: 'smart-home' };
      }},
      generate: async ({ tools }) => {
        toolNames = Object.keys(tools as object);
        return { text: 'OK', toolCalls: [], finishReason: 'stop' };
      },
    });
    await handleMessage(deps, {
      kind: 'text', updateId: 3, chatId: 100, userId: 999, messageId: 1, text: 'licht an', ts: 1,
    });
    expect(toolNames).toEqual(['smart-home__lights-status']);
  });

  it('returns smalltalk reply when llmRouter returns null', async () => {
    const deps = baseDeps({
      llmRouter: { pick: async () => null },
      generate: async ({ tools }) => {
        expect(Object.keys(tools as object)).toHaveLength(0);
        return { text: 'Ich helfe beim Homelab — frag mich gern.', toolCalls: [], finishReason: 'stop' };
      },
    });
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 4, chatId: 100, userId: 999, messageId: 1, text: 'Wie geht es dir?', ts: 1,
    });
    expect(reply).toContain('Homelab');
  });
});
