import { Database } from 'bun:sqlite';

export function initDb(db: Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS conversations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chat_id INTEGER NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      intent TEXT,
      success INTEGER,
      ts INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_chat_ts ON conversations (chat_id, ts ASC);

    CREATE TABLE IF NOT EXISTS processed_updates (
      update_id INTEGER PRIMARY KEY,
      ts INTEGER NOT NULL
    );
  `);
}

export function openDb(path: string): Database {
  const db = new Database(path);
  db.exec('PRAGMA journal_mode = WAL;');
  initDb(db);
  return db;
}
