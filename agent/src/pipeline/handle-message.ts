import type { Database } from 'bun:sqlite';
import { route, type Thresholds } from '../router/semantic';
import { SkillRegistry } from '../skills/registry';
import { defineSkillTool, inferPositionals } from '../tools/define-skill-tool';
import { buildSystemPrompt } from './system-prompt';
import { appendMessage, recentMessages } from '../memory/history';
import type { ParsedTextUpdate } from '../telegram/webhook';
import type { Tool } from 'ai';
import { log } from '../utils/logger';

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
  const t0 = Date.now();
  log.info('pipeline_start', { updateId: update.updateId, chatId: update.chatId, textLen: update.text.length });
  const ts = update.ts ?? Math.floor(Date.now() / 1000);
  appendMessage(deps.db, { chatId: update.chatId, role: 'user', content: { text: update.text }, ts });

  const tEmbed = Date.now();
  const queryEmbedding = await deps.embedQuery(update.text);
  log.info('embed_done', { ms: Date.now() - tEmbed, dim: queryEmbedding.length });

  const skills = deps.registry.all();
  const routable = skills
    .filter(s => deps.skillEmbeddings[s.id] !== undefined)
    .map(s => ({ id: s.id, embedding: deps.skillEmbeddings[s.id]! }));
  const routed = route(queryEmbedding, routable, deps.thresholds);
  log.info('routed', { band: routed.band, selected: routed.selectedIds, topScore: routed.scores[0]?.score });

  const selectedSkills = deps.registry.all().filter(s => routed.selectedIds.includes(s.id));
  const tools: Record<string, Tool> = {};
  for (const s of selectedSkills) {
    for (const t of s.tools) {
      tools[t.name] = defineSkillTool(t, { positionalArgs: inferPositionals(t) });
    }
  }
  const hasTools = Object.keys(tools).length > 0;
  log.info('tools_built', { count: Object.keys(tools).length, names: Object.keys(tools).slice(0, 5) });

  const system = buildSystemPrompt({
    skills: selectedSkills.map(s => ({ id: s.id, description: s.description })),
    hasTools,
  });

  const history = recentMessages(deps.db, update.chatId, HISTORY_LIMIT)
    .filter(m => m.role !== 'tool')
    .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content.text ?? '' }))
    .filter(m => m.content.length > 0);

  const tGen = Date.now();
  log.info('llm_call_start', { historyLen: history.length, hasTools });
  const out = await deps.generate({
    system,
    messages: history,
    tools,
    reasoningEffort: 'low',
  });
  log.info('llm_call_done', { ms: Date.now() - tGen, textLen: out.text.length, toolCallCount: out.toolCalls.length });

  const reply = out.text.trim() || '(Keine Antwort vom Modell)';
  log.info('pipeline_done', { totalMs: Date.now() - t0, replyLen: reply.length });

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
