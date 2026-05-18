import type { Database } from 'bun:sqlite';
import type { LlmRouter } from '../router/llm-router';
import type { SkillContextCache } from '../skills/context-cache';
import { SkillRegistry } from '../skills/registry';
import { defineSkillTool, inferPositionals } from '../tools/define-skill-tool';
import { buildSystemPrompt } from './system-prompt';
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
  /** Tool results paired with the calls above (same order, same length).
   *  Needed so the pipeline can persist a short "what scope / how many
   *  entities were affected" annotation in the chat history, so follow-up
   *  questions like "welche waren da noch an?" have the right context. */
  toolResults: Array<{ toolName: string; result: unknown }>;
  /** Why the final LLM step stopped. 'length' = hit max output tokens
   *  (response was truncated); 'stop' = clean completion. Used by the
   *  pipeline to craft a useful fallback when text comes back empty. */
  finishReason: string;
}

export interface HandleDeps {
  db: Database;
  registry: SkillRegistry;
  generate: (input: GenerateInput) => Promise<GenerateOutput>;
  /** Stage-1 LLM-based skill picker. Used only when >1 skill is loaded;
   *  the fast-path (1 skill) skips this entirely. */
  llmRouter: LlmRouter;
  /** Lazy-loaded context blocks per skill, fetched via `--json context`. */
  contextCache: SkillContextCache;
  /** Pre-rendered /start welcome text, assembled at startup from each loaded
   *  skill's `welcome:` frontmatter. Passed through here (not computed in this
   *  module) so the welcome reflects the exact skill set the bot booted with. */
  welcomeText: string;
  /** Optional: quick reachability check for LM Studio (returns true if up). */
  healthCheck?: () => Promise<boolean>;
  /** Optional: triggers Wake-on-LAN + waits until LM Studio answers again. */
  wakeGamingPc?: () => Promise<{ success: boolean; ms: number }>;
  /** Optional: side-channel to send a status message to the user mid-pipeline. */
  notifyStatus?: (chatId: number, text: string) => Promise<void>;
  /** Optional: resolve a Telegram voice file_id to its transcribed German text. */
  transcribeVoice?: (fileId: string) => Promise<string>;
}

const HISTORY_LIMIT = 20;

/** Suppress duplicate /start commands that arrive in quick succession. Some
 *  Telegram clients fire /start twice when the user taps it from the "Menü"
 *  button (once as the command, once as the bot-open deep-link), and a
 *  genuine double-tap looks the same. Either way, the second welcome message
 *  is just noise. In-memory map is fine — only matters within the burst, and
 *  Telegram never retries old updates after a server restart. */
const START_DEBOUNCE_MS = 3000;
const lastStartByChat = new Map<number, number>();

/** Sentinel returned from handleMessage when the pipeline decided to send
 *  nothing (e.g. debounced /start). Server checks for this and cleans up
 *  the placeholder instead of editing it with empty text. */
export const SUPPRESS_REPLY = '';

/** Compact one-liner summary of a tool result so the LLM can read it back
 *  in next turn's history. Surfaces the fields that matter for follow-up
 *  questions: scope label, affected count + ids for writes; count + state
 *  summary for reads. Falls back to "OK"/"Fehler" when shape is unknown. */
function summarizeToolResult(result: unknown): string {
  if (!result || typeof result !== 'object') return 'OK';
  const r = result as Record<string, unknown>;
  if (r.ok === false) {
    const err = typeof r.error === 'string' ? r.error : 'fehlgeschlagen';
    return `Fehler: ${err}`;
  }
  const affected = r.entities_affected;
  if (Array.isArray(affected)) {
    const ids = affected.slice(0, 8).map(String);
    const more = affected.length > 8 ? ` (+${affected.length - 8} weitere)` : '';
    return `${affected.length} Entit${affected.length === 1 ? 'y' : 'ies'} betroffen: ${ids.join(', ')}${more}`;
  }
  for (const key of ['lights', 'rollos', 'klimas'] as const) {
    if (Array.isArray(r[key])) {
      const list = r[key] as Array<{ entity_id?: unknown; state?: unknown }>;
      const ids = list.slice(0, 8)
        .map(it => typeof it.entity_id === 'string' ? it.entity_id : '?')
        .join(', ');
      const more = list.length > 8 ? ` (+${list.length - 8} weitere)` : '';
      return `${list.length} ${key}: ${ids}${more}`;
    }
  }
  return 'OK';
}

/** Format the tool-call/result trace from a single turn into a compact
 *  block we append to the persisted assistant message (NOT shown to the
 *  user via Telegram — they already got the reply text). The LLM reads
 *  this back in subsequent turns and can ground "welche waren das?",
 *  "wieder die gleichen", etc. on the actual scope it used last time. */
function formatToolTrace(
  calls: Array<{ toolName: string; args: unknown }>,
  results: Array<{ toolName: string; result: unknown }>,
): string | null {
  if (calls.length === 0) return null;
  const lines = calls.map((tc, i) => {
    const argsStr = JSON.stringify(tc.args ?? {});
    const matching = results[i];
    const resultStr = matching ? summarizeToolResult(matching.result) : 'kein Result';
    return `  • ${tc.toolName}(${argsStr}) → ${resultStr}`;
  });
  return `[Tool-Aufrufe in diesem Turn:\n${lines.join('\n')}]`;
}

/** Per-line patterns that mark a reasoning monologue (not user-facing text).
 *  Anchored with `^` and used line-by-line so the same patterns can split a
 *  reasoning prefix away from the actual answer the model wrote afterwards. */
const REASONING_LINE_MARKERS: RegExp[] = [
  /^\s*Plan:\s/i,                       // "Plan: ..."
  /^\s*Schritt\s+\d+:/i,                // "Schritt 1: ..."
  /^\s*Tool-Aufruf:\s/i,                // "Tool-Aufruf: ..."
  /^\s*Argumente:\s/i,                  // "Argumente: ..."
  /^\s*Ich\s+muss\b/i,                  // "Ich muss jetzt ..."
  /^\s*Die\s+Anfrage\s+(ist|enthält|betrifft|passt|bezieht)\b/i,
  /^\s*Die\s+Antwort\s+muss\b/i,
  /^\s*Daher\s+(kann|muss|sollte|wird)\b/i,
  /\bGemäß\s+Regel\b/i,
  // Structured-reasoning bullets Gemma emits before /start replies:
  //   "• Persona: ...", "• Goal: ...", "• Constraints: ..."
  /^\s*[•\-*]\s*(Persona|Recipient|Context|Goal|Constraints|Output|Format|Task|Role|Style|Tone|Audience|Scope|Final[\s-]+output)\s*:/i,
  // Self-correction wrapper. When the closing `)*` is on the SAME line as the
  // user-facing answer (Gemma often writes "Ja.)*Hallo Philipp!"), Strategy 1
  // in extractActualReply splits mid-line. This line marker only catches the
  // multi-line shape.
  /^\s*\*?\s*\(\s*Self-Correction/i,
  /^\s*\*?\s*\(\s*Check\b.*:/i,
];

/** Matches the wrapped self-correction / final-check block Gemma sometimes
 *  emits inline: `*(Self-Correction/Check: ...)*`. The actual answer follows
 *  the closing `)*` — possibly on the same line, so we can't rely on
 *  newline-splitting. Greedy across newlines so a multi-line block is captured. */
const WRAPPED_REASONING_BLOCK = /\*\(\s*(?:Self-Correction|Check|Final[\s-]+Check|Self[\s-]+Check)[\s\S]*?\)\*+/i;

/** Detects when the LLM's "final reply" is actually leaked chain-of-thought
 *  — e.g. Gemma narrating "Gemäß Regel F..." or "Tool-Aufruf: ..." instead
 *  of issuing a proper tool call. The prompt is supposed to prevent this,
 *  but a 4B model still slips occasionally; better to surface a clean error
 *  than to dump pseudo-code in the user's chat. */
function looksLikeLeakedReasoning(text: string): boolean {
  const t = text.trim();
  if (t.length === 0) return false;
  // Line-level reasoning markers (split on \n so anchors work).
  for (const line of t.split(/\n/)) {
    if (REASONING_LINE_MARKERS.some(re => re.test(line))) return true;
  }
  // JSON tool-call leak shapes (whole-text patterns, not per-line).
  const jsonMarkers: RegExp[] = [
    /"tool_name"\s*:/i,
    /"tool_calls"\s*:\s*\[/i,
    /"function"\s*:\s*"smart-home_/i,
    /"parameters"\s*:\s*\{[^}]*"entity(?:_id)?"\s*:/i,
  ];
  return jsonMarkers.some(re => re.test(t));
}

/** When the model writes a reasoning monologue AND then the actual answer,
 *  scrub the reasoning and surface just the user-facing text.
 *
 *  Two observed shapes:
 *    A) Multi-line: "Die Anfrage ist... Plan: ... \n Mir geht es gut..."
 *    B) Inline wrapper: "*(Self-Correction: ...Ja.)*Hallo Philipp! Schön..."
 *       — the closing `)*` sits on the same line as the answer, so we can't
 *       just split on newlines.
 *
 *  Strategy: first remove any wrapped `*(Self-Correction...)*` blocks (B);
 *  then walk lines from the END until we hit a reasoning-marker line (A).
 *  The collected suffix is the actual reply. Returns null if nothing clean
 *  remains (entire text was reasoning, or trailing portion is too short). */
export function extractActualReply(text: string): string | null {
  // Strategy 1: strip wrapped self-correction blocks so the answer that
  // immediately follows the closing `)*` is recoverable. Apply globally in
  // case the model emits more than one block.
  const stripped = text.replace(new RegExp(WRAPPED_REASONING_BLOCK.source, 'gi'), '\n');

  // Strategy 2: walk lines from the end, break at first reasoning marker.
  const lines = stripped.split(/\n/);
  const tail: string[] = [];
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i] ?? '';
    if (REASONING_LINE_MARKERS.some(re => re.test(line))) break;
    tail.unshift(line);
  }
  const result = tail.join('\n').trim();
  // Sanity floor: a 1-word "Ja." after pages of reasoning probably isn't the
  // real answer — likely a stray sentence the model wrote mid-reasoning. The
  // 12-char threshold keeps "Mir geht es gut" (15 chars) and rejects "Ja."
  return result.length >= 12 ? result : null;
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
  log.info('pipeline_start', { updateId: update.updateId, chatId: update.chatId, textLen: update.text.length });
  const ts = update.ts ?? Math.floor(Date.now() / 1000);

  // /start: clear THIS chat's history (other chats untouched), then return
  // a static welcome message. No LLM call — a 4B model on this prompt would
  // randomly leak its reasoning bullets ("• Persona:", "• Goal:") and the
  // welcome must be reliable. Keep the example list short and concrete so
  // the user immediately knows what to ask.
  const trimmed = update.text.trim();
  if (trimmed === '/start' || trimmed.startsWith('/start ')) {
    // Debounce: some Telegram clients fire /start twice (menu tap + auto-
    // start). Suppress the second one within the burst window so the user
    // only sees one welcome.
    const now = Date.now();
    const last = lastStartByChat.get(update.chatId) ?? 0;
    if (now - last < START_DEBOUNCE_MS) {
      log.info('start_debounced', { chatId: update.chatId, sinceLastMs: now - last });
      return SUPPRESS_REPLY;
    }
    lastStartByChat.set(update.chatId, now);
    const removed = clearHistory(deps.db, update.chatId);
    log.info('history_cleared', { chatId: update.chatId, removed });
    const reply = deps.welcomeText;
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

  const history = recentMessages(deps.db, update.chatId, HISTORY_LIMIT)
    .filter(m => m.role !== 'tool')
    .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content.text ?? '' }))
    .filter(m => m.content.length > 0);

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

  const loaded = deps.registry.all();
  let selectedSkill: ReturnType<SkillRegistry['all']>[number] | null = null;
  if (loaded.length === 1) {
    // Fast-path: single skill, skip Stage 1.
    selectedSkill = loaded[0]!;
    log.info('routing_fast_path', { skillId: selectedSkill.id });
  } else if (loaded.length > 1) {
    const picked = await deps.llmRouter.pick({
      msg: update.text,
      recentMessages: history.slice(-3),
      candidates: loaded.map(s => ({ id: s.id, description: s.description })),
    });
    if (picked) {
      selectedSkill = loaded.find(s => s.id === picked.skillId) ?? null;
    }
    log.info('routing_stage1', { picked: picked?.skillId ?? null, candidates: loaded.length });
  }

  const selectedSkills = selectedSkill ? [selectedSkill] : [];
  const tools: Record<string, Tool> = {};
  for (const s of selectedSkills) {
    for (const t of s.tools) {
      tools[t.name] = defineSkillTool(t, { positionalArgs: inferPositionals(t) });
    }
  }
  const hasTools = Object.keys(tools).length > 0;
  log.info('tools_built', { count: Object.keys(tools).length, names: Object.keys(tools).slice(0, 5) });

  // Fetch context blocks for routed skills (only those with hasContext=true).
  const contextBlocks: string[] = [];
  for (const s of selectedSkills) {
    if (s.hasContext) {
      const md = await deps.contextCache.get(s.id);
      if (md) contextBlocks.push(md);
    }
  }

  const system = buildSystemPrompt({
    skills: selectedSkills.map(s => ({ id: s.id, description: s.description })),
    hasTools,
    contextBlocks,
    ...(update.firstName !== undefined ? { firstName: update.firstName } : {}),
  });

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
    // ourselves, return the formatted result. Only attempt when tools were
    // actually available this turn — in smalltalk mode (hasTools=false) the
    // model has no business calling tools, recovering would just expose data
    // the user didn't ask for. Falls through to the friendly Rolly fallback.
    const recovered = hasTools ? await recoverFromLeakedToolCall(trimmedText, deps.registry) : null;
    if (recovered) {
      reply = recovered.reply;
    } else {
      // Prose-leak recovery: model wrote its reasoning AND then the actual
      // answer. Strip the reasoning prefix and surface just the trailing
      // user-facing text. Falls back to the friendly smalltalk message or
      // a generic warning if no clean tail can be extracted.
      const actualReply = extractActualReply(trimmedText);
      if (actualReply) {
        log.info('llm_reply_prose_leak_recovered', { from: trimmedText.length, to: actualReply.length });
        reply = actualReply;
      } else if (!hasTools) {
        reply = 'Ich bin Rolly, dein Homelab-Assistent. Ich kann dir mit Smart Home (Lichter, Heizung, Rollos), Kameras, Netzwerk, VMs und Wake-on-LAN helfen — frag einfach.';
      } else {
        reply = '⚠️ Das Modell hat statt einer Aktion seine Gedanken ausgegeben. Bitte versuch es nochmal, gerne spezifischer formuliert.';
      }
    }
  } else if (trimmedText) {
    reply = trimmedText;
  } else if (out.finishReason === 'length') {
    reply = '⚠️ Antwort wurde abgeschnitten — der Output war zu lang. Bitte spezifischer fragen (z.B. nur eine Area oder nur eine Domäne auf einmal).';
  } else if (out.toolCalls.length > 0) {
    // Tools liefen, aber das Modell hat keinen finalen Text produziert — meist
    // weil es nach ein paar Calls die Übersicht verloren hat. Häufigster
    // Auslöser: einzelne gerät-status-Calls aufgereiht statt lights-status/
    // rollos-status mit --where/--state.
    reply = '🤔 Ich hab die Daten geholt aber konnte sie nicht zusammenfassen. Frag bitte spezifischer (z.B. "welche Lichter sind an?" statt "was ist alles an?").';
  } else {
    reply = '🤔 Ich habe keine Antwort generiert. Bitte nochmal versuchen oder konkreter formulieren.';
  }
  log.info('pipeline_done', { totalMs: Date.now() - t0, replyLen: reply.length });

  // Persist the assistant turn. The text the USER sees is `reply`; what we
  // store includes a compact tool-trace block underneath so the LLM has
  // scope-grounding in future turns. The block is invisible to the user
  // (Telegram already received the bare reply) and only flows through
  // recentMessages() → next prompt.
  const trace = formatToolTrace(out.toolCalls, out.toolResults);
  const storedText = trace ? `${reply}\n\n${trace}` : reply;
  const primaryIntent = selectedSkills[0]?.id;
  appendMessage(deps.db, {
    chatId: update.chatId,
    role: 'assistant',
    content: { text: storedText },
    ...(primaryIntent !== undefined ? { intent: primaryIntent } : {}),
    success: true,
    ts: ts + 1,
  });

  return reply;
}
