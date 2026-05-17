import type { Database } from 'bun:sqlite';

interface ParsedBase {
  updateId: number;
  chatId: number;
  userId: number;
  messageId: number;
  ts: number;
  /** Telegram-provided first name of the sender. Passed to the LLM so it
   *  greets the actual user instead of conflating them with Philipp (owner). */
  firstName?: string;
}

export interface ParsedTextUpdate extends ParsedBase {
  kind: 'text';
  text: string;
}

export interface ParsedVoiceUpdate extends ParsedBase {
  kind: 'voice';
  /** Telegram file_id — fed into getFile to resolve the download URL. */
  fileId: string;
  /** Duration in seconds; useful for logging + early-rejection of clips that
   *  would obviously exhaust Whisper budget (currently advisory only). */
  durationSec: number;
  /** MIME type as reported by Telegram (typically audio/ogg with Opus codec). */
  mimeType?: string;
}

export type ParsedUpdate = ParsedTextUpdate | ParsedVoiceUpdate;

const SECRET_ENC = new TextEncoder();

export function verifySecret(expected: string, header: string | null): boolean {
  if (!header) return false;
  const a = SECRET_ENC.encode(expected);
  const b = SECRET_ENC.encode(header);
  const len = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < len; i++) {
    diff |= (a[i] ?? 0) ^ (b[i] ?? 0);
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

interface RawVoice {
  file_id: string;
  file_unique_id?: string;
  duration: number;
  mime_type?: string;
  file_size?: number;
}

interface RawMessage {
  message_id: number;
  chat: { id: number; type: string };
  from?: { id: number; is_bot: boolean; first_name?: string; last_name?: string; username?: string };
  date: number;
  text?: string;
  photo?: unknown[];
  voice?: RawVoice;
}

export function parseUpdate(update: { update_id: number; message?: RawMessage; callback_query?: unknown }): ParsedUpdate | null {
  if (update.callback_query) return null;
  const msg = update.message;
  if (!msg) return null;
  if (!msg.from) return null;
  const firstName = msg.from.first_name?.trim();
  const base: ParsedBase = {
    updateId: update.update_id,
    chatId: msg.chat.id,
    userId: msg.from.id,
    messageId: msg.message_id,
    ts: msg.date,
    ...(firstName ? { firstName } : {}),
  };
  if (typeof msg.text === 'string') {
    return { ...base, kind: 'text', text: msg.text };
  }
  if (msg.voice && typeof msg.voice.file_id === 'string') {
    return {
      ...base,
      kind: 'voice',
      fileId: msg.voice.file_id,
      durationSec: msg.voice.duration ?? 0,
      ...(msg.voice.mime_type ? { mimeType: msg.voice.mime_type } : {}),
    };
  }
  return null;
}
