import type { Database } from 'bun:sqlite';
import { route, type Thresholds } from '../router/semantic';
import { SkillRegistry } from '../skills/registry';
import { defineSkillTool, inferPositionals } from '../tools/define-skill-tool';
import { buildSystemPrompt, buildWelcomePrompt } from './system-prompt';
import { recoverFromLeakedToolCall } from './leak-recovery';
import { appendMessage, clearHistory, recentMessages } from '../memory/history';
import type { ParsedTextUpdate, ParsedUpdate, ParsedVoiceUpdate } from '../telegram/webhook';
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
  /** Why the final LLM step stopped. 'length' = hit max output tokens
   *  (response was truncated); 'stop' = clean completion. Used by the
   *  pipeline to craft a useful fallback when text comes back empty. */
  finishReason: string;
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
  /** Optional: resolve a Telegram voice file_id to its transcribed German text.
   *  Composes Telegram getFile + LM Studio Whisper in main.ts. */
  transcribeVoice?: (fileId: string) => Promise<string>;
  /** Optional: snapshot of all controllable HA entities (area → entity_id +
   *  friendly_name) captured at agent startup. Injected verbatim into the
   *  system prompt to ground the LLM and prevent entity_id hallucination. */
  entityCatalogue?: string;
}

const HISTORY_LIMIT = 20;

/** Detects when the LLM's "final reply" is actually leaked chain-of-thought
 *  — e.g. Gemma narrating "Gemäß Regel F..." or "Tool-Aufruf: ..." instead
 *  of issuing a proper tool call. The prompt is supposed to prevent this,
 *  but a 4B model still slips occasionally; better to surface a clean error
 *  than to dump pseudo-code in the user's chat. */
function looksLikeLeakedReasoning(text: string): boolean {
  const t = text.trim();
  if (t.length === 0) return false;
  const markers: RegExp[] = [
    /\bTool-Aufruf:\s/i,
    /\bArgumente:\s/i,
    /Gemäß Regel\b/i,
    /^Ich muss\b/m,
    /^Schritt \d+:/m,
    // Gemma's function-calling sometimes flips into text-mode and writes the
    // *intended* tool call as JSON instead of issuing a real function call.
    // Three observed shapes — single tool_name, OpenAI-style tool_calls array,
    // and bare function field with the homeassistant_ prefix.
    /"tool_name"\s*:/i,
    /"tool_calls"\s*:\s*\[/i,
    /"function"\s*:\s*"homeassistant_/i,
    /"parameters"\s*:\s*\{[^}]*entity_id/i,
  ];
  return markers.some(re => re.test(t));
}

export async function handleMessage(deps: HandleDeps, input: ParsedUpdate): Promise<string> {
  if (input.kind === 'voice') {
    return handleVoice(deps, input);
  }
  return handleText(deps, input);
}

async function handleVoice(deps: HandleDeps, voice: ParsedVoiceUpdate): Promise<string> {
  log.info('voice_received', { updateId: voice.updateId, durationSec: voice.durationSec, mimeType: voice.mimeType });
  if (!deps.transcribeVoice) {
    return '⚠️ Sprachnachrichten sind aktuell nicht aktiviert. Bitte als Text schreiben.';
  }
  const tTranscribe = Date.now();
  let transcript: string;
  try {
    transcript = (await deps.transcribeVoice(voice.fileId)).trim();
  } catch (err) {
    log.error('transcribe_failed', { err: String(err), updateId: voice.updateId });
    return '⚠️ Transkription fehlgeschlagen. Versuch es nochmal oder schreib es als Text.';
  }
  log.info('transcribed', { ms: Date.now() - tTranscribe, len: transcript.length, durationSec: voice.durationSec });
  if (!transcript) {
    return '🎤 Ich konnte nichts verstehen — sprich bitte deutlicher oder schreib es als Text.';
  }
  // Run the synthesized text through the normal pipeline, then prefix the
  // reply with the transcript so the user can verify what Whisper heard
  // (cheap defense against mis-transcriptions sending tool calls awry).
  const textUpdate: ParsedTextUpdate = {
    kind: 'text',
    updateId: voice.updateId,
    chatId: voice.chatId,
    userId: voice.userId,
    messageId: voice.messageId,
    ts: voice.ts,
    text: transcript,
    ...(voice.firstName !== undefined ? { firstName: voice.firstName } : {}),
  };
  const reply = await handleText(deps, textUpdate);
  return `🎤 _${transcript}_\n\n${reply}`;
}

async function handleText(deps: HandleDeps, update: ParsedTextUpdate): Promise<string> {
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
    ...(deps.entityCatalogue !== undefined ? { entityCatalogue: deps.entityCatalogue } : {}),
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
  log.info('llm_call_done', { ms: Date.now() - tGen, textLen: out.text.length, toolCallCount: out.toolCalls.length, finishReason: out.finishReason });

  const trimmedText = out.text.trim();
  let reply: string;
  if (trimmedText && looksLikeLeakedReasoning(trimmedText)) {
    log.warn('llm_reply_looks_like_reasoning', { textLen: trimmedText.length, finishReason: out.finishReason });
    // Best-effort recovery: parse the leaked JSON, run the intended tool
    // ourselves, return the formatted result. Falls through to the generic
    // fallback only if the JSON is unparseable or names an unknown tool.
    const recovered = await recoverFromLeakedToolCall(trimmedText, deps.registry);
    if (recovered) {
      reply = recovered.reply;
    } else if (!hasTools) {
      // Smalltalk mode: model leaked a phantom tool call but had no tools
      // available anyway. Give a friendly, on-brand fallback instead of the
      // generic "Gedanken ausgegeben" warning — the user just wanted to chat.
      reply = 'Ich bin Rolly, dein Homelab-Assistent. Ich kann dir mit Smart Home (Lichter, Heizung, Rollos), Kameras, Netzwerk, VMs und Wake-on-LAN helfen — frag einfach.';
    } else {
      reply = '⚠️ Das Modell hat statt einer Aktion seine Gedanken ausgegeben. Bitte versuch es nochmal, gerne spezifischer formuliert.';
    }
  } else if (trimmedText) {
    reply = trimmedText;
  } else if (out.finishReason === 'length') {
    reply = '⚠️ Antwort wurde abgeschnitten — der Output war zu lang. Bitte spezifischer fragen (z.B. nur eine Area oder nur eine Domäne auf einmal).';
  } else if (out.toolCalls.length > 0) {
    // Tools liefen, aber das Modell hat keinen finalen Text produziert — meist
    // weil es nach ein paar Calls die Übersicht verloren hat. Häufigster
    // Auslöser: einzelne get-state-Schleife statt entities --state-Filter.
    reply = '🤔 Ich hab die Daten geholt aber konnte sie nicht zusammenfassen. Frag bitte spezifischer (z.B. "welche Lichter sind an?" statt "was ist alles an?").';
  } else {
    reply = '🤔 Ich habe keine Antwort generiert. Bitte nochmal versuchen oder konkreter formulieren.';
  }
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
