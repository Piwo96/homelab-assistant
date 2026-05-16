import { describe, it, expect, beforeEach } from 'bun:test';
import { Database } from 'bun:sqlite';
import { initDb } from '../src/memory/db';
import { isDuplicate, markProcessed, parseUpdate, verifySecret } from '../src/telegram/webhook';

let db: Database;
beforeEach(() => { db = new Database(':memory:'); initDb(db); });

describe('verifySecret', () => {
  it('accepts matching secret header', () => {
    expect(verifySecret('expected', 'expected')).toBe(true);
  });
  it('rejects mismatched secret header', () => {
    expect(verifySecret('a', 'b')).toBe(false);
    expect(verifySecret('expected', null)).toBe(false);
  });
});

describe('dedup', () => {
  it('detects duplicates after marking', () => {
    expect(isDuplicate(db, 42)).toBe(false);
    markProcessed(db, 42);
    expect(isDuplicate(db, 42)).toBe(true);
  });
});

describe('parseUpdate', () => {
  it('extracts text message info', () => {
    const u = parseUpdate({
      update_id: 1,
      message: {
        message_id: 10,
        chat: { id: 555, type: 'private' },
        from: { id: 999, is_bot: false, first_name: 'P' },
        date: 1700000000,
        text: 'Hallo',
      },
    });
    expect(u).toEqual({
      kind: 'text',
      updateId: 1,
      chatId: 555,
      userId: 999,
      messageId: 10,
      text: 'Hallo',
      ts: 1700000000,
    });
  });

  it('returns null for callback queries (handled later)', () => {
    expect(parseUpdate({ update_id: 2, callback_query: { id: 'x' } } as never)).toBeNull();
  });

  it('returns null for unsupported message types in MVP', () => {
    expect(parseUpdate({
      update_id: 3,
      message: { message_id: 1, chat: { id: 1, type: 'private' }, from: { id: 1, is_bot: false }, date: 0, photo: [] },
    } as never)).toBeNull();
  });
});
