import { describe, it, expect, beforeEach } from 'bun:test';
import { Database } from 'bun:sqlite';
import { initDb } from '../src/memory/db';
import { appendMessage, recentMessages } from '../src/memory/history';

let db: Database;

beforeEach(() => {
  db = new Database(':memory:');
  initDb(db);
});

describe('history', () => {
  it('round-trips text user/assistant messages', () => {
    appendMessage(db, { chatId: 1, role: 'user', content: { text: 'hi' }, ts: 100 });
    appendMessage(db, { chatId: 1, role: 'assistant', content: { text: 'hello' }, ts: 101 });
    const msgs = recentMessages(db, 1, 10);
    expect(msgs).toHaveLength(2);
    expect(msgs[0]?.role).toBe('user');
    expect(msgs[1]?.content.text).toBe('hello');
  });

  it('orders by ts ASC and limits', () => {
    for (let i = 0; i < 5; i++) {
      appendMessage(db, { chatId: 1, role: 'user', content: { text: `m${i}` }, ts: i });
    }
    const msgs = recentMessages(db, 1, 3);
    expect(msgs.map(m => m.content.text)).toEqual(['m2', 'm3', 'm4']);
  });

  it('isolates by chatId', () => {
    appendMessage(db, { chatId: 1, role: 'user', content: { text: 'a' }, ts: 1 });
    appendMessage(db, { chatId: 2, role: 'user', content: { text: 'b' }, ts: 2 });
    expect(recentMessages(db, 1, 10)).toHaveLength(1);
    expect(recentMessages(db, 2, 10)).toHaveLength(1);
  });
});
