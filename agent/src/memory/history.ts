import type { Database } from 'bun:sqlite';

export type MessageRole = 'user' | 'assistant' | 'tool';

export interface MessageContent {
  text?: string;
  toolCall?: { name: string; args: unknown };
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
