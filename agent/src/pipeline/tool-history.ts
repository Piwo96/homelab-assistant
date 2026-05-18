import type { Database } from 'bun:sqlite';
import { recentMessages } from '../memory/history';

/** Compact one-line summary of a tool result. Surfaces the fields the LLM
 *  will care about in a follow-up turn — affected entities for writes,
 *  count + state for reads. Falls back to "ok"/"Fehler" when shape is
 *  unknown. */
function summarizeResult(result: unknown): string {
  if (!result || typeof result !== 'object') return 'ok';
  const r = result as Record<string, unknown>;
  if (r.ok === false) {
    return `Fehler: ${typeof r.error === 'string' ? r.error : 'fehlgeschlagen'}`;
  }
  const affected = r.entities_affected;
  if (Array.isArray(affected)) {
    if (affected.length === 0) return '0 Treffer';
    const ids = affected.slice(0, 8).map(String).join(', ');
    const more = affected.length > 8 ? ` (+${affected.length - 8})` : '';
    return `${affected.length} Entit${affected.length === 1 ? 'y' : 'ies'}: ${ids}${more}`;
  }
  for (const key of ['lights', 'rollos', 'klimas'] as const) {
    if (Array.isArray(r[key])) {
      const list = r[key] as Array<{ entity_id?: unknown; state?: unknown }>;
      if (list.length === 0) return `0 ${key}`;
      const ids = list.slice(0, 8)
        .map(it => typeof it.entity_id === 'string' ? it.entity_id : '?')
        .join(', ');
      const more = list.length > 8 ? ` (+${list.length - 8})` : '';
      return `${list.length} ${key}: ${ids}${more}`;
    }
  }
  return 'ok';
}

/** Build a "letzte tool-aktionen"-style context block from the recent
 *  assistant turns. Returns null when there is nothing to show. The block
 *  is meant for the SYSTEM prompt (via buildSystemPrompt's contextBlocks),
 *  not for the messages array — keeping it out of assistant.content
 *  prevents the model from copying the format into its own replies. */
export function buildToolHistoryBlock(
  db: Database,
  chatId: number,
  maxTurns = 3,
): string | null {
  const messages = recentMessages(db, chatId, 30);
  const turnsWithTools = messages.filter(m =>
    m.role === 'assistant' && Array.isArray(m.content.toolCalls) && m.content.toolCalls.length > 0,
  );
  if (turnsWithTools.length === 0) return null;
  const lastN = turnsWithTools.slice(-maxTurns);
  const lines: string[] = [];
  lastN.forEach((m, turnIdx) => {
    const calls = m.content.toolCalls ?? [];
    const results = m.content.toolResults ?? [];
    const turnsAgo = lastN.length - turnIdx;
    calls.forEach((c, i) => {
      const res = results[i];
      const args = JSON.stringify(c.args ?? {});
      lines.push(`- vor ${turnsAgo} Turn(s): ${c.name}(${args}) → ${summarizeResult(res?.result)}`);
    });
  });
  return [
    'LETZTE TOOL-AKTIONEN (für Folge-Befehle wie "die wieder aus", "noch heller", "auch im OG"):',
    ...lines,
    'Nutze die exakten entity_ids/Scopes oben für Folge-Aktionen — KEINE eigene Auflösung des User-Slang nötig.',
  ].join('\n');
}
