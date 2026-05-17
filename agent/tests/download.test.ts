import { describe, it, expect, afterEach } from 'bun:test';
import { downloadTelegramFile } from '../src/telegram/download';

const origFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = origFetch; });

describe('downloadTelegramFile', () => {
  it('chains getFile then file download, guessing mime from extension', async () => {
    const calls: string[] = [];
    globalThis.fetch = (async (input: Parameters<typeof fetch>[0]) => {
      const url = String(input);
      calls.push(url);
      if (url.includes('/getFile')) {
        return new Response(JSON.stringify({ ok: true, result: { file_path: 'voice/file_42.oga' } }), { status: 200 });
      }
      if (url.endsWith('/voice/file_42.oga')) {
        return new Response(new Uint8Array([1, 2, 3]).buffer, { status: 200 });
      }
      return new Response('unexpected', { status: 500 });
    }) as unknown as typeof fetch;

    const result = await downloadTelegramFile({ botToken: 'TOK' }, 'AwACAGV');
    expect(result.filename).toBe('file_42.oga');
    expect(result.mimeType).toBe('audio/ogg');
    expect(result.data).toEqual(new Uint8Array([1, 2, 3]));
    expect(calls[0]).toContain('/bot');
    expect(calls[0]).toContain('file_id=AwACAGV');
    expect(calls[1]).toContain('/file/bot');
  });

  it('throws when getFile returns ok=false', async () => {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ ok: false, description: 'file not found' }), { status: 200 })
    ) as unknown as typeof fetch;

    await expect(downloadTelegramFile({ botToken: 'TOK' }, 'bogus'))
      .rejects.toThrow(/file not found/);
  });
});
