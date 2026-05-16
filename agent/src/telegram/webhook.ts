import type { Database } from 'bun:sqlite';

export interface ParsedTextUpdate {
  kind: 'text';
  updateId: number;
  chatId: number;
  userId: number;
  messageId: number;
  text: string;
  ts: number;
}

export type ParsedUpdate = ParsedTextUpdate;

export function verifySecret(expected: string, header: string | null): boolean {
  if (!header) return false;
  if (header.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= expected.charCodeAt(i) ^ header.charCodeAt(i);
  }
  return diff === 0;
}

export function isDuplicate(db: Database, updateId: number): boolean {
  const row = db.prepare('SELECT 1 FROM processed_updates WHERE update_id = ?').get(updateId);
  return row !== null && row !== undefined;
}

export function markProcessed(db: Database, updateId: number): void {
  db.prepare('INSERT OR IGNORE INTO processed_updates (update_id, ts) VALUES (?, ?)').run(
    updateId, Math.floor(Date.now() / 1000),
  );
}

interface RawMessage {
  message_id: number;
  chat: { id: number; type: string };
  from?: { id: number; is_bot: boolean; first_name?: string; last_name?: string; username?: string };
  date: number;
  text?: string;
  photo?: unknown[];
  voice?: unknown;
}

export function parseUpdate(update: { update_id: number; message?: RawMessage; callback_query?: unknown }): ParsedUpdate | null {
  if (update.callback_query) return null;
  const msg = update.message;
  if (!msg) return null;
  if (typeof msg.text !== 'string') return null;
  if (!msg.from) return null;
  return {
    kind: 'text',
    updateId: update.update_id,
    chatId: msg.chat.id,
    userId: msg.from.id,
    messageId: msg.message_id,
    text: msg.text,
    ts: msg.date,
  };
}
