import type { Database } from 'bun:sqlite';
import { route, type Thresholds } from '../router/semantic';
import { SkillRegistry } from '../skills/registry';
import { defineSkillTool, inferPositionals } from '../tools/define-skill-tool';
import { buildSystemPrompt } from './system-prompt';
import { appendMessage, recentMessages } from '../memory/history';
import type { ParsedTextUpdate } from '../telegram/webhook';
import type { Tool } from 'ai';

export interface GenerateInput {
  system: string;
  messages: Array<{ role: 'user' | 'assistant'; content: string }>;
  tools: Record<string, Tool>;
  reasoningEffort: 'low' | 'high';
}

export interface GenerateOutput {
  text: string;
  toolCalls: Array<{ toolName: string; args: unknown }>;
}

export interface HandleDeps {
  db: Database;
  registry: SkillRegistry;
  embedQuery: (text: string) => Promise<number[]>;
  skillEmbeddings: Record<string, number[]>;
  generate: (input: GenerateInput) => Promise<GenerateOutput>;
  thresholds: Thresholds;
}

const HISTORY_LIMIT = 20;

export async function handleMessage(deps: HandleDeps, update: ParsedTextUpdate): Promise<string> {
  const ts = update.ts ?? Math.floor(Date.now() / 1000);
  appendMessage(deps.db, { chatId: update.chatId, role: 'user', content: { text: update.text }, ts });

  const queryEmbedding = await deps.embedQuery(update.text);
  const skills = deps.registry.all();
  const routable = skills
    .filter(s => deps.skillEmbeddings[s.id] !== undefined)
    .map(s => ({ id: s.id, embedding: deps.skillEmbeddings[s.id]! }));
  const routed = route(queryEmbedding, routable, deps.thresholds);

  const selectedSkills = deps.registry.all().filter(s => routed.selectedIds.includes(s.id));
  const tools: Record<string, Tool> = {};
  for (const s of selectedSkills) {
    for (const t of s.tools) {
      tools[t.name] = defineSkillTool(t, { positionalArgs: inferPositionals(t) });
    }
  }
  const hasTools = Object.keys(tools).length > 0;

  const system = buildSystemPrompt({
    skills: selectedSkills.map(s => ({ id: s.id, description: s.description })),
    hasTools,
  });

  const history = recentMessages(deps.db, update.chatId, HISTORY_LIMIT)
    .filter(m => m.role !== 'tool')
    .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content.text ?? '' }))
    .filter(m => m.content.length > 0);

  const out = await deps.generate({
    system,
    messages: history,
    tools,
    reasoningEffort: 'low',
  });

  const reply = out.text.trim() || '(Keine Antwort vom Modell)';

  appendMessage(deps.db, {
    chatId: update.chatId,
    role: 'assistant',
    content: { text: reply },
    ...(routed.selectedIds[0] !== undefined ? { intent: routed.selectedIds[0] } : {}),
    success: true,
    ts: ts + 1,
  });

  return reply;
}
