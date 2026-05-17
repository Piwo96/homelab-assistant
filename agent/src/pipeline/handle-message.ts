import type { Database } from 'bun:sqlite';
import { route, type Thresholds } from '../router/semantic';
import { SkillRegistry } from '../skills/registry';
import { defineSkillTool, inferPositionals } from '../tools/define-skill-tool';
import { buildSystemPrompt, buildWelcomePrompt } from './system-prompt';
import { appendMessage, clearHistory, recentMessages } from '../memory/history';
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
  /** Optional: quick reachability check for LM Studio (returns true if up). */
  healthCheck?: () => Promise<boolean>;
  /** Optional: triggers Wake-on-LAN + waits until LM Studio answers again. */
  wakeGamingPc?: () => Promise<{ success: boolean; ms: number }>;
  /** Optional: side-channel to send a status message to the user mid-pipeline
   *  (e.g. "PC schläft, wecke auf..."). Failures here must not abort the pipeline. */
  notifyStatus?: (chatId: number, text: string) => Promise<void>;
}

const HISTORY_LIMIT = 20;

export async function handleMessage(deps: HandleDeps, update: ParsedTextUpdate): Promise<string> {
  const t0 = Date.now();
  const bypassRouter = process.env.BYPASS_ROUTER === '1';
  log.info('pipeline_start', { updateId: update.updateId, chatId: update.chatId, textLen: update.text.length, bypassRouter });
  const ts = update.ts ?? Math.floor(Date.now() / 1000);

  // /start: clear THIS chat's history (other chats untouched), then ask the
  // LLM to generate a fresh welcome. No tools, no prior history fed in —
  // the welcome is the first turn of the new conversation.
  const trimmed = update.text.trim();
  if (trimmed === '/start' || trimmed.startsWith('/start ')) {
    const removed = clearHistory(deps.db, update.chatId);
    log.info('history_cleared', { chatId: update.chatId, removed });
    const tGen = Date.now();
    const out = await deps.generate({
      system: buildWelcomePrompt(update.firstName !== undefined ? { firstName: update.firstName } : {}),
      messages: [{ role: 'user', content: '/start' }],
      tools: {},
      reasoningEffort: 'low',
    });
    log.info('welcome_generated', { ms: Date.now() - tGen, textLen: out.text.length });
    const reply = out.text.trim() || 'Hallo, ich bin Rolly. Sag mir was du brauchst.';
    // Persist just the welcome so the next turn has a single anchor message
    // showing the assistant just greeted.
    appendMessage(deps.db, {
      chatId: update.chatId,
      role: 'assistant',
      content: { text: reply },
      ts: ts + 1,
    });
    return reply;
  }

  appendMessage(deps.db, { chatId: update.chatId, role: 'user', content: { text: update.text }, ts });

  // Pre-flight: if LM Studio is unreachable and we have WoL wired up, wake the
  // Gaming PC before doing the embed/generate calls. Otherwise the entire
  // pipeline silently fails on fetch ECONNREFUSED.
  if (deps.healthCheck && deps.wakeGamingPc) {
    const tHealth = Date.now();
    const up = await deps.healthCheck();
    log.info('lm_studio_health', { up, ms: Date.now() - tHealth });
    if (!up) {
      if (deps.notifyStatus) {
        deps.notifyStatus(update.chatId, 'Gaming-PC schläft, wecke auf — einen Moment...').catch(err =>
          log.warn('notify_status_failed', { err: String(err) }),
        );
      }
      const wake = await deps.wakeGamingPc();
      log.info('wol_wake_result', { success: wake.success, ms: wake.ms });
      if (!wake.success) {
        const failMsg = 'Gaming-PC kommt nicht hoch. Bitte manuell prüfen ob WoL aktiviert ist und der PC am Strom hängt.';
        appendMessage(deps.db, { chatId: update.chatId, role: 'assistant', content: { text: failMsg }, success: false, ts: ts + 1 });
        return failMsg;
      }
    }
  }

  let selectedSkills;
  if (bypassRouter) {
    // Skip embedding + cosine routing: expose all tool-bearing skills to the LLM.
    // Relies on the model (and its thinking mode + context) to pick the right tool.
    selectedSkills = deps.registry.all();
    log.info('routing_bypassed', { skillCount: selectedSkills.length });
  } else {
    const tEmbed = Date.now();
    const queryEmbedding = await deps.embedQuery(update.text);
    log.info('embed_done', { ms: Date.now() - tEmbed, dim: queryEmbedding.length });

    const skills = deps.registry.all();
    const routable = skills
      .filter(s => deps.skillEmbeddings[s.id] !== undefined)
      .map(s => ({ id: s.id, embedding: deps.skillEmbeddings[s.id]! }));
    const routed = route(queryEmbedding, routable, deps.thresholds);
    log.info('routed', { band: routed.band, selected: routed.selectedIds, topScore: routed.scores[0]?.score });

    selectedSkills = deps.registry.all().filter(s => routed.selectedIds.includes(s.id));
  }
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
    ...(update.firstName !== undefined ? { firstName: update.firstName } : {}),
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

  const primaryIntent = selectedSkills[0]?.id;
  appendMessage(deps.db, {
    chatId: update.chatId,
    role: 'assistant',
    content: { text: reply },
    ...(primaryIntent !== undefined ? { intent: primaryIntent } : {}),
    success: true,
    ts: ts + 1,
  });

  return reply;
}
