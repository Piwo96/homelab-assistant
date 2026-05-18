import type { Database } from 'bun:sqlite';

export type MessageRole = 'user' | 'assistant' | 'tool';

export interface MessageContent {
  text?: string;
  /** All tool calls the model made in this turn. Stored so the next turn's
   *  system prompt can show a "letzte aktionen" block — gives the LLM the
   *  exact entity_ids it touched, so follow-ups like "die wieder aus" or
   *  "noch heller" don't have to re-resolve scope. NOT mixed into the
   *  assistant text (an earlier "[Tool-Aufrufe …]" inline block trained
   *  the model to imitate the format in user-visible replies). */
  toolCalls?: Array<{ name: string; args: unknown }>;
  /** Paired 1:1 with toolCalls. Holds the structured JSON the tool returned. */
  toolResults?: Array<{ name: string; result: unknown }>;
  /** @deprecated single-tool fields kept for legacy DB rows. */
  toolCall?: { name: string; args: unknown };
  /** @deprecated single-tool fields kept for legacy DB rows. */
  toolResult?: { name: string; result: unknown };
}

export interface Message {
  chatId: number;
  role: MessageRole;
  content: MessageContent;
  intent?: string;
  success?: boolean;
  ts: number;
}

export function appendMessage(db: Database, msg: Message): void {
  db.prepare(
    `INSERT INTO conversations (chat_id, role, content, intent, success, ts)
     VALUES (?, ?, ?, ?, ?, ?)`,
  ).run(
    msg.chatId,
    msg.role,
    JSON.stringify(msg.content),
    msg.intent ?? null,
    msg.success === undefined ? null : msg.success ? 1 : 0,
    msg.ts,
  );
}

/**
 * Drop all stored messages for the given chat. Scoped to chat_id so other
 * users on the same instance are unaffected.
 */
export function clearHistory(db: Database, chatId: number): number {
  const result = db.prepare('DELETE FROM conversations WHERE chat_id = ?').run(chatId);
  return Number(result.changes);
}

export function recentMessages(db: Database, chatId: number, limit: number): Message[] {
  const rows = db.prepare(
    `SELECT chat_id, role, content, intent, success, ts FROM conversations
     WHERE chat_id = ?
     ORDER BY ts ASC
     LIMIT ? OFFSET MAX(0, (SELECT COUNT(*) FROM conversations WHERE chat_id = ?) - ?)`,
  ).all(chatId, limit, chatId, limit) as Array<{
    chat_id: number; role: MessageRole; content: string;
    intent: string | null; success: number | null; ts: number;
  }>;
  return rows.map(r => ({
    chatId: r.chat_id,
    role: r.role,
    content: JSON.parse(r.content) as MessageContent,
    ...(r.intent !== null ? { intent: r.intent } : {}),
    ...(r.success !== null ? { success: r.success === 1 } : {}),
    ts: r.ts,
  }));
}
