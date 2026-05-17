/**
 * Gemma occasionally dumps its intended tool call as a JSON code block in the
 * reply text instead of issuing a real function call. Three shapes observed
 * in prod / E2E tests:
 *
 *   {"tool_name": "homeassistant_get_state", "parameters": {...}}
 *   {"tool_calls": [{"function": "homeassistant_entities", "args": {...}}]}
 *   {"function": "homeassistant_turn_off", "arguments": {...}}
 *
 * Rather than asking the user to retry, we parse what the model meant,
 * normalize the tool name back to the registry's `skill__command` form, and
 * execute it ourselves. The result is formatted with a small German template
 * so we don't need a second LLM round-trip.
 */

import type { SkillRegistry } from '../skills/registry';
import { defineSkillTool, inferPositionals } from '../tools/define-skill-tool';
import { log } from '../utils/logger';

export interface RecoveredCall {
  toolName: string;
  args: Record<string, unknown>;
}

/** Best-effort extract of `{toolName, args}` from a model reply that leaked
 *  its intended tool call as JSON text. Returns null when nothing parseable
 *  is found — the caller falls back to a generic error message. */
export function parseLeakedToolCall(text: string): RecoveredCall | null {
  // Find the first `{...}` JSON object in the text. Models sometimes wrap
  // it in ```json ... ``` so strip that out first.
  const stripped = text.replace(/```(?:json)?/gi, '').trim();
  const firstBrace = stripped.indexOf('{');
  if (firstBrace < 0) return null;
  // Try expanding-window parses from the first brace.
  for (let end = stripped.length; end > firstBrace; end--) {
    const slice = stripped.slice(firstBrace, end);
    if (!slice.endsWith('}')) continue;
    try {
      const parsed = JSON.parse(slice);
      return extractFromParsed(parsed);
    } catch {
      // try a shorter window
    }
  }
  return null;
}

function extractFromParsed(parsed: unknown): RecoveredCall | null {
  if (!parsed || typeof parsed !== 'object') return null;
  const obj = parsed as Record<string, unknown>;

  // Shape 1: { tool_name: "...", parameters: {...} }
  if (typeof obj.tool_name === 'string') {
    return normalize(obj.tool_name, (obj.parameters ?? obj.args ?? obj.arguments) as unknown);
  }

  // Shape 2: { tool_calls: [{ function: "...", args/arguments/parameters: {...} }] }
  if (Array.isArray(obj.tool_calls) && obj.tool_calls.length > 0) {
    const first = obj.tool_calls[0] as Record<string, unknown> | undefined;
    if (!first) return null;
    const fn = first.function;
    const fnName = typeof fn === 'string'
      ? fn
      : (typeof fn === 'object' && fn !== null && typeof (fn as Record<string, unknown>).name === 'string')
        ? ((fn as Record<string, unknown>).name as string)
        : undefined;
    if (!fnName) return null;
    return normalize(fnName, (first.args ?? first.arguments ?? first.parameters
      ?? (typeof fn === 'object' && fn !== null ? (fn as Record<string, unknown>).arguments : undefined)) as unknown);
  }

  // Shape 3: { function: "...", arguments: {...} } at top level
  if (typeof obj.function === 'string') {
    return normalize(obj.function, (obj.arguments ?? obj.args ?? obj.parameters) as unknown);
  }

  return null;
}

/** Normalize the tool name the model wrote (`homeassistant_entities`) into
 *  the registry's `skill__command` form (`homeassistant__entities`). Most
 *  shapes use single underscore as the separator; we tolerate both. */
function normalize(rawName: string, rawArgs: unknown): RecoveredCall | null {
  const name = rawName.includes('__') ? rawName : rawName.replace(/_/, '__');
  const args = (rawArgs && typeof rawArgs === 'object' && !Array.isArray(rawArgs))
    ? (rawArgs as Record<string, unknown>)
    : {};
  return { toolName: name, args };
}

/** Format a tool's execution result as a short German reply for the user.
 *  Generic enough to handle entities lists, single states, and write actions
 *  without needing a second LLM call. */
export function formatRecoveredResult(call: RecoveredCall, result: unknown): string {
  const command = call.toolName.split('__')[1] ?? call.toolName;
  if (command === 'entities') {
    const list = Array.isArray(result) ? result as Array<{ entity_id: string; state: string; attributes?: Record<string, unknown> }> : [];
    if (list.length === 0) return 'Keine passenden Entities gefunden.';
    if (list.length > 15) return `${list.length} Treffer — bitte enger filtern (z.B. eine spezifische Area oder mit --state).`;
    const lines = list.map(e => {
      const fn = (e.attributes?.['friendly_name'] as string | undefined) ?? e.entity_id;
      return `• ${fn} — ${e.state}`;
    });
    return lines.join('\n');
  }
  if (command === 'get-state') {
    if (result && typeof result === 'object' && 'state' in (result as Record<string, unknown>)) {
      const r = result as { entity_id?: string; state: string; attributes?: Record<string, unknown> };
      const fn = (r.attributes?.['friendly_name'] as string | undefined) ?? r.entity_id ?? call.args['entity_id'];
      return `${fn}: ${r.state}`;
    }
  }
  if (command === 'turn-on' || command === 'turn-off' || command === 'toggle') {
    const verb = command === 'turn-on' ? 'eingeschaltet' : command === 'turn-off' ? 'ausgeschaltet' : 'umgeschaltet';
    return `${call.args['entity_id'] ?? 'Entity'}: ${verb}.`;
  }
  // Fallback: short JSON preview, capped.
  const preview = JSON.stringify(result).slice(0, 200);
  return `Tool ${call.toolName} ausgeführt. Ergebnis: ${preview}`;
}

// Recovery is gated to commands that map cleanly to "I wanted to {do X} on the
// user's behalf". Anything outside this set (system introspection like
// list-services, list-components, error-log, ...) just dumps raw data that's
// useless for the user and was almost certainly NOT what they asked for.
const RECOVERABLE_COMMANDS = new Set([
  'entities', 'get-state',
  'turn-on', 'turn-off', 'toggle',
  'call-service',
  'list-scenes', 'activate-scene',
  'list-scripts', 'run-script', 'stop-script',
  'list-automations', 'trigger', 'enable', 'disable',
  'history', 'logbook',
]);

/** Try to recover a leaked tool call from the model's reply: parse, find the
 *  tool in the registry, execute it, format the result. Returns null when
 *  recovery isn't possible (the caller then uses the generic fallback). */
export async function recoverFromLeakedToolCall(
  text: string,
  registry: SkillRegistry,
): Promise<{ reply: string; call: RecoveredCall; raw: unknown } | null> {
  const parsed = parseLeakedToolCall(text);
  if (!parsed) return null;

  // Skip recovery for anything outside the user-intent allowlist — prevents
  // raw HA system dumps (components / services / error_log) from leaking
  // through when the model just panicked.
  const command = parsed.toolName.split('__')[1] ?? parsed.toolName;
  if (!RECOVERABLE_COMMANDS.has(command)) {
    log.info('leak_recovery_skipped_unsafe_command', { tool: parsed.toolName, command });
    return null;
  }

  // Find the SkillTool by its registered name.
  const allSkills = registry.all();
  let skillTool: ReturnType<typeof registry.all>[number]['tools'][number] | undefined;
  for (const s of allSkills) {
    skillTool = s.tools.find(t => t.name === parsed.toolName);
    if (skillTool) break;
  }
  if (!skillTool) {
    log.warn('leak_recovery_unknown_tool', { name: parsed.toolName });
    return null;
  }

  const tool = defineSkillTool(skillTool, { positionalArgs: inferPositionals(skillTool) });
  try {
    // The defineSkillTool wrapper already turns subprocess failures into
    // structured {ok:false,error} objects, so we don't need to catch here —
    // but a Zod validation mismatch can still throw. Wrap defensively.
    const result = await tool.execute(parsed.args as never, {} as never);
    const reply = formatRecoveredResult(parsed, result);
    log.info('leak_recovery_succeeded', { tool: parsed.toolName, replyLen: reply.length });
    return { reply, call: parsed, raw: result };
  } catch (err) {
    log.warn('leak_recovery_exec_failed', { tool: parsed.toolName, err: String(err) });
    return null;
  }
}
