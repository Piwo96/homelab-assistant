import { describe, it, expect } from 'bun:test';
import { loadEnv } from '../src/config/env';

describe('loadEnv', () => {
  it('parses a valid env object', () => {
    const env = loadEnv({
      TELEGRAM_BOT_TOKEN: 'abc',
      TELEGRAM_WEBHOOK_SECRET: 'secret',
      TELEGRAM_ALLOWED_USERS: '111,222',
      ADMIN_TELEGRAM_ID: '111',
      LM_STUDIO_URL: 'http://localhost:1234',
      LM_STUDIO_MODEL: 'gemma-4-e4b',
      EMBEDDING_MODEL: 'nomic-embed-text-v2-moe',
      WHISPER_MODEL: 'whisper-large-v3-turbo',
      INTERNAL_NOTIFY_TOKEN: 't'.repeat(32),
      PORT: '8080',
      SKILLS_ROOT: '/tmp/skills',
      DATA_DIR: '/tmp/data',
    });
    expect(env.TELEGRAM_ALLOWED_USERS).toEqual([111, 222]);
    expect(env.ADMIN_TELEGRAM_ID).toBe(111);
    expect(env.PORT).toBe(8080);
  });

  it('throws on missing required field', () => {
    expect(() => loadEnv({})).toThrow();
  });

  it('throws on invalid PORT', () => {
    expect(() => loadEnv({
      TELEGRAM_BOT_TOKEN: 'abc', TELEGRAM_WEBHOOK_SECRET: 's',
      TELEGRAM_ALLOWED_USERS: '1', ADMIN_TELEGRAM_ID: '1',
      LM_STUDIO_URL: 'http://x', LM_STUDIO_MODEL: 'm',
      EMBEDDING_MODEL: 'e', WHISPER_MODEL: 'w',
      INTERNAL_NOTIFY_TOKEN: 't'.repeat(32),
      PORT: 'abc', SKILLS_ROOT: '/s', DATA_DIR: '/d',
    })).toThrow(/PORT/);
  });
});
